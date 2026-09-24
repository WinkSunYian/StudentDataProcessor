import traceback
from PySide6.QtCore import QObject, Signal
from Services.JihuaApiClient import JihuaApiClient
from Services.Logger import Logger

logger = Logger.instance()


class JihuaLoginWorker(QObject):
    """后台线程:通过钉钉账号密码获取 JSESSIONID。"""

    progress = Signal(str)
    finished = Signal(bool, str)
    """finished(success, jsessionid_or_error_msg)"""

    def __init__(self, account: str, password: str):
        super().__init__()
        self.account = account
        self.password = password

    def run(self):
        try:
            jsessionid = JihuaApiClient.fetch_jsessionid_from_dingtalk(self.account, self.password)
            self.finished.emit(True, jsessionid)
        except Exception as e:
            logger.error(f"获取 JSESSIONID 异常: {e}\n{traceback.format_exc()}")
            self.finished.emit(False, f"获取 JSESSIONID 失败: {e}")
