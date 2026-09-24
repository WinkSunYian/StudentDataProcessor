import os
import tempfile
from PySide6.QtCore import QObject, Signal
from Services.JihuaApiClient import download_term_excel
from Services.DirectoryService import DirectoryService
from Services.Logger import Logger

logger = Logger.instance()


class JihuaDownloadWorker(QObject):
    """后台子线程:仅做网络下载,落盘到临时文件,不创建业务记录目录。

    后续的"导入记录目录 -> 同步 -> 拆分"由 controller 串行执行,
    任一步骤失败时整体回滚(删除刚刚创建的记录目录 + 临时文件)。
    """

    progress = Signal(str)
    finished = Signal(bool, str, str)
    """finished(ok, message, tmp_xlsx_path)
    成功时 tmp_xlsx_path 是下载后的本地 xlsx 临时文件路径(由 controller 接管生命周期);
    失败时为空串。
    """

    def __init__(
        self,
        jsessionid: str,
        term_number: int,
        target_class: str,
        dir_service: DirectoryService,
    ):
        super().__init__()
        self.jsessionid = jsessionid
        self.term_number = term_number
        self.target_class = target_class
        self.dir_service = dir_service

    def run(self):
        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp_path = tmp.name

            logger.info(f"开始下载 Py{self.term_number}期 数据...")
            ok, msg = download_term_excel(self.jsessionid, self.term_number, tmp_path)
            if not ok:
                self._cleanup_tmp(tmp_path)
                self.finished.emit(False, msg, "")
                return

            self.finished.emit(True, "下载完成,等待同步与拆分", tmp_path)
        except Exception as e:
            logger.error(f"下载流程异常: {e}")
            self._cleanup_tmp(tmp_path)
            self.finished.emit(False, f"下载流程异常: {e}", "")

    @staticmethod
    def _cleanup_tmp(tmp_path: str):
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
