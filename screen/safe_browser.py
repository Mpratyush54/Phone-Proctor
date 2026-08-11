import sys
import os
import json
import psutil

# 🔥 CRITICAL: Enable WebRTC + Media + Secure Overrides
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    "--enable-webrtc "
    "--enable-media-stream "
    "--autoplay-policy=no-user-gesture-required "
    "--allow-file-access-from-files "
    "--unsafely-treat-insecure-origin-as-secure=file://"
)

try:
    from PyQt5.QtWidgets import QApplication, QMainWindow, QMessageBox
    from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
    from PyQt5.QtCore import QUrl, Qt, QBuffer, QIODevice, QObject, QThread, pyqtSignal, pyqtSlot
    from PyQt5.QtGui import QShowEvent, QImage
except ImportError as e:
    print(f"[CRITICAL ERROR] Missing Dependencies for Safe Browser: {e}")
    print("pip install PyQt5 PyQtWebEngine")
    input("Press Enter to close window...")
    sys.exit(1)


# ==========================
# Feed Encoder Worker (off GUI thread)
# ==========================
class FeedEncoder(QObject):
    """Encodes QImage frames to base64 JPEG on its own thread so the GUI
    thread only does the cheap runJavaScript call. Coalesces to the latest
    frame if a previous encode is still in flight, so a slow renderer never
    causes an unbounded queue / lag buildup."""

    camera_ready = pyqtSignal(str)
    phone_ready = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._camera_busy = False
        self._camera_pending = None
        self._phone_busy = False
        self._phone_pending = None

    @staticmethod
    def _to_b64(q_image):
        ba = QBuffer()
        ba.open(QIODevice.ReadWrite)
        q_image.save(ba, "JPG", 50)
        return ba.data().toBase64().data().decode()

    @pyqtSlot(QImage)
    def encode_camera(self, q_image):
        if self._camera_busy:
            self._camera_pending = q_image
            return
        self._camera_busy = True
        try:
            b64 = self._to_b64(q_image)
        finally:
            self._camera_busy = False
        self.camera_ready.emit(b64)
        pending = self._camera_pending
        self._camera_pending = None
        if pending is not None:
            self.encode_camera(pending)

    @pyqtSlot(QImage)
    def encode_phone(self, q_image):
        if self._phone_busy:
            self._phone_pending = q_image
            return
        self._phone_busy = True
        try:
            b64 = self._to_b64(q_image)
        finally:
            self._phone_busy = False
        self.phone_ready.emit(b64)
        pending = self._phone_pending
        self._phone_pending = None
        if pending is not None:
            self.encode_phone(pending)


