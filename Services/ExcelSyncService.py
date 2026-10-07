from PySide6.QtCore import QThread, QObject, Qt
from Services.ExcelExportWorker import ExcelExportWorker
from Services.ShuatiSyncWorker import ShuatiSyncWorker
from Services.XiaogetongSyncWorker import XiaogetongSyncWorker
from Services.Logger import Logger
from Services.MainThread import call_later
from Services.WeDocSyncWorker import WeDocSyncWorker

logger = Logger.instance()

# 上一个任务未结束时拒绝本次调用的理由
BUSY_REASON = "上一个同步任务尚未结束,本次调用已被丢弃"


class _WorkerRelay(QObject):
    """把 worker 的信号排队回主线程,再回调调用方。

    worker 是 `moveToThread` 出去的,信号直接连到普通 Python 函数时回调会跑在
    worker 线程里;那个线程马上就要被收掉,回调链就断了。这里用一个常驻主线程的
    QObject 做中转,保证 `on_progress` / `on_finished` 都落在主线程。
    """

    def __init__(self):
        super().__init__()  # 启动阶段在主线程创建 -> 亲和主线程
        self._thread = None
        self._on_finished = None
        self._on_progress = None

    def bind(self, thread, on_finished, on_progress):
        self._thread = thread
        self._on_finished = on_finished
        self._on_progress = on_progress

    def notify_progress(self, text):
        callback = self._on_progress
        if callback:
            callback(text)

    def notify_finished(self, ok: bool, msg: str):
        # 先快照再清空:on_finished 里可能会立刻启动下一次同步并重新 bind
        thread = self._thread
        callback = self._on_finished
        self._thread = None
        self._on_finished = None
        self._on_progress = None

        if thread is not None:
            # 关键顺序:先把自己的线程收干净,再回调。
            # 否则回调里(批量驱动器)启动下一次同步时,
            # 忙守卫看到的还是本线程 isRunning() == True,会被误判成并发而拒绝。
            thread.quit()
            thread.wait()

        if callback:
            callback(ok, msg)


class ExcelSyncService:
    def __init__(self):
        self._thread = None
        self._worker = None
        self._relay = _WorkerRelay()

    @staticmethod
    def _reject(on_finished, reason: str):
        """忙时补发一次失败回调,避免调用方的回调链卡死。

        旧实现是静默 return —— 没有任何回调,批量驱动器推进不到下一步。

        调用方此刻可能正跑在马上就要结束的工作线程里,所以必须投到主线程
        事件循环;排在工作线程里的定时器会随线程一起消失,回调就永久丢了。
        """
        def _emit():
            if on_finished:
                on_finished(False, reason)

        call_later(_emit)

    def _busy(self, on_finished) -> bool:
        if self._thread is not None and self._thread.isRunning():
            self._reject(on_finished, BUSY_REASON)
            return True
        return False

    def _start(self, worker, on_progress, on_finished) -> bool:
        thread = QThread()
        self._thread = thread
        self._worker = worker
        worker.moveToThread(thread)

        self._relay.bind(thread, on_finished, on_progress)

        thread.started.connect(worker.run)
        if on_progress:
            worker.progress.connect(
                self._relay.notify_progress, Qt.ConnectionType.QueuedConnection
            )
        worker.finished.connect(
            self._relay.notify_finished, Qt.ConnectionType.QueuedConnection
        )

        thread.start()
        return True

    def sync_xiaogetong_data(
        self, record_path: str, e_cookie: str, on_progress=None, on_finished=None
    ):
        """开启后台子线程同步小鹅通作业数据。

        注意:同步完成后的拆分表导出由调用方(controller)负责,
        避免在子线程里嵌套线程/事件循环。
        """
        if self._busy(on_finished):
            return False
        return self._start(
            XiaogetongSyncWorker(record_path, e_cookie), on_progress, on_finished
        )

    def sync_shuati_data(
        self, record_path: str, session_id: str, on_progress=None, on_finished=None
    ):
        """开启后台子线程同步刷题系统数据。

        注意:同步完成后的拆分表导出由调用方(controller)负责。
        """
        if self._busy(on_finished):
            return False
        return self._start(
            ShuatiSyncWorker(record_path, session_id), on_progress, on_finished
        )

    def sync_wedoc_data(
        self,
        record_path: str,
        sheet_id: str,
        doc_id: str = "",
        relative_time: bool = False,
        center_align: bool = True,
        on_progress=None,
        on_finished=None,
    ):
        """开启后台子线程同步课程表、作业表和上次活跃时间到企业微信在线文档。

        relative_time=True 时,上次活跃时间写成「3 小时前」这类相对时间,
        否则写完整绝对时间(本班配置项)。
        center_align=True 时给有值格带上水平居中格式,关掉则不碰格式、同步更快
        (本班配置项)。
        """
        if self._busy(on_finished):
            return False
        return self._start(
            WeDocSyncWorker(record_path, sheet_id, doc_id, relative_time, center_align),
            on_progress,
            on_finished,
        )

    def export_split_tables(self, record_path: str, on_progress=None, on_finished=None):
        """单独触发拆分表导出的异步接口"""
        if self._busy(on_finished):
            return False
        return self._start(
            ExcelExportWorker(record_path), on_progress, on_finished
        )
