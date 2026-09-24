import json
import time
import http.cookies
import requests
from Services.Logger import Logger

logger = Logger.instance()


class XiaoeTechClient:
    """负责与小鹅通 API 交互的客户端"""

    BASE_URL = "https://admin.xiaoe-tech.com"

    def __init__(self, cookie_str: str):
        self.cookie_str = cookie_str
        self.cookies_dict = self._parse_cookie_string(cookie_str)
        self.headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9",
            "cache-control": "no-cache",
            "content-type": "application/json;charset=UTF-8",
            "origin": self.BASE_URL,
            "pragma": "no-cache",
            "priority": "u=1, i",
            "referer": f"{self.BASE_URL}/t/exam/exercise",
            "sec-ch-ua": '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
            "x-requested-with": "XMLHttpRequest",
        }

    @staticmethod
    def _parse_cookie_string(cookie_str: str) -> dict:
        cookie_obj = http.cookies.SimpleCookie()
        try:
            cookie_obj.load(cookie_str)
            return {key: morsel.value for key, morsel in cookie_obj.items()}
        except Exception:
            return {}

    def get_exercise_book_id(self, class_name: str, log_func=None) -> str:
        log = log_func or logger.warn
        url = f"{self.BASE_URL}/xe.homework.get_exercise_book_list"
        for page in range(1, 6):
            payload = json.dumps(
                {"page_index": page, "search_content": ""}, separators=(",", ":")
            )
            try:
                response = requests.post(
                    url, headers=self.headers, cookies=self.cookies_dict, data=payload, timeout=10
                )
                if len(response.text) <= 1:
                    continue

                res = response.json()
                for item in res.get("data", {}).get("list", []):
                    if class_name in item.get("title", ""):
                        return item.get("exercise_book_id", "")
            except Exception as e:
                log_func(f"获取 exercise_book_id 第 {page} 页失败: {e}")
                continue

        return ""

    def get_exercise_list(self, exercise_book_id: str) -> dict:
        url = f"{self.BASE_URL}/xe.homework.get_exercise_list"
        payload = json.dumps(
            {
                "exercise_book_id": exercise_book_id,
                "search_content": "",
                "page_index": 1,
                "page_size": 40,
            },
            separators=(",", ":"),
        )
        try:
            response = requests.post(
                url, headers=self.headers, cookies=self.cookies_dict, data=payload, timeout=10
            )
            res = response.json()
            exercise_list = res.get("data", {}).get("list", [])
            return {
                item["title"].split(" ")[0]: item["exercise_id"]
                for item in exercise_list
                if "title" in item and "exercise_id" in item
            }
        except Exception:
            return {}

    def get_exercise_user_ids(self, exercise_book_id: str, exercise_id: str) -> list:
        url = f"{self.BASE_URL}/xe.homework.get_exercise_user_list"
        data = {
            "exercise_book_id": exercise_book_id,
            "exercise_id": exercise_id,
            "page_size": "250",
            "page_index": "1",
        }
        time.sleep(0.3)
        try:
            response = requests.post(
                url, data=data, headers={"Cookie": self.cookie_str}, timeout=10
            )
            res = response.json()
            return [
                item["answer_user_id"]
                for item in res.get("data", {}).get("list", [])
                if "answer_user_id" in item
            ]
        except Exception:
            return []