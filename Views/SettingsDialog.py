from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QVBoxLayout,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QWidget,
)
from Services.DirectoryService import DirectoryService
from version import APP_VERSION


class SettingsDialog(QDialog):
    """统一配置面板：刷题系统、钉钉及其它登录凭证。"""

    def __init__(self, dir_service: DirectoryService, parent=None):
        super().__init__(parent)
        self.dir_service = dir_service

        self.setWindowTitle("全局凭据配置")
        self.setMinimumWidth(540)
        self.setModal(True)

        self._build_ui()
        self._load_values()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        hint = QLabel(
            "在此集中维护刷题系统、钉钉及其它登录凭证，保存后全局生效。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.shuati_admin_id_input = QLineEdit()
        self.shuati_admin_id_input.setPlaceholderText("刷题系统管理员账号（ADMIN_ID）")

        self.shuati_password_input = QLineEdit()
        self.shuati_password_input.setPlaceholderText("刷题系统管理员密码（PASSWORD）")
        self.shuati_password_input.setEchoMode(QLineEdit.EchoMode.Password)

        self.dingtalk_account_input = QLineEdit()
        self.dingtalk_account_input.setPlaceholderText("钉钉账号（手机号）")

        self.dingtalk_password_input = QLineEdit()
        self.dingtalk_password_input.setPlaceholderText("钉钉登录密码")
        self.dingtalk_password_input.setEchoMode(QLineEdit.EchoMode.Password)

        form.addRow("刷题系统账号（ADMIN_ID）:", self.shuati_admin_id_input)
        form.addRow("刷题系统密码（PASSWORD）:", self.shuati_password_input)
        form.addRow("钉钉账号（手机号）:", self.dingtalk_account_input)
        form.addRow("钉钉密码:", self.dingtalk_password_input)

        section = QHBoxLayout()
        section.setContentsMargins(0, 10, 0, 6)
        section.setSpacing(8)
        section_label = QLabel("其它配置（通常情况下，你无需进行这些配置）")
        section_label.setObjectName("settingsSectionTitle")
        section_line = QFrame()
        section_line.setObjectName("settingsSectionLine")
        section_line.setFrameShape(QFrame.Shape.HLine)
        section_line.setFrameShadow(QFrame.Shadow.Sunken)
        section.addWidget(section_label)
        section.addWidget(section_line, 1)
        form.addRow(section)

        self.e_cookie_input = QLineEdit()
        self.e_cookie_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.e_cookie_input.setPlaceholderText(
            "小鹅通登录凭证，用于期号 ≤ 160 的班级同步"
        )

        self.jsessionid_input = QLineEdit()
        self.jsessionid_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.jsessionid_input.setPlaceholderText(
            "计划学院登录凭证，用于获取班级学习数据"
        )

        self.session_id_input = QLineEdit()
        self.session_id_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.session_id_input.setPlaceholderText(
            "刷题系统登录凭证，用于期号 > 160 的班级同步"
        )

        form.addRow("Ecookie（小鹅通登录凭证）:", self.e_cookie_input)
        form.addRow("JSESSIONID（计划学院登录凭证）:", self.jsessionid_input)
        form.addRow("sessionid（刷题系统登录凭证）:", self.session_id_input)

        layout.addWidget(form_widget)

        # 版本号:排查问题/反馈前先确认这一行
        self.version_label = QLabel(f"当前版本 v{APP_VERSION}")
        self.version_label.setObjectName("pageSubtitle")
        self.version_label.setContentsMargins(2, 6, 0, 0)
        layout.addWidget(self.version_label)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        self.cancel_btn = QPushButton("取消")
        self.save_btn = QPushButton("保存")
        self.save_btn.setDefault(True)
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.save_btn)
        layout.addLayout(btn_layout)

        self.cancel_btn.clicked.connect(self.reject)
        self.save_btn.clicked.connect(self._on_save_clicked)

    def _load_values(self):
        config = self.dir_service.load_config()
        self.jsessionid_input.setText(config.get("JSESSIONID", ""))
        self.e_cookie_input.setText(config.get("Ecookie", ""))
        self.session_id_input.setText(config.get("sessionid", ""))
        self.shuati_admin_id_input.setText(config.get("shuati_admin_id", ""))
        self.shuati_password_input.setText(config.get("shuati_password", ""))
        self.dingtalk_account_input.setText(config.get("dingtalk_account", ""))
        self.dingtalk_password_input.setText(config.get("dingtalk_password", ""))

    def _on_save_clicked(self):
        self.dir_service.save_config("JSESSIONID", self.jsessionid_input.text().strip())
        self.dir_service.save_config("Ecookie", self.e_cookie_input.text().strip())
        self.dir_service.save_config("sessionid", self.session_id_input.text().strip())
        self.dir_service.save_config("shuati_admin_id", self.shuati_admin_id_input.text().strip())
        self.dir_service.save_config("shuati_password", self.shuati_password_input.text().strip())
        self.dir_service.save_config("dingtalk_account", self.dingtalk_account_input.text().strip())
        self.dir_service.save_config("dingtalk_password", self.dingtalk_password_input.text().strip())
        self.accept()
