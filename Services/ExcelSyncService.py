from PySide6.QtCore import QThread, QTimer
from Services.ExcelExportWorker import ExcelExportWorker
from Services.ShuatiSyncWorker import ShuatiSyncWorker
from Services.XiaogetongSyncWorker import XiaogetongSyncWorker
from Services.Logger import Logger
from Services.WeDocSyncWorker import WeDocSyncWorker

logger = Logger.instance()

# 上一个任务未结束时拒绝本次调用的理由
BUSY_REASON = "上一个同步任务尚未结束,本次调用已被丢弃"


class ExcelSyncService:
    def __init__(self):
        self._thread = None
        self._worker = None

    @staticmethod
    def _reject(on_finished, reason: str):
        """忙时补发一次失败回调,避免调用方的回调链卡死。

        旧实现是静默 return —— 没有任何回调,批量驱动器推进不到下一步。
        """
        def _emit():
            if on_finished:
                on_finished(False, reason)

        QTimer.singleShot(0, _emit)

    def _busy(self, on_finished) -> bool:
        if self._thread is not None and self._thread.isRunning():
            self._reject(on_finished, BUSY_REASON)
            return True
        return False

    def sync_xiaogetong_data(
        self, record_path: str, e_cookie: str, on_progress=None, on_finished=None
    ):
        """开启后台子线程同步小鹅通作业数据。

        注意:同步完成后的拆分表导出由调用方(controller)负责,
        避免在子线程里嵌套线程/事件循环。
        """
        if self._busy(on_finished):
            return False

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
        return True

    def sync_shuati_data(
        self, record_path: str, session_id: str, on_progress=None, on_finished=None
    ):
        """开启后台子线程同步刷题系统数据。

        注意:同步完成后的拆分表导出由调用方(controller)负责。
        """
        if self._busy(on_finished):
            return False

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
        return True

    def sync_wedoc_data(
        self, record_path: str, sheet_id: str, doc_id: str, on_progress=None, on_finished=None
    ):
        """开启后台子线程同步课程表和作业表到企业微信在线文档。"""
        if self._busy(on_finished):
            return False

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
        return True

    def export_split_tables(self, record_path: str, on_progress=None, on_finished=None):
        """单独触发拆分表导出的异步接口"""
        if self._busy(on_finished):
            return False

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
        return True
