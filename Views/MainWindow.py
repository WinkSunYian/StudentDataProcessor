from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout
from Views.ClassTabBarView import ClassTabBarView
from Views.FileDetailView import FileDetailView


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("逸安老师的学生数据中心")
        self.resize(1440, 900)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.class_tab_bar_view = ClassTabBarView()
        self.file_detail_view = FileDetailView()

        self.main_layout.addWidget(self.class_tab_bar_view)
        self.main_layout.addWidget(self.file_detail_view, stretch=1)

    def get_class_tab_bar_view(self) -> ClassTabBarView:
        return self.class_tab_bar_view

    def get_file_detail_view(self) -> FileDetailView:
        return self.file_detail_view
