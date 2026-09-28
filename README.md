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

点击**右侧操作面板**顶部的 `全局凭据配置` 按钮 → 在弹窗中填写以下字段 → 点击 `保存`:

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

## 自动更新

更新入口**只在打包版出现**:源码运行没有可被替换的 exe,`检查更新` 按钮隐藏、启动也不查。

- **启动静默检查** —— 主窗口显示约 3 秒后在后台查一次 GitHub Releases,不阻塞启动;只有发现新版才弹窗。
- **手动检查** —— 点击右侧操作面板顶部的 `检查更新` 按钮。
- **更新流程** —— 弹窗展示版本说明 → `立即更新` → 后台下载 → 用 GitHub 自动给出的 `asset.digest` 做 SHA-256 校验 → 解压 → 生成 `%TEMP%\StudentDataProcessor-update\apply_update.bat` → 应用退出 → 脚本等进程真的退出后 `robocopy /MIR` 覆盖安装目录 → 自动重启。
- **覆盖时保留** —— `data\` 与 `sessionid.txt` 不被动(`robocopy /XD data /XF sessionid.txt`),本地凭据和数据都还在。
- **可取消** —— 下载阶段可以取消;校验、解压、替换期间关闭按钮被禁用(临界点之后不再接受取消)。
- **失败退避** —— 启动检查失败后 1 小时内不再重试(标记在 `%APPDATA%\StudentDataProcessor\update_state.json`);`检查更新` 手动入口不受此限制。
- **临时文件** —— 下载包与更新脚本都在 `%TEMP%\StudentDataProcessor-update\`,日志写在同目录的 `update.log`,下次启动自动清理。

### 发布新版本

```powershell
# 1. 改 version.py 的 APP_VERSION 为新版本号,提交并推送
# 2. 打包 + 打 tag + 上传 Release(需先 winget install GitHub.cli 并 gh auth login)
.\scripts\release.ps1 -Version 1.1.0 -Notes "1. 新增自动更新"
```

`release.ps1` 会强制校验:`version.py` 与 `-Version` 一致、工作区干净、分支已推送、tag 未重复;打包后再检查 exe 存在、`Resources` 已打包、没混进 `data\`,最后才压缩上传。只想打包不发版就加 `-SkipPublish`。

> 首次发布建议先用 `-SkipPublish` 打一次,确认 `dist\StudentDataProcessor-1.1.0-win64.zip` 正常再真发。

## 目录结构

```dir
StudentDataProcessor/
├── main.py                       # 程序入口
├── requirements.txt              # 依赖清单
├── version.py                    # 唯一版本源(APP_VERSION),发布脚本据此打 tag
├── .gitignore                    # 忽略 data/ venv/ dist/ build/ *.spec 等
├── README.md                     # 项目说明
│
├── Bootstrap/                    # 启动编排
│   ├── AppRunner.py              #   资源路径 / 全局样式 / 单实例检测 / 程序图标
│   └── AppOrchestrator.py        #   组装服务与视图控制器,解析数据根目录
│
├── Controllers/                  # 控制器层(MVC)
│   ├── ClassController.py        #   班级 tab 增删 + 切换
│   ├── FileProcessController.py  #   剪贴板监听 / 同步 / 拆分 / 图表
│   └── UpdateController.py       #   启动/手动检查更新、一键更新并重启
│
├── Services/                     # 业务服务
│   ├── DirectoryService.py       #   数据目录、班级、记录管理
│   ├── Logger.py                 #   全局日志(Qt 信号分发到日志面板)
│   ├── XiaoeTechClient.py        #   小鹅通 HTTP 客户端
│   ├── XiaogetongSyncWorker.py   #   小鹅通同步后台任务
│   ├── ShuatiApiClient.py        #   刷题系统 HTTP 客户端
│   ├── ShuatiLoginWorker.py      #   刷题系统登录与 sessionid 校验
│   ├── ShuatiSyncWorker.py       #   刷题系统同步后台任务
│   ├── JihuaApiClient.py         #   计划学院 HTTP 客户端(登录/同步/下载)
│   ├── JihuaLoginWorker.py       #   JSESSIONID 过期时自动重新登录
│   ├── JihuaDownloadWorker.py    #   下载完课/作业 Excel
│   ├── WeDocSyncWorker.py        #   企业微信在线文档分块写入
│   ├── ExcelSyncService.py       #   同步任务调度(子线程)
│   ├── ExcelSplitterService.py   #   拆分(完课/作业/完课作业)
│   ├── ExcelExportService.py     #   同步后自动重新拆分
│   ├── ExcelExportWorker.py      #   后台拆分 Worker
│   ├── ExcelChartService.py      #   pyecharts 折线图
│   ├── UpdateService.py          #   更新源访问 / 版本比较 / SHA-256 校验
│   └── UpdateWorker.py           #   下载解压 + 生成更新脚本的后台任务
│
├── Views/                        # 视图层(PySide6)
│   ├── MainWindow.py             #   主窗口(QSplitter)
│   ├── ClassTabBarView.py        #   顶部班级 tab + 新建按钮
│   ├── FileDetailView.py         #   右侧操作面板 + 日志区
│   ├── SettingsDialog.py         #   配置中心(全局凭据)
│   ├── SheetIdDialog.py          #   企业微信 DOC_ID / SHEET_ID 弹窗
│   └── UpdateDialog.py           #   新版本提示 + 下载进度弹窗
│
├── scripts/                      # 发布脚本
│   └── release.ps1               #   打包 + 打 tag + 上传 GitHub Release
│
└── Resources/                    # 打包随附资源
    └── icon.ico                  #   程序图标(打包必须,否则没图标)
```

运行时数据不在项目目录内,首次启动会创建 `%APPDATA%\StudentDataProcessor\`:

```dir
%APPDATA%\StudentDataProcessor\     # 运行时工作目录(自动创建)
├── config.json                     # 全局凭据
├── update_state.json               # 上次更新检查失败的时间,启动检查据此退避
└── class/
    └── <班级名>/
        └── <YYYYMMDD_HHMMSS>/      # 一份导入的 Excel 对应一个记录目录
            ├── data.xlsx
            └── split/              # 拆分后的输出目录
                └── course.xlsx
```
