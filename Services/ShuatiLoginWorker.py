import base64
import hashlib
import traceback

import pyaes
import requests

from PySide6.QtCore import QObject, Signal

from Services.Logger import Logger

logger = Logger.instance()


BASE_URL = "http://124.221.200.10"
TIMEOUT = 30

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
    "Content-Type": "application/json",
    "Origin": BASE_URL,
    "Proxy-Connection": "keep-alive",
    "Referer": f"{BASE_URL}/admin/users",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36 Edg/153.0.0.0"
    ),
}

SECRET = "44sk7qzkveFEVDZd1XHGDArX6CYrAckp593mPW_I0HI"


def encrypt_password(password: str) -> str:
    """
    AES-256-CBC + PKCS7
    与前端 CryptoJS 的加密逻辑保持一致。
    """
    sha256_obj = hashlib.sha256(SECRET.encode("utf-8"))
    key = sha256_obj.digest()
    iv = bytes.fromhex(sha256_obj.hexdigest()[:32])

    block_size = 16
    data = password.encode("utf-8")
    padding_length = block_size - (len(data) % block_size)
    padded_data = data + bytes([padding_length]) * padding_length

    aes = pyaes.AESModeOfOperationCBC(key, iv=iv)

    encrypted_data = bytearray()
    for i in range(0, len(padded_data), block_size):
        block = padded_data[i : i + block_size]
        encrypted_data.extend(aes.encrypt(block))

    return base64.b64encode(bytes(encrypted_data)).decode("utf-8")


def login(admin_id: str, password: str) -> str:
    """
    登录刷题系统并获取 sessionid。
    使用专门的 /api/csrf-token 接口初始化并获取 CSRF Token。
    """
    if not admin_id:
        raise ValueError("刷题系统管理员账号未配置")

    if not password:
        raise ValueError("刷题系统管理员密码未配置")

    session = requests.Session()
    session.headers.update(HEADERS)

    # 1. 访问专用接口初始化获取 csrftoken Cookie
    csrf_res = session.get(f"{BASE_URL}/api/csrf-token", timeout=TIMEOUT)
    csrf_res.raise_for_status()

    csrftoken = session.cookies.get("csrftoken")
    if not csrftoken:
        raise RuntimeError("未能从 /api/csrf-token 接口获取到 csrftoken Cookie")

    # 2. 对明文密码进行加密
    encrypted_password = encrypt_password(password)

    login_data = {
        "role": "admin",
        "admin_id": admin_id,
        "password": encrypted_password,
    }

    # 3. 携带 X-CSRFToken 请求头发送登录请求
    response = session.post(
        f"{BASE_URL}/api/auth/login",
        headers={"X-CSRFToken": csrftoken},
        json=login_data,
        timeout=TIMEOUT,
    )

    response.raise_for_status()

    # 4. 获取登录返回的 sessionid
    session_id = session.cookies.get("sessionid") or response.cookies.get(
        "sessionid"
    )

    if not session_id:
        raise RuntimeError("登录未返回 sessionid Cookie，请检查账号、密码或登录接口。")

    return session_id


def verify_sessionid(session_id: str) -> bool:
    """
    验证 sessionid 是否仍然有效。
    """
    if not session_id:
        return False

    try:
        response = requests.get(
            f"{BASE_URL}/api/admin/classes",
            headers=HEADERS,
            cookies={
                "sessionid": session_id,
            },
            timeout=10,
        )

        response.raise_for_status()

        return response.json().get("code") == 0

    except Exception:
        return False


class ShuatiLoginWorker(QObject):
    """
    刷题系统登录 Worker。
    """

    finished = Signal(bool, str)

    def __init__(
        self,
        admin_id: str,
        password: str,
    ):
        super().__init__()

        self.admin_id = admin_id
        self.password = password

    def run(self):
        try:
            logger.info("开始获取刷题系统 sessionid...")

            session_id = login(
                self.admin_id,
                self.password,
            )

            logger.info("刷题系统 sessionid 获取成功")

            self.finished.emit(
                True,
                session_id,
            )

        except Exception as e:
            logger.error(
                f"获取刷题系统 sessionid 异常: {e}\n{traceback.format_exc()}"
            )

            self.finished.emit(
                False,
                f"获取刷题系统 sessionid 失败: {e}",
            )