import os
from datetime import datetime, timedelta
import pandas as pd
from pyecharts.charts import Line, Timeline
from pyecharts import options as opts
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
        - 每节点展示 3 条线:完课率 / 作业完成率 / 差值
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
        timeline = Timeline(
            init_opts=opts.InitOpts(width="100%", height="95vh", page_title="学员数据图表")
        )
        timeline.add_schema(
            pos_bottom="0%",
            current_index=len(record_dirs) - 1,
            is_timeline_show=True,
        )
        last_lesson_cols: list[str] = []
        valid_records = 0
        for record_name in record_dirs:
            record_path = os.path.join(class_dir_path, record_name)
            data_path = os.path.join(record_path, "data.xlsx")
            if not os.path.isfile(data_path):
                continue

            try:
                course_rate, assignment_rate, rate_diff, lesson_cols, batch_period = (
                    self._compute_rates(data_path)
                )
            except Exception as e:
                logger.error(f"解析 {record_name} 失败: {e}")
                continue

            if not lesson_cols:
                continue

            last_lesson_cols = lesson_cols
            valid_records += 1

            point_label = self._format_timeline_label(record_name, now)
            line = Line()
            line.set_global_opts(
                yaxis_opts=opts.AxisOpts(
                    axislabel_opts=opts.LabelOpts(formatter="{value} %"),
                ),
                xaxis_opts={"boundaryGap": False, "splitLine": {"show": True}},
                title_opts=opts.TitleOpts(title=f"{batch_period} · {record_name}"),
                tooltip_opts=opts.TooltipOpts(trigger="axis"),
                legend_opts=opts.LegendOpts(pos_top="5%"),
            )

            label_fmt = JsCode("function (params) {return params.value[1] + '%'}")
            line.add_xaxis(lesson_cols)
            line.add_yaxis("完课率", course_rate, label_opts=opts.LabelOpts(formatter=label_fmt))
            line.add_yaxis("作业完成率", assignment_rate, label_opts=opts.LabelOpts(formatter=label_fmt))
            line.add_yaxis("差值", rate_diff, label_opts=opts.LabelOpts(formatter=label_fmt))

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

            timeline.add(line, point_label)

        if valid_records == 0:
            logger.error("没有任何可用的数据记录用于绘制图表")
            return ""

        output_html_path = os.path.join(class_dir_path, "timeline.html")
        timeline.render(output_html_path)
        return output_html_path

    def _format_timeline_label(self, record_name: str, now: datetime) -> str:
        try:
            record_time = datetime.strptime(record_name, "%Y%m%d_%H%M%S")
        except ValueError:
            return record_name
        return f"{record_name}\n{_humanize_timedelta(now - record_time)}"

    def _compute_rates(self, data_excel_path: str):
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

        course_counts = [0] * len(lesson_cols)
        assignment_counts = [0] * len(lesson_cols)

        for _, row in data.iterrows():
            course_flag = True
            assignment_flag = True
            for i, value in enumerate(row):
                if pd.isnull(value):
                    continue
                parts = str(value).split("/")
                if len(parts) < 2:
                    continue
                course_part, assignment_part = parts[0], parts[1]

                if course_part in ("直", "录") and course_flag:
                    course_counts[i] += 1
                else:
                    course_flag = False

                if assignment_part == "作" and assignment_flag:
                    assignment_counts[i] += 1
                else:
                    assignment_flag = False

        def to_rate(counts):
            r = [round(c / total * 100, 2) for c in counts]
            return [None if v == 0 else v for v in r]

        course_rate = to_rate(course_counts)
        assignment_rate = to_rate(assignment_counts)
        rate_diff = [
            None if (x is None or y is None) else round(x - y, 2)
            for x, y in zip(course_rate, assignment_rate)
        ]

        return course_rate, assignment_rate, rate_diff, lesson_cols, batch_period