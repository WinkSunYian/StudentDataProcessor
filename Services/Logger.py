import sys
from PySide6.QtCore import QObject, Signal


class Logger(QObject):
    """全局日志组件。

    - 通过 Qt 信号在不同线程间安全传递日志
    - 同一份日志既输出到 stdout(终端)又通过信号投递给 UI 日志面板
    - 调用方使用 `Logger.instance().info("xxx")` / `.error("xxx")` 等

    日志格式:`[文件名][级别] 消息内容`,文件名取调用方所在源文件(不含路径与扩展名)。
    """

    LEVELS = {
        "DEBUG": "[DEBUG]",
        "INFO": "[信息]",
        "WARN": "[警告]",
        "ERROR": "[错误]",
        "SUCCESS": "[成功]",
    }

    log_emitted = Signal(str)

    _instance: "Logger | None" = None

    @classmethod
    def instance(cls) -> "Logger":
        if cls._instance is None:
            cls._instance = Logger()
        return cls._instance

    def _emit(self, level: str, msg: str):
        import inspect

        caller_name = self._resolve_caller_filename()
        tag = self.LEVELS.get(level, f"[{level}]")
        out = sys.stdout if level not in ("ERROR",) else sys.stderr

        # 多行消息:每行单独加前缀,逐行 print / 逐行 emit,
        # 否则第一行之后的行在终端和 QPlainTextEdit 中都没有前缀。
        for raw_line in str(msg).splitlines() or [""]:
            line = f"[{caller_name}]{tag} {raw_line}"
            try:
                print(line, file=out, flush=True)
            except Exception:
                pass
            try:
                self.log_emitted.emit(line)
            except RuntimeError:
                pass

    def _resolve_caller_filename(self) -> str:
        """从调用栈中跳过 Logger 自身的帧,返回真实调用方源文件名(无路径无扩展)。"""
        import inspect
        import os as _os

        logger_file = _os.path.abspath(__file__)
        frame = inspect.currentframe()
        try:
            caller_name = "Logger"
            cur = frame.f_back
            while cur is not None:
                src_file = _os.path.abspath(cur.f_code.co_filename)
                if src_file != logger_file:
                    caller_name = _os.path.basename(src_file)
                    if caller_name.endswith(".py"):
                        caller_name = caller_name[:-3]
                    return caller_name
                cur = cur.f_back
            return caller_name
        finally:
            del frame

    def debug(self, msg: str):
        self._emit("DEBUG", msg)

    def info(self, msg: str):
        self._emit("INFO", msg)

    def warn(self, msg: str):
        self._emit("WARN", msg)

    def error(self, msg: str):
        self._emit("ERROR", msg)

    def success(self, msg: str):
        self._emit("SUCCESS", msg)
