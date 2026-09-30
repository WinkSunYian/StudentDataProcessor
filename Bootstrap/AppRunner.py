import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from Bootstrap.AppOrchestrator import AppOrchestrator
from Views.ShimmerButton import ShimmerButton


def resource_path(relative_path: str) -> str:
    """
    获取资源文件路径。

    开发环境：
        使用项目根目录。

    PyInstaller：
        使用 PyInstaller 解包后的临时目录。
    """
    if getattr(sys, "frozen", False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..")
        )

    return os.path.join(base_path, relative_path)


class AppRunner:
    INSTANCE_NAME = "StudentDataProcessor_SingleInstance"

    def __init__(self, sys_argv):
        self.app = QApplication(sys_argv)

        # --------------------------------------------------------------
        # 应用图标
        # --------------------------------------------------------------

        icon_path = resource_path("Resources/icon.ico")

        if os.path.exists(icon_path):
            self.app.setWindowIcon(QIcon(icon_path))

        # --------------------------------------------------------------
        # 单实例
        # --------------------------------------------------------------

        self._single_instance_server = None
        self._pending_sockets = []

        # --------------------------------------------------------------
        # Theme
        # --------------------------------------------------------------

        self._apply_system_theme()
        self.app.styleHints().colorSchemeChanged.connect(
            self._apply_system_theme
        )

        # --------------------------------------------------------------
        # Application
        # --------------------------------------------------------------

        self.orchestrator = AppOrchestrator()

    # ------------------------------------------------------------------
    # 单实例
    # ------------------------------------------------------------------

    def _check_single_instance(self) -> bool:
        """
        检查是否已经存在程序实例。

        True:
            当前进程是第一个实例。

        False:
            已经存在实例，当前进程应该退出。
        """

        # --------------------------------------------------------------
        # 1. 先尝试连接已经存在的实例
        # --------------------------------------------------------------

        socket = QLocalSocket()

        socket.connectToServer(self.INSTANCE_NAME)

        if socket.waitForConnected(500):
            # 已经存在第一个实例。
            #
            # 通知它激活窗口。
            socket.write(b"activate")
            socket.waitForBytesWritten(500)

            socket.disconnectFromServer()
            socket.deleteLater()

            return False

        # --------------------------------------------------------------
        # 2. 连接失败，尝试创建自己的 Server
        # --------------------------------------------------------------

        self._single_instance_server = QLocalServer(self.app)

        if self._single_instance_server.listen(self.INSTANCE_NAME):
            # 创建成功。
            #
            # 当前实例就是第一个实例。
            self._single_instance_server.newConnection.connect(
                self._on_new_instance
            )

            return True

        # --------------------------------------------------------------
        # 3. listen 失败
        #
        # 可能是：
        #   A. Server 确实已经存在
        #   B. 上一次程序异常退出留下了残留 Server
        # --------------------------------------------------------------

        QLocalServer.removeServer(self.INSTANCE_NAME)

        # 再尝试一次。
        if self._single_instance_server.listen(self.INSTANCE_NAME):
            self._single_instance_server.newConnection.connect(
                self._on_new_instance
            )

            return True

        return False

    def _on_new_instance(self):
        """
        第二个实例连接进来。
        """

        socket = self._single_instance_server.nextPendingConnection()

        if socket is None:
            return

        # 保存 socket，避免局部变量被销毁。
        self._pending_sockets.append(socket)

        socket.readyRead.connect(
            lambda s=socket: self._handle_instance_message(s)
        )

        socket.disconnected.connect(
            lambda s=socket: self._remove_socket(s)
        )

    def _handle_instance_message(self, socket):
        """
        接收第二个实例发送的消息。
        """

        message = bytes(socket.readAll())

        if message == b"activate":
            self._activate_main_window()

    def _remove_socket(self, socket):
        """
        清理已经断开的 socket。
        """

        if socket in self._pending_sockets:
            self._pending_sockets.remove(socket)

        socket.deleteLater()

    def _activate_main_window(self):
        """
        激活当前已经运行的主窗口。
        """

        window = self.orchestrator.get_main_window()

        if window is None:
            return

        # 如果窗口最小化，恢复。
        if window.isMinimized():
            window.showNormal()

        # 确保窗口显示。
        window.show()

        # 提升窗口层级。
        window.raise_()

        # 激活窗口。
        window.activateWindow()

        # Windows 强制前置。
        self._force_foreground_window(window)

    @staticmethod
    def _force_foreground_window(window):
        """
        Windows 下强制把窗口切到前台。
        """

        if sys.platform != "win32":
            return

        try:
            import ctypes

            hwnd = int(window.winId())

            user32 = ctypes.windll.user32

            # SW_RESTORE
            user32.ShowWindow(hwnd, 9)

            # 激活窗口
            user32.SetActiveWindow(hwnd)

            # 设置前台窗口
            user32.SetForegroundWindow(hwnd)

        except Exception:
            pass

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _apply_system_theme(self, *_):
        dark = self._is_system_dark_theme()

        colors = (
            {
                "window": "#17191D",
                "surface": "#20242A",
                "surface_alt": "#191D22",
                "border": "#343A43",
                "text": "#E7EAF0",
                "muted": "#AAB2C0",
                "button": "#282D35",
                "hover": "#303A4B",
                "disabled": "#242830",
                "disabled_text": "#6F7886",
                "input": "#191D22",
                "primary": "#4B86F7",
                "primary_hover": "#6A9BFA",
            }
            if dark
            else {
                "window": "#F7F8FA",
                "surface": "#FFFFFF",
                "surface_alt": "#F8FAFC",
                "border": "#E8ECF2",
                "text": "#172033",
                "muted": "#7B8494",
                "button": "#FFFFFF",
                "hover": "#F3F7FF",
                "disabled": "#F7F8FA",
                "disabled_text": "#ABB3C0",
                "input": "#FFFFFF",
                "primary": "#2864DC",
                "primary_hover": "#1F56C2",
            }
        )

        ShimmerButton.apply_theme(
            {"primary": colors["primary"], "button": colors["button"]}
        )

        self.app.setStyleSheet(
            f"""
            QMainWindow {{
                background: {colors['window']};
            }}

            QWidget {{
                color: {colors['text']};
                font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
                font-size: 13px;
            }}

            QFrame#topBar {{
                background: {colors['surface']};
                border-bottom: 1px solid {colors['border']};
            }}

            QFrame#summaryCard,
            QFrame#actionCard,
            QFrame#logCard,
            QFrame#metricCard {{
                background: {colors['surface']};
                border: 1px solid {colors['border']};
                border-radius: 12px;
            }}

            QLabel#pageTitle,
            QLabel#classTitle,
            QLabel#metricValue {{
                color: {colors['text']};
                font-weight: 700;
            }}

            QLabel#pageTitle {{
                font-size: 26px;
            }}

            QLabel#classTitle {{
                font-size: 18px;
            }}

            QLabel#metricValue {{
                font-size: 22px;
            }}

            QLabel#recordTimeLabel {{
                color: {colors['muted']};
                font-size: 12px;
                font-weight: 400;
            }}

            QLabel#settingsSectionTitle {{
                color: {colors['text']};
                font-weight: 700;
            }}

            QFrame#settingsSectionLine {{
                color: {colors['border']};
            }}

            QLabel#pageSubtitle,
            QLabel#cardDescription,
            QLabel#metricLabel {{
                color: {colors['muted']};
            }}

            QLabel#stepNumber {{
                color: {colors['primary']};
                font-weight: 700;
            }}

            QPushButton {{
                min-height: 34px;
                padding: 0 14px;
                border: 1px solid {colors['border']};
                border-radius: 7px;
                background: {colors['button']};
                color: {colors['text']};
            }}

            QPushButton:hover {{
                background: {colors['hover']};
                border-color: {colors['primary']};
            }}

            QPushButton:disabled {{
                background: {colors['disabled']};
                color: {colors['disabled_text']};
                border-color: {colors['border']};
            }}

            QPushButton#primaryButton {{
                background: {colors['primary']};
                border-color: {colors['primary']};
                color: #FFFFFF;
                font-weight: 600;
            }}

            QPushButton#primaryButton:hover {{
                background: {colors['primary_hover']};
            }}

            QPushButton#ghostButton {{
                border-color: transparent;
                color: {colors['muted']};
            }}

            QToolButton {{
                color: {colors['muted']};
                border: 0;
                padding: 4px 8px;
            }}

            QToolButton:hover {{
                color: {colors['primary']};
            }}

            QTabBar::tab {{
                background: transparent;
                color: {colors['muted']};
                padding: 12px 16px;
                margin: 0;
            }}

            QTabBar::tab:selected {{
                color: {colors['primary']};
                font-weight: 600;
                border-bottom: 2px solid {colors['primary']};
            }}

            QTabBar::tab:hover {{
                color: {colors['primary']};
            }}

            QPlainTextEdit {{
                background: {colors['surface_alt']};
                border: 1px solid {colors['border']};
                border-radius: 8px;
                padding: 8px;
                font-family: Consolas, "Microsoft YaHei UI";
                color: {colors['muted']};
            }}

            QLineEdit {{
                min-height: 28px;
                padding: 3px 8px;
                border: 1px solid {colors['border']};
                border-radius: 6px;
                background: {colors['input']};
                color: {colors['text']};
            }}

            QLineEdit:focus {{
                border-color: {colors['primary']};
            }}

            QDialog {{
                background: {colors['surface']};
            }}
            """
        )

    def _is_system_dark_theme(self) -> bool:
        return self.app.styleHints().colorScheme() == Qt.ColorScheme.Dark

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> int:

        # 单实例检查必须放在 setup() 之前。
        if not self._check_single_instance():
            return 0

        self.orchestrator.setup()

        window = self.orchestrator.get_main_window()

        # 设置主窗口图标，确保窗口自身也使用该图标。
        icon_path = resource_path("Resources/icon.ico")

        if os.path.exists(icon_path):
            window.setWindowIcon(QIcon(icon_path))

        window.showMaximized()

        return self.app.exec()