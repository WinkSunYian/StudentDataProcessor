import http.cookies
import requests


class ShuatiApiClient:
    """负责与刷题系统 API 交互的客户端"""

    BASE_URL = "http://124.221.200.10"

    def __init__(self, session_id: str, csrf_token: str = "YeZpb00Ic8VR5Le9Rn5d9G7d5nnZcoa5"):
        self.session_id = session_id
        self.csrf_token = csrf_token
        self.headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
            "Content-Type": "application/json",
            "Origin": self.BASE_URL,
            "Referer": f"{self.BASE_URL}/admin/records",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
            "X-CSRFToken": self.csrf_token,
        }
        self.cookies = {
            "sessionid": self.session_id,
            "csrftoken": self.csrf_token,
        }

    def get_classes(self) -> list:
        """获取班级列表数据"""
        url = f"{self.BASE_URL}/api/admin/classes"
        try:
            response = requests.get(
                url, headers=self.headers, cookies=self.cookies, verify=False, timeout=10
            )
            res = response.json()
            if res.get("code") == 0:
                return res.get("data", [])
            return []
        except Exception:
            return []

    def export_achievement_records(self, course_id: int, class_id: int, save_path: str) -> bool:
        """从刷题系统导出成绩 Excel 并保存至本地"""
        url = f"{self.BASE_URL}/api/admin/achievement-record-exports"
        payload = f'{{"course_id":{course_id},"class_id":{class_id}}}'.encode("utf-8", "surrogateescape")
        try:
            response = requests.post(
                url, headers=self.headers, cookies=self.cookies, data=payload, verify=False, timeout=30
            )
            if response.status_code == 200:
                with open(save_path, "wb") as f:
                    f.write(response.content)
                return True
            return False
        except Exception:
            return False