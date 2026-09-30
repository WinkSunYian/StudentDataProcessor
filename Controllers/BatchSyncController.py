import os

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from Services.Logger import Logger

logger = Logger.instance()


class BatchSyncController:
    """「全部同步」批量驱动器。

    职责边界:
      - 拍一份班期快照当队列,逐个驱动 FileProcessController 跑完
        「下载 -> 额外同步 -> 拆分」再同步企业微信;
      - 开跑前做一次配置预检查,有问题的班期列出来确认后跳过;
      - 遇错即停,结束时在日志区落一行汇总;
      - 流光按钮再点一次 = 请求停止,当前班期跑完后停在队列处。
    """

    def __init__(self, file_process_controller):
        self._fpc = file_process_controller
        self._queue: list[str] = []
        self._index = 0
        self._stop_requested = False
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    # ---------------- 对外入口 ----------------
    def start(self):
        if self._running:
            return
        if self._fpc.is_busy():
            return

        classes = self._fpc.dir_service.get_all_classes()
        if not classes:
            logger.warn("没有任何班期,无法执行「全部同步」")
            return

        plan, problems = self._preflight(classes)
        if not plan:
            logger.warn("所有班期都存在问题,已取消「全部同步」")
            return

        if problems and not self._confirm_skips(problems, len(plan)):
            logger.info("已取消「全部同步」")
            return

        self._queue = plan
        self._index = 0
        self._stop_requested = False
        self._running = True
        self._fpc.set_batch_running(True)

        skipped = len(classes) - len(plan)
        logger.info(
            f"「全部同步」开始:共 {len(plan)} 个班期"
            + (f",跳过 {skipped} 个有问题的班期" if skipped else "")
        )
        QTimer.singleShot(0, self._run_current)

    def request_stop(self):
        """再点一次流光按钮:当前班期跑完后停在队列处。"""
        if not self._running:
            return
        if self._stop_requested:
            return
        self._stop_requested = True
        logger.warn("已请求停止:当前班期处理完成后停止,后续班期不再执行")

    # ---------------- 预检查 ----------------
    def _preflight(self, classes: list[str]):
        """返回 (可执行队列, 问题列表[(班期, 原因)])。"""
        plan: list[str] = []
        problems: list[tuple[str, str]] = []

        for class_name in classes:
            if self._fpc.dir_service.extract_term_number(class_name) is None:
                problems.append((class_name, "无法从班级名解析出期号"))
                continue

            config = self._fpc.dir_service.load_class_config(class_name)
            doc_id = (config.get("DOC_ID") or "").strip()
            sheet_id = (config.get("SHEET_ID") or "").strip()
            if not doc_id or not sheet_id:
                problems.append((class_name, "未配置 DOC_ID / SHEET_ID"))
                continue

            plan.append(class_name)

        return plan, problems

    def _confirm_skips(self, problems, plan_size: int) -> bool:
        lines = "\n".join(
            f"  • {name} —— {reason}" for name, reason in problems
        )
        box = QMessageBox(self._fpc.main_window)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("部分班期存在问题")
        box.setText(
            f"以下 {len(problems)} 个班期存在问题,将被跳过:\n\n{lines}\n\n"
            f"确认后将处理剩余 {plan_size} 个班期,是否继续?"
        )
        confirm_btn = box.addButton("跳过并继续", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(confirm_btn)
        box.exec()
        return box.clickedButton() is confirm_btn

    # ---------------- 队列推进 ----------------
    def _current_class(self) -> str:
        if 0 <= self._index < len(self._queue):
            return self._queue[self._index]
        return ""

    def _progress(self) -> str:
        return f"{self._index + 1}/{len(self._queue)}"

    def _run_current(self):
        if not self._running:
            return
        if self._stop_requested:
            self._finish(stopped=True)
            return

        class_name = self._current_class()
        if not class_name:
            logger.warn("「全部同步」队列为空,已结束")
            self._teardown()
            return

        logger.info(f"【批量 {self._progress()}】开始处理 {class_name}")
        self._fpc.start_download_pipeline(class_name, self._on_pipeline_done)

    def _on_pipeline_done(self, ok: bool, reason: str, record_dir: str):
        if not self._running:
            return
        if not ok:
            self._fail(reason or "下载流程失败")
            return

        class_name = self._current_class()
        split_path = os.path.join(record_dir, "split")
        if not (
            os.path.exists(os.path.join(split_path, "course.xlsx"))
            and os.path.exists(os.path.join(split_path, "homework.xlsx"))
        ):
            self._fail("拆分表不存在,无法同步企业微信")
            return

        config = self._fpc.dir_service.load_class_config(class_name)
        sheet_id = (config.get("SHEET_ID") or "").strip()
        doc_id = (config.get("DOC_ID") or "").strip()

        logger.info(f"【批量 {self._progress()}】同步企业微信在线文档 {class_name}")
        # 忙时 ExcelSyncService 会异步补发失败回调,同样走 _on_wedoc_done
        self._fpc.sync_service.sync_wedoc_data(
            record_dir,
            sheet_id,
            doc_id,
            on_progress=logger.info,
            on_finished=self._on_wedoc_done,
        )

    def _on_wedoc_done(self, ok: bool, msg: str):
        if not self._running:
            return
        if not ok:
            self._fail(msg or "企业微信同步失败")
            return

        logger.success(f"【批量 {self._progress()}】完成:{msg}")
        self._index += 1

        if self._index >= len(self._queue):
            self._finish(stopped=False)
        else:
            QTimer.singleShot(0, self._run_current)

    # ---------------- 收尾 ----------------
    def _fail(self, reason: str):
        """遇错即停:汇总停在哪个班期、后面还有几个没跑。"""
        failed = self._current_class()
        total = len(self._queue)
        done = self._index
        remaining = total - done - 1
        logger.error(f"【批量 {self._progress()}】{failed} 失败:{reason}")
        logger.error(
            f"已处理 {done}/{total},第 {done + 1} 个「{failed}」失败:{reason}"
            + (f",后续 {remaining} 个未执行" if remaining > 0 else "")
        )
        self._teardown()

    def _finish(self, stopped: bool):
        total = len(self._queue)
        if stopped:
            logger.warn(
                f"「全部同步」已停止:完成 {self._index}/{total},"
                f"剩余 {total - self._index} 个未执行"
            )
        else:
            logger.success(f"「全部同步」完成:{total}/{total} 全部成功")
        self._teardown()

    def _teardown(self):
        self._running = False
        self._stop_requested = False
        self._queue = []
        self._index = 0
        self._fpc.set_batch_running(False)
