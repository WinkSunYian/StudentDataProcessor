"""更新后台任务:检查新版本 / 下载校验解压 / 生成并启动更新脚本。

放在子线程执行(由 controller 用 QThread + moveToThread 驱动),
不碰任何 Qt 控件,只通过信号把进度抛回主线程。

更新脚本 `apply_update.bat` 在运行时生成而非打进安装包:
逻辑要改时跟着新版走,也不受 --add-data 遗漏影响。
"""

import os
import shutil
import subprocess
import tempfile
import zipfile

import requests
from PySide6.QtCore import QObject, Signal

from Services.Logger import Logger
from Services.UpdateService import (
    ReleaseInfo,
    USER_AGENT,
    fetch_latest_release,
    is_newer,
    verify_sha256,
)
from version import APP_VERSION

logger = Logger.instance()

# %TEMP% 下的更新工作目录: 下载包 / 解压产物 / 更新脚本 / 日志 都在这里
WORK_DIR_NAME = "StudentDataProcessor-update"

CHUNK_SIZE = 1024 * 1024

# 等旧进程退出的最长时间(秒),超时后强制覆盖
WAIT_OLD_PROCESS_SECONDS = 30


# ----------------------------------------------------------------------
# 工作目录
# ----------------------------------------------------------------------

def work_dir() -> str:
    return os.path.join(tempfile.gettempdir(), WORK_DIR_NAME)


def staging_dir() -> str:
    return os.path.join(work_dir(), "staging")


def clear_work_dir() -> None:
    """清掉上一次更新留下的临时文件,启动时调用一次。"""
    target = work_dir()
    if os.path.isdir(target):
        # ignore_errors: 更新脚本可能还开着其中的文件,下次启动会再清一次
        shutil.rmtree(target, ignore_errors=True)


def human_size(n: int) -> str:
    value = float(max(n, 0))
    units = ("B", "KB", "MB", "GB")
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    if idx == 0:
        return f"{int(value)} B"
    return f"{value:.1f} {units[idx]}"


# ----------------------------------------------------------------------
# 检查更新
# ----------------------------------------------------------------------

class UpdateCheckWorker(QObject):
    """查询 GitHub 最新 Release,判断是否存在比本地更新的版本。

    finished 参数:
        ok      —— 网络与解析是否成功
        message —— 失败原因(成功时为空串)
        release —— 有新版时的 ReleaseInfo,否则 None
    """

    finished = Signal(bool, str, object)

    def run(self):
        try:
            release = fetch_latest_release()
        except Exception as exc:
            self.finished.emit(False, f"检查更新失败: {exc}", None)
            return

        if release is None:
            self.finished.emit(False, "远端没有可用的 zip 更新包", None)
            return

        if not is_newer(release.tag, APP_VERSION):
            # 成功但没有新版:ok=True, release=None
            self.finished.emit(True, "", None)
            return

        self.finished.emit(True, "", release)


# ----------------------------------------------------------------------
# 应用更新
# ----------------------------------------------------------------------

class _Cancelled(Exception):
    """用户在下载阶段点了取消。"""


class UpdateApplyWorker(QObject):
    """下载 -> 校验 -> 解压 -> 写更新脚本 -> 启动脚本。

    启动脚本成功后由 controller 负责退出本进程,
    更新脚本会等本进程真的退出再覆盖安装目录。
    """

    progress = Signal(str, int)  # (状态文字, 百分比; -1 表示不确定进度)
    point_of_no_return = Signal()  # 下载完成,此后不再接受取消
    finished = Signal(bool, str)

    def __init__(self, release: ReleaseInfo, install_dir: str, exe_name: str):
        super().__init__()
        self.release = release
        self.install_dir = install_dir
        self.exe_name = exe_name
        self._cancelled = False

    def cancel(self):
        """仅在下载阶段有效;进入解压后为不可取消的临界点。"""
        self._cancelled = True

    def _check_cancelled(self):
        if self._cancelled:
            raise _Cancelled()

    # ------------------------------------------------------------------
    def run(self):
        try:
            self._execute()
        except _Cancelled:
            logger.info("已取消更新,本地文件未做任何改动")
            self.finished.emit(False, "已取消")
        except Exception as exc:
            logger.error(f"更新失败: {exc}")
            self.finished.emit(False, str(exc))

    def _execute(self):
        base = work_dir()
        os.makedirs(base, exist_ok=True)

        # 1. 下载
        zip_path = os.path.join(base, self.release.name)
        self._download(zip_path)
        self._check_cancelled()

        # 2. 校验(临界点:下载已落地,从这里开始不再接受取消)
        self.point_of_no_return.emit()
        self.progress.emit("校验文件完整性...", -1)
        if not verify_sha256(zip_path, self.release.digest):
            raise RuntimeError("SHA-256 校验失败,已放弃更新")
        if self.release.digest:
            logger.info("SHA-256 校验通过")

        # 3. 解压
        self.progress.emit("解压更新包...", -1)
        staging = staging_dir()
        shutil.rmtree(staging, ignore_errors=True)
        os.makedirs(staging, exist_ok=True)

        app_root = _extract_to(zip_path, staging)
        exe_path = os.path.join(app_root, self.exe_name)
        if not os.path.isfile(exe_path):
            raise RuntimeError(f"更新包里找不到 {self.exe_name}")

        # 4. 写更新脚本
        self.progress.emit("准备更新脚本...", -1)
        bat_path = os.path.join(base, "apply_update.bat")
        _write_updater_script(
            bat_path,
            staging=app_root,
            target=self.install_dir,
            exe=self.exe_name,
            old_pid=os.getpid(),
            log_path=os.path.join(base, "update.log"),
        )

        # 5. 启动更新脚本,由它等待本进程退出后覆盖安装目录
        self.progress.emit("即将重启以完成更新...", -1)
        _launch_updater(bat_path, base)

        logger.info("更新脚本已启动,应用即将退出并重启")
        self.finished.emit(True, "更新脚本已启动,应用即将重启")

    # ------------------------------------------------------------------
    def _download(self, dest: str):
        total = int(self.release.size or 0)
        got = 0
        last_percent = -1

        logger.info(f"开始下载 {self.release.name} ({human_size(total)})")
        self.progress.emit("开始下载...", 0)

        with requests.get(
            self.release.download_url,
            stream=True,
            timeout=(15, 60),
            headers={"User-Agent": USER_AGENT},
        ) as resp:
            resp.raise_for_status()

            if not total:
                total = int(resp.headers.get("Content-Length") or 0)

            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(CHUNK_SIZE):
                    self._check_cancelled()
                    if not chunk:
                        continue
                    fh.write(chunk)
                    got += len(chunk)

                    if total > 0:
                        percent = int(got * 100 / total)
                        if percent != last_percent:
                            last_percent = percent
                            self.progress.emit(
                                f"下载中 {human_size(got)} / {human_size(total)}",
                                percent,
                            )

        if total and os.path.getsize(dest) != total:
            raise RuntimeError(
                f"下载不完整: {os.path.getsize(dest)} / {total} 字节"
            )

        logger.info(f"下载完成 {self.release.name} ({human_size(got)})")


