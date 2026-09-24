import os
import re
import time
import urllib.parse
import requests
import bs4
from Services.Logger import Logger

logger = Logger.instance()

SYNC_POLL_INTERVAL = 5  # 两次同步状态轮询的间隔(秒)


class JihuaApiClient:
    """计划学院(xs.jihuaxueyuan.com)HTTP 客户端,封装 test.py 中的下载 Excel 流程。"""

    BASE_URL = "https://xs.jihuaxueyuan.com"
    HEADERS = {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "origin": "https://xs.jihuaxueyuan.com",
        "referer": "https://xs.jihuaxueyuan.com/jihua/term/term",
        "sec-ch-ua": '"Chromium";v="152", "Not?A_Brand";v="24", "Google Chrome";v="152"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
        "x-requested-with": "XMLHttpRequest",
    }

    def __init__(self, jsessionid: str):
        self.jsessionid = jsessionid
        self.cookies = {"JSESSIONID": jsessionid} if jsessionid else {}

    # ---------------- 工具 ----------------
    @staticmethod
    def extract_term_number(text: str) -> int | None:
        """从班级名/学期别名里抓首个数字,例如 'Py140期' / 'Python140' -> 140。"""
        m = re.search(r"(\d+)", text or "")
        if not m:
            return None
        try:
            return int(m.group(1))
        except ValueError:
            return None

    @staticmethod
    def verify_jsessionid(jsessionid: str) -> bool:
        """通过调用学期列表接口验证 JSESSIONID 是否有效。"""
        if not jsessionid:
            return False
        client = JihuaApiClient(jsessionid)
        try:
            client.list_terms()
            return True
        except Exception:
            return False

    @staticmethod
    def fetch_jsessionid_from_dingtalk(account: str, password: str) -> str:
        """通过钉钉账号密码自动获取 JSESSIONID。"""
        if not account or not password:
            raise ValueError("钉钉账号或密码未配置")

        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36 Edg/138.0.0.0",
            }
        )

        url = "https://xs.jihuaxueyuan.com/jihua/auth/dingtalk/ODg4OA"
        logger.info(f"正在请求钉钉登录页面: {url}")
        resp = session.get(url)
        resp.raise_for_status()

        soup = bs4.BeautifulSoup(resp.text, features="lxml")
        script_blocks = soup.find_all("script")
        if len(script_blocks) < 3:
            raise RuntimeError("无法从登录页面提取二维码 URL")
        target_script = script_blocks[2].text
        lines = target_script.split("\n")
        if len(lines) < 2:
            raise RuntimeError("无法从脚本中提取二维码 URL")
        qr_login_url = lines[1].split(" = ")[1][1:-2]
        password_login_page = qr_login_url.split("=")[-1]
        ODg4OA = urllib.parse.unquote_plus(password_login_page).split("=")[-1]

        dingtalk_login_template_url = (
            "https://login.dingtalk.com/login/index.htm?goto=https%3A%2F%2F"
            "oapi.dingtalk.com%2Fconnect%2Foauth2%2Fsns_authorize%3F"
            "response_type%3Dcode%26appid%3Ddingbyrgij7ipkdxdknc%26"
            "scope%3Dsnsapi_login%26redirect_uri%3Dhttps%3A%2F%2F"
            "xs.jihuaxueyuan.com%2Fjihua%2Fauth%2Fcallback%2Fdingtalk%26state%3D"
        )
        dingtalk_url = dingtalk_login_template_url + ODg4OA

        login_headers = {
            "Origin": "https://login.dingtalk.com",
            "Referer": dingtalk_url,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36 Edg/138.0.0.0",
        }
        login_url = "https://login.dingtalk.com/login/login_with_pwd"
        data = {
            "mobile": f"+86-{account}",
            "pwd": password,
            "goto": (
                f"https://oapi.dingtalk.com/connect/oauth2/sns_authorize"
                f"?response_type=code&appid=dingbyrgij7ipkdxdknc"
                f"&scope=snsapi_login"
                f"&redirect_uri=https://xs.jihuaxueyuan.com/jihua/auth/callback/dingtalk"
                f"&state={ODg4OA}"
            ),
            "pdmToken": "",
            "araAppkey": "1917",
            "araToken": "0#19171753686591613322622626821754378296925776G6C0D512CD373977946CF199753BA219F0CC987",
            "araScene": "login",
            "captchaImgCode": "",
            "captchaSessionId": "",
            "type": "h5",
        }
        logger.info("正在提交钉钉账号密码登录...")
        resp = session.post(login_url, headers=login_headers, data=data)
        resp.raise_for_status()
        result = resp.json()
        if "data" not in result:
            raise RuntimeError(f"钉钉登录失败: {result}")
        ding_api_url = result["data"]

        s = requests.Session()
        logger.info(f"正在获取 JSESSIONID: {ding_api_url}")
        s.get(ding_api_url)
        cookies_dict = requests.utils.dict_from_cookiejar(s.cookies)
        jsessionid = cookies_dict.get("JSESSIONID")
        if not jsessionid:
            raise RuntimeError("未能从钉钉响应中提取 JSESSIONID")
        return jsessionid

    # ---------------- API ----------------
    def list_terms(self) -> list[dict]:
        """获取学期列表。

        失败或返回结构异常时,抛出 RuntimeError,提示用户更新 JSESSIONID。
        """
        url = f"{self.BASE_URL}/jihua/term/term/list"
        r = requests.post(url, headers=self.HEADERS, cookies=self.cookies, timeout=30)
        r.raise_for_status()
        try:
            data = r.json()
        except ValueError as e:
            raise RuntimeError(f"学期列表接口返回非 JSON 数据: {e}") from e

        if not isinstance(data, dict) or "rows" not in data:
            hint = data.get("msg") if isinstance(data, dict) else None
            detail = f"({hint})" if hint else ""
            raise RuntimeError(
                f"学期列表响应缺少 'rows' 字段{detail},JSESSIONID 可能已失效,请更新后重试"
            )

        return data.get("rows", [])

    def trigger_remote_sync(self, term_id: str | int) -> bool:
        """通知服务器把该学期的课程数据和作业数据同步到最新。

        课程和作业两个接口**都**返回 `code=500` 且 `msg` 包含
        "未超过半小时" 或 "请先同步班期课表" 时,说明数据已经是最新 —— 返回 True。

        其它任意情况视为"数据仍在同步中",每隔 5 秒重新请求一次,
        最多重试 60 次(5 分钟)后抛出 RuntimeError。
        """
        course_url = f"{self.BASE_URL}/jihua/term/termXeSync/syncTermStudentLiveData"
        homework_url = f"{self.BASE_URL}/jihua/term/termXeSync/syncTermStudentHomework"
        body = f"termId={term_id}".encode("utf-8", "surrogateescape")

        FRESH_MSG_KEYWORDS = ("未超过半小时", "请先同步班期课表")
        MAX_ATTEMPTS = 60

        for attempt in range(1, MAX_ATTEMPTS + 1):
            all_fresh = True
            for label, url in (("课程", course_url), ("作业", homework_url)):
                try:
                    r = requests.post(
                        url,
                        headers=self.HEADERS,
                        cookies=self.cookies,
                        data=body,
                        timeout=60,
                    )
                    r.raise_for_status()
                    payload = r.json()
                except (requests.RequestException, ValueError) as e:
                    logger.warn(f"[{label}同步] 请求/解析失败: {e}")
                    all_fresh = False
                    continue

                if not isinstance(payload, dict):
                    logger.info(f"[{label}同步] 响应: {payload}")
                    all_fresh = False
                    continue

                code = payload.get("code")
                msg = payload.get("msg", "")
                logger.info(f"[{label}同步] code={code} msg={msg}")

                if not (code == 500 and isinstance(msg, str)
                        and any(kw in msg for kw in FRESH_MSG_KEYWORDS)):
                    all_fresh = False

            if all_fresh:
                logger.success("课程和作业数据均已同步到最新,可以继续下载")
                return True

            logger.info(
                f"数据仍在同步中,{SYNC_POLL_INTERVAL} 秒后重新查询"
                f"(第 {attempt}/{MAX_ATTEMPTS} 次)..."
            )
            time.sleep(SYNC_POLL_INTERVAL)

        raise RuntimeError(
            f"数据同步轮询超过 {MAX_ATTEMPTS} 次仍未就绪,请稍后重试"
        )

    def find_term_id(self, term_number: int) -> str | None:
        """根据期号数字查找 termId。"""
        for row in self.list_terms():
            alias = str(row.get("termAlias", ""))
            if str(term_number) in alias:
                return row.get("termId")
        return None

    def trigger_export(self, term_id: str | int) -> str:
        """触发导出任务,返回远端生成的文件名(含 .xlsx 后缀)。"""
        url = f"{self.BASE_URL}/jihua/report/term/ReportTermStudentStudyData/export"
        data = (
            "params%5BselectType%5D=liveorrelive30minAndHomework&studentNo=&"
            "nickname=&mobile=&xeuid=&status=&params%5BfinishCount%5D=&"
            "params%5BactionStatus%5D=&params%5BabsenceLiveClassNoS%5D=&"
            "params%5BabsenceLiveClassNoE%5D=&params%5BabsenceHomeworkClassNoS%5D=&"
            "params%5BabsenceHomeworkClassNoE%5D=&"
            "params%5BagreedCompensationLiveTimeS%5D=&"
            "params%5BagreedCompensationLiveTimeE%5D=&"
            "params%5BagreedCompensationSubmitTimeS%5D=&"
            "params%5BagreedCompensationSubmitTimeE%5D=&homeworkFocus=&"
            "orderByColumn=&isAsc=asc"
        )
        r = requests.post(
            url,
            headers=self.HEADERS,
            cookies=self.cookies,
            params={"termId": term_id},
            data=data.encode("utf-8", "surrogateescape"),
            timeout=60,
        )
        r.raise_for_status()
        result = r.json()
        if result.get("code") != 0:
            raise RuntimeError(f"导出触发失败: {result}")
        return result.get("msg", "")

    def download_file(self, filename: str, save_to: str) -> str:
        """根据远端文件名下载 Excel 字节流到本地路径,返回文件大小(字节)。"""
        dl_url = (
            f"{self.BASE_URL}/jihua/common/download?fileName="
            + urllib.parse.quote(filename)
            + "&delete=true"
        )
        resp = requests.get(dl_url, headers=self.HEADERS, cookies=self.cookies, timeout=120)
        resp.raise_for_status()
        with open(save_to, "wb") as f:
            f.write(resp.content)
        return f"{len(resp.content) / 1024:.1f} KB"


def download_term_excel(jsessionid: str, term_number: int, save_to: str) -> tuple[bool, str]:
    """一键下载指定期号的完课作业明细 Excel 到本地路径。

    返回 (ok, message)。message 在失败时为错误信息,成功时为保存路径。
    """
    if not jsessionid:
        return False, "JSESSIONID 未配置"

    client = JihuaApiClient(jsessionid)
    try:
        logger.info(f"正在查询学期列表,目标期号: {term_number}")
        term_id = client.find_term_id(term_number)
        if not term_id:
            return False, f"未找到期号 {term_number} 对应的学期"

        logger.info("已通知服务器同步课程与作业数据(将持续轮询直到数据就绪)...")
        if not client.trigger_remote_sync(term_id):
            return False, "数据同步轮询被中断"

        logger.info(f"已匹配 termId: {term_id},触发导出任务...")
        filename = client.trigger_export(term_id)
        if not filename:
            return False, "导出接口未返回文件名"
        logger.info(f"远端文件名: {filename},开始下载...")

        size_str = client.download_file(filename, save_to)
        return True, f"下载成功: {save_to} ({size_str})"
    except requests.RequestException as e:
        return False, f"网络请求失败: {e}"
    except Exception as e:
        return False, f"下载失败: {e}"