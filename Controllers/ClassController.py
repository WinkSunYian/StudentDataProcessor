from PySide6.QtCore import QObject, Signal
from Views.ClassTabBarView import ClassTabBarView
from Services.DirectoryService import DirectoryService


class ClassController(QObject):
    class_changed = Signal(str)
    class_added = Signal(str)

    def __init__(
        self,
        class_tab_bar_view: ClassTabBarView,
        directory_service: DirectoryService,
    ):
        super().__init__()
        self.tab_view = class_tab_bar_view
        self.dir_service = directory_service

        self.tab_view.tab_bar.currentChanged.connect(self.on_tab_changed)
        self.tab_view.add_class_btn.clicked.connect(self.on_add_class_clicked)

    def initialize_classes(self):
        self.tab_view.clear_tabs()
        classes = self.dir_service.get_all_classes()
        for class_name in classes:
            self.tab_view.add_tab(class_name)
        if classes:
            self.tab_view.set_current_tab_by_name(classes[0])

    def rebuild_tabs(self, select_name: str | None = None):
        """清空并重新构建所有班级选项卡,选中指定名称(默认选第一个)。"""
        self.tab_view.clear_tabs()
        classes = self.dir_service.get_all_classes()
        for class_name in classes:
            self.tab_view.add_tab(class_name)
        target = select_name or (classes[0] if classes else "")
        if target:
            self.tab_view.set_current_tab_by_name(target)

    def on_tab_changed(self, index: int):
        class_name = self.tab_view.get_current_class_name()
        self.class_changed.emit(class_name or "")

    def on_add_class_clicked(self):
        input_name = self.tab_view.prompt_create_class_input()
        if not input_name:
            return
        real_name = self.dir_service.create_class_directory(input_name)
        self.rebuild_tabs(select_name=real_name)
        self.class_added.emit(real_name)
        self.class_changed.emit(real_name)
