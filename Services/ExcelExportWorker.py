from PySide6.QtCore import QObject, Signal
from Services.ExcelExportService import ExcelExportService
from Services.Logger import Logger

logger = Logger.instance()


class ExcelExportWorker(QObject):
    """拆分表导出后台工作线程 Worker"""

    progress = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, record_path: str):
        super().__init__()
        self.record_path = record_path

    def run(self):
        logger.info("正在开始解析并拆分数据表...")
        exporter = ExcelExportService()
        success, msg = exporter.export_split_tables(self.record_path)
        if success:
            logger.success(
                "拆分表保存完成:course.xlsx / homework.xlsx / "
                "finished_course_homework.xlsx / last_active.xlsx"
            )
            self.finished.emit(True, msg)
        else:
            self.finished.emit(False, msg)
