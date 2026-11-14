import asyncio
import json
import logging
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate, RTCConfiguration, RTCIceServer
import numpy as np

class WebRTCManager:
    def __init__(self, frame_callback=None, audio_callback=None):
        self.pcs = set()
        self.frame_callback = frame_callback
        self.audio_callback = audio_callback
        self.active_pc = None
        self._closed = False

    async def handle_offer(self, params):
        offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
        
        # Configure STUN to help with connectivity
        # FIX: Remove STUN to force LAN connection if on same network (avoids hairpinning issues)
        config = RTCConfiguration(iceServers=[])
        
        pc = RTCPeerConnection(configuration=config)
        self.pcs.add(pc)
        self.active_pc = pc 
        
        @pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            print(f"[WebRTC] ICE state: {pc.iceConnectionState}")
            if pc.iceConnectionState == "failed":
                await pc.close()
                self.pcs.discard(pc)
                if self.active_pc == pc: self.active_pc = None

        @pc.on("track")
        def on_track(track):
            print(f"[WebRTC] Track received: {track.kind}")
            
            if track.kind == "video":
               asyncio.ensure_future(self._handle_video_track(track))
            elif track.kind == "audio":
               asyncio.ensure_future(self._handle_audio_track(track))
        
        # Set Remote Description first!
        await pc.setRemoteDescription(offer)
        
        # Create Answer
        answer = await pc.createAnswer()
       
        await pc.setLocalDescription(answer)
        
        # HACK: Wait for ICE gathering to complete (or at least get STUN candidates)
        # aiortc gathers asynchronously. Without Trickle ICE on the client side handling server candidates,
        # we MUST send a complete SDP.
        print("[WebRTC] Gathering ICE candidates (Host Only)...")
        await asyncio.sleep(1.0) 
        
        print(f"[WebRTC] Complete SDP Generated:\n{pc.localDescription.sdp}")
        return {
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type
        }

    async def add_ice_candidate(self, candidate_data):
        if not self.active_pc:
             return
        
        try:
            # candidate_data is likely { 'candidate': '...', 'sdpMid': '...', ... }
            if isinstance(candidate_data, dict):
                sdp_candidate = candidate_data.get('candidate', '')
                sdp_mid = candidate_data.get('sdpMid')
                sdp_mline_index = candidate_data.get('sdpMLineIndex')
            else:
                return # Unknown format

            if not sdp_candidate: 
                return

            # Parse "candidate:..." string manually for aiortc
            # Format: candidate:{foundation} {component} {protocol} {priority} {ip} {port} typ {type} ...
            parts = sdp_candidate.split()
            
            # Basic validation
            if len(parts) < 8 or 'candidate' not in parts[0]:
                print(f"[WebRTC] Invalid candidate string: {sdp_candidate}")
                return

            foundation = parts[0].split(':')[1]
            component = int(parts[1])
            protocol = parts[2].lower()
            priority = int(parts[3])
            ip = parts[4]
            port = int(parts[5])
            # parts[6] is 'typ'
            type_val = parts[7]
            
            candidate = RTCIceCandidate(
                component=component,
                foundation=foundation,
                ip=ip,
                port=port,
                priority=priority,
                protocol=protocol,
                type=type_val,
                sdpMid=sdp_mid,
                sdpMLineIndex=sdp_mline_index
            )
            
            print(f"[WebRTC] Adding Remote Candidate: {ip}:{port} ({protocol} - Type: {type_val})")
            await self.active_pc.addIceCandidate(candidate)
            
        except Exception as e:
            print(f"[WebRTC] Candidate Error: {e}")
        
    async def _handle_video_track(self, track):
        print("[WebRTC] Starting video track handler...")
        frame_count = 0
        while not self._closed:
            try:
                # print("[WebRTC] Waiting for frame...") # Too noisy
                frame = await track.recv()
                
                frame_count += 1
                if frame_count % 30 == 0:
                     print(f"[WebRTC] Video Frame {frame_count} received. Size: {frame.width}x{frame.height}")
                
                # frame is an av.VideoFrame
                # Convert to numpy array (BGR for OpenCV)
                img = frame.to_ndarray(format="bgr24")
                
                if self.frame_callback:
                    if frame_count == 1:
                        print(f"[WebRTC] FIRST FRAME RECEIVED!")
                    self.frame_callback(img)
            except Exception as e:
                print(f"[WebRTC] Video track error/ended: {e}")
                import traceback
                traceback.print_exc()
                break

    async def _handle_audio_track(self, track):
        while not self._closed:
            try:
                frame = await track.recv()
                # frame is an av.AudioFrame
                # Convert to numpy array
                # frame.to_ndarray() shape is (channels, samples)
                # We can calculate volume/RMS
                data = frame.to_ndarray()
                rms = np.sqrt(np.mean(data**2))
                if self.audio_callback:
                    self.audio_callback(rms)
            except Exception as e:
                # print(f"[WebRTC] Audio track ended: {e}")
                break

    async def close(self):
        self._closed = True
        coros = [pc.close() for pc in list(self.pcs)]
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)
        self.pcs.clear()
        self.active_pc = None
