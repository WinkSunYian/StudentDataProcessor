import json
import os
from datetime import datetime

import pandas as pd

from Services.ExcelExportService import ExcelExportService
from Services.Logger import Logger

logger = Logger.instance()

# 索引文件,放在班级目录下(与该班 config.json 同级)
INDEX_FILE_NAME = "last_active_index.json"
# 完整绝对时间(年月日时分),存进 Excel 与索引的统一格式
ABSOLUTE_TIME_FORMAT = "%Y-%m-%d %H:%M"
# 记录目录名:YYYYMMDD_HHMMSS,同秒重名会追加 _01 等后缀
_RECORD_STAMP_FORMAT = "%Y%m%d_%H%M%S"
_RECORD_STAMP_LEN = len("YYYYMMDD_HHMMSS")


class LastActiveService:
    """上次活跃时间服务。

    口径:把班级下的记录按时间从旧到新逐条推进,每个学员维护一份
    「课程状态 + 作业状态」的字母向量(直/录/缺/到/销 → T/F/D/X,
    作业 作 → T),只要向量发生变化,就把**该条记录**的时间记为他的
    上次活跃时间。于是得到的正是「拿最新一条往回比,第一次发现不一样」
    的那条记录时间;从头到尾没变过的学员,用他首次出现的那条记录时间。

    用完整状态向量而不是完课数,是为了不漏掉「正在看但还没看完这一节」
    这类不改变完课数的变化。

    索引 last_active_index.json 增量维护:首次运行把班级里已有的记录
    全量回填一遍,之后每来一条新记录只读它自己的 data.xlsx(实测约 0.3s),
    因此记录无限保留也不会变慢。
    """

    @staticmethod
    def _index_path(class_dir: str) -> str:
        return os.path.join(class_dir, INDEX_FILE_NAME)

    @staticmethod
    def _record_names(class_dir: str) -> list[str]:
        """班级目录下所有带 data.xlsx 的记录目录,按时间升序。"""
        if not os.path.isdir(class_dir):
            return []
        names = [
            name
            for name in os.listdir(class_dir)
            if os.path.isdir(os.path.join(class_dir, name))
            and os.path.isfile(os.path.join(class_dir, name, "data.xlsx"))
        ]
        return sorted(names)

    @staticmethod
    def _stamp_time(record_name: str) -> datetime | None:
        try:
            return datetime.strptime(
                str(record_name)[:_RECORD_STAMP_LEN], _RECORD_STAMP_FORMAT
            )
        except (ValueError, TypeError):
            return None

    @classmethod
    def _load_index(cls, class_dir: str) -> dict:
        path = cls._index_path(class_dir)
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("students"), dict):
                    return data
                logger.warn(f"上次活跃时间索引结构异常,将重新回填: {path}")
            except Exception as e:
                logger.warn(f"上次活跃时间索引读取失败,将重新回填: {e}")
        return {"students": {}, "applied": ""}

    @classmethod
    def _save_index(cls, class_dir: str, index: dict) -> None:
        path = cls._index_path(class_dir)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)

    @staticmethod
    def _read_states(data_path: str) -> dict[str, str]:
        """读一个记录的 data.xlsx,返回 {学号: 课程状态|作业状态}。"""
        data = pd.read_excel(data_path)
        data.columns = data.columns.str.strip()

        status_col = next(
            (col for col in data.columns if "学员学籍状态" in str(col)), None
        )
        if status_col is not None:
            data = data[data[status_col] == "在读"]

        lesson_cols = [f"第{i}节课" for i in range(1, 33)]
        lesson_cols = [col for col in lesson_cols if col in data.columns]
        if not lesson_cols or "学号" not in data.columns:
            return {}

        target = data[lesson_cols]
        mapper = target.map if hasattr(target, "map") else target.applymap
        course_letters = mapper(ExcelExportService.parse_course)
        assign_letters = mapper(ExcelExportService.parse_homework)

        states: dict[str, str] = {}
        for pos, raw_sid in enumerate(data["学号"].tolist()):
            if pd.isna(raw_sid):
                continue
            sid = str(raw_sid).strip()
            if not sid:
                continue
            course_state = "".join(str(v) for v in course_letters.iloc[pos].tolist())
            assign_state = "".join(str(v) for v in assign_letters.iloc[pos].tolist())
            states[sid] = f"{course_state}|{assign_state}"
        return states

    def compute(self, record_dir: str) -> dict[str, str]:
        """推进索引到 record_dir,返回该记录里 {学号: 上次活跃时间(绝对时间)}。"""
        record_dir = os.path.abspath(record_dir)
        class_dir = os.path.dirname(record_dir)
        target = os.path.basename(record_dir)

        records = self._record_names(class_dir)
        if target not in records:
            raise FileNotFoundError(f"记录 {target} 下没有 data.xlsx")

        index = self._load_index(class_dir)
        students: dict[str, dict] = index["students"]
        applied = str(index.get("applied") or "")
        pending = [name for name in records if name > applied]

        if pending and applied:
            logger.info(f"上次活跃时间:推进 {len(pending)} 条新记录")
        elif pending:
            logger.info(f"上次活跃时间:首次回填 {len(pending)} 条历史记录")

        target_states: dict[str, str] | None = None
        for name in pending:
            path = os.path.join(class_dir, name, "data.xlsx")
            try:
                states = self._read_states(path)
            except Exception as e:
                # 当前记录读不出来直接抛出,避免索引标成已处理却没吃到数据
                if name == target:
                    raise
                logger.error(f"上次活跃时间:读取 {name} 失败,跳过该条: {e}")
                index["applied"] = name
                continue

            if name == target:
                target_states = states

            for sid, state in states.items():
                current = students.get(sid)
                # 首次出现 → 记首次出现的记录时间;其后只要状态变了就刷新
                if current is None or current.get("state") != state:
                    students[sid] = {"state": state, "active": name}
            index["applied"] = name

        self._save_index(class_dir, index)

        if target_states is None:
            target_states = self._read_states(os.path.join(record_dir, "data.xlsx"))

        result: dict[str, str] = {}
        for sid in target_states:
            active_name = (students.get(sid) or {}).get("active") or target
            stamp = self._stamp_time(active_name)
            result[sid] = stamp.strftime(ABSOLUTE_TIME_FORMAT) if stamp else ""
        return result

    @staticmethod
    def format_relative(abs_time: str, now: datetime | None = None) -> str:
        """把绝对时间转成「刚刚 / 3 分钟前 / 5 小时前 / 2 天前」这类相对时间。"""
        text = str(abs_time or "").strip()
        if not text:
            return ""
        try:
            moment = datetime.strptime(text, ABSOLUTE_TIME_FORMAT)
        except ValueError:
            return text

        reference = now or datetime.now()
        seconds = (reference - moment).total_seconds()
        if seconds < 0:
            return "刚刚"
        if seconds < 60:
            return "刚刚"
        if seconds < 3600:
            return f"{int(seconds // 60)} 分钟前"
        if seconds < 86400:
            return f"{int(seconds // 3600)} 小时前"
        if seconds < 86400 * 30:
            return f"{int(seconds // 86400)} 天前"
        return f"{int(seconds // (86400 * 30))} 个月前"
