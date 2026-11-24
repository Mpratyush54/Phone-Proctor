"""Phone-Proctor's student workspace and enrollment flow."""

import logging
from queue import Empty, SimpleQueue
from threading import Event, Thread

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QCloseEvent, QFont
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFrame, QHBoxLayout, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from agent.desktop_session import SessionError, check_endpoint, start_session
from screen.exam_workspace import ExamWorkspace, text
from utils.paths import user_data_root

STYLES = """
QMainWindow, QWidget { background: #fff; color: #202226; }
QLabel { background: transparent; }
QLabel#muted { color: #64686e; }
QLabel#brandMark { background: #24272d; border-radius: 7px; color: white; font-weight: 750; }
QLabel#brand { font-size: 16px; font-weight: 720; }
QLabel#title { font-size: 29px; font-weight: 720; }
QLabel#emptyTitle { font-size: 19px; font-weight: 650; }
QLabel#sectionTitle { font-size: 16px; font-weight: 650; }
QLabel#smallHeading { font-weight: 650; }
QLabel#status { background: #f1f2f4; color: #50555d; padding: 5px 10px; border-radius: 6px; }
QLabel#status[online="true"] { background: #eaf5ef; color: #216445; }
QLabel#notice { background: #fff6e6; color: #703f15; padding: 10px 12px; border-radius: 7px; }
QFrame#card, QFrame#deviceCard, QStackedWidget#examWorkspace { border: 1px solid #e5e7eb; border-radius: 12px; background: #fff; }
QFrame#sidebar, QFrame#sidebar QWidget, QFrame#sidebar QLabel { background: #f8f8f9; }
QFrame#sidebar { border-right: 1px solid #e7e8ec; }
QFrame#sidebar QLabel#brandMark { background: #24272d; }
QFrame#line { background: #e7e8ec; }
QLineEdit { background: white; border: 1px solid #dfe2e6; border-radius: 7px; padding: 9px 10px; selection-background-color: #245edc; }
QLineEdit:focus { border: 1px solid #245edc; }
QCheckBox { spacing: 8px; }
QPushButton { padding: 8px 12px; background: white; border: 1px solid #e0e3e7; border-radius: 7px; }
QPushButton:hover { background: #f6f7f9; }
QPushButton:focus { border: 1px solid #245edc; }
QPushButton[primary="true"] { background: #245edc; color: #fff; border-color: #245edc; font-weight: 650; }
QPushButton[primary="true"]:hover { background: #1b50c4; }
QPushButton#nav { background: transparent; border-color: transparent; text-align: left; }
QPushButton#nav:hover, QPushButton#nav:checked { background: #ebecf0; }
QPushButton:disabled { color: #767a83; background: #f3f4f6; }
"""


def button(caption, action, *, primary=False):
    control = QPushButton(caption)
    control.setCursor(Qt.CursorShape.PointingHandCursor)
    control.setProperty("primary", primary)
    control.clicked.connect(action)
    return control


def frame(name, layout_type=QVBoxLayout, *, padding=0, gap=0):
    panel = QFrame()
    panel.setObjectName(name)
    layout = layout_type(panel)
    layout.setContentsMargins(padding, padding, padding, padding)
    layout.setSpacing(gap)
    return panel, layout


