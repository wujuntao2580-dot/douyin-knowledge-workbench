# 抖音主播知识工作台

在 Windows 电脑上，把自己的视频整理成可按主播、关键词和小主题查阅的个人知识库。导入本地 MP4 后，可生成简体逐字稿和 SRT，再用本地模型整理摘要、要点和时间点。安装后从空库开始。

## 让 AI 部署

把仓库链接或解压后的文件夹交给能在你电脑上执行命令的 AI，发这句话。

> 请阅读仓库根目录的 AGENTS.md，按里面的步骤在我的 Windows 电脑上部署并验收。默认启用本地视频转写和离线摘要。部署结束告诉我以后双击哪个文件。

## 手动部署

准备 Windows x64 的 Python 3.12 和 Microsoft Edge。首次安装会联网下载依赖和模型。运行以下命令，然后双击 Open-Workbench.cmd。

~~~powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1 -Models
~~~

需要在线采集时，用同一命令加上 -Downloader。安装后打开 .runtime\douk\DouK-Downloader.exe，在它的主菜单自行完成抖音登录配置。回到工作台的「下载与入库」，可以用主页链接或视频链接清单。导入本地 MP4 时无需抖音登录。

视频压缩需准备支持 libx265 的 FFmpeg。把 ffmpeg.exe 放到 .runtime\ffmpeg\，或把它所在目录加入 PATH。压缩版的时间跳转使用 VLC，把官方 Windows 免安装版解压至 .runtime\vlc\，让 vlc.exe 直接位于该目录。暂未配置时，可在提交批次前取消勾选「下载后压缩」，保留原视频供浏览器播放。

## 代码和数据

| 位置 | 用途 |
|---|---|
| app/catalog/ | 生成知识库页面并登记作品清单 |
| app/workbench/、app/workflow/ | 本机入口、批次队列和导入界面 |
| app/transcription/、app/summary/ | 本地转写和摘要 |
| app/compression/ | 视频压缩 |
| data/、.runtime/ | 安装后生成的个人数据和依赖，由 Git 忽略 |

本机自检可运行 Check.ps1。它检查页面数据和本地入库接口。加 -RequireModels 可检查模型文件是否齐全。实际转写和摘要用自备的短中文口播 MP4 验收。
