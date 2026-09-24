import os
import re
import pandas as pd
from PySide6.QtCore import QObject, Signal
from Services.XiaoeTechClient import XiaoeTechClient
from Services.Logger import Logger

logger = Logger.instance()


class XiaogetongSyncWorker(QObject):
    """小鹅通后台同步线程 Worker"""
    progress = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, record_path: str, e_cookie: str):
        super().__init__()
        self.record_path = record_path
        self.e_cookie = e_cookie
        self.excel_path = os.path.join(record_path, "data.xlsx")

    def _extract_course_title(self, record_path: str) -> str:
        """从记录目录的上一层（即班级文件夹名称）中截取括号内的小鹅通课程名"""
        class_dir_name = os.path.basename(os.path.dirname(record_path))
        match = re.search(r"[（\(](.*?)[）\)]", class_dir_name)
        if match:
            return match.group(1).strip()
        return class_dir_name.strip()

    def run(self):
        if not os.path.exists(self.excel_path):
            self.finished.emit(False, f"找不到 Excel 文件: {self.excel_path}")
            return

        if not self.e_cookie:
            self.finished.emit(False, "Ecookie 不能为空！")
            return

        target_class_title = self._extract_course_title(self.record_path)
        logger.info(f"从班级目录解析得到小鹅通课程名: '{target_class_title}'")

        client = XiaoeTechClient(self.e_cookie)

        logger.info("正在获取小鹅通 exercise_book_id...")
        book_id = client.get_exercise_book_id(target_class_title, log_func=logger.info)
        if not book_id:
            self.finished.emit(False, f"未找到课程 '{target_class_title}'，请检查课程名称或 Cookie 是否有效。")
            return

        logger.info("正在获取作业列表 (exercise_list)...")
        exercise_map = client.get_exercise_list(book_id)
        if not exercise_map:
            self.finished.emit(False, "未获取到作业列表。")
            return

        logger.info(f"获取到 {len(exercise_map)} 门作业，开始抓取作业提交用户数据...")
        homework_data = {}
        for idx, (prefix, ex_id) in enumerate(exercise_map.items(), 1):
            logger.info(f"[{idx}/{len(exercise_map)}] 正在抓取第 {prefix} 课作业用户...")
            user_ids = client.get_exercise_user_ids(book_id, ex_id)
            homework_data[prefix] = user_ids

        logger.info("抓取完毕，开始更新本地 Excel 数据...")
        try:
            df = pd.read_excel(self.excel_path)
        except PermissionError:
            self.finished.emit(False, "读写 Excel 权限被拒绝，请检查文件是否被 Excel 打开占用。")
            return
        except Exception as e:
            self.finished.emit(False, f"读取 Excel 失败: {e}")
            return

        if "关联小鹅通用户ID" not in df.columns:
            self.finished.emit(False, "Excel 表格中未找到列 '关联小鹅通用户ID'，无法匹配！")
            return

        exception_dict = {}
        update_dict = {}

        for i in range(1, 33):
            key = f"{i:02d}"
            user_ids = homework_data.get(key, [])
            col_name = f"第{i}节课"

            if col_name not in df.columns:
                continue

            for uid in user_ids:
                cond = df["关联小鹅通用户ID"] == uid
                if cond.any():
                    matched_indices = df[cond].index
                    for idx_row in matched_indices:
                        val = str(df.loc[idx_row, col_name])
                        parts = val.split("/")
                        course = parts[0]
                        homework = parts[1] if len(parts) > 1 else "无"

                        if homework == "无":
                            update_dict[uid] = True

                        df.loc[idx_row, col_name] = f"{course}/作"
                else:
                    exception_dict[uid] = True

        log_msg = (
            f"小鹅通数据同步完成！\n"
            f"- 已更新数据条数: {len(update_dict)}\n"
            f"- 异常数据条数(小鹅通有但Excel无): {len(exception_dict)}"
        )
        logger.info(log_msg)

        try:
            df.to_excel(self.excel_path, index=False)
            self.finished.emit(True, log_msg)
        except PermissionError:
            self.finished.emit(False, "保存 Excel 时权限被拒绝，请关闭打开该 Excel 的程序后重试。")
        except Exception as e:
            self.finished.emit(False, f"保存 Excel 失败: {e}")
