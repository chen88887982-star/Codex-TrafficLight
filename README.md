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

在 Rainmeter 所在的 Windows 上，先打开项目文件夹，再双击：

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

### 方式 A：Codex 和 Rainmeter 在同一台 Windows

1. 打开项目文件夹。

如果项目放在桌面，先在资源管理器里进入：

```text
Codex-TrafficLight
```

2. 在这台 Windows 上启动状态服务，双击：

```text
win\codex_status_server\start-server.cmd
```

3. 启动后不要关闭黑色命令窗口。窗口开着，就代表状态服务还在运行。

4. Rainmeter 设置页里填：

```text
http://127.0.0.1:8765/rainmeter
```

5. 浏览器验证：

```text
http://127.0.0.1:8765/status
```

### 方式 B：Codex 在一台 Windows，Rainmeter 在另一台 Windows

1. 在运行 Codex 的 A 电脑上打开项目文件夹。

2. 在 A 电脑上启动状态服务，双击：

```text
win\codex_status_server\start-server.cmd
```

3. 在 A 电脑上查看本机 IP。

打开命令提示符，输入：

```cmd
ipconfig
```

找到当前正在联网的网卡，例如 `无线局域网适配器 WLAN` 或 `以太网适配器 以太网`，复制里面的 `IPv4 地址`，一般长这样：

```text
192.168.2.112
```

4. 在 Rainmeter 那台 B 电脑的浏览器验证：

```text
http://运行Codex电脑的IP:8765/status
```

例如：

```text
http://192.168.2.112:8765/status
```

5. 在 B 电脑的 Rainmeter 设置页填：

```text
http://运行Codex电脑的IP:8765/rainmeter
```

例如：

```text
http://192.168.2.112:8765/rainmeter
```

### Windows 端说明

Windows 状态服务默认使用 Python 标准库 HTTP 服务。运行电脑需要安装 Python 3，并且命令行能识别 `py -3` 或 `python`。

Windows 状态服务会自动监听当前用户的 Codex 会话日志，并根据对话任务状态更新灯光：任务开始、生成回复、执行工具或处理工具结果都会立即保持红灯，任务完成为绿灯，完成 45 秒后回到灰灯。

状态服务也会自动读取当前用户的 Codex 剩余额度。这里显示的不是官方实时额度，而是“最近一次 Codex 本地会话日志记录到的额度”。默认路径是：

```text
Windows: %USERPROFILE%\.codex\sessions
macOS: ~/.codex/sessions
```

如果用户把 Codex 数据目录放在别处，可以在启动服务前设置 `CODEX_HOME` 环境变量，指向自己的 `.codex` 目录。服务会读取日志里的 `rate_limits.used_percent`，并自动换算成剩余额度 `100 - used_percent`。

服务会把最新一次成功读取到的额度写入本地 `usage-cache.json`。只有发现新的 `rate_limits` 时才更新缓存；如果本次日志里没有新的 `rate_limits`，就继续使用上次缓存，不清空、不伪造实时数据。Rainmeter 皮肤读取状态服务输出的缓存结果，并显示“更新 HH:MM”或“可能滞后 HH:MM”。默认超过 15 分钟没有新额度记录会提示可能滞后，可用环境变量 `USAGE_STALE_SECONDS` 调整。

如果不想保留黑色窗口，可以双击：

```text
win\codex_status_server\start-server-background.cmd
```

后台启动后用下面这个脚本停止：

```text
win\codex_status_server\stop-server.cmd
```

如果使用黑色窗口版，不要在窗口里拖选文字。窗口标题出现“选择”时，Windows 会暂停控制台程序，Rainmeter 就会连接失败；按 `Esc` 可以退出选择状态。

查看剩余额度接口：

```text
http://127.0.0.1:8765/usage
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

### Mac 作为 Codex 状态服务电脑

Rainmeter 仍然运行在 Windows 上；Mac 负责运行 Codex 和状态服务。

1. 确认项目已经在 Mac 上。

如果你是用 Git 克隆的，项目一般在类似下面的位置：

```text
/Users/你的用户名/Documents/Codex-TrafficLight
```

2. 打开 Mac 终端，先进入 Mac 服务目录。

如果项目就在当前这台 Mac 的 Documents 里，可以直接复制这一行：

```bash
cd ~/Documents/Codex-TrafficLight/mac/codex_status_server
```

如果你的项目在别的位置，就进入你自己的路径，例如：

```text
cd /你的路径/Codex-TrafficLight/mac/codex_status_server
```

3. 确认自己进对目录。

```bash
ls
```

正常应该能看到：

```text
README.md
server.py
set-status.sh
start.command
status.example.json
```

4. 第一次运行前给脚本执行权限：

```bash
chmod +x set-status.sh start.command
```

如果提示 `No such file or directory`，说明你还没有进入 `mac/codex_status_server` 这个目录。先重新执行第 2 步的 `cd ...`。

5. 启动服务：

```bash
./start.command
```

终端窗口不要关闭。

6. 先在 Mac 本机验证服务：

```bash
curl http://127.0.0.1:8765/status
```

能看到 JSON 内容，说明 Mac 服务已经启动成功。

7. 获取 Mac 本机 IP。

图形界面：

```text
系统设置 -> 网络 -> 当前正在使用的 Wi-Fi 或以太网
```

终端方式，Wi-Fi 通常用：

```bash
ipconfig getifaddr en0
```

如果没有输出，可以试：

```bash
ipconfig getifaddr en1
```

8. 在 Windows 浏览器验证：

```text
http://Mac-IP:8765/status
```

例如：

```text
http://192.168.2.50:8765/status
```

9. 在 Windows Rainmeter 设置页填：

```text
http://Mac-IP:8765/rainmeter
```

例如：

```text
http://192.168.2.50:8765/rainmeter
```

### Mac 端手动切换状态

手动切换前，也要先进入 Mac 服务目录：

```bash
cd ~/Documents/Codex-TrafficLight/mac/codex_status_server
```

然后执行：

```bash
./set-status.sh idle
./set-status.sh running "Codex 正在执行任务"
./set-status.sh waiting "等待用户确认"
./set-status.sh success "任务完成"
./set-status.sh error "任务失败"
```

能看到 JSON 后，Rainmeter 就能自动变灯。Windows 和 Mac 需要在同一局域网，或者通过 Tailscale、ZeroTier、VPN 等方式互通。

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
