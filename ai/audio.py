import torch
import numpy as np
import pyaudio
import threading
import time
from collections import deque

class AudioMonitor:
    def __init__(self, sample_rate=16000, chunk_size=512):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.format = pyaudio.paInt16
        self.channels = 1
        
        self.audio = pyaudio.PyAudio()
        self.stream = None
        self.is_running = False
        
        # Buffer for VAD processing
        self.buffer = deque(maxlen=sample_rate * 5) # 5 seconds history
        self.current_chunk = None
        self.lock = threading.Lock()
        
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
            self.stream.start_stream()
            print("[INFO] Audio Monitoring Started")
        except Exception as e:
            print(f"[ERROR] Failed to open microphone: {e}")

    def _callback(self, in_data, frame_count, time_info, status):
        audio_data = np.frombuffer(in_data, dtype=np.int16)
        
        with self.lock:
            self.current_chunk = audio_data.copy()
            # Normalize to float32 for VAD [ -1, 1 ]
            float_audio = audio_data.astype(np.float32) / 32768.0
            self.buffer.extend(float_audio)
            
        return (in_data, pyaudio.paContinue)

    def get_voice_activity(self):
        """
        Returns probability of speech in the current chunk.
        """
        if not self.model or not self.is_running:
            return 0.0

        with self.lock:
            if self.current_chunk is None:
                return 0.0
            
            # Process the latest chunk
            audio_tensor = torch.from_numpy(
                self.current_chunk.astype(np.float32) / 32768.0
            )
            
            # Silero expects (batch, time) or just (time)
            # But the model forward pass usually takes a larger context or manages state via VADIterator
            
            # Using VADIterator is safer for streaming
            if len(audio_tensor) > 0:
                speech_prob = self.model(audio_tensor, self.sample_rate).item()
                # Or use iterator:
                # speech_dict = self.vad_iterator(audio_tensor, return_seconds=True)
                return speech_prob
                
        return 0.0

    def stop(self):
        self.is_running = False
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        self.audio.terminate()
