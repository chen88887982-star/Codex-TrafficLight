# Codex 运行状态交通灯 Rainmeter 皮肤

这个项目是一套通用 Rainmeter 交通灯方案。Rainmeter 固定运行在 Windows 上，Codex 可以运行在同一台 Windows、另一台 Windows，或者一台 Mac。

## 0.2 任务监控面板

主皮肤在原交通灯下增加了任务卡片，可以显示：

- 当前项目名和 Codex 任务标题；
- 同时运行的其他项目列表与完整活动任务清单；
- Git 分支、当前未提交修改、本地上游跟踪状态，以及相对任务开始提交的累计改动；
- 当前工作区是否有修改、本地领先或落后远端跟踪分支多少提交；
- 本轮 token、上下文占用、模型和推理强度；
- 状态服务健康度、额度缓存新鲜度和可选 Credits 余额。

状态服务现在按 `session_id + turn_id` 分别管理并行任务，识别当前 Codex 的工具调用、`task_complete` 和中止事件；服务在任务执行中重启时，也会回看最近会话恢复状态。JSON 接口提供完整活动任务列表，Rainmeter 用紧凑文本显示最多两个其他并行项目和剩余数量。项目、当前轮任务标题、Git、token 和模型详情默认直接提供给 Rainmeter，无需配置访问令牌。

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
win\codex_status_server\start-server-lan.cmd
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

Windows 状态服务会自动监听当前用户的 Codex 会话日志，并根据对话任务状态更新灯光：任务开始、分析、生成回复、执行工具或处理工具结果都会立即保持红灯，需要授权时显示等待状态，任务完成为绿灯，完成 45 秒后回到灰灯。多个任务同时运行时会分别跟踪，皮肤优先显示最近活动任务并提示其他活动任务列表。任务卡片中，分支右侧显示从本次任务开始到当前工作区的累计修改；“跟踪”状态和“待推送”统计只比较本地 `@{upstream}` 跟踪引用，不会冒充已经联网确认的云端状态。需要确认远端最新状态时，应先执行 `git fetch`。

状态服务会监控当前用户的 Codex 本地会话日志以更新任务状态，并优先通过本机已登录的 Codex App Server 查询实时账户额度。仅当实时查询失败或已有实时快照过期时，才使用最新会话中的 `rate_limits` 作为降级数据，并明确标记为“日志快照”，不会伪装成实时账户查询结果。

```text
Windows: %USERPROFILE%\.codex\sessions
macOS: ~/.codex/sessions
```

服务默认调用 `codex app-server --stdio`；如 Codex 可执行文件不在 PATH 中，可设置 `CODEX_COMMAND`。皮肤显示 App Server 返回的 Codex 周额度，并在跨日时显示完整重置日期和时间；如果 `account/usage/read` 返回可识别的 Credits 余额，皮肤会自动增加一行，否则保持隐藏。额度查询在独立后台线程执行，同一时间只运行一个查询；重复触发会合并为下一次查询，不会阻塞任务状态监听。Git 统计也在后台生成快照，Rainmeter 请求和任务事件处理不会等待 Git 子进程。`ACCOUNT_QUERY_TIMEOUT_SECONDS` 控制整次查询的总超时，Credits 查询失败不会丢弃已经获取到的额度。

旧版本留下的 `usage-cache.json` 会被忽略。新的缓存只接受来源为 `app_server` 的实时查询结果；查询失败时保留最后一次成功结果，并在皮肤上显示可能滞后。

如果不想保留黑色窗口，可以双击：

```text
win\codex_status_server\start-server-background.cmd
```

后台启动后用下面这个脚本停止。服务会记录自己的 PID，停止脚本会核对进程命令行，只结束本项目的状态服务，不会按端口误杀其它程序：

```text
win\codex_status_server\stop-server.cmd
```

如果使用黑色窗口版，不要在窗口里拖选文字。窗口标题出现“选择”时，Windows 会暂停控制台程序，Rainmeter 就会连接失败；按 `Esc` 可以退出选择状态。

查看剩余额度接口：

```text
http://127.0.0.1:8765/usage
```

查看服务健康和任务遥测。接口会根据监控心跳、额度查询、缓存新鲜度和 Git 后台统计返回 `ok`、`degraded` 或 `error`：

```text
http://127.0.0.1:8765/health
```

如果是另一台 Windows 读取，就在另一台电脑浏览器打开：

```text
http://运行Codex电脑的IP:8765/status
```

Windows 状态服务会写日志：

```text
win\codex_status_server\status-server.log
```

日志只记录启动、停止、异常、认证失败和未知路径，不再记录每秒一次的正常 `/rainmeter` 请求。默认单个日志最大 5 MiB、保留 3 份历史文件；可通过 `LOG_MAX_BYTES` 和 `LOG_BACKUP_COUNT` 调整。如果 Rainmeter 一直显示连接失败，可查看启动或认证错误，再检查 Rainmeter 调试信息和返回内容。

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
chmod +x set-status.sh start.command start-lan.command
```

如果提示 `No such file or directory`，说明你还没有进入 `mac/codex_status_server` 这个目录。先重新执行第 2 步的 `cd ...`。

5. 启动服务：

```bash
./start-lan.command
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