# ==========================
# Secure Web Page
# ==========================
class SecurePage(QWebEnginePage):
    def __init__(self, parent=None):
        super(SecurePage, self).__init__(parent)

        self.allowed_domains = ["pratyushes.dev"]

        settings = self.settings()

        # Preserve your original settings
        settings.setAttribute(settings.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(settings.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(settings.ErrorPageEnabled, True)
        settings.setAttribute(settings.AllowRunningInsecureContent, True)
        settings.setAttribute(settings.WebGLEnabled, True)
        settings.setAttribute(settings.Accelerated2dCanvasEnabled, True)
        settings.setAttribute(settings.LocalStorageEnabled, True)

        # 🔥 ADDED: Media Permissions
        self.featurePermissionRequested.connect(self.handle_permission)

    # 🔥 ADDED: Auto grant camera + mic
    def handle_permission(self, url, feature):
        print(f"[PERMISSION REQUEST] {feature} from {url.host()}")

        if feature in (
            QWebEnginePage.MediaAudioCapture,
            QWebEnginePage.MediaVideoCapture,
            QWebEnginePage.MediaAudioVideoCapture,
        ):
            self.setFeaturePermission(
                url,
                feature,
                QWebEnginePage.PermissionGrantedByUser,
            )
            print("[PERMISSION] Granted")
        else:
            self.setFeaturePermission(
                url,
                feature,
                QWebEnginePage.PermissionDeniedByUser,
            )
            print("[PERMISSION] Denied")

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        print(f"[JS] {message}")
        if message.startswith("CMD:KILL:"):
            try:
                pid_str = message.split(":")[2]
                pid = int(pid_str)
                proc = psutil.Process(pid)
                proc.terminate()
                print(f"[PY] Terminated process {pid}")
            except Exception as e:
                print(f"[PY] Failed to terminate {pid_str}: {e}")

    def acceptNavigationRequest(self, url, _type, isMainFrame):
        host = url.host()
        scheme = url.scheme()

        print(f"[NAVIGATE] Scheme: '{scheme}', Host: '{host}', Path: '{url.path()}'")

        # Allow local files
        if scheme == "file" or host == "":
            return True

        # Allow pratyushes.dev and subdomains
        if host == "pratyushes.dev" or host.endswith(".pratyushes.dev"):
            return True

        print(f"[BLOCKED] Navigation to: {host} (Scheme: {scheme})")
        return False


# ==========================
# Safe Browser Window
# ==========================
class SafeBrowser(QMainWindow):
    camera_request = pyqtSignal(QImage)
    phone_request = pyqtSignal(QImage)

    def __init__(self):
        super().__init__()

        log_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "logs",
            "browser_debug.txt",
        )
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        self.log_file = open(log_path, "a")

        def log(msg):
            self.log_file.write(f"[DEBUG] {msg}\n")
            self.log_file.flush()

        log("SafeBrowser initializing...")

        self.setWindowTitle("Secure Exam Environment")

        # Fullscreen lock: frameless + always-on-top + fullscreen
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.showFullScreen()
        self.activateWindow()
        self.raise_()

        log("Fullscreen + TopMost applied")

        self.browser = QWebEngineView()
        self.browser.page().setBackgroundColor(Qt.black)

        self.page = SecurePage(self.browser)
        self.browser.setPage(self.page)

        self.browser.loadFinished.connect(
            lambda ok: print(f"[BROWSER] Load Status: {'SUCCESS' if ok else 'FAILED'}")
        )

        # Load Local Dashboard (file:// preserved)
        dashboard_path = os.path.abspath(
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..",
                "assets",
                "dashboard.html",
            )
        )

        if os.path.exists(dashboard_path):
            url = QUrl.fromLocalFile(dashboard_path)
            print(f"[BROWSER] Loading Dashboard: {url.toString()}")
        else:
            print(f"[ERROR] Dashboard not found at {dashboard_path}")
            url = QUrl("about:blank")

        self.browser.setUrl(url)
        self.setCentralWidget(self.browser)

        # Feed encoding happens on a worker thread: the GUI thread only
        # receives the finished base64 string and does the runJavaScript call.
        self._encoder = FeedEncoder()
        self._encoder_thread = QThread(self)
        self._encoder.moveToThread(self._encoder_thread)
        self._encoder_thread.start()

        # GUI thread -> encoder thread (queued)
        self.camera_request.connect(self._encoder.encode_camera)
        self.phone_request.connect(self._encoder.encode_phone)
        # Encoder thread -> GUI thread (queued)
        self._encoder.camera_ready.connect(self._inject_camera_feed)
        self._encoder.phone_ready.connect(self._inject_phone_feed)

        self.is_loaded = False
        self._warned_phone_feed = False
        self.browser.loadFinished.connect(self._on_load_finished)

    def _on_load_finished(self, ok):
        self.is_loaded = ok
        self._warned_phone_feed = False
        print(f"[BROWSER] Load Status: {'SUCCESS' if ok else 'FAILED'}")
        if ok:
            self.update_phone_status(False, "N/A")

    # ==========================
    # JS Injection Methods
    # ==========================
    def update_phone_status(self, connected, ip, logs=[], phoneVol=0.0, pcVol=0.0, blockingApps=[]):
        if not self.is_loaded:
            return

        ip_str = str(ip) if ip else "N/A"
        logs_json = json.dumps(logs)
        apps_json = json.dumps(blockingApps)

        js = f"""
        if(window.updatePhoneStatus)
            window.updatePhoneStatus(
                {str(connected).lower()},
                "{ip_str}",
                {logs_json},
                {phoneVol},
                {pcVol},
                {apps_json}
            );
        """

        self.browser.page().runJavaScript(js)

    def update_status_signal(self, status):
        # Throttle: status text/numbers don't need per-frame refresh (~33fps).
        # 2Hz is plenty and removes a huge GUI-thread load (json.dumps + JS
        # injection on every single proctor-loop tick caused lag/freezes).
        import time
        current_time = time.time()
        if not hasattr(self, "last_status_update"):
            self.last_status_update = 0
        if current_time - self.last_status_update < 0.5:
            return
        self.last_status_update = current_time

        self.update_phone_status(
            status.get("connected", False),
            status.get("ip", "N/A"),
            status.get("logs", []),
            status.get("phone_vol", 0.0),
            status.get("pc_vol", 0.0),
            status.get("blocking_apps", [])
        )

    def update_camera_feed(self, q_image):
        if not self.is_loaded:
            return
        self.camera_request.emit(q_image)

    def _inject_camera_feed(self, b64_data):
        js = f"""
        (function() {{
            var el = document.getElementById('camera-feed');
            if (el) {{
                el.src = "data:image/jpeg;base64,{b64_data}";
            }}
        }})();
        """
        self.browser.page().runJavaScript(js)

    def update_phone_feed(self, q_image):
        if not self.is_loaded:
            return
        self.phone_request.emit(q_image)

    def _inject_phone_feed(self, b64_data):
        js = f"""
        (function() {{
            var el = document.getElementById('phone-feed');
            if (el) {{
                el.src = "data:image/jpeg;base64,{b64_data}";
            }} else if (!window.__phoneFeedWarned) {{
                window.__phoneFeedWarned = true;
                console.warn("PY: phone-feed element missing");
            }}
        }})();
        """
        self.browser.page().runJavaScript(js)

    def update_gaze_viz(self, yaw, pitch, direction, violation, phone_face):
        """Push head pose data to the 3D visualization canvas."""
        if not self.is_loaded:
            return

        import time
        current_time = time.time()
        if not hasattr(self, "last_gaze_update"):
            self.last_gaze_update = 0
        if current_time - self.last_gaze_update < 0.05:  # 20fps max
            return
        self.last_gaze_update = current_time

        v = "true" if violation else "false"
        pf = "true" if phone_face else "false"
        safe_dir = direction.replace("'", "\\'")

        js = f"""
        (function() {{
            if (window.updateGazeViz) {{
                window.updateGazeViz({yaw:.1f}, {pitch:.1f}, '{safe_dir}', {v}, {pf});
            }}
        }})();
        """
        self.browser.page().runJavaScript(js)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()

    def closeEvent(self, event):
        # Stop the encoder worker thread cleanly.
        if getattr(self, "_encoder_thread", None) and self._encoder_thread.isRunning():
            self._encoder_thread.quit()
            self._encoder_thread.wait(2000)
        super().closeEvent(event)


# ==========================
# Run App
# ==========================
def run_browser_app():
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)

    app = QApplication(sys.argv)
    app.setApplicationName("SafeBrowser")

    window = SafeBrowser()
    window.show()

    return app, window


def main():
    app, window = run_browser_app()
    sys.exit(app.exec_())


if __name__ == "__main__":
    print("[INFO] Safe Browser Process Started...")
    try:
        main()
    except Exception as e:
        print(f"[ERROR] Browser Crashed: {e}")
        input("Press Enter to Exit...")
