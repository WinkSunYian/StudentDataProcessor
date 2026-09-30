"""把回调安全地投递到 GUI 主线程的事件循环。

Qt 把信号连到**普通 Python 函数**时,回调执行在发送方对象所在线程里。
`ExcelSyncService` 的 worker 是 `moveToThread` 出去的,所以 `on_finished`
全都跑在工作线程上;而那个线程紧接着就要被 `quit()/wait()` 收掉 ——
排在它里面的 `QTimer.singleShot` 永远不会再触发,调用方的回调链就此断掉
(「全部同步」跑完第一个班期就卡死,根因就在这里)。

统一走 `call_later`:事件挂到主线程的队列里,发送方线程死掉也不受影响。
"""

from PySide6.QtCore import Qt, QObject, Signal


class _Dispatcher(QObject):
    _call = Signal(object)

    def __init__(self):
        super().__init__()
        # 显式 QueuedConnection:无论从哪个线程 post,
        # 事件都排到本对象(主线程)的事件循环,且必然是异步的
        self._call.connect(self._exec, Qt.ConnectionType.QueuedConnection)

    def _exec(self, fn):
        fn()

    def post(self, fn):
        self._call.emit(fn)


# 模块在启动阶段的主线程被导入,与 Services.Logger 同样的约定
_dispatcher = _Dispatcher()


def call_later(fn):
    """在 GUI 主线程**异步**执行 fn。可从任意线程安全调用。"""
    _dispatcher.post(fn)
