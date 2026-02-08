
import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QMessageBox
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
from PyQt5.QtCore import QUrl, Qt
from PyQt5.QtGui import QShowEvent

class SecurePage(QWebEnginePage):
    def __init__(self, parent=None):
        super(SecurePage, self).__init__(parent)
        self.allowed_domains = ["pratyushes.dev"]

    def acceptNavigationRequest(self, url, _type, isMainFrame):
        host = url.host()
        # Allow pratyushes.dev and all subdomains
        if host == "pratyushes.dev" or host.endswith(".pratyushes.dev"):
            return True
            
        print(f"[BLOCKED] Navigation to: {host}")
        return False

class SafeBrowser(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Secure Exam Environment")
        self.showMaximized()
        
        # Enforce Fullscreen / Always on Top
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.showFullScreen()

        self.browser = QWebEngineView()
        self.page = SecurePage(self.browser)
        self.browser.setPage(self.page)
        
        # Start at Exam Portal
        self.browser.setUrl(QUrl("https://pratyushes.dev"))
        
        self.setCentralWidget(self.browser)
        
    def keyPressEvent(self, event):
        # Disable Esc to exit? Or Allow for dev
        if event.key() == Qt.Key_Escape:
             self.close()

def main():
    app = QApplication(sys.argv)
    window = SafeBrowser()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    print("[INFO] Safe Browser Process Started...")
    try:
        main()
    except Exception as e:
        print(f"[ERROR] Browser Crashed: {e}")
        input("Press Enter to Exit Browser Process...")
