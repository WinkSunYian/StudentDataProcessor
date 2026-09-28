import os
import sys
from Services.DirectoryService import DirectoryService
from Services.ExcelSyncService import ExcelSyncService
from Services.ExcelChartService import ExcelChartService
from Services.Logger import Logger
from Services.UpdateService import is_packaged

from Views.MainWindow import MainWindow
from Controllers.ClassController import ClassController
from Controllers.FileProcessController import FileProcessController
from Controllers.UpdateController import UpdateController

# 本地数据根目录名,位于 %APPDATA% 下
DATA_ROOT_DIR_NAME = "StudentDataProcessor"


def resolve_data_root() -> str:
    """本地数据根目录:%APPDATA%\\StudentDataProcessor。

    取不到 APPDATA(非 Windows 等)时退回旧规则:<程序目录>/data。
    """
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        return os.path.join(appdata, DATA_ROOT_DIR_NAME)
    return os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "data")


class AppOrchestrator:
    def __init__(self):
        self.directory_service = None
        self.excel_sync_service = None
        self.excel_chart_service = None

        self.main_window = None
        self.class_controller = None
        self.file_process_controller = None
        self.update_controller = None

    def setup(self):
        data_root_path = resolve_data_root()

        self.directory_service = DirectoryService(data_root=data_root_path)
        self.excel_sync_service = ExcelSyncService()
        self.excel_chart_service = ExcelChartService()

        self.main_window = MainWindow()
        self.main_window.get_file_detail_view().bind_global_logger(Logger.instance())
        Logger.instance().info(f"本地数据目录: {data_root_path}")

        self.class_controller = ClassController(
            class_tab_bar_view=self.main_window.get_class_tab_bar_view(),
            directory_service=self.directory_service,
        )

        self.file_process_controller = FileProcessController(
            main_window=self.main_window,
            file_detail_view=self.main_window.get_file_detail_view(),
            class_tab_bar_view=self.main_window.get_class_tab_bar_view(),
            directory_service=self.directory_service,
            excel_sync_service=self.excel_sync_service,
            excel_chart_service=self.excel_chart_service,
            class_controller=self.class_controller,
        )

        self.class_controller.initialize_classes()

        # 自动更新:仅打包版生效,源码运行时按钮隐藏、不排启动检查
        self.update_controller = UpdateController(
            main_window=self.main_window,
            file_detail_view=self.main_window.get_file_detail_view(),
            directory_service=self.directory_service,
        )
        if is_packaged():
            self.update_controller.schedule_startup_check()

    def get_main_window(self) -> MainWindow:
        return self.main_window

    def get_file_process_controller(self) -> FileProcessController:
        return self.file_process_controller

    def get_update_controller(self) -> "UpdateController":
        return self.update_controller
