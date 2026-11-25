# 给接收方 AI 的完整安装要求

请帮我在这台 Windows 电脑上安装并实际验证「本地视频知识工作台」最新版：

https://github.com/wujuntao2580-dot/douyin-knowledge-workbench

请直接执行安装，不要只给步骤。先确认你能读写本机和运行程序。本仓库公开提供源码；遇到 404／下载失败请检查地址和网络，不要换成其他同名项目，也不要让我把密码或令牌贴到聊天里。

1. 查询 GitHub 最新稳定 Release 和 main，取得远端代码并核对 VERSION、标签及提交号。当前发布版本为 1.1.1；安装时重新查询最新版，不使用旧缓存或仅凭 ZIP 文件名判断。先阅读根目录 AGENTS.md、README.md、CHANGELOG.md、VALIDATION.md、PRIVACY.md。
2. 选用我有写权限的固定安装目录并告知位置。若已有安装，先备份并保护 data/、.runtime/ 和本地改动；确认后台没有活动任务再更新，不能为更新而清空资料。
3. 检查 Windows x64、Microsoft Edge、Python 3.12 x64，缺少的基础软件先配置。没有 py.exe 时用已核实的 Python 3.12 路径作为 -PythonPath。
4. 在仓库目录执行：

   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1 -Models -Downloader -Player -DesktopShortcut

   需要指定 Python 时追加 -PythonPath "实际的python.exe完整路径"。等待模型、DouK、F2、VLC 和依赖安装结束；网络失败先排查并接续，不跳过校验，不宣称下载中已经完成。不要开通付费服务或配置在线 AI Key。
5. 执行：

   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Check.ps1 -RequireModels -RequireDownloader -RequirePlayer

   默认以 CPU 验收，显卡加速须单独实测。确认桌面「知识工作台」及 Open-Workbench.cmd 都能打开，后台不弹命令窗口，能进入「下载与入库」。新用户空知识库显示 0 条视频正常。
6. 首次 DouK 需要语言和提示初始化时，引导我自行完成首次提示。抖音扫码、手机号登录及平台验证由我本人操作，不复制作者登录信息，不将 Cookie 写进报告。
7. 用我提供的短中文 MP4 临时副本验收：导入、简体口播稿、SRT、离线摘要、时间要点、主题归属、关键词搜索、实际播放和跳转。每批让我选择自动归属或推荐后手动确认；验证视频和小主题收藏刷新后保留。删除测试只用临时副本，禁止删除原文件。没有样片或尚未登录时，清楚列出对应未验证步骤。
8. 最后报告远端版本与提交号、安装位置、快捷方式、检查结果、实测功能和剩余问题。不要把依赖安装、接口返回、真实转写、实际播放及联网下载混为同一种验证，也不要在检查失败时宣布全部完成。
