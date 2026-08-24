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

内部 Python、PowerShell 和维护脚本统一放在 `.internal`；状态、额度缓存、PID 和日志统一放在 `.runtime`。中文入口会把这两个目录设为 Windows 隐藏目录，旧版本位于当前目录的运行文件会在首次启动时自动迁移。

维护命令需要在 PowerShell 中执行：

```powershell
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