## 任务详情与可选访问令牌

默认情况下，`/status`、`/health` 和 `/rainmeter` 会直接输出项目名、任务标题、Git、token 和模型详情，Rainmeter 地址不需要附加密码：

```text
http://运行Codex电脑的IP:8765/rainmeter
```

如果以后需要限制访问，可以选择启用令牌：

1. 复制根目录的 `status-auth.example.json` 为 `status-auth.json`。
2. 把 `access_token` 换成只在你设备间使用的长随机字符串。
3. `status-auth.json` 已加入 `.gitignore`，不要提交或发送给别人。
4. 在 Rainmeter 设置页把地址写成带同一令牌的形式：

```text
http://运行Codex电脑的IP:8765/rainmeter?token=你的令牌
```

也可以不用 JSON，改用环境变量启用令牌：

```text
STATUS_ACCESS_TOKEN=你的令牌
```

如果只想临时隐藏详情，可以单独设置：

```text
EXPOSE_TASK_DETAILS=0
```

只要配置了 `STATUS_ACCESS_TOKEN`，所有接口都会拒绝没有正确令牌的请求。服务日志只记录请求路径，不会记录 URL 查询参数中的令牌。CORS 默认关闭，需要时再显式设置 `ALLOW_CORS=1`。

## 可调运行参数

状态服务会校验数字、布尔值和枚举参数；无效值不会再导致服务在启动阶段崩溃，而是回退到安全默认值并在终端显示原因。

| 参数 | 默认值 | 作用 |
|---|---:|---|
| `TASK_STATS_SCOPE` | `task` | “本次”统计范围：`turn` 单轮、`task` 整个任务、`service` 本次服务运行期 |
| `GIT_STATS_EXCLUDE` | `.DS_Store` | 不计入 Git 项目数的逗号分隔通配模式；同时匹配相对路径和文件名 |
| `GIT_INCLUDE_MODE_ONLY` | `0` | 是否把仅文件权限变化计入“本次/待推送”项目数 |
| `GIT_CACHE_SECONDS` | `2` | Git 统计缓存秒数，允许 `0` 到 `60` |
| `GIT_TIMEOUT_SECONDS` | `2.5` | 每条 Git 查询的超时秒数，允许 `0.1` 到 `30` |
| `MONITOR_INTERVAL_SECONDS` | `0.25` | Codex 会话日志轮询间隔，允许 `0.05` 到 `60` |
| `SESSION_DISCOVERY_INTERVAL_SECONDS` | `3` | 递归发现新会话文件的间隔，允许 `0.5` 到 `300`；已发现日志仍按监控间隔读取 |
| `SUCCESS_HOLD_SECONDS` | `45` | 完成绿灯保持时间，允许 `0` 到 `3600` |
| `RUNNING_STALE_SECONDS` | `300` | 多久没有任务事件后回到空闲，允许 `5` 到 `86400` |
| `PORT` | `8765` | 状态服务端口，允许 `1` 到 `65535` |

例如，让“本次”只统计当前一轮，同时忽略临时目录和纯权限变化：

```bash
cd mac/codex_status_server
TASK_STATS_SCOPE=turn GIT_STATS_EXCLUDE='.DS_Store,tmp/*' GIT_INCLUDE_MODE_ONLY=0 ./start.command
```

Rainmeter 的网络刷新间隔只在 `@Resources/variables.inc` 中配置：

```ini
UpdateInterval=1
```

## 安全说明

状态服务只提供只读 `/status`、`/health`、`/usage` 和 `/rainmeter` 接口，不提供远程执行命令能力。完整任务遥测不会包含用户提示词全文或完整工作目录；项目只显示目录名。

默认启动脚本只监听本机 `127.0.0.1`。如果需要让另一台电脑上的 Rainmeter 读取状态，请使用局域网启动脚本：

```text
Windows: win\codex_status_server\start-server-lan.cmd
macOS: mac/codex_status_server/start-lan.command
```

安装皮肤时，如果目标 Rainmeter 目录里已经有 `@Resources\variables.inc`，安装脚本会先备份并保留它，避免覆盖你已调整的地址、颜色、透明度和尺寸；仅会把旧版默认高度 `568` 或 `716` 自动迁移到新版任务卡片需要的 `736`。

## 开发与测试

项目运行只依赖 Python 标准库。建议使用项目内环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m ruff check common tests mac/codex_status_server/server.py win/codex_status_server/server.py
python -m ruff format --check common tests mac/codex_status_server/server.py win/codex_status_server/server.py
PYTHONPATH=common python -m unittest discover -s tests -v
```

Windows PowerShell：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m ruff check common tests mac/codex_status_server/server.py win/codex_status_server/server.py
python -m ruff format --check common tests mac/codex_status_server/server.py win/codex_status_server/server.py
$env:PYTHONPATH = "common"
python -m unittest discover -s tests -v
```

Rainmeter 的 `.ini` 和 `.inc` 必须保持 UTF-16LE with BOM。提交前还应检查两端 Python 语法、Rainmeter 编码和 `git diff --check`。
