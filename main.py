import sys
import os
import argparse

# Windows: register torch DLLs before any torchvision/torchaudio import.
# Mismatched torch/vision/audio wheels cause "procedure entry point ... could
# not be located" dialogs — fix with scripts/install_agent_deps.ps1.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
try:
    if os.name == "nt":
        site_packages = next((p for p in sys.path if "site-packages" in p), None)
        if site_packages:
            torch_lib = os.path.join(site_packages, "torch", "lib")
            if os.path.isdir(torch_lib):
                os.add_dll_directory(torch_lib)
    import torch  # noqa: F401
except Exception as e:
    print(f"[WARN] torch not ready ({e}). Use scripts/install_agent_deps.ps1")
    print("[WARN] AI audio/YOLO may be unavailable; --dev still works.")

from network.server import ProctorServer
from utils.logger import EventLogger
from screen.safe_browser import run_browser_app
from screen.proctor_thread import ProctorThread
from analysis.session_analyzer import SessionAnalyzer
from agent.consent import ConsentGate, ConsentRecord
from agent.product_mode import current_mode
from agent.supervisor import AgentSupervisor
from agent.wal import EventWal
from utils.paths import wal_dir


def main():
    # -------------------------------
    # Unified Proctoring App
    # -------------------------------
    DEV_MODE = False  # Set to False to enable AI models in ProctorThread
    
    print("[INIT] Starting AI Proctoring System...")
    print(f"[INIT] Mode: {current_mode().value}")

    consent = ConsentRecord.from_dict({
        "camera": True,
        "microphone": os.environ.get("PHONE_PROCTOR_CONSENT_MIC", "1") == "1",
        "screen": os.environ.get("PHONE_PROCTOR_CONSENT_SCREEN", "0") == "1",
        "keystrokes": os.environ.get("PHONE_PROCTOR_CONSENT_KEYS", "0") == "1",
        "network_monitor": os.environ.get("PHONE_PROCTOR_CONSENT_NET", "1") == "1",
    })
    decision = ConsentGate().evaluate(consent)
    
    # 1. Start Network Server (Background Thread)
    # The server runs mostly on asyncio/websockets in its own thread
    server = ProctorServer(port=5000)
    server.start()
    
    logger = EventLogger()
    print(f"[DATA] Session ID: {logger.session_id}. Logging to {logger.session_dir}")

    wal = EventWal(wal_dir() / f"{logger.session_id}.sqlite")
    supervisor = AgentSupervisor(wal=wal, consent=consent)
    supervisor.consent_decision = decision

    # Local development: keep current UX (AI starts with the UI).
    # Product/control-plane: AI scoring waits for EXAM_START (C1).
    wait_for_start = os.environ.get("PHONE_PROCTOR_WAIT_EXAM_START", "0") == "1"
    
    if DEV_MODE:
        print("[INFO] DEV_MODE=True. AI modules are DISABLED, but Camera is enabled for preview.")
    
    # 2. Initialize UI (Safe Browser)
    # This creates the QApplication and the Window
    print("[INIT] Launching Safe Browser UI...")
    app, browser_window = run_browser_app()
    
    # 3. Start Proctor Logic Thread (Handle Camera + AI + Status)
    # This thread handles the heavy lifting without freezing the UI
    print("[INIT] Starting Proctor Logic Thread...")
    start_ai = (not wait_for_start) and decision.readiness.value != "BLOCKED"
    proctor_thread = ProctorThread(server=server, dev_mode=DEV_MODE or not start_ai, logger=logger)
    proctor_thread.consent_decision = decision
    
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
    wal.close()
    
    # Run Final Analysis
    print("[INFO] Generating Observable Session Summary...")
    try:
        analyzer = SessionAnalyzer(logger.session_dir)
        analyzer.analyze()
    except Exception as e:
        print(f"[ERROR] Failed to generate report: {e}")

    sys.exit(exit_code)


def _parse_args():
    p = argparse.ArgumentParser(description="Phone-Proctor Laptop Agent")
    p.add_argument("--server", default=os.environ.get("PP_SERVER_URL", ""),
                   help="Central server URL (e.g. ws://host:8080/agent). Empty = local-only MVP mode.")
    p.add_argument("--exam-code", default=os.environ.get("PP_EXAM_CODE", ""))
    p.add_argument("--student-id", default=os.environ.get("PP_STUDENT_ID", ""))
    p.add_argument("--skip-consent", action="store_true",
                   help="Reuse last consent file if present (dev only).")
    p.add_argument("--dev", action="store_true", help="Disable AI modules in ProctorThread.")
    return p.parse_args()


