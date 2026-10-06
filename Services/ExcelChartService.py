import io
import json
import os
import re
from datetime import datetime, timedelta

import pandas as pd
from pyecharts import options as opts
from pyecharts.charts import Bar, Line, Timeline
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
    # 分布图页面模板。用 __XXX__ 占位符做替换,避免 f-string 转义大段 CSS/JS。
    _DISTRIBUTION_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<title>学员分布图</title>
__DEPS__
<style>
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    margin: 0;
    font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
    color: #1f2329;
    background: #fff;
    font-size: 14px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .page { flex: 1 1 auto; display: flex; min-height: 0; }
  #chart { flex: 1 1 auto; min-width: 0; }
  /* 整列都可点,所以图区内一律用可点光标 */
  #chart canvas { cursor: pointer; }
  .side {
    flex: 0 0 38%;
    max-width: 560px;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 12px;
    border-left: 1px solid #eceef1;
  }
  .toolbar {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 10px 18px;
    border-top: 1px solid #eceef1;
    border-bottom: 1px solid #eceef1;
    background: #fafbfc;
    font-size: 13px;
    color: #646a73;
  }
  .toolbar .cur { margin-left: auto; color: #1f2329; }
  .toolbar .cur b { color: #1456f0; }
  .panel {
    flex: 1 1 0;
    min-width: 0;
    min-height: 0;
    border: 1px solid #e5e6eb;
    border-radius: 8px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }
  .panel > header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 12px;
    background: #f7f8fa;
    border-bottom: 1px solid #e5e6eb;
    font-weight: 600;
  }
  .panel > header .cnt { font-weight: 400; color: #86909c; font-size: 13px; }
  .panel > header button {
    margin-left: auto;
    padding: 4px 12px;
    border: 1px solid #c9cdd4;
    border-radius: 6px;
    background: #fff;
    color: #1f2329;
    font-size: 13px;
    cursor: pointer;
  }
  .panel > header button:hover { border-color: #1456f0; color: #1456f0; }
  .panel .scroll { flex: 1 1 auto; min-height: 0; overflow: auto; }
  table { width: 100%; border-collapse: collapse; }
  thead th {
    position: sticky;
    top: 0;
    background: #fff;
    text-align: left;
    font-weight: 600;
    color: #646a73;
    padding: 8px 12px;
    border-bottom: 1px solid #eceef1;
    font-size: 13px;
  }
  tbody td {
    padding: 7px 12px;
    border-bottom: 1px solid #f2f3f5;
    font-size: 13px;
  }
  tbody tr:hover { background: #f7f9fc; }
  th.no, td.no { width: 56px; color: #86909c; }
  td.empty { color: #a0a4ab; text-align: center; padding: 18px 0; }
  #tip {
    position: fixed;
    right: 18px;
    bottom: 18px;
    padding: 8px 14px;
    border-radius: 6px;
    background: #1f2329;
    color: #fff;
    font-size: 13px;
    opacity: 0;
    transition: opacity .2s;
    pointer-events: none;
  }
</style>
</head>
<body>
<div class="toolbar">
  <span>点击左侧图中的任意一节，整列都可以点，右侧两表随之切换</span>
  <span class="cur">当前：<b id="curLesson"></b></span>
</div>
<div class="page">
  <div id="chart"></div>
  <aside class="side">
  <section class="panel">
    <header>
      完课分布名单<em class="cnt" id="courseCount"></em>
      <button type="button" onclick="copyNames('course')">复制名单</button>
    </header>
    <div class="scroll">
      <table>
        <thead><tr><th class="no">#</th><th>姓名</th></tr></thead>
        <tbody id="courseBody"></tbody>
      </table>
    </div>
  </section>
  <section class="panel">
    <header>
      作业分布名单<em class="cnt" id="assignCount"></em>
      <button type="button" onclick="copyNames('assign')">复制名单</button>
    </header>
    <div class="scroll">
      <table>
        <thead><tr><th class="no">#</th><th>姓名</th></tr></thead>
        <tbody id="assignBody"></tbody>
      </table>
    </div>
  </section>
  </aside>
</div>
<div id="tip"></div>
<script>
var OPTION = __OPTION__;
var DATA = __DATA__;
var LESSONS = __LESSONS__;
var CUR = "";
// 悬停提示只给人数,不给百分比、不列名单
OPTION.tooltip.formatter = function (ps) {
  if (!ps || !ps.length) return "";
  var map = {};
  for (var i = 0; i < ps.length; i++) map[ps[i].seriesName] = ps[i].value;
  var h = "<b>" + ps[0].name + "</b>";
  if (map["完课分布"] !== undefined) h += "<br/>完课分布: " + map["完课分布"] + " 人";
  if (map["作业分布"] !== undefined) h += "<br/>作业分布: " + map["作业分布"] + " 人";
  return h;
};
// 整列热区:每一节从上半顶端铺一张透明矩形一直盖到下半底端(clip:false 允许画出 grid)
// 这样点柱子、点空白、点中间的课次标签,效果都一样 = 选中这一节
var YMAX = OPTION.yAxis[0].max;
function hitRender(params, api) {
  var name = LESSONS[params.dataIndex];
  if (!name) return null;
  var w = api.size([1, 0])[0];
  var x = api.coord([name, 0])[0];
  var y0 = api.coord([name, 0])[1];
  var y1 = api.coord([name, YMAX])[1];
  return {
    type: "rect",
    shape: {x: x - w / 2, y: Math.min(y0, y1), width: w, height: 5000},
    style: {fill: "rgba(0,0,0,0)"}
  };
}
OPTION.series.forEach(function (s) {
  if (s.name === "_hit") s.renderItem = hitRender;
});
var chart = echarts.init(
  document.getElementById("chart"), "white", {renderer: "canvas", locale: "ZH"}
);
chart.setOption(OPTION);
window.addEventListener("resize", function () { chart.resize(); });
function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function fill(id, names) {
  var html = "";
  for (var i = 0; i < names.length; i++) {
    html += "<tr><td class='no'>" + (i + 1) + "</td><td>" + esc(names[i]) + "</td></tr>";
  }
  document.getElementById(id).innerHTML =
    html || "<tr><td class='empty' colspan='2'>（无）</td></tr>";
}
function select(lesson) {
  if (!DATA[lesson]) return;
  CUR = lesson;
  var d = DATA[lesson];
  document.getElementById("curLesson").textContent = lesson;
  document.getElementById("courseCount").textContent = "（" + d.course.length + " 人）";
  document.getElementById("assignCount").textContent = "（" + d.assign.length + " 人）";
  fill("courseBody", d.course);
  fill("assignBody", d.assign);
}
function copyNames(which) {
  var names = DATA[CUR][which];
  var text = names.join("\\n");
  var done = function () { tip("已复制 " + names.length + " 个姓名"); };
  function legacy() {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    document.body.removeChild(ta);
    if (ok) { done(); } else { window.prompt("复制下面的名单：", text); }
  }
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done, legacy);
  } else {
    legacy();
  }
}
function tip(msg) {
  var el = document.getElementById("tip");
  el.textContent = msg;
  el.style.opacity = "1";
  setTimeout(function () { el.style.opacity = "0"; }, 1800);
}
chart.on("click", function (params) {
  if (!params) return;
  // 点柱子时 params.name 就是课次;点整列热区时靠 dataIndex 兜底
  var name = params.name || LESSONS[params.dataIndex];
  if (DATA[name]) select(name);
});
// 默认选中人数最多的一节,而不是空的第 32 节
var BEST = LESSONS[0];
var BESTN = -1;
for (var k = 0; k < LESSONS.length; k++) {
  var d = DATA[LESSONS[k]];
  var total = d.course.length + d.assign.length;
  if (total > BESTN) { BESTN = total; BEST = LESSONS[k]; }
}
select(BEST);
</script>
</body>
</html>
"""

    def generate_timeline_chart(self, class_dir_path: str) -> str:
        """扫描班级目录下所有记录(按时间戳目录名),生成时间轴折线图。

        - X 轴:第1节课 ~ 第32节课
        - 每个记录目录 = 时间轴上的一个节点(标签 = 目录名)
        - 每节点展示 3 条线(口径不变):
          完课率     = 连续完课到第 i 节(含)的人数占在读人数的比例(累计口径)
          作业完成率 = 连续完成作业到第 i 节(含)的人数占在读人数的比例(累计口径)
          差值       = 完课率 - 作业完成率
        - 主标题「班期 · 记录目录」下方带副标题「在读人数:XX」
        - 鼠标悬停提示窗口显示每条线对应的人数(不显示百分比):
          完课率/作业完成率 = 累计人数;差值 = 累计完课 - 累计作业
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

    def generate_distribution_chart(self, class_dir_path: str) -> str:
        """取最新一条记录,生成「蝴蝶图 + 名单表格」的 distribution.html。

        - 竖向蝴蝶图:上半 = 完课分布、下半 = 作业分布,共用课次轴与同一 y 上限
        - 悬停提示只显示人数(不给百分比、不列名单)
        - 整列可点:点柱子、点空白、点课次标签都切换到该节 → 右侧两表列出学员姓名
        - 两个表格各带「复制名单」,一键拷成一行一个姓名
        """
        if not os.path.isdir(class_dir_path):
            logger.error(f"班级目录不存在: {class_dir_path}")
            return ""

        latest = ""
        for name in sorted(
            d
            for d in os.listdir(class_dir_path)
            if os.path.isdir(os.path.join(class_dir_path, d))
        ):
            if os.path.isfile(os.path.join(class_dir_path, name, "data.xlsx")):
                latest = name
        if not latest:
            logger.error("当前班级下没有任何数据记录")
            return ""

        try:
            metrics = self._compute_metrics(
                os.path.join(class_dir_path, latest, "data.xlsx")
            )
        except Exception as e:
            logger.error(f"解析 {latest} 失败: {e}")
            return ""

        if not metrics["lesson_cols"]:
            logger.error("当前记录没有可绘制的课程列")
            return ""

        output_html_path = os.path.join(class_dir_path, "distribution.html")
        io.open(output_html_path, "w", encoding="utf-8").write(
            self._build_distribution_html(latest, metrics)
        )
        return output_html_path

    def _build_distribution_html(self, record_name: str, m: dict) -> str:
        """竖向蝴蝶图:上半 = 完课分布、下半 = 作业分布,中间共用课次轴。

        右侧上下两块表格分别对应完课/作业。整列(含柱子、空白、课次标签)
        铺了透明热区,点任意位置即选中该节并联动表格。
        """
        lessons = ["未开始"] + m["lesson_cols"]
        course = [len(x) for x in m["course_names"]]
        assign = [len(x) for x in m["assign_names"]]

        # 上下两半共用同一个上限,才谈得上「哪边长」
        peak = max(max(course), max(assign), 1)
        y_max = peak + max(1, peak // 8)

        option = {
            "backgroundColor": "#ffffff",
            "animationDurationUpdate": 300,
            "title": {
                "text": f"{m['batch_period']} · {record_name}",
                "subtext": f"在读人数：{m['total']}",
                "left": 16,
                "top": 8,
                "textStyle": {"fontSize": 16, "color": "#1f2329", "fontWeight": 600},
                "subtextStyle": {"fontSize": 12, "color": "#86909c"},
            },
            "legend": {
                "top": 10,
                "right": 16,
                # 显式指定,否则整列热区序列也会出现在图例里
                "data": ["完课分布", "作业分布"],
                "textStyle": {"color": "#1f2329"},
            },
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            # 两个 grid 的十字准星联动,悬停同一节课时上下同时高亮
            "axisPointer": {"link": [{"xAxisIndex": "all"}]},
            "grid": [
                {"left": 62, "right": 24, "top": "13%", "height": "32%"},
                {"left": 62, "right": 24, "top": "55%", "height": "34%"},
            ],
            "xAxis": [
                {
                    "type": "category",
                    "gridIndex": 0,
                    "data": lessons,
                    # 课次标签竖排,33 个分类才挤得进一屏
                    "axisLabel": {"interval": 0, "rotate": 90, "fontSize": 10},
                    "axisTick": {"alignWithLabel": True},
                },
                {
                    "type": "category",
                    "gridIndex": 1,
                    "data": lessons,
                    # 下半的轴贴在中间那条线上,标签与上半重复故隐藏
                    "position": "top",
                    "axisLabel": {"show": False},
                    "axisTick": {"alignWithLabel": True},
                },
            ],
            "yAxis": [
                {
                    "type": "value",
                    "gridIndex": 0,
                    "name": "人数",
                    "minInterval": 1,
                    "max": y_max,
                    "nameTextStyle": {"color": "#86909c"},
                    "axisLabel": {"formatter": "{value}"},
                },
                {
                    "type": "value",
                    "gridIndex": 1,
                    "name": "人数",
                    "minInterval": 1,
                    "max": y_max,
                    # 反向:0 轴在上,柱子从中线向下长
                    "inverse": True,
                    "nameTextStyle": {"color": "#86909c"},
                    "axisLabel": {"formatter": "{value}"},
                },
            ],
            "series": [
                {
                    "type": "bar",
                    "name": "完课分布",
                    "xAxisIndex": 0,
                    "yAxisIndex": 0,
                    "data": course,
                    "barMaxWidth": 14,
                    "itemStyle": {"color": "#1456f0", "borderRadius": [3, 3, 0, 0]},
                },
                {
                    "type": "bar",
                    "name": "作业分布",
                    "xAxisIndex": 1,
                    "yAxisIndex": 1,
                    "data": assign,
                    "barMaxWidth": 14,
                    "itemStyle": {"color": "#00b578", "borderRadius": [0, 0, 3, 3]},
                },
                {
                    # 整列点击热区:柱子又细又短很难点中,所以给每一节从上半顶端
                    # 一路铺到下半底端(含中间课次标签带)一张透明矩形,
                    # 点到这一列任意位置都等同于选中这一节。
                    # renderItem 是 JS 函数,渲染前在页面里注入,见 _DISTRIBUTION_PAGE。
                    "type": "custom",
                    "name": "_hit",
                    "xAxisIndex": 0,
                    "yAxisIndex": 0,
                    "data": lessons,
                    "z": 5,
                    "clip": False,
                    "itemStyle": {"color": "rgba(0,0,0,0)"},
                    "emphasis": {"disabled": True},
                    "tooltip": {"show": False},
                },
            ],
        }

        payload = json.dumps(
            {
                label: {
                    "course": m["course_names"][i],
                    "assign": m["assign_names"][i],
                }
                for i, label in enumerate(lessons)
            },
            ensure_ascii=False,
        ).replace("<", "\\u003c").replace(">", "\\u003e")

        return (
            self._DISTRIBUTION_PAGE.replace("__DEPS__", self._echarts_deps())
            .replace(
                "__OPTION__",
                json.dumps(option, ensure_ascii=False)
                .replace("<", "\\u003c")
                .replace(">", "\\u003e"),
            )
            .replace("__DATA__", payload)
            .replace("__LESSONS__", json.dumps(lessons, ensure_ascii=False))
        )

    @classmethod
    def _echarts_deps(cls) -> str:
        """取 pyecharts 当前 ECharts 依赖的 <script src> 标签,避免硬编码 CDN 版本。"""
        stub = Bar(init_opts=opts.InitOpts(width="100%", height="1px"))
        stub.add_xaxis([""])
        stub.add_yaxis("_", [0])
        deps, _ = cls._split_chart_page(stub.render_embed())
        return deps

    @staticmethod
    def _split_chart_page(page: str) -> tuple:
        """把 pyecharts 整页拆成「依赖脚本」与「图表内容」两段,便于套进自定义页面。

        pyecharts 2.x 的 render_embed() 返回的是完整 HTML(simple_chart.html 模板),
        所以按 <head> 里的 <script src> 与 <body> 切开复用。
        """
        deps = "".join(
            re.findall(r'<script[^>]+src="[^"]+\.js"[^>]*>\s*</script>', page)
        )
        body = re.search(r"<body[^>]*>(.*?)</body>", page, re.S)
        return deps, body.group(1).strip() if body else page

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
                title_opts=opts.TitleOpts(
                    title=f"{m['batch_period']} · {m['record_name']}",
                    subtitle=f"在读人数：{m['total']}",
                    pos_top="1%",
                ),
                tooltip_opts=opts.TooltipOpts(
                    trigger="axis", formatter=self._tooltip_formatter(m)
                ),
                legend_opts=opts.LegendOpts(pos_top="8%"),
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
                "top": "17%",
                "bottom": "18%",
                "containLabel": True,
            }

            timeline.add(line, m["point_label"])

        return timeline

    def _tooltip_formatter(self, m: dict) -> JsCode:
        """生成悬停提示格式化函数:每条线显示自己对应的人数,不显示百分比。

        - 完课率/作业完成率行:累计人数(连续完成到该节含该节的人数)
        - 差值行:累计完课人数 - 累计作业人数(与率差线对应)
        人数数组直接烘焙进函数,不依赖任何全局状态。
        """
        payload = json.dumps(
            {
                "E": m["course_counts"],  # 累计完课
                "F": m["assign_counts"],  # 累计作业
                "D": m["count_diff"],  # 累计差(人数)
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
        """解析 data.xlsx,返回累计口径的完课/作业人数、率与逐节名单。

        - course_counts/assign_counts:连续完成到第 i 节(含)的人数 → 换算成率(累计口径)
        - course_names/assign_names:恰好连续完成到第 i 节的学员名单,
          下标 0 = 一节都没完成(「未开始」),1..n = 第 1..n 节
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

        students = self._student_labels(data)

        data = data[lesson_cols]
        total = len(data)
        if total == 0:
            raise ValueError("在读学员为 0")

        n = len(lesson_cols)
        course_counts = [0] * n
        assignment_counts = [0] * n
        # 下标 = 恰好连续进度(0 = 一节都没完成,单独归到「未开始」)
        course_names = [[] for _ in range(n + 1)]
        assign_names = [[] for _ in range(n + 1)]

        for pos, (_, row) in enumerate(data.iterrows()):
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

            course_names[course_len].append(students[pos])
            assign_names[assignment_len].append(students[pos])

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
            "course_names": course_names,
            "assign_names": assign_names,
        }

    @staticmethod
    def _student_labels(data) -> list:
        """在读学员的展示名:优先「真实姓名」,空则退化到「学号」。

        注意 data.columns 里存在「创建人姓名」,只能按精确名挑,不能做包含匹配。
        """
        def pick(*candidates):
            for cand in candidates:
                for col in data.columns:
                    if str(col).strip() == cand:
                        return col
            return None

        name_col = pick("真实姓名", "学员姓名", "姓名")
        if name_col is None:
            name_col = next(
                (
                    col
                    for col in data.columns
                    if str(col).strip().endswith("姓名") and "创建人" not in str(col)
                ),
                None,
            )
        id_col = pick("学号")

        def column(col):
            if col is None:
                return [""] * len(data)
            return ["" if pd.isnull(v) else str(v).strip() for v in data[col].tolist()]

        names = column(name_col)
        ids = column(id_col)
        return [name or sid or "未知" for name, sid in zip(names, ids)]
