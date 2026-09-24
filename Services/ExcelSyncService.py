from PySide6.QtCore import QThread
from Services.ExcelExportWorker import ExcelExportWorker
from Services.ShuatiSyncWorker import ShuatiSyncWorker
from Services.XiaogetongSyncWorker import XiaogetongSyncWorker
from Services.Logger import Logger
from Services.WeDocSyncWorker import WeDocSyncWorker

logger = Logger.instance()


class ExcelSyncService:
    def __init__(self):
        self._thread = None
        self._worker = None

    def sync_xiaogetong_data(
        self, record_path: str, e_cookie: str, on_progress=None, on_finished=None
    ):
        """开启后台子线程同步小鹅通作业数据。

        注意:同步完成后的拆分表导出由调用方(controller)负责,
        避免在子线程里嵌套线程/事件循环。
        """
        if self._thread is not None and self._thread.isRunning():
            return

        self._thread = QThread()
        self._worker = XiaogetongSyncWorker(record_path, e_cookie)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)

        if on_progress:
            self._worker.progress.connect(on_progress)

        def handle_finished(success: bool, msg: str):
            if on_finished:
                on_finished(success, msg)
            if self._thread:
                self._thread.quit()
                self._thread.wait()

        self._worker.finished.connect(handle_finished)
        self._thread.start()

    def sync_shuati_data(
        self, record_path: str, session_id: str, on_progress=None, on_finished=None
    ):
        """开启后台子线程同步刷题系统数据。

        注意:同步完成后的拆分表导出由调用方(controller)负责。
        """
        if self._thread is not None and self._thread.isRunning():
            return

        self._thread = QThread()
        self._worker = ShuatiSyncWorker(record_path, session_id)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)

        if on_progress:
            self._worker.progress.connect(on_progress)

        def handle_finished(success: bool, msg: str):
            if on_finished:
                on_finished(success, msg)
            if self._thread:
                self._thread.quit()
                self._thread.wait()

        self._worker.finished.connect(handle_finished)
        self._thread.start()

    def sync_wedoc_data(
        self, record_path: str, sheet_id: str, doc_id: str, on_progress=None, on_finished=None
    ):
        """开启后台子线程同步课程表和作业表到企业微信在线文档。"""
        if self._thread is not None and self._thread.isRunning():
            return

        self._thread = QThread()
        self._worker = WeDocSyncWorker(record_path, sheet_id, doc_id)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)

        if on_progress:
            self._worker.progress.connect(on_progress)

        def handle_finished(success: bool, msg: str):
            if on_finished:
                on_finished(success, msg)
            if self._thread:
                self._thread.quit()
                self._thread.wait()

        self._worker.finished.connect(handle_finished)
        self._thread.start()

    def export_split_tables(self, record_path: str, on_progress=None, on_finished=None):
        """单独触发拆分表导出的异步接口"""
        if self._thread is not None and self._thread.isRunning():
            return

        self._thread = QThread()
        self._worker = ExcelExportWorker(record_path)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)

        if on_progress:
            self._worker.progress.connect(on_progress)

        def handle_finished(success: bool, msg: str):
            if on_finished:
                on_finished(success, msg)
            if self._thread:
                self._thread.quit()
                self._thread.wait()

        self._worker.finished.connect(handle_finished)
        self._thread.start()
