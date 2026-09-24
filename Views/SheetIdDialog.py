from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QWidget,
)
from Services.DirectoryService import DirectoryService


class SheetIdDialog(QDialog):
    """配置当前班级的企业微信在线文档 DOC_ID 和 SHEET_ID(每个班级独立)。"""

    def __init__(self, dir_service: DirectoryService, class_name: str, parent=None):
        super().__init__(parent)
        self.dir_service = dir_service
        self.class_name = class_name

        self.setWindowTitle(f"配置在线文档 - {class_name}")
        self.setMinimumWidth(420)
        self.setModal(True)

        self._build_ui()
        self._load_value()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        hint = QLabel(
            f"在此维护班级「{self.class_name}」的企业微信在线文档 DOC_ID 和 SHEET_ID,保存后仅对该班级生效。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.doc_id_input = QLineEdit()
        self.doc_id_input.setPlaceholderText("请输入 DOC_ID")
        form.addRow("DOC_ID:", self.doc_id_input)

        self.sheet_id_input = QLineEdit()
        self.sheet_id_input.setPlaceholderText("请输入 SHEET_ID")
        form.addRow("SHEET_ID:", self.sheet_id_input)

        layout.addWidget(form_widget)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        self.cancel_btn = QPushButton("取消")
        self.save_btn = QPushButton("确定")
        self.save_btn.setDefault(True)
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.save_btn)
        layout.addLayout(btn_layout)

        self.cancel_btn.clicked.connect(self.reject)
        self.save_btn.clicked.connect(self._on_save_clicked)

    def _load_value(self):
        config = self.dir_service.load_class_config(self.class_name)
        self.doc_id_input.setText(config.get("DOC_ID", ""))
        self.sheet_id_input.setText(config.get("SHEET_ID", ""))

    def _on_save_clicked(self):
        self.dir_service.save_class_config(
            self.class_name, "DOC_ID", self.doc_id_input.text().strip()
        )
        self.dir_service.save_class_config(
            self.class_name, "SHEET_ID", self.sheet_id_input.text().strip()
        )
        self.accept()
