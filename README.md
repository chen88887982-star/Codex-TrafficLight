# Codex 运行状态交通灯 Rainmeter 皮肤

这个项目是一套通用 Rainmeter 交通灯方案。Rainmeter 固定运行在 Windows 上，Codex 可以运行在同一台 Windows、另一台 Windows，或者一台 Mac。

## 组合方式

| 装备组合 | 状态服务运行位置 | Rainmeter 配置 |
|---|---|---|
| Win + Win 同一台电脑 | 本机 Windows | `http://127.0.0.1:8765/rainmeter` |
| Win + 另一台 Win | 运行 Codex 的 Windows | `http://对方Windows-IP:8765/rainmeter` |
| Win + Mac | 运行 Codex 的 Mac | `http://Mac-IP:8765/rainmeter` |

Rainmeter 只负责读取 `StatusUrl`。所以两套装备通用的关键就是：哪台电脑运行 Codex，就在哪台电脑启动状态服务。

## Windows 端安装皮肤

在 Rainmeter 所在的 Windows 上双击：

```text
install-rainmeter-skin.cmd
```

它会复制皮肤到：

```text
%USERPROFILE%\Documents\Rainmeter\Skins\CodexTrafficLight
```

然后打开 Rainmeter 管理器，点击“刷新全部”，加载：

```text
CodexTrafficLight\CodexTrafficLight.ini
```

右键主皮肤可以打开“设置”。设置页会显示当前接口地址，可以一键设为本机 Windows，也可以手动填写远程电脑地址、调整背景透明度、显示调试信息。

## 配置 Rainmeter 读取地址

默认配置适合 Codex 和 Rainmeter 都在同一台 Windows：

```ini
StatusUrl=http://127.0.0.1:8765/rainmeter
```

跨电脑时，在设置页把地址改成运行 Codex 那台电脑的局域网 IP：

```ini
StatusUrl=http://对方IP:8765/rainmeter
```

浏览器验证服务是否可访问时，用 `/status`：

```text
http://对方IP:8765/status
```

查看 Windows 本机 IP：在运行 Codex 的 Windows 上打开命令提示符，输入 `ipconfig`，找当前联网网卡下的 `IPv4 地址`，通常是 `192.168.x.x`、`10.x.x.x` 或 `172.16-31.x.x`。

查看 Mac 本机 IP：打开“系统设置” -> “网络”，点当前正在使用的 Wi-Fi 或以太网，查看 IP 地址；也可以在终端运行 `ipconfig getifaddr en0`，有线网络可能是 `en1` 或其他网卡。

## Codex 在 Windows 时

在运行 Codex 的 Windows 上双击：

```text
win\codex_status_server\start-server.cmd
```

Windows 状态服务现在默认使用 Python 标准库 HTTP 服务。运行电脑需要安装 Python 3，并且命令行能识别 `py -3` 或 `python`。

Windows 状态服务会自动监听当前用户的 Codex 会话日志，并根据对话任务状态更新灯光：任务开始、生成回复、执行工具或处理工具结果都会立即保持红灯，任务完成为绿灯，完成 45 秒后回到灰灯。

如果不想保留黑色窗口，可以双击：

```text
win\codex_status_server\start-server-background.cmd
```

后台启动后用下面这个脚本停止：

```text
win\codex_status_server\stop-server.cmd
```

如果使用黑色窗口版，不要在窗口里拖选文字。窗口标题出现“选择”时，Windows 会暂停控制台程序，Rainmeter 就会连接失败；按 `Esc` 可以退出选择状态。

浏览器打开：

```text
http://127.0.0.1:8765/status
```

如果是另一台 Windows 读取，就在另一台电脑浏览器打开：

```text
http://运行Codex电脑的IP:8765/status
```

Windows 状态服务会写日志：

```text
win\codex_status_server\status-server.log
```

如果 Rainmeter 一直显示连接失败，先看这个日志里有没有 `Request from`。没有请求，说明 Rainmeter 没有访问到服务；有请求但仍失败，再看 Rainmeter 的调试信息和返回内容。

旧的 `server.ps1` 只是保留作备用，不再作为默认启动方式。

切换状态：

```powershell
.\win\codex_status_server\set-status.ps1 idle
.\win\codex_status_server\set-status.ps1 running "Codex 正在执行任务"
.\win\codex_status_server\set-status.ps1 waiting "等待用户确认"
.\win\codex_status_server\set-status.ps1 success "任务完成"
.\win\codex_status_server\set-status.ps1 error "任务失败"
```

## Codex 在 Mac 时

把这个目录复制到 Mac：

```text
mac/codex_status_server
```

在 Mac 终端执行：

```bash
chmod +x set-status.sh start.command
./start.command
```

切换状态：

```bash
./set-status.sh idle
./set-status.sh running "Codex 正在执行任务"
./set-status.sh waiting "等待用户确认"
./set-status.sh success "任务完成"
./set-status.sh error "任务失败"
```

Windows 浏览器打开：

```text
http://Mac-IP:8765/status
```

能看到 JSON 后，Rainmeter 就能自动变灯。

## 状态含义

| 状态 | 含义 | 灯光 |
|---|---|---|
| `idle` | 空闲 | 灰灯 |
| `running` | 正在运行 | 红灯 |
| `waiting` | 等待用户确认 | 黄灯 |
| `success` | 运行完成 | 绿灯 |
| `error` | 运行失败、异常或连接失败 | 红色错误态 |

## 乱码处理

Rainmeter 对中文配置文件的编码比较敏感。本项目的 Rainmeter 文件应使用 Unicode 编码保存。如果桌面显示乱码，重新安装最新项目文件，然后在 Rainmeter 里刷新皮肤。

## 安全说明

状态服务只提供只读 `/status` 接口，不提供远程执行命令能力。`message` 建议只写简短状态，不要写路径、账号、密钥等敏感内容。
