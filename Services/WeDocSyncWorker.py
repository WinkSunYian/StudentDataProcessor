import json
import os
import re
import subprocess
import time

import pandas as pd
from PySide6.QtCore import QObject, Signal

from Services.LastActiveService import LastActiveService
from Services.Logger import Logger

logger = Logger.instance()

SUBPROCESS_CREATION_FLAGS = 0x08000000 if os.name == "nt" else 0

NODE_EXE = "node"
WECOM_CLI = "wecom-cli.cmd"

# 在线文档的列位(0 基索引):
#   AA(26) = 上次活跃时间 | AC(28)~BH(59) = 课程 | BJ(61)~CO(92) = 作业
#   AB(27) 是上一次插入新列后留下的间隔列,不同步
LAST_ACTIVE_COLUMN = 26
ONLINE_START_COLUMN = 28
# 在线文档中作业表的起始列索引（从 0 开始计数）
HOMEWORK_ONLINE_START_COLUMN = 61

NUMBER_START = 1
NUMBER_END = 32

MAX_RETRIES = 3
RETRY_DELAY = 2

# wecom-cli.cmd 由 cmd.exe 执行，其命令行硬上限为 8191 字符，超出会报「命令行太长。」。
# 这里按完整命令行（含 list2cmdline 对 JSON 内引号的翻倍）计长并留出余量。
MAX_CMD_CHARS = 7900