def main():
    args = _parse_args()
    DEV_MODE = bool(args.dev)

    print("[INIT] Starting AI Proctoring System...")

    # --- Consent + capability probe (product gates) ---
    from pp_platform import (
        load_consent,
        prompt_console_consent,
        probe_capabilities,
        verify_against_manifest,
    )

    caps = probe_capabilities()
    print(f"[CAPS] OS={caps.os_name} frozen={caps.frozen} torch={caps.torch_available} "
          f"scapy={caps.scapy_available} npcap~={caps.npcap_likely}")
    for note in caps.notes:
        print(f"[CAPS] {note}")

    consent = load_consent() if args.skip_consent else None
    if consent is None:
        consent = prompt_console_consent(
            student_id=args.student_id,
            exam_code=args.exam_code,
            require_network_monitor=False,
        )
    else:
        print("[CONSENT] Reusing saved consent (--skip-consent)")

    enable_sniff = (
        bool(consent.network_monitor)
        and caps.scapy_available
        and caps.npcap_likely
    )

    integrity = verify_against_manifest()
    print(f"[INTEGRITY] {integrity.get('status')} fingerprint={integrity.get('attestation')}")

    logger = EventLogger()
    print(f"[DATA] Session ID: {logger.session_id}. Logging to {logger.session_dir}")

    # --- Optional central uplink (product path) ---
    uplink = None
    if args.server:
        try:
            from agent import AgentUplink, WriteAheadJournal
            journal = WriteAheadJournal(logger.session_id)
            uplink = AgentUplink(
                server_url=args.server,
                session_id=logger.session_id,
                journal=journal,
                exam_code=args.exam_code or consent.exam_code,
                student_id=args.student_id or consent.student_id,
            )
            logger.uplink = uplink
            uplink.start()
            uplink.emit("SESSION_START", {
                "integrity": integrity.get("status"),
                "capabilities": caps.to_dict(),
                "consent": consent.to_dict(),
            })
            print(f"[UPLINK] Connected path → {args.server}")
        except Exception as e:
            print(f"[UPLINK] Failed to start (continuing local-only): {e}")
            uplink = None
    else:
        print("[UPLINK] No --server set; running local MVP phone bridge only.")

    # 1. Start Network Server (phone LAN bridge — kept for MVP / desk camera)
    server = ProctorServer(port=5000)
    server.start()

    if DEV_MODE:
        print("[INFO] DEV_MODE=True. AI modules are DISABLED, but Camera is enabled for preview.")

    # 2. Initialize UI (Safe Browser)
    print("[INIT] Launching Safe Browser UI...")
    app, browser_window = run_browser_app()

    # 3. Start Proctor Logic Thread
    print("[INIT] Starting Proctor Logic Thread...")
    proctor_thread = ProctorThread(
        server=server,
        dev_mode=DEV_MODE,
        logger=logger,
        enable_sniff=enable_sniff,
        uplink=uplink,
    )

    proctor_thread.image_update.connect(browser_window.update_camera_feed)
    proctor_thread.phone_update.connect(browser_window.update_phone_feed)
    proctor_thread.gaze_update.connect(browser_window.update_gaze_viz)
    proctor_thread.status_update.connect(browser_window.update_status_signal)
    proctor_thread.start()

    print("[INFO] Application Started.")
    print("[INFO] Use the Dashboard to manage the session.")

    try:
        exit_code = app.exec_()
    except KeyboardInterrupt:
        exit_code = 0

    print("[INFO] Shutting down...")
    if uplink:
        try:
            uplink.emit("SESSION_END", {})
        except Exception:
            pass
        uplink.stop()
    proctor_thread.stop()
    server.stop()

    print("[INFO] Generating Final Report...")
    try:
        analyzer = SessionAnalyzer(logger.session_dir)
        analyzer.analyze()
    except Exception as e:
        print(f"[ERROR] Failed to generate report: {e}")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
