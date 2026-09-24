import json
import os
from datetime import datetime, timedelta

import pandas as pd
from pyecharts import options as opts
from pyecharts.charts import Line, Timeline
from pyecharts.commons.utils import JsCode

from Services.Logger import Logger

logger = Logger.instance()


def _humanize_timedelta(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}秒前"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}分钟前"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}小时前"
    days = hours // 24
    if days < 30:
        return f"{days}天前"
    months = days // 30
    if months < 12:
        return f"{months}个月前"
    years = days // 365
    return f"{years}年前"


class ExcelChartService:
    def generate_timeline_chart(self, class_dir_path: str) -> str:
        """扫描班级目录下所有记录(按时间戳目录名),生成时间轴折线图。

        - X 轴:第1节课 ~ 第32节课
        - 每个记录目录 = 时间轴上的一个节点(标签 = 目录名)
        - 每节点展示 5 条线:
          完课率     = 连续完课到第 i 节(含)的人数占在读人数的比例(原有,累计口径)
          作业完成率 = 连续完成作业到第 i 节(含)的人数占在读人数的比例(原有,累计口径)
          差值       = 完课率 - 作业完成率(原有,不变)
          完课分布   = 恰好连续完课到该节的人数占在读人数的比例(新增)
          作业分布   = 恰好连续完成作业到该节的人数占在读人数的比例(新增)
        - 鼠标悬停提示窗口显示每条线对应的人数(不显示百分比):
          完课率/作业完成率 = 累计人数;差值 = 累计完课 - 累计作业
          完课分布/作业分布 = 该节点的分布人数(不累计前面的节点)
        - 输出:class_dir_path/timeline.html
        """
        if not os.path.isdir(class_dir_path):
            logger.error(f"班级目录不存在: {class_dir_path}")
            return ""

        record_dirs = sorted(
            [
                d
                for d in os.listdir(class_dir_path)
                if os.path.isdir(os.path.join(class_dir_path, d))
            ],
            reverse=False,
        )
        if not record_dirs:
            logger.error("当前班级下没有任何数据记录")
            return ""

        now = datetime.now()
        metrics_list = []
        for record_name in record_dirs:
            record_path = os.path.join(class_dir_path, record_name)
            data_path = os.path.join(record_path, "data.xlsx")
            if not os.path.isfile(data_path):
                continue

            try:
                metrics = self._compute_metrics(data_path)
            except Exception as e:
                logger.error(f"解析 {record_name} 失败: {e}")
                continue

            if not metrics["lesson_cols"]:
                continue

            metrics["record_name"] = record_name
            metrics["point_label"] = self._format_timeline_label(record_name, now)
            metrics_list.append(metrics)

        if not metrics_list:
            logger.error("没有任何可用的数据记录用于绘制图表")
            return ""

        timeline = self._build_timeline(metrics_list)
        output_html_path = os.path.join(class_dir_path, "timeline.html")
        timeline.render(output_html_path)
        return output_html_path

    def _build_timeline(self, metrics_list: list[dict]) -> Timeline:
        """用百分比折线 + 人数提示窗口构建时间轴图。"""
        current_index = len(metrics_list) - 1
        timeline = Timeline(
            init_opts=opts.InitOpts(width="100%", height="95vh", page_title="学员数据图表")
        )
        timeline.add_schema(
            pos_bottom="0%",
            current_index=current_index,
            is_timeline_show=True,
        )

        for m in metrics_list:
            lesson_cols = m["lesson_cols"]
            line = Line()
            line.set_global_opts(
                yaxis_opts=opts.AxisOpts(
                    axislabel_opts=opts.LabelOpts(formatter="{value} %"),
                ),
                xaxis_opts={"boundaryGap": False, "splitLine": {"show": True}},
                title_opts=opts.TitleOpts(title=f"{m['batch_period']} · {m['record_name']}"),
                tooltip_opts=opts.TooltipOpts(
                    trigger="axis", formatter=self._tooltip_formatter(m)
                ),
                legend_opts=opts.LegendOpts(pos_top="5%"),
            )

            label_fmt = JsCode("function (params) {return params.value[1] + '%'}")
            line.add_xaxis(lesson_cols)
            line.add_yaxis(
                "完课率",
                m["course_rate"],
                label_opts=opts.LabelOpts(formatter=label_fmt),
            )
            line.add_yaxis(
                "作业完成率",
                m["assign_rate"],
                label_opts=opts.LabelOpts(formatter=label_fmt),
            )
            line.add_yaxis(
                "差值", m["rate_diff"], label_opts=opts.LabelOpts(formatter=label_fmt)
            )
            line.add_yaxis(
                "完课分布",
                self._to_rate(m["course_hist"], m["total"]),
                label_opts=opts.LabelOpts(formatter=label_fmt),
            )
            line.add_yaxis(
                "作业分布",
                self._to_rate(m["assign_hist"], m["total"]),
                label_opts=opts.LabelOpts(formatter=label_fmt),
            )

            if lesson_cols:
                line.set_series_opts(
                    markline_opts=opts.MarkLineOpts(
                        is_silent=True,
                        linestyle_opts=opts.LineStyleOpts(color="red", type_="solid"),
                        symbol=["none", "none"],
                        data=[{"xAxis": lesson_cols[-1], "name": lesson_cols[-1]}],
                    )
                )

            line.options["grid"] = {
                "left": "5%",
                "right": "5%",
                "top": "15%",
                "bottom": "18%",
                "containLabel": True,
            }

            timeline.add(line, m["point_label"])

        return timeline

    def _to_rate(self, counts: list[int], total: int) -> list:
        """人数 → 占在读人数的比例(%),0 显示为断点(与原图口径一致)。"""
        r = [round(c / total * 100, 2) for c in counts]
        return [None if v == 0 else v for v in r]

    def _tooltip_formatter(self, m: dict) -> JsCode:
        """生成悬停提示格式化函数:每条线显示自己对应的人数,不显示百分比。

        - 完课率/作业完成率行:累计人数(连续完成到该节含该节的人数)
        - 差值行:累计完课人数 - 累计作业人数(与率差线对应)
        - 完课分布/作业分布行:该节点的分布人数(恰好连续完成到该节,不累计)
        人数数组直接烘焙进函数,不依赖任何全局状态。
        """
        payload = json.dumps(
            {
                "E": m["course_counts"],  # 累计完课
                "F": m["assign_counts"],  # 累计作业
                "D": m["count_diff"],  # 累计差(人数)
                "C": m["course_hist"],  # 完课分布
                "A": m["assign_hist"],  # 作业分布
            },
            ensure_ascii=False,
        ).replace('"', "'")
        js = (
            "function (params) {\n"
            f"    var d = {payload};\n"
            "    var i = params[0].dataIndex;\n"
            "    var map = {};\n"
            "    for (var k = 0; k < params.length; k++) { map[params[k].seriesName] = params[k]; }\n"
            "    function mk(n) { return map[n] ? map[n].marker : ''; }\n"
            "    var h = '<b>' + params[0].name + '</b>';\n"
            "    h += '<br/>' + mk('完课率') + '完课（累计）: ' + d.E[i] + ' 人';\n"
            "    h += '<br/>' + mk('作业完成率') + '作业（累计）: ' + d.F[i] + ' 人';\n"
            "    h += '<br/>' + mk('差值') + '差值: ' + d.D[i] + ' 人';\n"
            "    h += '<br/>' + mk('完课分布') + '完课分布: ' + d.C[i] + ' 人';\n"
            "    h += '<br/>' + mk('作业分布') + '作业分布: ' + d.A[i] + ' 人';\n"
            "    return h;\n"
            "}"
        )
        return JsCode(js)

    def _format_timeline_label(self, record_name: str, now: datetime) -> str:
        try:
            record_time = datetime.strptime(record_name, "%Y%m%d_%H%M%S")
        except ValueError:
            return record_name
        return f"{record_name}\n{_humanize_timedelta(now - record_time)}"

    def _compute_metrics(self, data_excel_path: str) -> dict:
        """解析 data.xlsx,返回率(累计)与人数(恰好进度)两类指标。

        - course_counts/assign_counts:连续完成到第 i 节(含)的人数 → 换算成率(累计口径)
        - course_hist/assign_hist:恰好连续完成到第 i 节的人数(不累计,直方图口径)
        """
        data = pd.read_excel(data_excel_path)
        data.columns = data.columns.str.strip()

        status_col = next(
            (c for c in data.columns if "学员学籍状态" in str(c)), None
        )
        if status_col is None:
            raise ValueError("缺少 '学员学籍状态' 列")

        data = data[data[status_col] == "在读"]

        term_col = next((c for c in data.columns if "班期" in str(c)), None)
        if term_col is not None and not data[term_col].dropna().empty:
            batch_period = str(data[term_col].dropna().iloc[0])
        else:
            batch_period = "学员数据"

        lesson_cols = [f"第{i}节课" for i in range(1, 33)]
        lesson_cols = [c for c in lesson_cols if c in data.columns]
        if not lesson_cols:
            raise ValueError("缺少 '第X节课' 列")

        data = data[lesson_cols]
        total = len(data)
        if total == 0:
            raise ValueError("在读学员为 0")

        n = len(lesson_cols)
        course_counts = [0] * n
        assignment_counts = [0] * n
        # 下标 = 恰好连续进度(0 = 一节都没完成,不参与显示)
        course_hist = [0] * (n + 1)
        assignment_hist = [0] * (n + 1)

        for _, row in data.iterrows():
            course_flag = True
            assignment_flag = True
            course_len = 0
            assignment_len = 0
            for i, value in enumerate(row):
                if pd.isnull(value):
                    continue
                parts = str(value).split("/")
                if len(parts) < 2:
                    continue
                course_part, assignment_part = parts[0], parts[1]

                if course_part in ("直", "录") and course_flag:
                    course_counts[i] += 1
                    course_len = i + 1
                else:
                    course_flag = False

                if assignment_part == "作" and assignment_flag:
                    assignment_counts[i] += 1
                    assignment_len = i + 1
                else:
                    assignment_flag = False

            course_hist[course_len] += 1
            assignment_hist[assignment_len] += 1

        def to_rate(counts):
            r = [round(c / total * 100, 2) for c in counts]
            return [None if v == 0 else v for v in r]

        course_rate = to_rate(course_counts)
        assignment_rate = to_rate(assignment_counts)
        rate_diff = [
            None if (x is None or y is None) else round(x - y, 2)
            for x, y in zip(course_rate, assignment_rate)
        ]

        return {
            "lesson_cols": lesson_cols,
            "batch_period": batch_period,
            "total": total,
            "course_counts": [int(c) for c in course_counts],
            "assign_counts": [int(c) for c in assignment_counts],
            "course_rate": course_rate,
            "assign_rate": assignment_rate,
            "rate_diff": rate_diff,
            "count_diff": [
                int(c) - int(a)
                for c, a in zip(course_counts, assignment_counts)
            ],
            "course_hist": [int(v) for v in course_hist[1:]],
            "assign_hist": [int(v) for v in assignment_hist[1:]],
        }
