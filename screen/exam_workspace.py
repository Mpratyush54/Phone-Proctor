"""Embedded exam content and dedicated display states."""

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from agent.desktop_session import exam_link


def text(value="", name=""):
    label = QLabel(value)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    if name:
        label.setObjectName(name)
    return label


class ExamPage(QWebEnginePage):
    def __init__(self, profile, parent):
        super().__init__(profile, parent)
        self.featurePermissionRequested.connect(self.deny_feature)
        self.fullScreenRequested.connect(lambda request: request.reject())

    def deny_feature(self, origin, feature):
        self.setFeaturePermission(origin, feature, QWebEnginePage.PermissionPolicy.PermissionDeniedByUser)

    def acceptNavigationRequest(self, url, navigation_type, main_frame):
        if not main_frame and url.scheme() in {"about", "blob", "data"}:
            return True
        return exam_link(url.toString()) is not None

    def createWindow(self, window_type):
        return None


class ExamWorkspace(QStackedWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("examWorkspace")
        placeholder = QWidget()
        contents = QVBoxLayout(placeholder)
        contents.setContentsMargins(24, 24, 24, 24)
        contents.addStretch()
        self.heading = text(name="emptyTitle")
        self.heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.explanation = text(name="muted")
        self.explanation.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.retry = QPushButton("Retry loading exam")
        self.retry.setAccessibleName("Retry loading exam")
        self.retry.clicked.connect(self.retry_loading)
        contents.addWidget(self.heading)
        contents.addWidget(self.explanation)
        contents.addSpacing(10)
        contents.addWidget(self.retry, alignment=Qt.AlignmentFlag.AlignHCenter)
        contents.addStretch()
        self.addWidget(placeholder)
        self.placeholder = placeholder
        self.browser = self.profile = None
        self.link = ""
        self.active = self.loaded = self.failed = False

    def update_session(self, lifecycle, online, link):
        if lifecycle == "ENDED" or not lifecycle:
            self.clear_browser()
        self.active = lifecycle == "IN_EXAM" and online
        if self.browser and self.link != link:
            self.clear_browser()
        self.link = link
        if self.active and link and self.browser is None:
            self.begin_load()
        if self.browser and self.active:
            self.browser.page().setLifecycleState(QWebEnginePage.LifecycleState.Active)
        self.render(lifecycle, online)
        if self.browser and not self.active:
            self.browser.page().setLifecycleState(QWebEnginePage.LifecycleState.Frozen)

    def render(self, lifecycle="IN_EXAM", online=True):
        self.retry.hide()
        if self.active and self.loaded:
            self.setCurrentWidget(self.browser)
            return
        self.setCurrentWidget(self.placeholder)
        if lifecycle == "ENDED":
            heading, detail = "Session complete", "Exam staff have ended your session. You can close Phone-Proctor."
        elif lifecycle == "PAUSED":
            heading, detail = "Exam paused", "Your exam will reappear when staff resume the session."
        elif not online:
            heading, detail = "Waiting for a connection", "Keep the app open while Phone-Proctor reconnects to exam staff."
        elif lifecycle == "BLOCKED":
            heading, detail = "Camera check required", "Open Device check, allow the webcam check, and try again."
        elif not self.active:
            heading, detail = "Waiting for exam staff", "Your exam will open here when staff start the session."
        elif not self.link:
            heading, detail = "Exam website unavailable", "Ask exam staff for the exam website. This session has no website assigned."
        elif self.failed:
            heading, detail = "Couldn't load the exam", "Check your connection and try again. Contact exam staff if the website remains unavailable."
            self.retry.show()
        else:
            heading, detail = "Loading your exam", "The exam website is opening in Phone-Proctor."
        self.heading.setText(heading)
        self.explanation.setText(detail)

    def begin_load(self):
        self.profile = QWebEngineProfile(self)
        self.profile.downloadRequested.connect(lambda request: request.cancel())
        self.browser = view = QWebEngineView()
        view.setPage(ExamPage(self.profile, view))
        view.setAccessibleName("Embedded exam website")
        view.loadFinished.connect(lambda ok: self.load_finished(view, ok))
        view.renderProcessTerminated.connect(lambda *_args: self.load_finished(view, False))
        self.addWidget(view)
        view.load(QUrl(self.link))

    def load_finished(self, view, ok):
        if view is not self.browser:
            return
        self.loaded = ok
        self.failed = not ok
        if self.active:
            self.render()

    def retry_loading(self):
        if self.active and self.browser:
            self.failed = False
            self.render()
            self.browser.reload()

    def clear_browser(self):
        view, profile = self.browser, self.profile
        self.browser = self.profile = None
        self.loaded = self.failed = False
        if view is not None:
            self.setCurrentWidget(self.placeholder)
            self.removeWidget(view)
            view.stop()
            view.page().destroyed.connect(profile.deleteLater)
            view.deleteLater()