class ConnectionSettings(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Connection settings")
        self.setMinimumWidth(420)
        content = QVBoxLayout(self)
        content.setContentsMargins(22, 22, 22, 22)
        content.setSpacing(8)
        content.addWidget(text("Connection settings", "sectionTitle"))
        content.addWidget(text("Use the API and gateway addresses provided by exam staff.", "muted"))
        self.api = QLineEdit(parent.api)
        self.gateway = QLineEdit(parent.gateway)
        for caption, field in (("Control-plane API", self.api), ("Agent gateway", self.gateway)):
            label = text(caption, "smallHeading")
            label.setBuddy(field)
            field.setAccessibleName(caption)
            content.addWidget(label)
            content.addWidget(field)
        self.error = text(name="notice")
        self.error.hide()
        content.addWidget(self.error)
        content.addWidget(button("Save settings", self.save, primary=True))

    def save(self):
        try:
            self.endpoint = check_endpoint(self.api.text(), websocket=False)
            self.socket_url = check_endpoint(self.gateway.text(), websocket=True)
        except SessionError as error:
            self.error.setText(str(error))
            self.error.show()
            return
        self.accept()


class StudentWindow(QMainWindow):
    def __init__(self, api, gateway):
        super().__init__()
        self.api, self.gateway = api, gateway
        self.setWindowTitle("Phone-Proctor · Student workspace")
        self.resize(1160, 760)
        self.setMinimumSize(860, 610)
        self.updates, self.rechecks = SimpleQueue(), SimpleQueue()
        self.stop = Event()
        self.worker = None
        self.lifecycle = ""
        self.link = ""
        self.online = self.joined = self.closing = False

        shell, structure = frame("shell", QHBoxLayout)
        self.setCentralWidget(shell)
        rail, sidebar = frame("sidebar", padding=13, gap=7)
        rail.setFixedWidth(202)
        structure.addWidget(rail)
        brand = QHBoxLayout()
        mark = text("P", "brandMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(27, 27)
        brand.addWidget(mark)
        brand.addWidget(text("Phone-Proctor", "brand"), 1)
        sidebar.addLayout(brand)
        sidebar.addSpacing(16)
        self.exam_nav = self.nav_button("Join exam", self.open_exam)
        self.devices_nav = self.nav_button("Device check", self.open_devices)
        sidebar.addWidget(self.exam_nav)
        sidebar.addWidget(self.devices_nav)
        sidebar.addStretch()
        self.connection_badge = text("Disconnected", "status")
        sidebar.addWidget(self.connection_badge)
        self.settings = button("Connection settings", self.open_settings)
        sidebar.addWidget(self.settings)
        self.leave = button("Leave session", self.leave_session)
        sidebar.addWidget(self.leave)
        self.leave.hide()

        right, workspace = frame("column")
        structure.addWidget(right, 1)
        toolbar, toolbar_row = frame("toolbar", QHBoxLayout, padding=14, gap=7)
        self.breadcrumb = text("Join exam", "smallHeading")
        toolbar_row.addWidget(self.breadcrumb)
        toolbar_row.addStretch()
        toolbar_row.addWidget(text("Student workspace", "muted"))
        workspace.addWidget(toolbar)
        rule = QFrame()
        rule.setObjectName("line")
        rule.setFixedHeight(1)
        workspace.addWidget(rule)
        self.pages = QStackedWidget()
        workspace.addWidget(self.pages, 1)
        self.join_view = self.build_join()
        self.session_view = self.build_session()
        self.devices_view = self.build_devices()
        for page in (self.join_view, self.session_view, self.devices_view):
            self.pages.addWidget(page)
        self.open_exam()
        self.token.setFocus()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.drain)
        self.timer.start(80)

    def nav_button(self, caption, action):
        item = button(caption, action)
        item.setObjectName("nav")
        item.setCheckable(True)
        return item

    def build_join(self):
        view, layout = frame("joinPage", padding=26)
        layout.addStretch()
        card, grid = frame("card", QHBoxLayout, padding=36, gap=36)
        card.setMaximumWidth(820)
        card.setMinimumHeight(332)
        layout.addWidget(card, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()
        form = QVBoxLayout()
        form.setSpacing(10)
        intro = QVBoxLayout()
        intro.setSpacing(10)
        grid.addLayout(form, 1)
        grid.addLayout(intro, 1)
        form.addStretch()
        form.addWidget(text("Join your exam", "title"))
        form.addWidget(text("Use the enrollment token from your exam staff.", "muted"))
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setAccessibleName("Enrollment token")
        self.token.setPlaceholderText("Paste enrollment token")
        self.token.setMaxLength(256)
        self.token.returnPressed.connect(self.join)
        form.addWidget(self.token)
        self.join_consent = QCheckBox("Allow webcam availability check")
        form.addWidget(self.join_consent)
        self.join_button = button("Join exam", self.join, primary=True)
        form.addWidget(self.join_button)
        self.join_message = text(name="notice")
        self.join_message.hide()
        form.addWidget(self.join_message)
        form.addStretch()
        intro.addStretch()
        intro.addWidget(text("Before you start", "sectionTitle"))
        intro.addWidget(text("Your exam website opens here automatically when staff start your session.", "muted"))
        intro.addWidget(text("Keep Phone-Proctor open so staff can see your connection status.", "muted"))
        intro.addStretch()
        return view

    def build_session(self):
        view, content = frame("session", padding=20, gap=10)
        title_row = QHBoxLayout()
        self.exam_title = text("Your exam", "title")
        self.exam_title.setMaximumHeight(62)
        self.session_status = text("Connecting", "status")
        title_row.addWidget(self.exam_title, 1)
        title_row.addWidget(self.session_status, alignment=Qt.AlignmentFlag.AlignVCenter)
        content.addLayout(title_row)
        self.notice = text(name="notice")
        self.notice.hide()
        content.addWidget(self.notice)
        self.exam = ExamWorkspace()
        content.addWidget(self.exam, 1)
        return view

    def build_devices(self):
        view, layout = frame("devices", padding=32, gap=13)
        layout.addWidget(text("Device check", "title"))
        layout.addWidget(text("Manage the webcam availability check for this session.", "muted"))
        card, fields = frame("deviceCard", padding=18, gap=10)
        card.setMaximumWidth(610)
        fields.addWidget(text("Webcam", "sectionTitle"))
        self.camera_status = text("Waiting for your choice", "muted")
        fields.addWidget(self.camera_status)
        self.consent = QCheckBox("Allow a webcam availability check")
        self.consent.toggled.connect(self.camera_choice)
        self.consent.toggled.connect(self.join_consent.setChecked)
        self.join_consent.toggled.connect(self.consent.setChecked)
        fields.addWidget(self.consent)
        fields.addWidget(text("Phone-Proctor sends camera availability and exam activity. Camera frames stay on your computer.", "muted"))
        self.recheck = button("Check again", self.recheck_camera)
        self.recheck.hide()
        fields.addWidget(self.recheck, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(card)
        layout.addStretch()
        return view

    def open_exam(self):
        self.pages.setCurrentWidget(self.session_view if self.joined else self.join_view)
        self.breadcrumb.setText("Exam" if self.joined else "Join exam")
        self.exam_nav.setChecked(True)
        self.devices_nav.setChecked(False)

    def open_devices(self):
        self.pages.setCurrentWidget(self.devices_view)
        self.breadcrumb.setText("Device check")
        self.exam_nav.setChecked(False)
        self.devices_nav.setChecked(True)

    def open_settings(self):
        dialog = ConnectionSettings(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.api, self.gateway = dialog.endpoint, dialog.socket_url

    def join(self):
        if self.worker and self.worker.is_alive():
            return
        try:
            api = check_endpoint(self.api, websocket=False)
            gateway = check_endpoint(self.gateway, websocket=True)
            token = self.token.text().strip()
            if not token:
                raise SessionError("Enter the enrollment token provided by exam staff.")
        except SessionError as error:
            self.show_message(self.join_message, str(error))
            return
        self.token.clear()
        self.stop, self.rechecks = Event(), SimpleQueue()
        allowed = self.consent.isChecked()
        self.show_message(self.join_message, "")
        self.show_message(self.notice, "")
        self.join_button.setEnabled(False)
        self.token.setEnabled(False)
        self.join_consent.setEnabled(False)
        self.settings.hide()
        self.leave.setText("Cancel connection")
        self.leave.setEnabled(True)
        self.leave.show()
        self.connection_badge.setText("Connecting…")
        self.consent.setEnabled(False)

        def work():
            def publish(kind, value=""):
                self.updates.put((kind, value))
            try:
                start_session(api, gateway, token, allowed, user_data_root(), publish, self.stop, self.rechecks)
            except SessionError as error:
                if not self.stop.is_set():
                    publish("error", str(error))
            except Exception:
                logging.getLogger(__name__).exception("Desktop session failed")
                if not self.stop.is_set():
                    publish("error", "The desktop session stopped. Check the connection settings and try again.")
            finally:
                publish("finished")

        self.worker = Thread(target=work, daemon=True)
        self.worker.start()

    def camera_choice(self, _checked):
        if self.joined and self.online:
            self.recheck_camera()

    def recheck_camera(self):
        if self.online and self.lifecycle != "ENDED":
            self.camera_status.setText("Checking…")
            self.recheck.setEnabled(False)
            self.consent.setEnabled(False)
            self.rechecks.put(self.consent.isChecked())

    def leave_session(self):
        if not self.confirm_leave():
            return
        self.stop.set()
        self.leave.setText("Disconnecting…")
        self.leave.setEnabled(False)

    def confirm_leave(self):
        return self.lifecycle not in {"IN_EXAM", "PAUSED"} or QMessageBox.question(
            self, "Leave session?", "Exam staff will see you go offline. Leave the session?"
        ) == QMessageBox.StandardButton.Yes

    def closeEvent(self, event: QCloseEvent):
        if self.worker and self.worker.is_alive():
            event.ignore()
            if self.confirm_leave():
                self.closing = True
                self.stop.set()
                self.connection_badge.setText("Disconnecting…")
            return
        self.exam.clear_browser()
        event.accept()

    @staticmethod
    def show_message(label, value):
        label.setText(value)
        label.setVisible(bool(value))

    def sync_state(self):
        self.connection_badge.setProperty("online", self.online)
        self.connection_badge.style().unpolish(self.connection_badge)
        self.connection_badge.style().polish(self.connection_badge)
        self.session_status.setText({
            "READY": "Waiting to start", "DEGRADED": "Ready with limitations",
            "IN_EXAM": "In progress", "PAUSED": "Paused", "ENDED": "Complete", "BLOCKED": "Device check required",
        }.get(self.lifecycle, "Connecting"))
        self.recheck.setVisible(self.joined and self.lifecycle != "ENDED")
        self.recheck.setEnabled(self.online)
        self.consent.setEnabled(self.online and self.lifecycle != "ENDED")
        self.exam.update_session(self.lifecycle, self.online, self.link)

    def drain(self):
        while True:
            try:
                kind, value = self.updates.get_nowait()
            except Empty:
                return
            if kind == "enrolled":
                self.joined = True
                self.exam_title.setText(value)
                self.exam_nav.setText("Exam")
                self.leave.setText("Leave session")
                self.open_exam()
            elif kind == "exam-link":
                self.link = value
            elif kind == "connection":
                self.connection_badge.setText(value)
                self.online = value.startswith("Connected")
            elif kind == "lifecycle":
                self.lifecycle = value
                if value in {"IN_EXAM", "PAUSED", "ENDED"}:
                    self.open_exam()
            elif kind == "camera":
                self.camera_status.setText(value)
            elif kind == "notice":
                self.show_message(self.notice, value)
            elif kind == "error":
                self.show_message(self.join_message, value)
            elif kind == "finished":
                self.finish()
                return
            self.sync_state()

    def finish(self):
        self.worker.join()
        if self.closing:
            self.close()
            return
        self.joined = self.online = False
        self.lifecycle = self.link = ""
        self.sync_state()
        self.connection_badge.setText("Disconnected")
        self.camera_status.setText("Waiting for your choice")
        self.exam_nav.setText("Join exam")
        self.join_button.setEnabled(True)
        self.token.setEnabled(True)
        self.join_consent.setEnabled(True)
        self.consent.setEnabled(True)
        self.settings.show()
        self.leave.hide()
        self.open_exam()
        self.token.setFocus()


def launch(api, gateway):
    app = QApplication(["Phone-Proctor"])
    app.setFont(QFont("Arial", 10))
    app.setStyleSheet(STYLES)
    window = StudentWindow(api, gateway)
    window.show()
    app.exec()
