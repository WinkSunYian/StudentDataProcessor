from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QPushButton,
    QLabel,
    QLineEdit,
    QDialog,
    QTabBar,
    QSizePolicy,
)
from PySide6.QtCore import Qt

from Views.ShimmerButton import ShimmerButton


class ClassTabBarView(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("topBar")
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(32, 4, 32, 4)
        self.layout.setSpacing(12)

        self.tab_bar = QTabBar()
        self.tab_bar.setUsesScrollButtons(True)
        self.tab_bar.setElideMode(Qt.TextElideMode.ElideRight)

        self.add_class_btn = QPushButton("+ 新建班级")
        self.add_class_btn.setFixedHeight(32)
        self.add_class_btn.setToolTip("添加新班级")

        self.batch_sync_btn = ShimmerButton("全部同步")
        self.batch_sync_btn.setFixedHeight(32)
        self.batch_sync_btn.setToolTip("下载全部班期并同步至企业微信文档")

        self.layout.addWidget(self.tab_bar, stretch=1)
        self.layout.addWidget(self.add_class_btn)
        self.layout.addWidget(self.batch_sync_btn)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def prompt_create_class_input(self) -> str:
        dialog = QDialog(self)
        dialog.setWindowTitle("新建班级")
        dialog.setMinimumWidth(420)
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        hint = QLabel(
            "请输入完整企业微信群名称，如：Py001期课堂梳理群（Python编程课_01XXYY12）"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.class_name_input = QLineEdit()
        self.class_name_input.setPlaceholderText("请输入班级名称")
        layout.addWidget(self.class_name_input)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        cancel_btn = QPushButton("取消")
        ok_btn = QPushButton("新建")
        ok_btn.setDefault(True)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

        cancel_btn.clicked.connect(dialog.reject)
        ok_btn.clicked.connect(dialog.accept)

        if dialog.exec() == dialog.DialogCode.Accepted:
            return self.class_name_input.text().strip()
        return ""

    def add_tab(self, class_name: str):
        self.tab_bar.addTab(class_name)

    def clear_tabs(self):
        while self.tab_bar.count() > 0:
            self.tab_bar.removeTab(0)

    def set_locked(self, locked: bool):
        """下载/同步/批量期间锁定改动类入口。

        只锁「新建班级」,tab 始终可以切换(切班只读,不干扰正在跑的流水线)。
        """
        self.add_class_btn.setEnabled(not locked)

    def get_current_class_name(self) -> str:
        index = self.tab_bar.currentIndex()
        if index != -1:
            return self.tab_bar.tabText(index)
        return ""

    def set_current_tab_by_name(self, name: str):
        for i in range(self.tab_bar.count()):
            if self.tab_bar.tabText(i) == name:
                self.tab_bar.setCurrentIndex(i)
                break