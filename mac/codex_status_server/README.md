# macOS 状态服务

日常只需双击：

```text
启动状态服务.command
```

服务会隐藏在后台运行，首次默认监听 `0.0.0.0:8767`，供同一局域网内的 Windows Rainmeter 读取。重复双击不会启动第二个实例。

0.5.1 起，跨电脑读取需要访问令牌。先在项目根目录执行 `python3 common/configure_access.py`，保存显示的私有令牌，再启动或重启服务。Windows 皮肤使用 `http://Mac-IP:8767/rainmeter?token=你的令牌`；远程健康检查也要带 `/health?token=你的令牌`。浏览器看板打开 `http://Mac-IP:8767/`，在“访问设置”输入令牌。未配置或令牌不匹配时返回 403；Mac 本机仍可直接访问。

首次终端启动、查 IP 和 Windows 皮肤安装的完整步骤见 [普通用户快速开始](../../docs/快速开始.md)。

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

## 只读体检

运行 `bash .internal/health-check.command`，会核验版本、协议、端口、进程身份及登录启动配置，并给出日志位置和处理建议。自定义端口通过 `PORT` 指定。异常退出码为 1，不会自动停止任何进程。

## 0.5 启动配置

成功启动后，地址与端口保存到 `.runtime/launch-settings.json`。以后双击和登录启动会沿用；`CODEX_STATUS_HOST`、`CODEX_STATUS_PORT` 或 `PORT` 可显式覆盖。只读体检默认检查保存的端口。

Windows 皮肤的通知和维护按钮仅操作 Windows 本机。Mac 的服务通知设置应在 Mac 上调整；Windows 可以从皮肤打开 Mac 的状态看板，查看健康、历史及额度刷新进度。
