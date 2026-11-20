# 在接收方 Windows 电脑部署与验收

1. 目标仓库是 https://github.com/wujuntao2580-dot/douyin-knowledge-workbench 。先确认用户拥有访问权限，下载当前 main 或最新稳定 Release；核对 VERSION。不要用同名项目或旧缓存代替。访问受限时明确需要仓库授权，不询问或展示用户的密码和令牌。
2. 以接收方有写权限、用户认可的目录为安装目录。已有安装先保护 data/、.runtime/ 和本地改动，不能为更新而清空数据。
3. 检查 Windows x64、Edge、Python 3.12 x64。缺少 Python 时可用系统的软件安装工具为当前用户安装 Python.Python.3.12。没有 py.exe 时把已核实的 Python 3.12 路径传给 Install.ps1 -PythonPath。
4. 默认运行 powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1 -Models -Downloader -Player -DesktopShortcut 。仅本地模式可按用户目标省略下载器。不要把安装过程中仍在下载的状态说成完成。遇到网络问题修复当前网络后重跑；不要跳过校验或删除 data/。
5. 运行 powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Check.ps1 -RequireModels -RequireDownloader -RequirePlayer ，参数应与安装组件一致。CPU 是默认验收路线；不要仅凭检测到 NVIDIA 就宣布显卡转写可用。
6. 打开桌面「知识工作台」或 Open-Workbench.cmd，确认知识库及「下载与入库」可进入。新安装应为零条视频，不能复制作者的私人资料或登录信息。首次 DouK 需要语言和提示初始化时，引导用户自行完成提示确认。抖音扫码、手机号登录及任何平台验证由用户本人完成。
7. 用户提供短中文 MP4 时，先用临时副本验收转写、简体逐字稿、SRT、摘要、知识主题、关键词搜索和时间点。每批须让用户选择自动归属或推荐后手动确认。收藏视频和小主题后刷新检查保留；删除功能只用验收副本测试，不删除用户的原文件。
8. 最后报告仓库、版本与提交号、安装位置、快捷方式、已实测步骤和未完成部分。结构检查、模型文件存在、真实转写、实际播放及在线下载是不同证据，不可混为一谈。缺少用户登录或样本时明确对应功能尚未实测，不冒称全部通过。
