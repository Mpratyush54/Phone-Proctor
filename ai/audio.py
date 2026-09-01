import torch
import numpy as np
import pyaudio
import threading
import time
import wave
import os
import queue
import speech_recognition as sr
from collections import deque

from agent.product_mode import google_stt_enabled
from utils.paths import audio_dir

class AudioMonitor:
    def __init__(self, sample_rate=16000, chunk_size=512, logger=None):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.format = pyaudio.paInt16
        self.channels = 1
        self.logger = logger
        
        self.audio = pyaudio.PyAudio()
        self.stream = None
        self.is_running = False
        
        # Audio Queue & Processing
        self.audio_queue = queue.Queue()
        self.process_thread = None
        self.stop_event = threading.Event()
        # Persistent shared lock — never instantiate a Lock inside the loop.
        self._chunk_lock = threading.Lock()
        self._transcript_lock = threading.Lock()
        
        # Buffer for VAD processing
        self.vad_buffer = deque(maxlen=sample_rate * 5) # 5 seconds history
        self.current_chunk = None

        # Recording State
        self.is_recording = False
        self.recording_frames = []
        self.silence_frames = 0
        self.silence_threshold_chunks = int((sample_rate / chunk_size) * 1.5) # 1.5s silence to stop
        
        # Transcription Callback
        self.last_transcript = ""

        self.data_dir = str(audio_dir())
              
        # Load Silero VAD
        try:
            self.model, utils = torch.hub.load(repo_or_dir='snakers4/silero-vad',
                                             model='silero_vad',
                                             force_reload=False,
                                             trust_repo=True)
            (self.get_speech_timestamps,
             self.save_audio,
             self.read_audio,
             self.VADIterator,
             self.collect_chunks) = utils
             
            self.vad_iterator = self.VADIterator(self.model)
            print("[INFO] Silero VAD Loaded Successfully")
        except Exception as e:
            print(f"[ERROR] Failed to load Silero VAD: {e}")
            self.model = None

        self.recognizer = sr.Recognizer()

    def start(self):
        if self.is_running:
            return

        try:
            self.stream = self.audio.open(format=self.format,
                                        channels=self.channels,
                                        rate=self.sample_rate,
                                        input=True,
                                        frames_per_buffer=self.chunk_size,
                                        stream_callback=self._callback)
            self.is_running = True
            self.stop_event.clear()
            self.stream.start_stream()
            
            # Start Processing Thread
            self.process_thread = threading.Thread(target=self._process_loop, daemon=True)
            self.process_thread.start()
            
            print("[INFO] Audio Monitoring Started")
        except Exception as e:
            print(f"[ERROR] Failed to open microphone: {e}")

    def _callback(self, in_data, frame_count, time_info, status):
        if self.is_running:
            self.audio_queue.put(in_data)
        return (in_data, pyaudio.paContinue)

    def _process_loop(self):
        while not self.stop_event.is_set():
            try:
                # Process queue items
                try:
                    in_data = self.audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                
                audio_data = np.frombuffer(in_data, dtype=np.int16)
                
                # Update current chunk for real-time VAD display
                with self._chunk_lock:
                    self.current_chunk = audio_data.copy()
                
                # 1. VAD Check
                prob = self._check_vad(audio_data)
                
                # 2. State Machine: Idle <-> Recording
                if prob > 0.5:
                    if not self.is_recording:
                         #print("[AUDIO] User Started Speaking...")
                         self.is_recording = True
                         self.recording_frames = []
                         self.silence_frames = 0
                    
                    self.silence_frames = 0 # Reset silence counter
                    self.recording_frames.append(in_data)
                
                elif self.is_recording:
                    self.silence_frames += 1
                    self.recording_frames.append(in_data)
                    
                    if self.silence_frames > self.silence_threshold_chunks:
                        # Stop Recording
                        self._save_and_process_recording()
                        self.is_recording = False
                        self.recording_frames = []
                        self.silence_frames = 0
                
            except Exception as e:
                #print(f"[ERROR] Audio Processing Loop: {e}")
                pass
                
    def _check_vad(self, audio_data):
        if not self.model: return 0.0
        
        # Normalize
        float_audio = audio_data.astype(np.float32) / 32768.0
        audio_tensor = torch.from_numpy(float_audio)
        
        if len(audio_tensor) > 0:
            try:
                # Just use forward pass on small chunk
                # Note: Silero expects a specific chunk size or state management for best results,
                # but this simple approach often works for basic boolean VAD.
                speech_prob = self.model(audio_tensor, self.sample_rate).item()
                return speech_prob
            except:
                return 0.0
        return 0.0

    def _save_and_process_recording(self):
        # Write to WAV in a separate thread to avoid blocking processing
        frames_to_save = list(self.recording_frames) # Copy
        threading.Thread(target=self._async_save_transcribe, args=(frames_to_save,), daemon=True).start()

    def _async_save_transcribe(self, frames):
        if not frames: return
        
        filename = f"voice_{int(time.time())}.wav"
        filepath = os.path.join(self.data_dir, filename)
        
        try:
            wf = wave.open(filepath, 'wb')
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.audio.get_sample_size(self.format))
            wf.setframerate(self.sample_rate)
            wf.writeframes(b''.join(frames))
            wf.close()
            
            # Transcribe
            self._transcribe(filepath)
            
            # Log Event
            if self.logger:
                transcript_text = getattr(self, "last_transcript", "N/A")
                # Fix: Pass details as a single dictionary
                log_data = {
                    "msg": f"Recording Saved: {filename} ({transcript_text})",
                    "path": filepath,
                    "transcript": transcript_text
                }
                self.logger.log("AUDIO", log_data)
            
        except Exception as e:
            print(f"[ERROR] Failed to save audio: {e}")

    def _transcribe(self, audio_path):
        try:
            with sr.AudioFile(audio_path) as source:
                audio = self.recognizer.record(source)
            
            if not google_stt_enabled():
                # Product default: no off-box transcription.
                return
            text = self.recognizer.recognize_google(audio)
            print(f"[TRANSCRIPT] {text}")
            with self._transcript_lock:
                self.last_transcript = text
                
        except sr.UnknownValueError:
            pass # No speech recognized
        except sr.RequestError as e:
            print(f"[ERROR] Speech Recognition Service Error: {e}")
        except Exception as e:
            print(f"[ERROR] Transcription failed: {e}")

    def get_voice_activity(self):
        with self._chunk_lock:
            chunk = None if self.current_chunk is None else self.current_chunk.copy()
        if chunk is not None:
            return self._check_vad(chunk)
        return 0.0

    def get_current_volume(self):
        """Returns RMS volume of the current audio chunk (0.0 to 1.0 approx)"""
        with self._chunk_lock:
            chunk = None if self.current_chunk is None else self.current_chunk.copy()
        if chunk is not None:
             f = chunk.astype(np.float32)
             rms = np.sqrt(np.mean(f**2))
             return min(rms / 10000.0, 1.0)
        return 0.0

    def get_last_transcript(self):
        with self._transcript_lock:
            return self.last_transcript

    def stop(self):
        self.stop_event.set()
        self.is_running = False
        if self.process_thread:
            self.process_thread.join(timeout=2.0)
            self.process_thread = None
        if self.stream:
            try:
                self.stream.stop_stream()
            except Exception:
                pass
            try:
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        if self.audio:
            try:
                self.audio.terminate()
            except Exception:
                pass
            self.audio = None
