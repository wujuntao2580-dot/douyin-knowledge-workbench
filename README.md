# 本地视频知识工作台

当前版本：**1.1.1**。Windows x64 本地应用，从自己的空知识库开始使用。

将视频转成简体口播稿与字幕，用本地模型整理摘要和时间要点，按主播、关键词、大主题和小主题查阅。支持收藏夹、主题调整，以及按范围删除资料。首次安装需要联网下载依赖和数 GB 模型，之后转写、摘要、收藏和主题管理不调用在线 AI API。

## 让 AI 安装最新版

将本仓库链接交给**能在你的 Windows 电脑上读写文件、运行程序的 AI**，要求阅读根目录 `AGENTS.md`，按下面流程部署并验收。网页聊天本身不能替你安装软件。

可直接复制 [完整 AI 安装描述](INSTALL_WITH_AI.md)。本次验收记录及边界见 [VALIDATION.md](VALIDATION.md)。

本仓库公开提供程序源码和安装脚本，下载无需获得作者的私人账号或资料。不要将 GitHub 密码、令牌或抖音 Cookie 贴到聊天里。个人数据位置及提交注意事项见 [隐私说明](PRIVACY.md)。

## 完整安装

需要 Windows x64、Microsoft Edge 和 Python **3.12 x64**。CPU 是默认验收方式；首次下载请留足空间和时间。如果没有 Python，可由你的 AI 使用系统的软件安装工具安装 Python.Python.3.12。

在本仓库目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1 -Models -Downloader -Player -DesktopShortcut
```

没有 `py.exe` 时指定 Python 3.12 的真实位置：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1 -PythonPath "C:\实际位置\python.exe" -Models -Downloader -Player -DesktopShortcut
```

- `-Models`：本地 Whisper 中文转写和 Qwen 离线摘要。
- `-Downloader`：DouK 下载器、独立 F2 环境与工作台登录支持。首次需要初始化 DouK 时，自行打开 `.runtime\douk\DouK-Downloader.exe` 选择语言并阅读首次提示，然后回工作台。
- `-Player`：免费 VLC，用于 H.265 压缩视频及时间点播放。
- `-DesktopShortcut`：创建「知识工作台」快捷方式，后台运行时不显示命令窗口。

FFmpeg 会随基础依赖安装。登录窗口使用自带的 Python Playwright 驱动与系统 Edge，不需要额外安装 Node 或 Chromium。

只整理本地视频时，可以省略 `-Downloader`；不压缩时可省略 `-Player`，并在提交批次前关闭「下载后压缩」。默认摘要按 CPU 运行；NVIDIA 转写选项需另行配置显卡运行组件，未实际验证时保留 CPU。

安装脚本只在当前进程中沿用系统已经启用的代理，不修改系统网络设置。模型站点不可达时先修复网络，然后重跑同一命令；不要删除 `data/`。

## 验收与启动

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Check.ps1 -RequireModels -RequireDownloader -RequirePlayer
```

按实际安装组件省略对应 `-Require...`。检查包括基础组件、模型文件、本机接口及主题／收藏／删除规则测试，**不等于真实视频已经处理成功**。

从桌面「知识工作台」或 `Open-Workbench.cmd` 打开。首次安装显示 **0 条视频**是正常状态。请使用自备的短中文 MP4，选择文件夹、勾选视频，并为本批选择主题归属方式，再验证逐字稿、SRT、摘要、搜索和时间点。需要下载抖音视频时，在右上角「抖音账号」由你自己完成登录；不会携带作者的登录信息。

## 主题、收藏与删除

- 默认八个大主题；每批选择自动归属或推荐后手动确认，不明确的新主题进入「待确认归属」。
- 「管理」中可给大、小主题改名、合并，调整小主题所属大主题。相同视频可关联多个小主题。
- 视频、小主题均可放入自建收藏夹；收藏小主题会持续显示以后新归入的内容。
- 勾选视频后点击「删除视频」，或从详情删除。紧凑弹窗四项默认勾选，可逐项取消。
- 文件送入 Windows 回收站，清空回收站后才释放相应空间。仅移除工作台记录时，本地视频和口播文件保留。共享主题、收藏夹、原始导入清单和独立历史导出不作为单个视频文件删除。
- 删除只针对登记的单个文件；拒绝目录链接和仍被其他视频引用的文件。后台有处理任务时先等任务结束。

## 更新和迁移

已有安装更新时，先保存改动和备份，再拉取 `main` 或最新稳定 Release，重跑安装命令。始终保留 `data/` 和 `.runtime/`。`VERSION`、提交号和最新 Release 可用于核对版本。

| 位置 | 用途 |
|---|---|
| `app/` | 程序源码 |
| `tests/` | 隔离测试，不会删除用户原视频 |
| `data/` | 个人目录、逐字稿、收藏、主题和批次 |
| `data/workbench-personal.json` | 个人主题、归属、收藏及删除记录；`.bak` 为上一保存版本 |
| `.runtime/` | Python 环境、下载器、播放器及模型 |

`data/`、`.runtime/`、媒体文件和凭据均被 Git 忽略。复制项目到另一台电脑时，代码可重新安装，个人数据应另外备份迁移。

第三方组件来自各自的上游项目，采用各自许可证：[DouK](https://github.com/JoeanAmier/TikTokDownloader)、[F2](https://github.com/Johnserf-Seed/f2)、[VLC](https://www.videolan.org/vlc/)、[llama.cpp](https://github.com/ggml-org/llama.cpp)、[Whisper 模型](https://huggingface.co/Systran/faster-whisper-small)、[Qwen 模型](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF)。
