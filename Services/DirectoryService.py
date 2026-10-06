import os
import re
import shutil
import json
from datetime import datetime
from Services.Logger import Logger

logger = Logger.instance()

RECORD_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
RECORD_DIRNAME_PATTERN = re.compile(r"^\d{8}_\d{6}$")

# 记录本身永不删除(每次下载都留一份,历史越全「上次活跃时间」越准),
# 下面这套规则现在只用来给趋势图筛点:当天最多 RECORD_KEEP_TODAY 条,
# 前 1~7 天每天只画该天最晚的 RECORD_KEEP_PREVIOUS_PER_DAY 条,更早的不画
RECORD_KEEP_TODAY = 2
RECORD_KEEP_PREVIOUS_DAYS = 7
RECORD_KEEP_PREVIOUS_PER_DAY = 1


class DirectoryService:
    def __init__(self, data_root: str):
        self.data_root = data_root
        self.class_root = os.path.join(self.data_root, "class")
        self.config_file = os.path.join(self.data_root, "config.json")
        os.makedirs(self.class_root, exist_ok=True)

    def load_config(self) -> dict:
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"读取配置文件失败: {e}")
        return {}

    def save_config(self, key: str, value: str):
        config = self.load_config()
        config[key] = value
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            logger.info(f"配置已保存: {key}")
        except Exception as e:
            logger.error(f"写入配置文件失败: {e}")

    def _class_config_path(self, class_name: str) -> str:
        return os.path.join(self.class_root, class_name, "config.json")

    def load_class_config(self, class_name: str) -> dict:
        path = self._class_config_path(class_name)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"读取班级配置失败 {class_name}: {e}")
        return {}

    def save_class_config(self, class_name: str, key: str, value: str):
        path = self._class_config_path(class_name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        config = self.load_class_config(class_name)
        config[key] = value
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            logger.info(f"班级配置已保存: {class_name}/{key}")
        except Exception as e:
            logger.error(f"写入班级配置失败 {class_name}: {e}")

    def get_all_classes(self) -> list[str]:
        if os.path.exists(self.class_root):
            return [
                d
                for d in os.listdir(self.class_root)
                if os.path.isdir(os.path.join(self.class_root, d))
            ]
        return []

    def create_class_directory(self, class_name: str) -> str:
        class_path = os.path.join(self.class_root, class_name)
        os.makedirs(class_path, exist_ok=True)
        return class_name

    def get_records_in_class(self, class_name: str) -> list[str]:
        class_path = os.path.join(self.class_root, class_name)
        if os.path.exists(class_path):
            return [
                d
                for d in os.listdir(class_path)
                if os.path.isdir(os.path.join(class_path, d))
                and RECORD_DIRNAME_PATTERN.match(d)
            ]
        return []

    @staticmethod
    def select_records_to_keep(
        records: list[str], today: datetime | None = None
    ) -> set[str]:
        """按「每天一条 + 当天最多两条」挑选要显示的记录名(趋势图筛点用)。

        记录文件不会被删除,这个规则只决定哪些记录画进时间轴:

        - 当天:取最新 RECORD_KEEP_TODAY 条;
        - 前 1~7 天:每天只取该天最晚的 RECORD_KEEP_PREVIOUS_PER_DAY 条;
        - 8 天前及更早:不画。

        目录名不是合法日期的一律保留;日期在未来(系统时钟异常)按当天处理。
        该方法不碰磁盘,便于单独测试。
        """
        today_date = (today or datetime.now()).date()
        keep: set[str] = set()
        by_age: dict[int, list[str]] = {}

        for name in records:
            try:
                day = datetime.strptime(name[:8], "%Y%m%d").date()
            except ValueError:
                keep.add(name)
                continue
            age = (today_date - day).days
            if age < 0:
                age = 0
            by_age.setdefault(age, []).append(name)

        for age, names in by_age.items():
            if age == 0:
                limit = RECORD_KEEP_TODAY
            elif age <= RECORD_KEEP_PREVIOUS_DAYS:
                limit = RECORD_KEEP_PREVIOUS_PER_DAY
            else:
                limit = 0
            # 目录名 YYYYMMDD_HHMMSS 字典序即时间序,倒序后取最前的
            keep.update(sorted(names, reverse=True)[:limit])

        return keep

    def get_next_record_dir(self, class_name: str) -> str:
        """在该班级下生成一个新的时间戳记录目录(YYYYMMDD_HHMMSS),保证不重复。"""
        class_path = os.path.join(self.class_root, class_name)
        os.makedirs(class_path, exist_ok=True)

        existing = set(os.listdir(class_path))
        stamp = datetime.now().strftime(RECORD_TIMESTAMP_FORMAT)
        candidate = stamp
        suffix = 0
        while candidate in existing:
            suffix += 1
            candidate = f"{stamp}_{suffix:02d}"
        record_dir = os.path.join(class_path, candidate)
        os.makedirs(record_dir, exist_ok=True)
        return record_dir

    def import_excel_to_record(
        self, source_file_path: str, target_class: str, record_dir: str | None = None
    ) -> str:
        """复制源 xlsx 到指定班级的记录目录。

        若 record_dir 不传则自动生成一个时间戳目录。返回最终记录目录的绝对路径。
        """
        if record_dir is None:
            record_dir = self.get_next_record_dir(target_class)
        else:
            os.makedirs(record_dir, exist_ok=True)

        target_file_path = os.path.join(record_dir, "data.xlsx")
        shutil.copy2(source_file_path, target_file_path)
        return record_dir

    @staticmethod
    def extract_term_number(class_name: str) -> int | None:
        m = re.search(r"(\d+)", class_name or "")
        if not m:
            return None
        try:
            return int(m.group(1))
        except ValueError:
            return None