import sys
import threading
import time
import os
import cv2
import json
from datetime import datetime

# Local Modules
# Local Modules
# FIX: Handle DLL loading issues on Windows for PyTorch

try:
    if os.name == 'nt':
        # Add Torch lib folder to DLL search path
        # 1. Find site-packages
        site_packages = next(p for p in sys.path if 'site-packages' in p)
        torch_lib_path = os.path.join(site_packages, 'torch', 'lib')
        if os.path.exists(torch_lib_path):
            os.add_dll_directory(torch_lib_path)
            # Also try setting env var for OpenMP just in case
            os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'
            
    # Force import torch to lock in the DLLs
    import torch
except Exception as e:
    print(f"[WARN] Failed to configure DLL search path for PyTorch: {e}")

from network.server import ProctorServer
from utils.logger import EventLogger
from screen.safe_browser import run_browser_app
from screen.proctor_thread import ProctorThread
from analysis.session_analyzer import SessionAnalyzer

def main():
    # -------------------------------
    # Unified Proctoring App
    # -------------------------------
    DEV_MODE = False  # Set to False to enable AI models in ProctorThread
    
    print("[INIT] Starting AI Proctoring System...")
    
    # 1. Start Network Server (Background Thread)
    # The server runs mostly on asyncio/websockets in its own thread
    server = ProctorServer(port=5000)
    server.start()
    
    logger = EventLogger()
    print(f"[DATA] Session ID: {logger.session_id}. Logging to {logger.session_dir}")
    
    if DEV_MODE:
        print("[INFO] DEV_MODE=True. AI modules are DISABLED, but Camera is enabled for preview.")
    
    # 2. Initialize UI (Safe Browser)
    # This creates the QApplication and the Window
    print("[INIT] Launching Safe Browser UI...")
    app, browser_window = run_browser_app()
    
    # 3. Start Proctor Logic Thread (Handle Camera + AI + Status)
    # This thread handles the heavy lifting without freezing the UI
    print("[INIT] Starting Proctor Logic Thread...")
    proctor_thread = ProctorThread(server=server, dev_mode=DEV_MODE, logger=logger)
    
    # Connect Signals
    # Video Frame Update -> Browser.update_camera_feed
    proctor_thread.image_update.connect(browser_window.update_camera_feed)
    proctor_thread.phone_update.connect(browser_window.update_phone_feed)
    
    # Gaze 3D Viz -> Browser.update_gaze_viz
    proctor_thread.gaze_update.connect(browser_window.update_gaze_viz)
    
    # Status Update -> Browser.update_status_signal
    proctor_thread.status_update.connect(browser_window.update_status_signal)
    
    # Start the thread
    proctor_thread.start()
    
    print("[INFO] Application Started.")
    print("[INFO] Use the Dashboard to manage the session.")
    
    # 4. Run Main Event Loop (Blocking)
    try:
        exit_code = app.exec_()
    except KeyboardInterrupt:
        exit_code = 0
        
    # Cleanup
    print("[INFO] Shutting down...")
    proctor_thread.stop()
    server.stop()
    
    # Run Final Analysis
    print("[INFO] Generating Final Report...")
    try:
        analyzer = SessionAnalyzer(logger.session_dir)
        analyzer.analyze()
    except Exception as e:
        print(f"[ERROR] Failed to generate report: {e}")

    sys.exit(exit_code)

if __name__ == "__main__":
    main()
