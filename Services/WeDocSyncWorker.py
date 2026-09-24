import json
import os
import re
import subprocess
import time

import pandas as pd
from PySide6.QtCore import QObject, Signal

from Services.Logger import Logger

logger = Logger.instance()

SUBPROCESS_CREATION_FLAGS = 0x08000000 if os.name == "nt" else 0

NODE_EXE = "node"
WECOM_CLI = "wecom-cli.cmd"

# 在线文档中课程表和作业表的起始列索引（从 0 开始计数）
ONLINE_START_COLUMN = 27
# 在线文档中作业表的起始列索引（从 0 开始计数）
HOMEWORK_ONLINE_START_COLUMN = 60

NUMBER_START = 1
NUMBER_END = 32

MAX_RETRIES = 3
RETRY_DELAY = 2


class WeDocSyncWorker(QObject):
    """企业微信在线文档后台同步 Worker"""

    progress = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, record_path: str, sheet_id: str, doc_id: str = ""):
        super().__init__()
        self.record_path = record_path
        self.sheet_id = sheet_id.strip()
        self.doc_id = doc_id.strip()
        self.split_path = os.path.join(record_path, "split")
        self.course_path = os.path.join(self.split_path, "course.xlsx")
        self.homework_path = os.path.join(self.split_path, "homework.xlsx")

    def _build_env(self) -> dict:
        env = os.environ.copy()
        # node 和 wecom-cli 均通过 PATH 解析，无需手动拼接路径
        return env

    def _check_environment(self):
        logger.info("检查企业微信在线文档同步环境")

        env = self._build_env()

        result = subprocess.run(
            [NODE_EXE, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=SUBPROCESS_CREATION_FLAGS,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Node.js 执行失败：\n{result.stderr}")

        logger.info(f"Node 版本：{result.stdout.strip()}")

        result = subprocess.run(
            [WECOM_CLI, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            shell=False,
            creationflags=SUBPROCESS_CREATION_FLAGS,
        )

        logger.info(f"wecom-cli returncode：{result.returncode}")
        logger.info(f"wecom-cli：{result.stdout.strip() or result.stderr.strip()}")

        if result.returncode != 0:
            raise RuntimeError("wecom-cli 无法正常运行")

        logger.info("环境检查通过")

    def _run_wecom_cli(self, args: list[str]) -> str:
        """执行 wecom-cli 命令，失败自动重试。

        调用方应通过 progress 信号自行输出日志，本方法内部不打印进度。
        """
        env = self._build_env()
        last_exception = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = subprocess.run(
                    [WECOM_CLI, *args],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                    shell=False,
                    creationflags=SUBPROCESS_CREATION_FLAGS,
                )

                if result.returncode == 0:
                    return result.stdout

                error_msg = (
                    f"returncode={result.returncode}\n"
                    f"stdout:\n{result.stdout}\n"
                    f"stderr:\n{result.stderr}"
                )
                raise RuntimeError(error_msg)
            except Exception as exc:
                last_exception = exc
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)

        raise RuntimeError(
            f"wecom-cli 连续执行 {MAX_RETRIES} 次均失败。"
            f"最后一次报错信息:\n{last_exception}"
        )

    @staticmethod
    def parse_student_row(student_id) -> int | None:
        if pd.isna(student_id):
            return None

        student_id = str(student_id).strip()
        match = re.search(r"(\d{3})[A-Za-z]$", student_id)
        if not match:
            return None

        return int(match.group(1)) + 2

    @staticmethod
    def is_non_empty(value) -> bool:
        if pd.isna(value):
            return False
        return str(value).strip() != ""

    @staticmethod
    def get_number_columns(df: pd.DataFrame) -> list[int]:
        result = []
        for number in range(NUMBER_START, NUMBER_END + 1):
            if str(number) in df.columns:
                result.append(number)
        return result

    @staticmethod
    def get_contiguous_ranges(numbers: list[int]) -> list[tuple[int, int]]:
        if not numbers:
            return []

        numbers = sorted(numbers)
        ranges = []
        start = numbers[0]
        previous = numbers[0]

        for number in numbers[1:]:
            if number == previous + 1:
                previous = number
                continue

            ranges.append((start, previous))
            start = number
            previous = number

        ranges.append((start, previous))
        return ranges

    @staticmethod
    def build_grid_data(
        row_number: int,
        start_number: int,
        values: list,
        online_start_column: int,
    ) -> dict:
        return {
            "start_row": row_number - 1,
            "start_column": online_start_column + (start_number - NUMBER_START),
            "rows": [
                {
                    "values": [
                        {
                            "data_type": "TEXT",
                            "cell_value": {"text": str(value).strip()},
                        }
                        for value in values
                    ]
                }
            ],
        }

    def _sync_student(
        self,
        course_row: pd.Series,
        homework_row: pd.Series,
        course_number_columns: list[int],
        homework_number_columns: list[int],
        completed: int,
        total: int,
    ) -> tuple[str, str, str]:
        """同步单个学生的数据（课程+作业，各自独立区间分别调用）。

        返回值：(状态, 学号, 备注)
        状态: success / skip / error
        """
        student_id = course_row["学号"]
        online_row = self.parse_student_row(student_id)

        if online_row is None:
            return "skip", student_id, "无法解析学号"

        # 收集所有需要写入的区间：(start_number, end_number, online_start_column, source_row)
        write_ranges = []

        course_non_empty = [
            number
            for number in course_number_columns
            if self.is_non_empty(course_row[str(number)])
        ]
        if course_non_empty:
            for start_number, end_number in self.get_contiguous_ranges(course_non_empty):
                write_ranges.append(
                    (start_number, end_number, ONLINE_START_COLUMN, course_row)
                )

        homework_non_empty = [
            number
            for number in homework_number_columns
            if self.is_non_empty(homework_row[str(number)])
        ]
        if homework_non_empty:
            for start_number, end_number in self.get_contiguous_ranges(homework_non_empty):
                write_ranges.append(
                    (start_number, end_number, HOMEWORK_ONLINE_START_COLUMN, homework_row)
                )

        if not write_ranges:
            return "skip", student_id, "没有需要同步的数据"

        # 逐个区间调用 wecom-cli（每个区间只写一行，避免越界）
        for start_number, end_number, online_start_column, source_row in write_ranges:
            values = [
                source_row[str(number)]
                for number in range(start_number, end_number + 1)
            ]
            grid_data = self.build_grid_data(
                row_number=online_row,
                start_number=start_number,
                values=values,
                online_start_column=online_start_column,
            )

            try:
                self._run_wecom_cli(
                    [
                        "sheet",
                        "contents",
                        "update",
                        "--docid",
                        self.doc_id,
                        "--sheet-id",
                        self.sheet_id,
                        "--grid-data",
                        json.dumps(grid_data, ensure_ascii=False),
                    ]
                )
            except Exception as exc:
                return (
                    "error",
                    student_id,
                    f"第 {online_row} 行 编号 {start_number}~{end_number} 失败: {exc}",
                )

        return "success", student_id, f"第 {online_row} 行"

    def _sync_table(
        self,
        course_path: str,
        homework_path: str,
    ) -> tuple[int, int, int]:
        """同步课程表+作业表，合并为一次 wecom-cli 调用。

        返回值：(成功数, 跳过数, 失败数)
        """
        logger.info(f"读取 Excel：{course_path}")
        try:
            course_df = pd.read_excel(course_path, dtype=str)
        except PermissionError:
            raise PermissionError(
                f"读取课程表 Excel 失败：文件被占用，请关闭后重试"
            )
        except Exception as exc:
            raise RuntimeError(f"读取课程表 Excel 失败：{exc}") from exc

        logger.info(f"读取 Excel：{homework_path}")
        try:
            homework_df = pd.read_excel(homework_path, dtype=str)
        except PermissionError:
            raise PermissionError(
                f"读取作业表 Excel 失败：文件被占用，请关闭后重试"
            )
        except Exception as exc:
            raise RuntimeError(f"读取作业表 Excel 失败：{exc}") from exc

        required_columns = ["学号", "真实姓名", "计数"]
        for label, df in (("课程表", course_df), ("作业表", homework_df)):
            missing_columns = [
                column for column in required_columns if column not in df.columns
            ]
            if missing_columns:
                raise ValueError(
                    f"{label} Excel 缺少字段：{', '.join(missing_columns)}"
                )

        course_number_columns = self.get_number_columns(course_df)
        homework_number_columns = self.get_number_columns(homework_df)
        if not course_number_columns and not homework_number_columns:
            raise ValueError("Excel 中没有找到编号列")

        logger.info(
            f"课程编号列：{course_number_columns} | 作业编号列：{homework_number_columns}"
        )

        # 按学号对齐两个表
        course_index = {
            str(row["学号"]).strip(): row for _, row in course_df.iterrows()
        }
        homework_index = {
            str(row["学号"]).strip(): row for _, row in homework_df.iterrows()
        }

        # 合并学号集合（以课程表为主，作业表补充）
        all_student_ids = list(course_index.keys())
        for sid in homework_index:
            if sid not in course_index:
                all_student_ids.append(sid)

        # 过滤出需要同步的行
        tasks = []
        skip_count = 0

        for student_id in all_student_ids:
            course_row = course_index.get(student_id)
            homework_row = homework_index.get(student_id)

            online_row = self.parse_student_row(student_id)
            if online_row is None:
                skip_count += 1
                continue

            course_non_empty = [
                number
                for number in course_number_columns
                if course_row is not None
                and self.is_non_empty(course_row[str(number)])
            ]
            homework_non_empty = [
                number
                for number in homework_number_columns
                if homework_row is not None
                and self.is_non_empty(homework_row[str(number)])
            ]

            if not course_non_empty and not homework_non_empty:
                skip_count += 1
                continue

            tasks.append((student_id, course_row, homework_row))

        total = len(tasks)
        logger.info(
            f"开始同步 | 待同步：{total} | 跳过：{skip_count}"
        )

        success_count = 0
        error_count = 0
        completed = 0

        for student_id, course_row, homework_row in tasks:
            completed += 1

            try:
                status, result_student_id, message = self._sync_student(
                    course_row,
                    homework_row,
                    course_number_columns,
                    homework_number_columns,
                    completed,
                    total,
                )
            except Exception as exc:
                error_count += 1
                logger.info(
                    f"[{completed}/{total}] "
                    f"学号 {student_id} | 失败 | 异常: {exc}"
                )
                continue

            if status == "success":
                success_count += 1
                logger.info(
                    f"[{completed}/{total}] "
                    f"学号 {result_student_id} | 成功 | {message}"
                )
            elif status == "skip":
                skip_count += 1
                logger.info(
                    f"[{completed}/{total}] "
                    f"学号 {result_student_id} | 跳过 | {message}"
                )
            else:
                error_count += 1
                logger.info(
                    f"[{completed}/{total}] "
                    f"学号 {result_student_id} | 失败 | {message}"
                )

        logger.info(
            f"同步完成 | 成功：{success_count} | "
            f"跳过：{skip_count} | 失败：{error_count}"
        )
        return success_count, skip_count, error_count

    def run(self):
        try:
            if not self.sheet_id:
                self.finished.emit(False, "SHEET_ID 不能为空")
                return

            if not self.doc_id:
                self.finished.emit(False, "DOC_ID 不能为空")
                return

            if not os.path.exists(self.course_path):
                self.finished.emit(False, f"找不到课程表：{self.course_path}")
                return

            if not os.path.exists(self.homework_path):
                self.finished.emit(False, f"找不到作业表：{self.homework_path}")
                return

            self._check_environment()

            result = self._sync_table(
                self.course_path,
                self.homework_path,
            )

            success_count, skip_count, error_count = result

            if error_count:
                self.finished.emit(
                    False,
                    f"在线文档同步完成但存在失败：成功 {success_count}，"
                    f"跳过 {skip_count}，失败 {error_count}",
                )
                return

            self.finished.emit(
                True,
                f"在线文档同步完成：成功 {success_count}，"
                f"共跳过 {skip_count}",
            )
        except Exception as exc:
            logger.error(f"企业微信在线文档同步异常：{exc}")
            self.finished.emit(False, f"企业微信在线文档同步失败：{exc}")
