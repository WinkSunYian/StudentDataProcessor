import os
import sys
import shutil
import subprocess
from datetime import datetime

import pandas as pd
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QMessageBox
from Services.Logger import Logger
from Services.JihuaDownloadWorker import JihuaDownloadWorker
from Services.JihuaApiClient import JihuaApiClient
from Services.JihuaLoginWorker import JihuaLoginWorker
from Services.ShuatiLoginWorker import ShuatiLoginWorker, verify_sessionid
from Services.MainThread import call_later
from Views.SettingsDialog import SettingsDialog
from Views.SheetIdDialog import SheetIdDialog
from Controllers.BatchSyncController import BatchSyncController

logger = Logger.instance()

# 数据超过该时长未更新时，同步企业微信前需要二次确认
SYNC_STALE_THRESHOLD_SECONDS = 30 * 60


class FileProcessController:
    def __init__(
        self,
        main_window,
        file_detail_view,
        class_tab_bar_view,
        directory_service,
        excel_sync_service,
        excel_chart_service,
        class_controller,
    ):
        self.main_window = main_window
        self.detail_view = file_detail_view
        self.tab_bar_view = class_tab_bar_view
        self.dir_service = directory_service
        self.sync_service = excel_sync_service
        self.chart_service = excel_chart_service
        self.class_controller = class_controller

        # 忙状态拆成两把锁:
        #   _downloading —— 单班「下载 -> 同步 -> 拆分」流水线正在跑
        #   _batching    —— 「全部同步」批量任务正在跑
        self._downloading = False
        self._batching = False
        # 批量驱动器挂在流水线末端的完成回调,单班下载时为 None
        self._pipeline_callback = None

        self._dl_thread = None
        self._dl_worker = None
        self._login_thread = None
        self._login_worker = None
        self._shuati_login_thread = None
        self._shuati_login_worker = None
        self._current_class = ""
        self._current_record = ""

        self.batch_controller = BatchSyncController(self)

        self.class_controller.class_changed.connect(self.on_class_changed)

        self.detail_view.settings_btn.clicked.connect(self.on_settings_clicked)
        self.detail_view.download_btn.clicked.connect(self.on_download_clicked)
        self.detail_view.open_split_dir_btn.clicked.connect(
            self.on_open_split_dir_clicked
        )
        self.detail_view.chart_btn.clicked.connect(self.on_chart_clicked)
        self.detail_view.dist_btn.clicked.connect(self.on_distribution_clicked)
        self.detail_view.config_btn.clicked.connect(self.on_config_clicked)
        self.detail_view.sync_wedoc_btn.clicked.connect(self.on_sync_wedoc_clicked)
        self.tab_bar_view.batch_sync_btn.clicked.connect(self.on_batch_sync_clicked)

        self._refresh_button_states()

    # ---------------- 状态 ----------------
    def is_busy(self) -> bool:
        return self._downloading or self._batching

    def set_batch_running(self, value: bool):
        self._batching = bool(value)
        self._refresh_button_states()

    def _refresh_button_states(self):
        has_class = bool(self._current_class)
        record_path = self._get_current_record_path()
        has_split = bool(record_path) and os.path.isdir(
            os.path.join(record_path, "split")
        )
        has_class_records = has_class and bool(
            self.dir_service.get_records_in_class(self._current_class)
        )
        busy = self.is_busy()

        # 浏览类:只受前置条件约束,下载/同步/批量期间照常可用
        self.detail_view.open_split_dir_btn.setEnabled(has_split)
        self.detail_view.chart_btn.setEnabled(has_class_records)
        self.detail_view.dist_btn.setEnabled(has_class_records)

        # 改动类:下载/同步/批量期间一律置灰
        self.detail_view.settings_btn.setEnabled(not busy)
        self.detail_view.config_btn.setEnabled(has_class and not busy)
        self.detail_view.sync_wedoc_btn.setEnabled(has_class and not busy)
        self.tab_bar_view.set_locked(busy)

        # 下载按钮:始终亮着,用流光表达「正在下载」,点击由 handler 拦截
        downloading = self._downloading or self._batching
        self.detail_view.download_btn.setEnabled(has_class)
        self.detail_view.download_btn.set_flowing(downloading)
        self.detail_view.download_btn.setToolTip(
            "正在下载数据,请稍候…" if downloading else "下载当前班级的最新数据"
        )

        # 顶栏「全部同步」:批量中必须保持可点(再点一次 = 请求停止)
        batch_btn = self.tab_bar_view.batch_sync_btn
        if self._batching:
            batch_btn.setEnabled(True)
            batch_btn.set_flowing(True)
            batch_btn.setToolTip("正在批量同步,点击请求停止(当前班期跑完后停止)")
        else:
            batch_btn.setEnabled(not self._downloading)
            batch_btn.set_flowing(False)
            batch_btn.setToolTip("下载全部班期并同步至企业微信文档")

    def _set_downloading(self, value: bool):
        self._downloading = bool(value)
        self._refresh_button_states()

    def _finish_pipeline(self, ok: bool, reason: str = "", record_dir: str = ""):
        """单条下载流水线的唯一出口:复位状态并通知批量驱动器。"""
        callback, self._pipeline_callback = self._pipeline_callback, None
        self._set_downloading(False)
        if callback is not None:
            callback(ok, reason, record_dir)

    def _get_current_class_name(self) -> str:
        return self._current_class

    def _get_current_record_path(self) -> str:
        if not (self._current_class and self._current_record):
            return ""
        return os.path.join(
            self.dir_service.class_root, self._current_class, self._current_record
        )

    def _load_latest_record(self):
        """在当前班级下取最新(目录名最大)的记录,刷新 UI。"""
        if not self._current_class:
            self._current_record = ""
            self.detail_view.set_active_record("")
            self.detail_view.set_summary()
            self._refresh_button_states()
            return

        records = self.dir_service.get_records_in_class(self._current_class)
        if records:
            latest = sorted(records, reverse=True)[0]
            self._current_record = latest
            self.detail_view.set_active_record(latest)
            self._log_active_record_stats()
        else:
            self._current_record = ""
            self.detail_view.set_active_record("")
            self.detail_view.set_summary(class_name=self._current_class)
        self._refresh_button_states()

    def _log_active_record_stats(self):
        record_path = self._get_current_record_path()
        if not record_path:
            return
        data_excel_path = os.path.join(record_path, "data.xlsx")
        if not os.path.exists(data_excel_path):
            return
        try:
            df = pd.read_excel(data_excel_path)
        except Exception as e:
            logger.error(f"读取 data.xlsx 失败: {e}")
            return
        df.columns = df.columns.str.strip()
        if "学员学籍状态" not in df.columns:
            return
        total = len(df)
        active = len(df[df["学员学籍状态"] == "在读"])
        term_number = self.dir_service.extract_term_number(self._current_class)
        self.detail_view.set_summary(
            class_name=self._current_class,
            record_name=self._current_record,
            total=total,
            active=active,
            term_number=term_number,
        )
        logger.info(
            f"当前数据: {self._current_record} | 总人数: {total} | 在读人数: {active}"
            + (f" | 班期: Py{term_number}期" if term_number else "")
        )

    # ---------------- 配置 ----------------
    def on_settings_clicked(self):
        if self.is_busy():
            return
        dlg = SettingsDialog(self.dir_service, self.main_window)
        dlg.exec()

    def on_config_clicked(self):
        if self.is_busy():
            return
        class_name = self._get_current_class_name()
        if not class_name:
            logger.warn("请先在顶部选择一个班级")
            return
        dlg = SheetIdDialog(self.dir_service, class_name, self.main_window)
        dlg.exec()

    @staticmethod
    def _parse_record_time(record_name: str) -> datetime | None:
        try:
            return datetime.strptime(record_name, "%Y%m%d_%H%M%S")
        except (TypeError, ValueError):
            return None

    def _confirm_sync_if_stale(self) -> bool:
        """最新数据超过半小时未更新时弹确认框,返回是否继续同步。"""
        record_time = self._parse_record_time(self._current_record)
        if record_time is None:
            return True

        age_seconds = (datetime.now() - record_time).total_seconds()
        if age_seconds < SYNC_STALE_THRESHOLD_SECONDS:
            return True

        age_text = self.detail_view.format_record_time(self._current_record)
        box = QMessageBox(self.main_window)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("数据可能不是最新的")
        box.setText(
            f"当前数据获取于 {age_text}（记录 {self._current_record}），确定要更新吗？"
        )
        confirm_btn = box.addButton("确定更新", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(confirm_btn)
        box.exec()

        if box.clickedButton() is confirm_btn:
            return True

        logger.info(
            f"已取消同步:当前数据获取于 {age_text}(记录 {self._current_record})"
        )
        return False

    def on_sync_wedoc_clicked(self):
        if self.is_busy():
            return
        class_name = self._get_current_class_name()
        if not class_name:
            logger.warn("请先在顶部选择一个班级")
            return

        record_path = self._get_current_record_path()
        if not record_path:
            logger.warn("请先选择班级并下载数据")
            return

        split_path = os.path.join(record_path, "split")
        course_path = os.path.join(split_path, "course.xlsx")
        homework_path = os.path.join(split_path, "homework.xlsx")
        if not os.path.exists(course_path) or not os.path.exists(homework_path):
            logger.warn("拆分数据不存在,请先下载一次数据")
            self._refresh_button_states()
            return

        config = self.dir_service.load_class_config(class_name)
        sheet_id = config.get("SHEET_ID", "").strip()
        doc_id = config.get("DOC_ID", "").strip()
        if not sheet_id:
            logger.warn("当前班级未配置 SHEET_ID,请先点击「配置」按钮")
            return
        if not doc_id:
            logger.warn("当前班级未配置 DOC_ID,请先点击「配置」按钮")
            return

        if not self._confirm_sync_if_stale():
            return

        self._set_downloading(True)
        logger.info(
            f"开始同步企业微信在线文档(class={class_name}, doc_id={doc_id}, sheet_id={sheet_id})"
        )
        self.sync_service.sync_wedoc_data(
            record_path,
            sheet_id,
            doc_id,
            on_progress=logger.info,
            on_finished=self._on_sync_wedoc_finished,
        )

    def _on_sync_wedoc_finished(self, success: bool, msg: str):
        self._set_downloading(False)
        if success:
            logger.success(msg)
        else:
            logger.error(msg)

    # ---------------- 班级切换 ----------------
    def on_class_changed(self, class_name: str):
        """切班只改视图,不干扰正在跑的流水线(流水线的班级名已快照)。"""
        self._current_class = class_name
        self.detail_view.set_summary(class_name=class_name)
        self._load_latest_record()

    # ---------------- 全部同步(批量) ----------------
    def on_batch_sync_clicked(self):
        if self.batch_controller.running:
            # 批量中再点一次 = 请求停止,当前班期跑完后停在队列处
            self.batch_controller.request_stop()
            return
        if self.is_busy():
            return
        self.batch_controller.start()

    # ---------------- 下载最新数据 ----------------
    def on_download_clicked(self):
        if self.is_busy():
            return
        if not self._current_class:
            logger.warn("请先在顶部选择/新建一个班级")
            return
        self._begin_download(self._current_class)

    def start_download_pipeline(self, class_name: str, on_finished=None):
        """批量入口:对指定班期跑完整条「下载 -> 同步 -> 拆分」流水线。

        on_finished(ok, reason, record_dir) 一定会被调用一次。
        """
        if self._downloading:
            logger.warn("已有下载任务在执行,已忽略本次请求")
            if on_finished:
                on_finished(False, "已有下载任务在执行", "")
            return
        self._pipeline_callback = on_finished
        self._begin_download(class_name)

    def _begin_download(self, class_name: str):
        """凭据校验 + 必要的自动登录,然后启动下载。班级名全程用快照。"""
        self._set_downloading(True)
        try:
            self._auth_and_download(class_name)
        except Exception as e:
            logger.error(f"下载启动异常: {e}")
            self._finish_pipeline(False, f"下载启动异常: {e}")

    def _auth_and_download(self, class_name: str):
        term_number = self.dir_service.extract_term_number(class_name)
        if term_number is None:
            reason = f"无法从班级名 '{class_name}' 中解析出期号"
            logger.error(reason)
            self._finish_pipeline(False, reason)
            return

        config = self.dir_service.load_config()
        jsessionid = config.get("JSESSIONID", "").strip()
        dingtalk_account = config.get("dingtalk_account", "").strip()
        dingtalk_password = config.get("dingtalk_password", "").strip()
        session_id = ""
        shuati_admin_id = ""
        shuati_password = ""

        if jsessionid:
            logger.info("正在验证 JSESSIONID...")
            try:
                if JihuaApiClient.verify_jsessionid(jsessionid):
                    logger.info("JSESSIONID 验证通过")
                else:
                    logger.warn("JSESSIONID 验证失败")
                    jsessionid = ""
            except Exception as e:
                logger.warn(f"JSESSIONID 验证异常: {e}")
                jsessionid = ""

        if term_number > 160:
            session_id = config.get("sessionid", "").strip()
            shuati_admin_id = config.get("shuati_admin_id", "").strip()
            shuati_password = config.get("shuati_password", "").strip()
            if session_id:
                logger.info("正在验证刷题系统 sessionid...")
                if verify_sessionid(session_id):
                    logger.info("刷题系统 sessionid 验证通过")
                else:
                    logger.warn("刷题系统 sessionid 已过期，正在准备自动更新")
                    session_id = ""
            else:
                logger.warn("刷题系统 sessionid 未配置，正在准备自动登录")

        if not jsessionid:
            if not dingtalk_account or not dingtalk_password:
                reason = "JSESSIONID 已失效且未配置钉钉账号密码,请先更新配置"
                logger.warn(reason)
                self._finish_pipeline(False, reason)
                return
            logger.info("正在通过钉钉账号密码获取新的 JSESSIONID...")
            self._login_thread = QThread()
            self._login_worker = JihuaLoginWorker(dingtalk_account, dingtalk_password)
            self._login_worker.moveToThread(self._login_thread)
            self._login_thread.started.connect(self._login_worker.run)

            # 信号连到普通 Python 函数时回调跑在 worker 线程里,
            # 而失败分支会 _finish_pipeline -> 刷新按钮,必须回主线程
            login_thread = self._login_thread

            def on_login_finished(ok: bool, result: str):
                def _on_main():
                    login_thread.quit()
                    login_thread.wait()
                    if not ok:
                        logger.error(result)
                        self._finish_pipeline(False, f"钉钉登录失败: {result}")
                        return
                    new_jsessionid = result
                    self.dir_service.save_config("JSESSIONID", new_jsessionid)
                    logger.success(f"已自动更新 JSESSIONID: {new_jsessionid}")
                    self._continue_download(
                        class_name,
                        new_jsessionid,
                        term_number,
                        session_id,
                        shuati_admin_id,
                        shuati_password,
                    )

                call_later(_on_main)

            self._login_worker.finished.connect(on_login_finished)
            self._login_thread.start()
            return

        self._continue_download(
            class_name,
            jsessionid,
            term_number,
            session_id,
            shuati_admin_id,
            shuati_password,
        )

    def _continue_download(
        self,
        class_name: str,
        jsessionid: str,
        term_number: int,
        session_id: str,
        shuati_admin_id: str,
        shuati_password: str,
    ):
        if term_number > 160 and not session_id:
            if not shuati_admin_id or not shuati_password:
                reason = "刷题系统 sessionid 已失效且未配置管理员账号密码,请先更新配置"
                logger.warn(reason)
                self._finish_pipeline(False, reason)
                return
            logger.info("正在通过管理员账号密码获取新的刷题系统 sessionid...")
            self._shuati_login_thread = QThread()
            self._shuati_login_worker = ShuatiLoginWorker(
                shuati_admin_id, shuati_password
            )
            self._shuati_login_worker.moveToThread(self._shuati_login_thread)
            self._shuati_login_thread.started.connect(self._shuati_login_worker.run)

            shuati_thread = self._shuati_login_thread

            def on_shuati_login_finished(ok: bool, result: str):
                def _on_main():
                    shuati_thread.quit()
                    shuati_thread.wait()
                    if not ok:
                        logger.error(result)
                        self._finish_pipeline(False, f"刷题系统登录失败: {result}")
                        return
                    self.dir_service.save_config("sessionid", result)
                    logger.success(f"已自动更新刷题系统 sessionid: {result}")
                    self._start_download(class_name, jsessionid, term_number, result)

                call_later(_on_main)

            self._shuati_login_worker.finished.connect(on_shuati_login_finished)
            self._shuati_login_thread.start()
            return

        self._start_download(class_name, jsessionid, term_number, session_id)

    def _start_download(
        self, class_name: str, jsessionid: str, term_number: int, session_id: str = ""
    ):
        logger.info(f"开始下载 Py{term_number}期 最新数据...")

        self._dl_thread = QThread()
        self._dl_worker = JihuaDownloadWorker(
            jsessionid=jsessionid,
            term_number=term_number,
            target_class=class_name,
            dir_service=self.dir_service,
        )
        self._dl_worker.moveToThread(self._dl_thread)
        self._dl_thread.started.connect(self._dl_worker.run)

        dl_thread = self._dl_thread

        def on_dl_finished(ok: bool, msg: str, tmp_xlsx_path: str):
            def _on_main():
                # 先收线程,后续整条流水线都在主线程上跑
                dl_thread.quit()
                dl_thread.wait()
                if not ok:
                    logger.error(f"下载失败: {msg}")
                    self._finish_pipeline(False, f"下载失败: {msg}")
                    return

                logger.success(msg)
                self._run_download_pipeline(
                    class_name, tmp_xlsx_path, term_number, session_id
                )

            call_later(_on_main)

        self._dl_worker.finished.connect(on_dl_finished)
        self._dl_thread.start()

    def _run_download_pipeline(
        self,
        class_name: str,
        tmp_xlsx_path: str,
        term_number: int,
        session_id: str = "",
    ):
        """下载完成后的串行流程:创建记录目录 -> 同步 -> 拆分 -> 收尾。

        任何一步失败都会:
          - 删除已创建的记录目录
          - 删除临时 xlsx
          - 通过 _finish_pipeline 通知调用方(批量驱动器)
        """
        record_dir = ""
        try:
            record_dir = self.dir_service.get_next_record_dir(class_name)
            shutil.copy2(tmp_xlsx_path, os.path.join(record_dir, "data.xlsx"))
            logger.info(f"临时记录已创建: {os.path.basename(record_dir)}")
        except Exception as e:
            logger.error(f"创建记录目录失败: {e}")
            self._cleanup_failed_download(tmp_xlsx_path, record_dir)
            self._finish_pipeline(False, f"创建记录目录失败: {e}")
            return

        config = self.dir_service.load_config()
        use_shuati = term_number > 160

        def on_sync_finished(ok: bool, msg: str):
            if not ok:
                logger.error(f"自动同步失败: {msg}")
                self._cleanup_failed_download(tmp_xlsx_path, record_dir)
                self._finish_pipeline(False, f"自动同步失败: {msg}")
                return

            logger.info("同步完成,开始生成拆分表...")
            self._run_split_after_sync(class_name, tmp_xlsx_path, record_dir)

        try:
            if use_shuati:
                shuati_session_id = session_id.strip() or config.get(
                    "sessionid", ""
                ).strip()
                if not shuati_session_id:
                    reason = "下载完成,但未配置 sessionid,无法自动同步刷题系统"
                    logger.warn(reason)
                    self._cleanup_failed_download(tmp_xlsx_path, record_dir)
                    self._finish_pipeline(False, reason)
                    return
                self.sync_service.sync_shuati_data(
                    record_dir, shuati_session_id,
                    on_progress=logger.info, on_finished=on_sync_finished,
                )
            else:
                e_cookie = config.get("Ecookie", "").strip()
                if not e_cookie:
                    reason = "下载完成,但未配置 Ecookie,无法自动同步小鹅通"
                    logger.warn(reason)
                    self._cleanup_failed_download(tmp_xlsx_path, record_dir)
                    self._finish_pipeline(False, reason)
                    return
                self.sync_service.sync_xiaogetong_data(
                    record_dir, e_cookie,
                    on_progress=logger.info, on_finished=on_sync_finished,
                )
        except Exception as e:
            logger.error(f"启动同步异常: {e}")
            self._cleanup_failed_download(tmp_xlsx_path, record_dir)
            self._finish_pipeline(False, f"启动同步异常: {e}")

    def _run_split_after_sync(
        self, class_name: str, tmp_xlsx_path: str, record_dir: str
    ):
        try:
            from Services.ExcelExportService import ExcelExportService
            exp_ok, exp_msg = ExcelExportService().export_split_tables(record_dir)
            if not exp_ok:
                logger.error(f"拆分表生成失败: {exp_msg}")
                self._cleanup_failed_download(tmp_xlsx_path, record_dir)
                self._finish_pipeline(False, f"拆分表生成失败: {exp_msg}")
                return
            logger.success(f"拆分表已生成: {exp_msg}")
        except Exception as e:
            logger.error(f"拆分表生成异常: {e}")
            self._cleanup_failed_download(tmp_xlsx_path, record_dir)
            self._finish_pipeline(False, f"拆分表生成异常: {e}")
            return

        self._finalize_download(class_name, tmp_xlsx_path, record_dir)

    def _finalize_download(
        self, class_name: str, tmp_xlsx_path: str, record_dir: str
    ):
        """全部成功:清理临时文件,清理旧记录,刷新 UI。"""
        try:
            os.remove(tmp_xlsx_path)
        except OSError:
            pass

        # 按流水线处理的班期清理,而不是「当前正在看的班期」
        try:
            removed = self.dir_service.trim_records(class_name)
            if removed > 0:
                logger.info(
                    f"已清理 {removed} 条旧数据,保留规则:前七天每天 1 条 + 当天最多 2 条"
                )
        except Exception as e:
            logger.error(f"清理旧数据异常: {e}")

        record_name = os.path.basename(record_dir)
        # 用户可能已经切到别的班期看别的数据,只有处理的正是当前班期时才刷视图
        if class_name == self._current_class:
            self._current_record = record_name
            self.detail_view.set_active_record(record_name)
            self._log_active_record_stats()
        logger.success(f"数据流程完成: {record_name}")

        self._finish_pipeline(True, "", record_dir)

    def _cleanup_failed_download(self, tmp_xlsx_path: str, record_dir: str):
        """任意步骤失败时回滚:删除临时 xlsx + 临时记录目录。"""
        if tmp_xlsx_path:
            try:
                os.remove(tmp_xlsx_path)
            except OSError:
                pass
        if record_dir and os.path.isdir(record_dir):
            try:
                shutil.rmtree(record_dir)
                logger.info(f"已回滚:删除临时记录目录 {os.path.basename(record_dir)}")
            except Exception as e:
                logger.error(f"回滚失败 {record_dir}: {e}")

    # ---------------- 操作 ----------------
    def on_open_split_dir_clicked(self):
        path = self._get_current_record_path()
        if not path:
            logger.warn("请先选择班级并下载数据")
            return
        split_path = os.path.join(path, "split")
        if not os.path.isdir(split_path):
            logger.warn("拆分数据不存在,请先下载一次数据")
            self._refresh_button_states()
            return
        try:
            if sys.platform == "win32":
                os.startfile(split_path)
            elif sys.platform == "darwin":
                subprocess.run(["open", split_path])
            else:
                subprocess.run(["xdg-open", split_path])
        except Exception as e:
            logger.error(f"无法打开文件夹: {e}")

    def on_chart_clicked(self):
        class_name = self._current_class
        if not class_name:
            logger.warn("请先选择班级并下载数据")
            return
        class_path = os.path.join(self.dir_service.class_root, class_name)
        if not os.path.isdir(class_path):
            logger.warn("班级目录不存在")
            return

        records = self.dir_service.get_records_in_class(class_name)
        if not records:
            logger.warn("当前班级下没有数据记录,无法绘制图表")
            return

        logger.info(
            f"开始绘制 {class_name} 的时间轴折线图(共 {len(records)} 个时间点)..."
        )
        self._open_chart_output(
            self.chart_service.generate_timeline_chart(class_path),
            "折线图生成失败,请查看上方日志",
        )

    def on_distribution_clicked(self):
        class_name = self._current_class
        if not class_name:
            logger.warn("请先选择班级并下载数据")
            return
        class_path = os.path.join(self.dir_service.class_root, class_name)
        if not os.path.isdir(class_path):
            logger.warn("班级目录不存在")
            return

        if not self.dir_service.get_records_in_class(class_name):
            logger.warn("当前班级下没有数据记录,无法绘制分布图")
            return

        logger.info(f"开始绘制 {class_name} 的分布图(取最新记录)...")
        self._open_chart_output(
            self.chart_service.generate_distribution_chart(class_path),
            "分布图生成失败,请查看上方日志",
        )

    @staticmethod
    def _open_chart_output(out: str, fail_text: str):
        if out and os.path.exists(out):
            logger.success(f"已生成: {out}")
            try:
                if sys.platform == "win32":
                    os.startfile(out)
                elif sys.platform == "darwin":
                    subprocess.run(["open", out])
                else:
                    subprocess.run(["xdg-open", out])
            except Exception as e:
                logger.error(f"无法打开文件: {e}")
        else:
            logger.error(fail_text)
