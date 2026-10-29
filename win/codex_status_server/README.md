# Windows 状态服务

日常只需双击：

```text
启动状态服务.cmd
```

服务会隐藏在后台运行，默认只监听 `127.0.0.1:8767`，供本机 Rainmeter 读取。重复双击不会启动第二个实例。

浏览器验证：

```text
http://127.0.0.1:8767/health
```

如果需要让另一台电脑读取，在命令提示符中给同一个入口增加 `lan` 参数：

```cmd
启动状态服务.cmd lan
```

跨电脑前，在项目根目录执行 `python common/configure_access.py`，保存生成的私有令牌，之后启动或重启服务。皮肤读取地址使用 `http://服务电脑IP:8767/rainmeter?token=你的令牌`，远程健康检查使用 `/health?token=你的令牌`。浏览器看板打开服务根地址，在“访问设置”输入令牌。未配置或令牌不匹配时，局域网数据访问返回 403；本机访问无需令牌。

完整路线见 [普通用户快速开始](../../docs/快速开始.md)。

内部 Python、PowerShell 和维护脚本统一放在 `.internal`；状态、额度缓存、PID 和日志统一放在 `.runtime`。中文入口会把这两个目录设为 Windows 隐藏目录，旧版本位于当前目录的运行文件会在首次启动时自动迁移。

从旧版 8765 升级时，先在 Rainmeter 设置页点击“体检并修复服务”。脚本只会停止命令行确认属于当前项目的旧进程，随后迁移运行文件、启动 8767，并验证服务版本和协议版本。任务卡片可点击打开最多五行的活动任务面板。

维护命令需要在 PowerShell 中执行：

```powershell
.\.internal\service-doctor.ps1
.\.internal\service-doctor.ps1 -Repair
.\.internal\check-server-health.ps1
.\.internal\stop-server.ps1
.\.internal\install-login-autostart.ps1
.\.internal\uninstall-login-autostart.ps1
```

一般不需要手动切换状态；调试时可使用：

```powershell
.\.internal\set-status.ps1 idle
.\.internal\set-status.ps1 running "Codex 正在执行任务"
```

## 0.5 升级与安装路径

首次启动默认只监听本机。成功启动后，监听地址与端口保存在 `.runtime/launch-settings.json`；以后双击、登录启动、修改通知后重启均沿用该配置。`lan` 参数显式切换为局域网监听；需要自定义端口可设置 `CODEX_STATUS_PORT` 后启动。

皮肤安装会读取正在运行的 Rainmeter/便携配置中的 `SkinPath`，并支持 Windows 文档目录重定向。自定义安装时可执行：

```cmd
install-rainmeter-skin.cmd -SkinPath "D:\Rainmeter Skins"
install-rainmeter-skin.cmd -SettingsPath "D:\Portable Rainmeter\Rainmeter.ini"
```

`-SkinPath` 指向整个 Skins 目录，安装器自动创建其中的 `CodexTrafficLight` 子目录。旧用户设置会备份并保留。

设置页的“只读服务体检”不会修复或清理；“修复本机服务”是独立操作。显示远程电脑时，本机维护和通知按钮会说明目标范围，不会修改远程服务。点击主皮肤标题可打开状态看板，右键标题进入历史；点击额度数字可在看板手动刷新额度并查看进度。

整体缩放支持 75–180%，文字、图形和点击区域同步。离线标签显示本机最后成功读取数据的时间，超过 10 秒没有新数据后状态灯变灰。
