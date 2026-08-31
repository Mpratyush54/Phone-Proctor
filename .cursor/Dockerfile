# Cloud Agent base image for Phone-Proctor.
# Stable system libraries live here; Python dependencies are installed from the
# checked-out source by .cursor/install.sh so they track requirements.txt.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    # Python toolchain + build essentials (pyaudio compiles against portaudio)
    python3 python3-venv python3-dev build-essential pkg-config \
    git curl ca-certificates \
    # OpenCV / MediaPipe runtime
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 ffmpeg \
    # PortAudio for PyAudio
    portaudio19-dev \
    # Qt5 / PyQtWebEngine runtime (headless-capable via xvfb)
    libnss3 libxcomposite1 libxdamage1 libxrandr2 libxi6 libxtst6 \
    libxkbcommon0 libxkbcommon-x11-0 libasound2t64 libegl1 libopengl0 \
    libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
    libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xfixes0 \
    libxcb-cursor0 libdbus-1-3 xvfb \
    # aiortc (WebRTC) native codecs
    libopus0 libvpx9 libsrtp2-1 \
    && rm -rf /var/lib/apt/lists/*

# Cloud Agents run as the non-root "ubuntu" user (uid 1000 already exists on 24.04).
USER ubuntu
WORKDIR /home/ubuntu
