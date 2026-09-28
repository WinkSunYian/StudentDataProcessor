from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from Services.UpdateService import ReleaseInfo
from version import APP_VERSION


class UpdateDialog(QDialog):
    """新版本提示 + 下载进度,一个弹窗走完全程。

    状态机: idle -> updating -> (done | failed | idle)
    idle     未开始,可点「立即更新」
    updating 下载中,可点「取消」;下载落地后关闭按钮被禁用(临界点)
    failed   可「重试」或「关闭」
    done     已启动更新脚本,等待 controller 退出应用
    """

    updateRequested = Signal()  # 「立即更新」/「重试」
    cancelRequested = Signal()  # 下载阶段的「取消」

    def __init__(self, release: ReleaseInfo, parent=None):
        super().__init__(parent)
        self.release = release
        self._state = "idle"

        self.setWindowTitle("软件更新")
        self.setMinimumWidth(520)
        self.setModal(True)

        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        title = QLabel("发现新版本")
        title.setObjectName("classTitle")
        layout.addWidget(title)

        self.version_label = QLabel(
            f"当前版本 v{APP_VERSION}   →   新版本 {self.release.tag}"
        )
        self.version_label.setObjectName("pageSubtitle")
        layout.addWidget(self.version_label)

        if self.release.notes:
            self.notes = QPlainTextEdit()
            self.notes.setPlainText(self.release.notes)
            self.notes.setReadOnly(True)
            self.notes.setMinimumHeight(140)
            self.notes.setMaximumHeight(240)
            layout.addWidget(self.notes)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.status_label = QLabel("")
        self.status_label.setObjectName("pageSubtitle")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.close_btn = QPushButton("稍后")
        self.primary_btn = QPushButton("立即更新")
        self.primary_btn.setObjectName("primaryButton")
        self.primary_btn.setDefault(True)
        buttons.addWidget(self.close_btn)
        buttons.addWidget(self.primary_btn)
        layout.addLayout(buttons)

        self.close_btn.clicked.connect(self._on_close_clicked)
        self.primary_btn.clicked.connect(self._on_primary_clicked)

    # ------------------------------------------------------------------
    # 状态流转(由 controller 调用)
    # ------------------------------------------------------------------
    def begin_update(self):
        self._state = "updating"
        self.close_btn.setEnabled(True)
        self.close_btn.setText("取消")
        self.primary_btn.setEnabled(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.show()
        self.status_label.setText("准备下载...")

    def set_progress(self, text: str, percent: int):
        if self._state != "updating":
            return
        if percent < 0:
            self.progress.setRange(0, 0)
        else:
            if self.progress.maximum() == 0:
                self.progress.setRange(0, 100)
            self.progress.setValue(percent)
        self.status_label.setText(text)

    def begin_irreversible(self):
        """下载已落地,校验/解压/替换期间不允许再取消。"""
        self.close_btn.setEnabled(False)

    def set_failed(self, message: str):
        self._state = "failed"
        self.progress.hide()
        self.status_label.setText(message or "更新失败")
        self.close_btn.setEnabled(True)
        self.close_btn.setText("关闭")
        self.primary_btn.setText("重试")
        self.primary_btn.setEnabled(True)

    def set_cancelled(self):
        self._state = "idle"
        self.progress.hide()
        self.status_label.setText("")
        self.close_btn.setEnabled(True)
        self.close_btn.setText("稍后")
        self.primary_btn.setText("立即更新")
        self.primary_btn.setEnabled(True)

    def set_succeeded(self, message: str):
        self._state = "done"
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.status_label.setText(message)
        self.close_btn.setEnabled(True)
        self.close_btn.setText("关闭")
        self.primary_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def _on_primary_clicked(self):
        if self._state == "updating":
            return
        self.updateRequested.emit()

    def _on_close_clicked(self):
        if self._state == "updating":
            self.close_btn.setEnabled(False)
            self.status_label.setText("正在取消...")
            self.cancelRequested.emit()
            return
        self.reject()

    def reject(self):
        # 更新进行中不允许 Esc / 关闭退出,否则信号目标会先被销毁
        if self._state == "updating":
            return
        super().reject()

    def closeEvent(self, event):
        if self._state == "updating":
            event.ignore()
            return
        super().closeEvent(event)
