import os
import re
import pandas as pd
from PySide6.QtCore import QObject, Signal
from Services.ShuatiApiClient import ShuatiApiClient
from Services.Logger import Logger

logger = Logger.instance()


class ShuatiSyncWorker(QObject):
    """刷题系统后台同步线程 Worker"""

    progress = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, record_path: str, session_id: str):
        super().__init__()
        self.record_path = record_path
        self.session_id = session_id
        self.data_excel_path = os.path.join(record_path, "data.xlsx")
        self.patch_excel_path = os.path.join(record_path, "patch.xlsx")

    def _extract_class_code_num(self, record_path: str) -> str:
        """从 record_path 中提取 class 下层文件夹名称中的 pyxxx 里的 xxx 数字部分"""
        norm_path = os.path.normpath(record_path)
        parts = norm_path.split(os.sep)

        folder_name = ""
        for i, part in enumerate(parts):
            if part.lower() == "class" and i + 1 < len(parts):
                folder_name = parts[i + 1]
                break

        if not folder_name:
            folder_name = os.path.basename(norm_path)

        match = re.search(r"py(\d+)", folder_name, re.IGNORECASE)
        if match:
            return match.group(1)

        digits = re.findall(r"\d+", folder_name)
        if digits:
            return digits[-1]

        return folder_name

    def run(self):
        if not os.path.exists(self.data_excel_path):
            self.finished.emit(False, f"找不到本地 Excel 文件: {self.data_excel_path}")
            return

        if not self.session_id:
            self.finished.emit(False, "刷题系统 SessionID 不能为空！")
            return

        class_num = self._extract_class_code_num(self.record_path)
        logger.info(f"解析得到的目标班级编号: '{class_num}'")

        client = ShuatiApiClient(self.session_id)

        logger.info("正在请求刷题系统班级列表...")
        classes = client.get_classes()
        if not classes:
            self.finished.emit(
                False, "获取刷题系统班级列表失败，请检查 SessionID 是否过期！"
            )
            return

        matched_class = None
        for item in classes:
            code = str(item.get("code", "")).lower()
            name = str(item.get("name", "")).lower()

            if (
                code == f"py{class_num}"
                or code.endswith(class_num)
                or class_num in name
            ):
                matched_class = item
                break

        if not matched_class:
            self.finished.emit(
                False,
                f"刷题系统中未找到匹配编号 '{class_num}' (py{class_num}) 的班级！",
            )
            return

        class_id = matched_class["id"]
        course_ids = matched_class.get("primary_course_ids", [2])
        course_id = course_ids[0] if course_ids else 2

        logger.info(
            f"已匹配班级: {matched_class.get('name')} (ID: {class_id})，开始下载最新成绩单..."
        )
        download_success = client.export_achievement_records(
            course_id, class_id, self.patch_excel_path
        )
        if not download_success:
            self.finished.emit(False, "从刷题系统导出成绩 Excel 失败！")
            return

        logger.info("成绩单下载成功，开始读取并处理数据...")

        try:
            data = pd.read_excel(self.data_excel_path)
            patch_data = pd.read_excel(self.patch_excel_path)
        except PermissionError:
            self.finished.emit(
                False, "读取 Excel 失败：文件被其他程序占用，请关闭后重试！"
            )
            return
        except Exception as e:
            self.finished.emit(False, f"读取 Excel 异常: {e}")
            return

        if "学号" not in data.columns or "学号" not in patch_data.columns:
            self.finished.emit(False, "Excel 文件中丢失 '学号' 列，无法进行数据合并！")
            return

        last_c = ""
        for c in patch_data.columns:
            if str(c).startswith("第"):
                next_val = f"{int(last_c) + 1}" if last_c.isdigit() else "1"
                patch_data.rename(columns={c: next_val}, inplace=True)
                last_c = next_val
            else:
                last_c = str(c)

        if not last_c.isdigit():
            self.finished.emit(False, "未能在导出的成绩单中解析出有效的课程列信息！")
            return

        max_lesson = int(last_c)
        update_dict = {}
        exception_dict = {}
        existing_users = set(data["学号"])

        for user in patch_data["学号"]:
            if user not in existing_users:
                exception_dict[user] = True
                continue

            for i in range(1, max_lesson + 1):
                col_name = f"{i}"
                target_col = f"第{i}节课"

                if col_name not in patch_data.columns or target_col not in data.columns:
                    continue

                patch_rows = patch_data.loc[patch_data["学号"] == user, col_name].values
                if len(patch_rows) == 0 or pd.isna(patch_rows[0]):
                    continue

                value = str(patch_rows[0])
                parts = value.split("/")
                homework = parts[0]

                if homework != "完成":
                    continue

                data_rows = data.loc[data["学号"] == user, target_col].values
                if len(data_rows) == 0 or pd.isna(data_rows[0]):
                    continue

                orig_value = str(data_rows[0])
                if "/" not in orig_value:
                    continue

                orig_course, orig_homework = orig_value.split("/", 1)

                if orig_homework.strip() == "作":
                    continue

                data.loc[data["学号"] == user, target_col] = f"{orig_course}/作"
                update_dict[user] = True

        log_msg = (
            f"刷题系统数据同步完成！\n"
            f"- 已更新数据条数: {len(update_dict)}\n"
            f"- 异常数据条数(patch有但data无): {len(exception_dict)}"
        )
        logger.info(log_msg)

        try:
            data.to_excel(self.data_excel_path, index=False)
            if os.path.exists(self.patch_excel_path):
                os.remove(self.patch_excel_path)
            self.finished.emit(True, log_msg)
        except PermissionError:
            self.finished.emit(
                False, "保存 Excel 失败：文件被占用，请关闭 Excel 后重试！"
            )
        except Exception as e:
            self.finished.emit(False, f"保存 Excel 失败: {e}")
