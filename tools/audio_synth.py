"""
TTS audio synthesis for synthetic proctoring sessions
(tools/audio_synth.py)

Generates a realistic spoken clip per AUDIO event so the synthetic
dataset has real sound (not just fake audio/*.wav path references).

Engines:
    edge-tts   - natural neural voice, requires internet (Azure edge TTS).
                 Produces MP3; converted to 16kHz mono 16-bit WAV via the
                 ffmpeg binary bundled with imageio-ffmpeg.
    pyttsx3    - offline system TTS (SAPI on Windows / espeak-ng on Linux).
                 Falls back to this if edge-tts is unavailable or fails.

Output format (matches ai/audio.py recorder + scipy.io.wavfile):
    sample rate 16000, mono, PCM int16.
"""

import os
import subprocess

_AUDIO_RATE = 16000

_FFMPEG_EXE = None


def _ffmpeg():
    global _FFMPEG_EXE
    if _FFMPEG_EXE is None:
        try:
            import imageio_ffmpeg

            _FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            _FFMPEG_EXE = ""
    return _FFMPEG_EXE


def _wav_from_mp3(mp3_path, wav_path):
    """Convert an MP3 to 16kHz mono 16-bit WAV using bundled ffmpeg."""
    exe = _ffmpeg()
    if not exe:
        raise RuntimeError("imageio-ffmpeg not available for mp3->wav conversion")
    r = subprocess.run(
        [exe, "-y", "-loglevel", "error", "-i", mp3_path,
         "-ac", "1", "-ar", str(_AUDIO_RATE), "-sample_fmt", "s16", wav_path],
        capture_output=True)
    if r.returncode != 0 or not os.path.isfile(wav_path):
        raise RuntimeError(f"ffmpeg conversion failed: {r.stderr.decode(errors='ignore')[:200]}")
    return wav_path


def synth_edge_tts(text, wav_path, voice="en-US-JennyNeural"):
    """Synthesize via edge-tts (needs internet). Returns wav_path."""
    import asyncio

    import edge_tts

    mp3_path = wav_path + ".mp3.tmp"
    try:
        asyncio.run(edge_tts.Communicate(text, voice=voice).save(mp3_path))
        if not os.path.isfile(mp3_path) or os.path.getsize(mp3_path) == 0:
            raise RuntimeError("edge-tts produced no audio")
        return _wav_from_mp3(mp3_path, wav_path)
    finally:
        if os.path.isfile(mp3_path):
            os.remove(mp3_path)


def synth_pyttsx3(text, wav_path):
    """Offline fallback via pyttsx3 (system TTS). Returns wav_path."""
    try:
        import pyttsx3

        engine = pyttsx3.init()
        engine.setProperty("rate", 160)
        try:
            engine.setProperty("voice", engine.getProperty("voices")[0].id)
        except Exception:
            pass
        engine.save_to_file(text, wav_path)
        engine.runAndWait()
        engine.stop()
    except Exception as e:
        raise RuntimeError(f"pyttsx3 synthesis failed: {e}") from e
    if not os.path.isfile(wav_path) or os.path.getsize(wav_path) == 0:
        raise RuntimeError("pyttsx3 produced no audio")
    return wav_path


def synth_clip(text, wav_path, engine="edge-tts", voice="en-US-JennyNeural"):
    """Synthesize text to a 16kHz mono 16-bit WAV.

    engine: 'edge-tts' (preferred) or 'pyttsx3'. On edge-tts failure with
    pyttsx3 available, silently falls back so generation never dies on audio.
    Returns wav_path on success, or None if synthesis is unavailable.
    """
    wav_path = os.path.abspath(wav_path)
    try:
        if engine == "pyttsx3":
            return synth_pyttsx3(text, wav_path)
        return synth_edge_tts(text, wav_path, voice=voice)
    except Exception:
        # Last resort offline fallback
        try:
            return synth_pyttsx3(text, wav_path)
        except Exception:
            return None
