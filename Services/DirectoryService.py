import os
import re
import shutil
import json
from datetime import datetime
from Services.Logger import Logger

logger = Logger.instance()

RECORD_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
RECORD_DIRNAME_PATTERN = re.compile(r"^\d{8}_\d{6}$")


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

    def trim_records(self, class_name: str, keep: int = 6) -> int:
        """保留最新的 N 条记录(按目录名 YYYYMMDD_HHMMSS 字典序即时间序),
        删除多余的旧记录及其下的 split/ 子目录与 line.html。

        返回被删除的记录数。
        """
        records = self.get_records_in_class(class_name)
        if len(records) <= keep:
            return 0

        records_sorted = sorted(records, reverse=True)
        to_delete = records_sorted[keep:]

        import shutil as _shutil

        deleted = 0
        for name in to_delete:
            record_path = os.path.join(self.class_root, class_name, name)
            try:
                _shutil.rmtree(record_path)
                deleted += 1
            except Exception as e:
                logger.error(f"删除旧记录失败 {record_path}: {e}")
        return deleted

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