import os
import sys
from Services.DirectoryService import DirectoryService
from Services.ExcelSyncService import ExcelSyncService
from Services.ExcelChartService import ExcelChartService
from Services.Logger import Logger

from Views.MainWindow import MainWindow
from Controllers.ClassController import ClassController
from Controllers.FileProcessController import FileProcessController


class AppOrchestrator:
    def __init__(self):
        self.directory_service = None
        self.excel_sync_service = None
        self.excel_chart_service = None

        self.main_window = None
        self.class_controller = None
        self.file_process_controller = None

    def setup(self):
        main_file_path = os.path.abspath(sys.argv[0])
        app_root_dir = os.path.dirname(main_file_path)
        data_root_path = os.path.join(app_root_dir, "data")

        self.directory_service = DirectoryService(data_root=data_root_path)
        self.excel_sync_service = ExcelSyncService()
        self.excel_chart_service = ExcelChartService()

        self.main_window = MainWindow()
        self.main_window.get_file_detail_view().bind_global_logger(Logger.instance())

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

    def get_main_window(self) -> MainWindow:
        return self.main_window

    def get_file_process_controller(self) -> FileProcessController:
        return self.file_process_controller
