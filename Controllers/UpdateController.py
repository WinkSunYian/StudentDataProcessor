import json
import os
import sys
import time

from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QApplication

from Services.Logger import Logger
from Services.UpdateService import ReleaseInfo, is_packaged
from Services.UpdateWorker import (
    UpdateApplyWorker,
    UpdateCheckWorker,
    clear_work_dir,
)
from Views.UpdateDialog import UpdateDialog
from version import APP_VERSION

logger = Logger.instance()

# 启动后延迟多久做静默检查(毫秒),让主窗口先显示出来,绝不阻塞启动
STARTUP_CHECK_DELAY_MS = 3000

# 上次检查失败后的重试冷却(秒)。没有它,断网时每次启动都要白等一次超时。
FAILURE_BACKOFF_SECONDS = 3600

STATE_FILE_NAME = "update_state.json"


class UpdateController:
    """自动更新:启动静默检查 + 配置区手动检查 + 一键更新并重启。

    只在打包版(is_packaged())生效;源码运行没有可替换的 exe,
    入口按钮隐藏、启动检查也不排。
    """

    def __init__(self, main_window=None, file_detail_view=None, directory_service=None):
        self.main_window = main_window
        self.detail_view = file_detail_view
        self.directory_service = directory_service

        self._state_path = ""
        if directory_service is not None:
            self._state_path = os.path.join(
                directory_service.data_root, STATE_FILE_NAME
            )

        self._check_thread = None
        self._check_worker = None
        self._checking = False

        self._apply_thread = None
        self._apply_worker = None
        self._applying = False

        self._dialog = None
        self._should_restart = False

        if is_packaged():
            # 上一轮留下的下载包 / 解压目录 / 更新脚本已经没用了
            clear_work_dir()
            self._show_manual_button()
        else:
            self._hide_manual_button()

    # ------------------------------------------------------------------
    # 入口按钮
    # ------------------------------------------------------------------
    def _manual_button(self):
        if self.detail_view is None:
            return None
        return getattr(self.detail_view, "update_btn", None)

    def _show_manual_button(self):
        btn = self._manual_button()
        if btn is None:
            return
        btn.show()
        btn.clicked.connect(lambda: self.check(manual=True))

    def _hide_manual_button(self):
        btn = self._manual_button()
        if btn is not None:
            btn.hide()

    # ------------------------------------------------------------------
    # 检查更新
    # ------------------------------------------------------------------
    def schedule_startup_check(self):
        if not is_packaged():
            return
        QTimer.singleShot(STARTUP_CHECK_DELAY_MS, lambda: self.check(manual=False))

    def check(self, manual: bool = False):
        if not is_packaged() or self._checking:
            return

        if not manual and self._in_backoff():
            # 上次失败后冷却中,静默跳过(手动检查不受此限制)
            return

        self._checking = True
        logger.info("手动检查更新..." if manual else "正在检查更新...")

        self._check_thread = QThread()
        self._check_worker = UpdateCheckWorker()
        self._check_worker.moveToThread(self._check_thread)
        self._check_thread.started.connect(self._check_worker.run)
        self._check_worker.finished.connect(self._on_checked)
        self._check_thread.start()

    def _on_checked(self, ok: bool, message: str, release):
        self._check_thread.quit()
        self._check_thread.wait()
        # 这里不能把 thread/worker 置空:本槽正是由该线程的信号投递进来的,
        # 在槽内销毁发送方线程会直接 std::terminate(0xC0000409)。
        # 引用留在实例上,由下一次 check() 覆盖时销毁 —— 那是主线程的普通事件上下文。
        self._checking = False

        if not ok:
            logger.warn(message)
            self._mark_failure()
            return

        self._clear_failure()

        if release is None:
            logger.success(f"已是最新版本 (v{APP_VERSION})")
            return

        logger.info(f"发现新版本 {release.tag},当前版本 v{APP_VERSION}")
        self._show_dialog(release)

    # ------------------------------------------------------------------
    # 更新弹窗
    # ------------------------------------------------------------------
    def _show_dialog(self, release: ReleaseInfo):
        self._should_restart = False

        dlg = UpdateDialog(release, self.main_window)
        self._dialog = dlg
        dlg.updateRequested.connect(lambda: self._begin_apply(release))
        dlg.cancelRequested.connect(self._cancel_apply)

        dlg.exec()

        # 走到这里时弹窗已关闭。必须在嵌套事件循环之外调用 exit(),
        # 否则只会退出弹窗自己那一层。
        self._dialog = None
        if self._should_restart:
            logger.info("正在重启应用...")
            QApplication.exit(0)

    def _begin_apply(self, release: ReleaseInfo):
        if self._applying:
            return

        dlg = self._dialog
        if dlg is None:
            return

        dlg.begin_update()
        self._applying = True

        # 旧的 thread/worker 在这里覆盖销毁(主线程普通事件上下文),
        # 与 FileProcessController 的下载线程写法一致
        self._apply_thread = QThread()
        self._apply_worker = UpdateApplyWorker(
            release=release,
            install_dir=os.path.dirname(os.path.abspath(sys.executable)),
            exe_name=os.path.basename(sys.executable),
        )
        self._apply_worker.moveToThread(self._apply_thread)
        self._apply_thread.started.connect(self._apply_worker.run)

        self._apply_worker.progress.connect(dlg.set_progress)
        self._apply_worker.point_of_no_return.connect(dlg.begin_irreversible)
        self._apply_worker.finished.connect(self._on_apply_finished)

        self._apply_thread.start()

    def _cancel_apply(self):
        if self._applying and self._apply_worker is not None:
            self._apply_worker.cancel()

    def _on_apply_finished(self, ok: bool, message: str):
        thread, dlg = self._apply_thread, self._dialog

        if thread is not None:
            thread.quit()
            thread.wait()
        # 同样不能在这里销毁发送方线程,交给下一次 _begin_apply 覆盖
        self._applying = False

        if not ok:
            if message == "已取消":
                if dlg is not None:
                    dlg.set_cancelled()
                return
            logger.error(f"更新失败: {message}")
            if dlg is not None:
                dlg.set_failed(message)
            return

        logger.success("更新完成,应用即将重启")
        self._should_restart = True
        if dlg is not None:
            dlg.set_succeeded(message)
            # 停一下,让用户看清"更新完成"再关窗退出
            QTimer.singleShot(800, dlg.accept)

    # ------------------------------------------------------------------
    # 检查失败的冷却(写在数据目录,不碰凭据 config.json)
    # ------------------------------------------------------------------
    def _in_backoff(self) -> bool:
        if not self._state_path or not os.path.isfile(self._state_path):
            return False
        try:
            with open(self._state_path, encoding="utf-8") as fh:
                failed_at = float(json.load(fh).get("failed_at") or 0)
        except (OSError, ValueError, TypeError, AttributeError):
            return False
        return (time.time() - failed_at) < FAILURE_BACKOFF_SECONDS

    def _mark_failure(self):
        if not self._state_path:
            return
        try:
            os.makedirs(os.path.dirname(self._state_path), exist_ok=True)
            with open(self._state_path, "w", encoding="utf-8") as fh:
                json.dump({"failed_at": time.time()}, fh)
        except OSError:
            pass

    def _clear_failure(self):
        try:
            if self._state_path and os.path.isfile(self._state_path):
                os.remove(self._state_path)
        except OSError:
            pass
