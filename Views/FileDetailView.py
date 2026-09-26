from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)


class FileDetailView(QWidget):
    """留白优先的班级数据工作台。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(48, 34, 48, 30)
        self.main_layout.setSpacing(22)
        self._active_record_name = ""
        self._build_header()
        self._build_summary()
        self._build_workflow()
        self._build_logs()

        self._record_time_timer = QTimer(self)
        self._record_time_timer.setInterval(60_000)
        self._record_time_timer.timeout.connect(self._refresh_active_record_time)
        self._record_time_timer.start()

    def _build_header(self):
        header = QHBoxLayout()
        copy = QVBoxLayout()
        copy.setSpacing(4)
        title = QLabel("学生数据中心")
        title.setObjectName("pageTitle")
        subtitle = QLabel("下载、整理并同步每个班级的学习数据")
        subtitle.setObjectName("pageSubtitle")
        copy.addWidget(title)
        copy.addWidget(subtitle)
        header.addLayout(copy)
        header.addStretch(1)
        self.settings_btn = QPushButton("全局凭据配置")
        self.settings_btn.setObjectName("ghostButton")
        header.addWidget(self.settings_btn)
        self.main_layout.addLayout(header)

    def _build_summary(self):
        card = QFrame()
        card.setObjectName("summaryCard")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(34)

        class_info = QVBoxLayout()
        class_info.setSpacing(5)
        caption = QLabel("当前班级")
        caption.setObjectName("metricLabel")
        self.class_title_label = QLabel("请选择一个班级")
        self.class_title_label.setObjectName("classTitle")
        self.status_label = QLabel("等待下载")
        self.status_label.setObjectName("pageSubtitle")
        class_info.addWidget(caption)
        class_info.addWidget(self.class_title_label)
        class_info.addWidget(self.status_label)
        layout.addLayout(class_info, 2)

        self.active_record_label = self._make_record_metric("最近记录", "暂无数据")
        self.total_label = self._make_metric("学员总数", "—")
        self.active_label = self._make_metric("在读学员", "—")
        layout.addWidget(self.active_record_label, 2)
        layout.addWidget(self.total_label)
        layout.addWidget(self.active_label)
        self.main_layout.addWidget(card)

    def _make_record_metric(self, label: str, value: str) -> QFrame:
        card = QFrame()
        card.setObjectName("metricCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        label_widget = QLabel(label)
        label_widget.setObjectName("metricLabel")
        value_row = QHBoxLayout()
        value_row.setSpacing(8)
        self.active_record_value_label = QLabel(value)
        self.active_record_value_label.setObjectName("metricValue")
        self.active_record_value_label.setWordWrap(True)
        self.active_record_time_label = QLabel()
        self.active_record_time_label.setObjectName("recordTimeLabel")
        self.active_record_time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        value_row.addWidget(self.active_record_value_label, 1)
        value_row.addWidget(self.active_record_time_label)
        layout.addWidget(label_widget)
        layout.addLayout(value_row)
        return card

    @staticmethod
    def _make_metric(label: str, value: str) -> QFrame:
        card = QFrame()
        card.setObjectName("metricCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        label_widget = QLabel(label)
        label_widget.setObjectName("metricLabel")
        value_widget = QLabel(value)
        value_widget.setObjectName("metricValue")
        value_widget.setWordWrap(True)
        layout.addWidget(label_widget)
        layout.addWidget(value_widget)
        return card

    @staticmethod
    def _metric_value(card: QFrame) -> QLabel:
        return card.findChildren(QLabel)[1]

    @staticmethod
    def format_record_time(record_name: str, now: datetime | None = None) -> str:
        if not record_name:
            return ""
        try:
            record_time = datetime.strptime(record_name, "%Y%m%d_%H%M%S")
        except ValueError:
            return ""

        now = now or datetime.now()
        seconds = max(0, int((now - record_time).total_seconds()))
        if seconds < 60:
            return "刚刚"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}分钟前"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}小时前"
        days = hours // 24
        return f"{days}天前"

    def _refresh_active_record_time(self):
        self.active_record_time_label.setText(
            self.format_record_time(self._active_record_name)
        )

    def _set_active_record(self, record_name: str):
        self._active_record_name = record_name or ""
        self.active_record_value_label.setText(record_name or "暂无数据")
        self._refresh_active_record_time()

    def _build_workflow(self):
        title = QLabel("工作流程")
        title.setObjectName("classTitle")
        self.main_layout.addWidget(title)

        cards = QHBoxLayout()
        cards.setSpacing(16)
        process_card = self._make_action_card(
            "01", "获取最新数据", "下载班级数据，并自动完成同步与拆分。"
        )
        process_layout = process_card.layout()
        self.download_btn = QPushButton("下载最新数据")
        self.download_btn.setObjectName("primaryButton")
        process_layout.addWidget(self.download_btn)
        cards.addWidget(process_card, 2)

        results_card = self._make_action_card(
            "02", "查看与分析", "打开拆分结果或查看班级学习趋势。"
        )
        results_layout = results_card.layout()
        result_buttons = QHBoxLayout()
        self.open_split_dir_btn = QPushButton("打开拆分数据")
        self.chart_btn = QPushButton("查看趋势图")
        result_buttons.addWidget(self.open_split_dir_btn)
        result_buttons.addWidget(self.chart_btn)
        results_layout.addLayout(result_buttons)
        cards.addWidget(results_card, 3)

        sync_card = self._make_action_card(
            "03", "同步在线文档", "将最新课程与作业数据写入企业微信文档。"
        )
        sync_layout = sync_card.layout()
        sync_buttons = QHBoxLayout()
        self.sync_wedoc_btn = QPushButton("同步企业微信")
        self.config_btn = QPushButton("本班配置")
        self.config_btn.setObjectName("ghostButton")
        sync_buttons.addWidget(self.sync_wedoc_btn)
        sync_buttons.addWidget(self.config_btn)
        sync_layout.addLayout(sync_buttons)
        cards.addWidget(sync_card, 3)
        self.main_layout.addLayout(cards)

    @staticmethod
    def _make_action_card(number: str, title: str, description: str) -> QFrame:
        card = QFrame()
        card.setObjectName("actionCard")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(8)
        number_label = QLabel(number)
        number_label.setObjectName("stepNumber")
        title_label = QLabel(title)
        title_label.setObjectName("classTitle")
        description_label = QLabel(description)
        description_label.setObjectName("cardDescription")
        description_label.setWordWrap(True)
        layout.addWidget(number_label)
        layout.addWidget(title_label)
        layout.addWidget(description_label)
        layout.addStretch(1)
        return card

    def _build_logs(self):
        card = QFrame()
        card.setObjectName("logCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 18)
        layout.setSpacing(10)
        header = QHBoxLayout()
        title = QLabel("运行日志")
        title.setObjectName("classTitle")
        self.log_clear_btn = QToolButton()
        self.log_clear_btn.setText("清空日志")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.log_clear_btn)
        layout.addLayout(header)
        self.info_label = QPlainTextEdit()
        self.info_label.setReadOnly(True)
        self.info_label.setMaximumBlockCount(2000)
        self.info_label.setPlaceholderText("执行任务后，详细日志会显示在这里。")
        self.info_label.setMinimumHeight(190)
        self.log_clear_btn.clicked.connect(self.info_label.clear)
        layout.addWidget(self.info_label)
        self.main_layout.addWidget(card, 1)

    def set_summary(self, class_name="", record_name="", total=None, active=None, term_number=None):
        display_name = class_name or "请选择一个班级"
        self.class_title_label.setText(display_name)
        self._set_active_record(record_name)
        self._metric_value(self.total_label).setText(str(total) if total is not None else "—")
        self._metric_value(self.active_label).setText(str(active) if active is not None else "—")
        self.status_label.setText("数据已就绪，可以继续处理" if record_name else "等待下载最新数据")

    def set_active_record(self, record_name: str):
        self._set_active_record(record_name)

    def append_log(self, msg: str):
        self.info_label.appendPlainText(msg)

    def bind_global_logger(self, logger):
        logger.log_emitted.connect(self.append_log)

    def clear(self):
        self.set_summary()
        self.info_label.clear()
