# StudentDataProcessor

基于 PySide6 的桌面端工具,用于处理**追光鲸**导出的学员完课/作业数据。

首次启动会创建 `%APPDATA%\StudentDataProcessor\` 工作目录,内含:

- `config.json` —— 保存小鹅通 Ecookie、刷题系统 sessionid
- `class/` —— 班级目录(每个班级下放一份份 Excel 数据)

## 快速开始

### 0. 启动程序

双击 `main.py` (或在虚拟环境中运行 `python main.py`)。

### 1. 添加班级

点击界面**顶部栏最右侧的 `+` 按钮** → 在弹出的输入框中填写**企业微信群的完整群名** → 回车确认。

> **群名格式要求**：必须是企业微信群的完整名称,例如 `Py164期课堂梳理群（Python编程课_08FJXY14）`。
> 班级名中提取的期号数字(如 `164`)决定了后续下载同步时所用接口 —— 期号 ≤ 160 时使用小鹅通 Ecookie,期号 > 160 时使用刷题系统 sessionid。

添加后,该班级会出现在顶部的 tab 栏中并自动选中。

### 2. 配置 Cookies (一次性,全局生效)

点击**右侧操作面板**顶部的 `配置` 按钮 → 在 `配置中心` 弹窗中填写以下字段 → 点击 `保存`:

| 字段 | 说明 | 取得方式 |
|------|------|----------|
| **JSESSIONID** | 计划学院(jihuaxueyuan.com)登录会话 | 登录网址 `https://xs.jihuaxueyuan.com` 后,从浏览器 DevTools → Application → Cookies 中复制 `JSESSIONID` 值 |
| **Ecookie** | 小鹅通登录 cookie | 登录小鹅通后台后,从浏览器 DevTools → Application → Cookies 中复制 `Ecookie` 的 Value |
| **sessionid** | 刷题系统登录会话 | 刷题系统官网登录后,从浏览器 DevTools → Application → Cookies 中复制 `sessionid` 的 Value |
| **钉钉账号** | 手机号 | 用于 JSESSIONID 过期时自动重新获取 |
| **钉钉密码** | 密码 | 同上,建议在 JSESSIONID 过期后填写 |

> - 期号 ≤ 160 的班级: **仅需 JSESSIONID + Ecookie**
> - 期号 > 160 的班级: **仅需 JSESSIONID + sessionid**
> - JSESSIONID 过期后程序会自动尝试用钉钉账号密码重新获取,无需手动操作。

### 3. 配置企业微信在线文档 (每个班级独立)

点击**右侧操作面板**中 `同步至企业微信在线文档` 按钮旁边的 `配置` 按钮 → 在弹窗中填写:

| 字段 | 说明 | 取得方式 |
|------|------|----------|
| **DOC_ID** | 企业微信在线文档(表格)的文档 ID | 在企业微信中打开目标群 → 群文件 → 在线文档 → 文档 URL 中提取 |
| **SHEET_ID** | 对应工作表的 sheet ID | 在线文档 → 表格 → 工作表标签右键复制 sheet id |

保存后,该配置仅对当前选中的班级生效。

### 4. 下载最新数据

点击**右侧操作面板**的 `下载最新数据` 按钮。程序会:

1. 验证 JSESSIONID,过期则用钉钉账号自动重新登录。
2. 触发计划学院服务器同步课程与作业数据(轮询直至就绪)。
3. 下载最新的学员完课/作业 Excel。
4. 保存到 `%APPDATA%\StudentDataProcessor\class\<班级名>\<YYYYMMDD_HHMMSS>\data.xlsx`。
5. 根据期号自动选择小鹅通或刷题系统接口,同步额外学员数据。
6. 自动拆分 Excel 为 `course.xlsx`、`homework.xlsx` 等。

整个过程在后台线程执行,按钮会短时禁用,完成后在**日志区**显示结果。

### 5. 查看拆分数据

点击 `打开拆分数据文件夹` 按钮 → 系统自动打开 `%APPDATA%\StudentDataProcessor\class\<班级名>\<记录目录>\split\`。

### 6. 绘制折线图

点击 `绘制折线图` 按钮 → 程序读取当前班级下所有记录,生成时间轴折线图(html),并自动在浏览器中打开。

### 7. 同步到企业微信在线文档

点击 `同步至企业微信在线文档` 按钮 → 程序读取拆分后的 `course.xlsx` 和 `homework.xlsx`,将学员的编号课时数据写入企业微信在线文档的对应单元格。

> - 同步前**必须**完成第 3 步的 DOC_ID 和 SHEET_ID 配置。
> - 使用 `wecom-cli` 工具调用企业微信 API,请确保 Node.js 和 wecom-cli 环境已就绪(详见 `WeDocSyncWorker.py`)。

### 操作流程图

```
添加班级(+)  →  配置 Cookies  →  配置在线文档(DOC_ID/SHEET_ID)  →  下载最新数据
                                                                              ↓
                                                          →  查看拆分数据  /  绘制折线图  /  同步到企业微信
```

## 目录结构

```dir
StudentDataProcessor/
├── main.py                       # 程序入口
│
├── Bootstrap/                    # 启动编排
│   ├── AppRunner.py
│   └── AppOrchestrator.py
│
├── Controllers/                  # 控制器层(MVC)
│   ├── ClassController.py        #   班级 tab 增删 + 切换
│   └── FileProcessController.py  #   剪贴板监听 / 同步 / 拆分 / 图表
│
├── Services/                     # 业务服务
│   ├── DirectoryService.py       #   数据目录、班级、记录管理
│   ├── XiaoeTechClient.py        #   小鹅通 HTTP 客户端
│   ├── XiaogetongSyncWorker.py   #   小鹅通同步后台任务
│   ├── ShuatiApiClient.py        #   刷题系统 HTTP 客户端
│   ├── ShuatiSyncWorker.py       #   刷题系统同步后台任务
│   ├── ExcelSyncService.py       #   同步任务调度(子线程)
│   ├── ExcelSplitterService.py   #   拆分(完课/作业/完课作业)
│   ├── ExcelExportService.py     #   同步后自动重新拆分
│   ├── ExcelExportWorker.py      #   后台拆分 Worker
│   └── ExcelChartService.py      #   pyecharts 折线图
│
├── Views/                        # 视图层(PySide6)
│   ├── MainWindow.py             #   主窗口(QSplitter)
│   ├── ClassTabBarView.py        #   顶部班级 tab + 新建按钮
│   ├── FileListView.py           #   左侧记录列表
│   ├── FileDetailView.py         #   右侧操作面板 + 日志区
│   └── FileDropArea.py
│
└── (项目内不再产生运行时数据,数据目录已移出,见下)
```

运行时数据不在项目目录内,首次启动会创建 `%APPDATA%\StudentDataProcessor\`:

```dir
%APPDATA%\StudentDataProcessor\     # 运行时工作目录(自动创建)
├── config.json                     # 全局凭据
└── class/
    └── <班级名>/
        └── <YYYYMMDD_HHMMSS>/      # 一份导入的 Excel 对应一个记录目录
            ├── data.xlsx
            └── split/              # 拆分后的输出目录
                └── course.xlsx
```
