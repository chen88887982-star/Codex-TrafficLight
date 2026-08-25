# macOS 状态服务

日常只需双击：

```text
启动状态服务.command
```

服务会隐藏在后台运行，默认监听 `0.0.0.0:8767`，供同一局域网内的 Windows Rainmeter 读取。重复双击不会启动第二个实例。

本机验证：

```text
http://127.0.0.1:8767/health
```

如果只允许本机访问，可在终端中使用：

```bash
CODEX_STATUS_HOST=127.0.0.1 ./启动状态服务.command
```

内部实现和维护脚本统一放在隐藏目录 `.internal`；状态、额度缓存、PID 和日志统一放在隐藏目录 `.runtime`。旧版本位于当前目录的运行文件会在首次启动时自动迁移。

启动器会同时验证服务身份、`service_version` 和 `protocol_version`，不会把未重启的旧后端当作当前服务复用。状态服务支持定时额度刷新和可选的 macOS 通知。

维护命令：

```bash
./.internal/health-check.command
./.internal/stop.command
./.internal/install-login-autostart.command
./.internal/uninstall-login-autostart.command
```

一般不需要手动切换状态；调试时可使用：

```bash
./.internal/set-status.sh idle
./.internal/set-status.sh running "Codex 正在执行任务"
```