# ----------------------------------------------------------------------
# 解压
# ----------------------------------------------------------------------

def _extract_to(zip_path: str, dest: str) -> str:
    """解压到 dest,返回真正包含应用文件的目录。

    兼容两种压缩布局:
        1. zip 根目录直接是 StudentDataProcessor.exe
        2. zip 根目录是一个 StudentDataProcessor/ 文件夹
    """
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)

    entries = [e for e in os.listdir(dest) if e not in (".", "..")]
    if len(entries) == 1:
        only = os.path.join(dest, entries[0])
        if os.path.isdir(only):
            return only
    return dest


# ----------------------------------------------------------------------
# 更新脚本
# ----------------------------------------------------------------------

# 只用 ASCII 正文,路径按 ANSI(中文系统即 GBK)写入,
# 与 cmd 的默认代码页一致,避免 UTF-8 脚本里中文路径乱码。
_UPDATER_TEMPLATE = """@echo off
setlocal
set "TARGET=__TARGET__"
set "STAGING=__STAGING__"
set "EXE=__EXE__"
set "PID=__PID__"
set "LOG=__LOG__"
set /a _waited=0

echo [update] start > "%LOG%"
echo [update] staging __STAGING__ >> "%LOG%"
echo [update] target __TARGET__ >> "%LOG%"

:wait
rem 旧进程还在就等,最多等 __WAIT__ 秒
tasklist /FI "PID eq %PID%" /NH 2>nul | findstr /I /C:".exe" >nul
if errorlevel 1 goto apply
if %_waited% geq __WAIT__ goto apply
ping -n 2 127.0.0.1 >nul
set /a _waited+=1
goto wait

:apply
echo [update] apply begin >> "%LOG%"
robocopy "%STAGING%" "%TARGET%" /MIR /R:1 /W:1 /NP /NFL /NDL /XD data /XF sessionid.txt >> "%LOG%" 2>&1
set /a _rc=%errorlevel%
echo [update] robocopy exit=%_rc% >> "%LOG%"
if %_rc% geq 8 echo [update] robocopy reported a serious error >> "%LOG%"

start "" "%TARGET%\\%EXE%"
echo [update] restarted >> "%LOG%"
endlocal
"""


def _bat_escape(path: str) -> str:
    """批处理里 % 是变量定界符,路径中的 % 必须写成 %% 。"""
    return str(path).replace("%", "%%")


def _write_updater_script(
    bat_path: str,
    staging: str,
    target: str,
    exe: str,
    old_pid: int,
    log_path: str,
) -> None:
    script = (
        _UPDATER_TEMPLATE
        .replace("__TARGET__", _bat_escape(target))
        .replace("__STAGING__", _bat_escape(staging))
        .replace("__EXE__", _bat_escape(exe))
        .replace("__PID__", str(int(old_pid)))
        .replace("__LOG__", _bat_escape(log_path))
        .replace("__WAIT__", str(WAIT_OLD_PROCESS_SECONDS))
    )

    encoding = "mbcs" if os.name == "nt" else "utf-8"
    with open(bat_path, "w", encoding=encoding, newline="\r\n") as fh:
        fh.write(script)


def _launch_updater(bat_path: str, cwd: str) -> None:
    """把更新脚本丢到后台跑,窗口隐藏(失败信息统一写 update.log)。"""
    subprocess.Popen(
        ["cmd.exe", "/c", bat_path],
        cwd=cwd,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        close_fds=True,
    )
