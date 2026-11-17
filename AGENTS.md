# 在接收方电脑上部署

1. 以接收方有写权限的项目目录为工作目录。确认系统可用 Windows x64、Microsoft Edge 和 Python 3.12 x64。没有 Python 时，可通过 Windows 的应用安装工具为当前用户安装 Python.Python.3.12，然后重新打开终端。没有 py.exe 时，将 Python 3.12 可执行文件的完整路径传给 Install.ps1 的 -PythonPath。
2. 默认运行 powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1 -Models，准备本地中文转写和离线摘要。如果接收方只查阅或维护已有目录，可以省略 -Models。安装失败时保留 data/，根据错误恢复所缺依赖后重跑。使用现有工作目录时同样保留 data/。
3. 用户需要在线下载时才加 -Downloader 安装 DouK 5.8。用户在 DouK 自行登录。FFmpeg 和 VLC 的配置见 README。默认按 CPU 路径验收。
4. 运行 powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Check.ps1 -RequireModels。未安装模型时去掉 -RequireModels。通过 Open-Workbench.cmd 打开浏览器，确认首页能进入「下载与入库」。全新安装预期有零条视频。
5. 用户提供自己的短中文口播 MP4 时，用「本地视频」选择该文件所在的目录，取消压缩，顺序验证转写、确认入库、摘要、按标题搜索和时间点。记录实际通过的步骤和遇到的错误。
6. 将 Open-Workbench.cmd 的位置交给用户。data/ 是个人资料，.runtime/ 是依赖目录。提交程序修改时继续使用仓库的忽略规则。
