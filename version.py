"""应用版本号 —— 唯一版本源。

- 程序启动后据此与 GitHub Release 的 tag 比较,判断是否有新版本。
- `scripts/release.ps1` 读取本文件校验 APP_VERSION 与命令行参数一致,
  一致才允许打 tag 并创建 Release,避免"改了代码忘了改版本号"。

发布流程:改本文件 -> commit -> `scripts\\release.ps1 -Version x.y.z`
"""

APP_VERSION = "1.0.0"