class WeDocSyncWorker(QObject):
    """企业微信在线文档后台同步 Worker"""

    progress = Signal(str)
    finished = Signal(bool, str)

    def __init__(
        self,
        record_path: str,
        sheet_id: str,
        doc_id: str = "",
        relative_time: bool = False,
    ):
        super().__init__()
        self.record_path = record_path
        self.sheet_id = sheet_id.strip()
        self.doc_id = doc_id.strip()
        # 上次活跃时间是否按相对时间(「3 小时前」)显示,由本班配置决定
        self.relative_time = relative_time
        self.split_path = os.path.join(record_path, "split")
        self.course_path = os.path.join(self.split_path, "course.xlsx")
        self.homework_path = os.path.join(self.split_path, "homework.xlsx")
        self.last_active_path = os.path.join(self.split_path, "last_active.xlsx")

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
    def build_grid_data(
        rows: list[int],
        start_column: int,
        end_column: int,
        cells: dict[int, dict[int, str]],
    ) -> dict:
        """构造一个矩形区块的 grid_data。

        rows 为 1 基行号列表，start_column/end_column 为 0 基绝对列闭区间；
        rows × 列区间内的每个单元格都必须已存在于 cells 中。
        """
        return {
            "start_row": rows[0] - 1,
            "start_column": start_column,
            "rows": [
                {
                    "values": [
                        {
                            "data_type": "TEXT",
                            "cell_value": {"text": cells[row][column]},
                        }
                        for column in range(start_column, end_column + 1)
                    ]
                }
                for row in rows
            ],
        }

    @staticmethod
    def build_cli_args(doc_id: str, sheet_id: str, grid_json: str) -> list[str]:
        return [
            "sheet",
            "contents",
            "update",
            "--docid",
            doc_id,
            "--sheet-id",
            sheet_id,
            "--grid-data",
            grid_json,
        ]

    def _command_length(
        self,
        rows: list[int],
        start_column: int,
        end_column: int,
        cells: dict[int, dict[int, str]],
    ) -> int:
        """区块写入时实际交给 cmd.exe 的命令行长度。

        注意 list2cmdline 会把 JSON 内的双引号翻倍，因此不能只看 JSON 长度。
        """
        grid = self.build_grid_data(rows, start_column, end_column, cells)
        grid_json = json.dumps(grid, ensure_ascii=False)
        args = [WECOM_CLI, *self.build_cli_args(self.doc_id, self.sheet_id, grid_json)]
        return len(subprocess.list2cmdline(args))

    def _split_rows_to_fit(
        self,
        rows: list[int],
        start_column: int,
        end_column: int,
        cells: dict[int, dict[int, str]],
    ) -> list[list[int]]:
        """按命令行长度上限把行切成若干块（二分查找最大可容纳行数，每块至少 1 行）。"""
        chunks: list[list[int]] = []
        rest = list(rows)
        while rest:
            low, high, take = 1, len(rest), 1
            while low <= high:
                mid = (low + high) // 2
                if (
                    self._command_length(rest[:mid], start_column, end_column, cells)
                    <= MAX_CMD_CHARS
                ):
                    take = mid
                    low = mid + 1
                else:
                    high = mid - 1
            chunks.append(rest[:take])
            rest = rest[take:]
        return chunks

    def pack_blocks(
        self, cells: dict[int, dict[int, str]]
    ) -> list[tuple[list[int], int, int]]:
        """把稀疏单元格打包成最少的矩形区块。

        cells 形如 {1 基行号: {0 基绝对列: 文本}}，
        返回 [(rows, start_column, end_column), ...]。

        每个区块都保证「区域内全部单元格都待写入」，因此不会覆盖未指定的单元格；
        数据连续时自然合并成一块，遇到行断点或列断点才切开；
        单个区块受命令行长度上限约束，超限时按行再切分。
        """
        remaining = {row: set(columns) for row, columns in cells.items() if columns}
        blocks: list[tuple[list[int], int, int]] = []

        while remaining:
            row = min(remaining)
            start_column = min(remaining[row])
            end_column = start_column
            while end_column + 1 in remaining[row]:
                end_column += 1

            # 沿行号向下延伸：后续每一行都必须完整包含该列区间
            rows = [row]
            probe = row + 1
            while probe in remaining and all(
                column in remaining[probe]
                for column in range(start_column, end_column + 1)
            ):
                rows.append(probe)
                probe += 1

            for chunk in self._split_rows_to_fit(rows, start_column, end_column, cells):
                blocks.append((chunk, start_column, end_column))
                for packed_row in chunk:
                    remaining[packed_row].difference_update(
                        range(start_column, end_column + 1)
                    )
                    if not remaining[packed_row]:
                        del remaining[packed_row]

        return blocks

    def _load_last_active(self) -> dict[str, str]:
        """读拆分目录里的 last_active.xlsx,返回 {学号: 要写进 AA 列的文本}。

        文件不存在(老记录)就返回空 dict,本次同步跳过上次活跃时间列;
        是否转成相对时间由本班配置的 relative_time 决定。
        """
        if not os.path.exists(self.last_active_path):
            logger.info("未找到 last_active.xlsx,本次不同步「上次活跃时间」列")
            return {}

        try:
            df = pd.read_excel(self.last_active_path, dtype=str)
        except Exception as e:
            logger.error(f"读取 last_active.xlsx 失败,跳过该列: {e}")
            return {}

        if "学号" not in df.columns or "上次活跃时间" not in df.columns:
            logger.warn("last_active.xlsx 缺少学号/上次活跃时间列,跳过该列")
            return {}

        result: dict[str, str] = {}
        for _, row in df.iterrows():
            raw_sid = row["学号"]
            raw_time = row["上次活跃时间"]
            if pd.isna(raw_sid) or pd.isna(raw_time):
                continue
            sid = str(raw_sid).strip()
            text = str(raw_time).strip()
            if not sid or not text:
                continue
            if self.relative_time:
                text = LastActiveService.format_relative(text)
            result[sid] = text
        return result

    def _sync_table(
        self,
        course_path: str,
        homework_path: str,
    ) -> tuple[int, int, int]:
        """同步课程表+作业表+上次活跃时间：先收集全部待写单元格，再按连续区域分块写入。

        连续的数据合并成一个矩形区块、只调用一次 wecom-cli，
        只有遇到行或列断点才切开，因此调用次数远小于学生人数。
        上次活跃时间单独占 AA 列，和课程块之间隔着 AB 间隔列，自然会切成独立区块。

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

        # 收集所有待写单元格：{1 基行号: {0 基绝对列: 文本}}
        cells: dict[int, dict[int, str]] = {}
        student_rows: dict[str, int] = {}
        skip_count = 0
        last_active_index = self._load_last_active()

        for student_id in all_student_ids:
            course_row = course_index.get(student_id)
            homework_row = homework_index.get(student_id)

            online_row = self.parse_student_row(student_id)
            if online_row is None:
                skip_count += 1
                logger.info(f"学号 {student_id} | 跳过 | 无法解析学号")
                continue

            row_cells: dict[int, str] = {}
            for source_row, number_columns, online_start_column in (
                (course_row, course_number_columns, ONLINE_START_COLUMN),
                (homework_row, homework_number_columns, HOMEWORK_ONLINE_START_COLUMN),
            ):
                if source_row is None:
                    continue
                for number in number_columns:
                    value = source_row[str(number)]
                    if not self.is_non_empty(value):
                        continue
                    row_cells[online_start_column + (number - NUMBER_START)] = str(
                        value
                    ).strip()

            # 上次活跃时间写进 AA 列;没有别的数据也要写,否则掉队的人反而同步不到
            active_value = last_active_index.get(student_id)
            if active_value:
                row_cells[LAST_ACTIVE_COLUMN] = active_value

            if not row_cells:
                skip_count += 1
                logger.info(f"学号 {student_id} | 跳过 | 没有需要同步的数据")
                continue

            cells.setdefault(online_row, {}).update(row_cells)
            student_rows[student_id] = online_row

        # 把连续的单元格合并成矩形区块，每个区块只调用一次 wecom-cli
        blocks = self.pack_blocks(cells)
        logger.info(
            f"开始同步 | 待同步：{len(student_rows)} | 跳过：{skip_count} | 区块：{len(blocks)}"
        )

        failed_blocks: set[int] = set()

        for index, (rows, start_column, end_column) in enumerate(blocks, start=1):
            grid_data = self.build_grid_data(rows, start_column, end_column, cells)
            label = (
                f"行 {rows[0]}~{rows[-1]} 列 {start_column}~{end_column}"
                f" | {len(rows)} 行 × {end_column - start_column + 1} 列"
            )

            try:
                self._run_wecom_cli(
                    self.build_cli_args(
                        self.doc_id,
                        self.sheet_id,
                        json.dumps(grid_data, ensure_ascii=False),
                    )
                )
                logger.info(f"[{index}/{len(blocks)}] 区块 {label} | 成功")
            except Exception as exc:
                failed_blocks.add(index - 1)
                row_set = set(rows)
                affected = sorted(
                    sid for sid, row in student_rows.items() if row in row_set
                )
                shown = ", ".join(affected[:10]) + ("…" if len(affected) > 10 else "")
                logger.info(
                    f"[{index}/{len(blocks)}] 区块 {label} | 失败"
                    f" | 学号 {shown} | {exc}"
                )

        # 行号 -> 该行涉及的区块
        row_blocks: dict[int, set[int]] = {}
        for block_index, (rows, _start, _end) in enumerate(blocks):
            for row in rows:
                row_blocks.setdefault(row, set()).add(block_index)

        success_count = 0
        failed_students: list[str] = []
        for student_id, online_row in student_rows.items():
            if row_blocks.get(online_row, set()) & failed_blocks:
                failed_students.append(student_id)
            else:
                success_count += 1

        error_count = len(failed_students)
        if failed_students:
            logger.info(f"写入失败的学号：{', '.join(sorted(failed_students))}")

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
