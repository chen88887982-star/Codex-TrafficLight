# Codex 运行状态交通灯 Rainmeter 皮肤

这个项目是一套通用 Rainmeter 交通灯方案。Rainmeter 固定运行在 Windows 上，Codex 可以运行在同一台 Windows、另一台 Windows，或者一台 Mac。

## 0.5 状态看板、任务管理与历史

启动状态服务后，直接用浏览器访问 `http://127.0.0.1:8767/`。同一局域网中的电脑或手机可访问 `http://服务电脑IP:8767/`。Rainmeter 标题点击打开看板，右键菜单可以打开任务历史；原有 `/rainmeter` 28 字段协议仍为版本 2。

- **任务总览**：任务阶段、耗时、本轮 token、上下文、Git 待推送/待拉取和未提交修改，以及监听、监控、额度、Git、版本和运行数据分项状态。
- **任务管理**：选择关注、固定显示、取消固定、重新核验日志和忽略当前轮。忽略只隐藏本工具监控，真实 Codex 任务继续运行；下一轮自动恢复。选择/固定在当前服务进程有效。重新核验会保留原忽略选择，可用选择关注恢复显示。
- **额度刷新**：看板可手动刷新并显示查询进度、失败原因和最后更新时间。默认空闲每 15 分钟、忙碌每 2 分钟刷新；成功、异常或中止结束后各仅额外查询一次。`USAGE_REFRESH_INTERVAL_SECONDS=0` 可关闭定时刷新，`USAGE_BUSY_REFRESH_SECONDS=0` 可关闭忙碌加速。百分比差值表示期间账户变化，不能归因到单个任务。
- **任务历史**：按项目、状态、日期查询与分页，记录任务摘要、每轮 token、耗时及 Git 汇总。SQLite 位于服务 `.runtime/task-history.sqlite3`，默认保留最近 90 天、最多 10000 条已结束任务；活动任务不因保留期限被删除。不会保存提示词全文、原始工具输出或绝对工作目录。历史存储故障不会阻断任务监控。
- **多电脑聚合**：设备页添加其他已升级到 0.5 的状态服务根地址，可选填写对端令牌。最多 8 台设备，后台并发读取，失败保留快照并明确标为离线；每台设备的任务、账户额度独立展示。远程源只读，在设备卡片打开对端看板后管理其任务偏好。

本机看板可直接操作本工具偏好。局域网操作需在服务机配置 `STATUS_ACCESS_TOKEN` 或私有 `status-auth.json`；在看板输入访问令牌后仅保存在该浏览器标签页的 sessionStorage，使用 Authorization 请求头发送。静态页面可先打开，接口仍执行访问检查；所有偏好操作均为同源 POST，不提供执行命令、结束 Codex 任务或自动 Git 推送能力。设备令牌仅保存在私有 `.runtime/peer-services.json`，不会出现在公开接口。

Rainmeter 断连显示最后成功读取时间，超过默认 10 秒离线阈值后灯光变灰。设置中的尺寸按整体比例缩放；脚本在用户提交配置后刷新皮肤。安装器自动识别当前 Rainmeter SkinPath，也支持：

```cmd
install-rainmeter-skin.cmd -SkinPath "D:\Rainmeter\Skins"
install-rainmeter-skin.cmd -SettingsPath "D:\PortableRainmeter\Rainmeter.ini"
```

Windows 和 macOS 启动参数保存在服务 `.runtime/launch-settings.json`，通知设置和重新启动沿用监听地址、端口。设置页提供独立的“只读体检”和“确认后修复”；远程源的维护需在服务电脑进行。

本轮修复还包括：启动恢复与增量读取共用截止位置；大日志分块恢复；仓库子目录新文件统计；仅远端领先时的待拉取统计；Windows 空格路径；macOS 同端口快速重启；无效运行 JSON 的降级读取；日志额度与实时查询之间的原子缓存比较。

新增接口：

| 方法与路径 | 用途 |
|---|---|
| `GET /api/snapshot` | 本机任务、额度、状态、健康分项与刷新进度 |
| `GET /api/tasks` | 任务列表与关注/固定状态 |
| `GET /api/history` | `project/status/since/until/limit/offset` 筛选历史 |
| `GET /api/peers` | 已配置设备及独立连接状态；不返回令牌 |
| `POST /api/usage/refresh` | 合并后台刷新请求，立即返回进度 |
| `POST /api/tasks/control` | JSON：`action/session_id/turn_id`，动作 `select/pin/unpin/recheck/ignore/clear_selection` |
| `POST /api/peers` | JSON：添加 `action=add/name/url/token`，移除 `action=remove/peer_id` |

额度解析与查询、HTTP、运行配置、JSON 校验、历史和设备聚合分别位于 `common/usage_data.py`、`usage_client.py`、`service_http.py`、`service_config.py`、`state_store.py`、`service_state.py`、`service_monitor.py`、`task_history.py` 和 `peer_services.py`。App Server 初始化遵循 [官方握手协议](https://learn.chatgpt.com/docs/app-server#initialization)，查询不创建推理任务。

## 0.4 任务监控面板

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
| Win + Win 同一台电脑 | 本机 Windows | `http://127.0.0.1:8767/rainmeter` |
| Win + 另一台 Win | 运行 Codex 的 Windows | `http://对方Windows-IP:8767/rainmeter` |
| Win + Mac | 运行 Codex 的 Mac | `http://Mac-IP:8767/rainmeter` |

Rainmeter 只负责读取 `StatusUrl`。所以两套装备通用的关键就是：哪台电脑运行 Codex，就在哪台电脑启动状态服务。

## Windows 端安装皮肤

在 Rainmeter 所在的 Windows 上，先打开项目文件夹，再双击：

```text
install-rainmeter-skin.cmd
```

它会复制皮肤到当前 Rainmeter 配置的 `SkinPath` 下的 `CodexTrafficLight` 目录。未检测到配置时，使用 Windows 的 Documents 已知文件夹，因此兼容 OneDrive 重定向；便携版可传入 `-SettingsPath` 或 `-SkinPath`。

然后打开 Rainmeter 管理器，点击“刷新全部”，加载：

```text
CodexTrafficLight\CodexTrafficLight.ini
```

右键主皮肤可以打开“设置”。设置页会显示当前接口地址，可以一键设为本机 Windows，也可以手动填写远程电脑地址、调整背景透明度、显示调试信息。

## 配置 Rainmeter 读取地址

默认配置适合 Codex 和 Rainmeter 都在同一台 Windows：

```ini
StatusUrl=http://127.0.0.1:8767/rainmeter
```

跨电脑时，在设置页把地址改成运行 Codex 那台电脑的局域网 IP：

```ini
StatusUrl=http://对方IP:8767/rainmeter
```

浏览器验证服务是否可访问时，用 `/status`：

```text
http://对方IP:8767/status
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
win\codex_status_server\启动状态服务.cmd
```

3. 服务会隐藏在后台运行；重复双击不会启动第二个实例。

4. Rainmeter 设置页里填：

```text
http://127.0.0.1:8767/rainmeter
```

5. 浏览器验证：

```text
http://127.0.0.1:8767/status
```

### 方式 B：Codex 在一台 Windows，Rainmeter 在另一台 Windows

1. 在运行 Codex 的 A 电脑上打开项目文件夹。

2. 在 A 电脑上打开命令提示符，用同一个中文入口增加 `lan` 参数启动：

```text
win\codex_status_server\启动状态服务.cmd lan
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
http://运行Codex电脑的IP:8767/status
```

例如：

```text
http://192.168.2.112:8767/status
```

5. 在 B 电脑的 Rainmeter 设置页填：

```text
http://运行Codex电脑的IP:8767/rainmeter
```

例如：

```text
http://192.168.2.112:8767/rainmeter
```

### Windows 端说明

Windows 状态服务默认使用 Python 标准库 HTTP 服务。运行电脑需要安装 Python 3，并且命令行能识别 `py -3` 或 `python`。

Windows 状态服务会自动监听当前用户的 Codex 会话日志，并根据对话任务状态更新灯光：任务开始、分析、生成回复、执行工具或处理工具结果都会立即保持红灯，需要授权时显示等待状态，任务完成为绿灯，完成 45 秒后回到灰灯。多个任务同时运行时会分别跟踪，皮肤优先显示最近活动任务并提示其他活动任务列表。任务卡片中，分支右侧显示从本次任务开始到当前工作区的累计修改；“云端”状态和“待推送”统计比较本地 `@{upstream}` 跟踪引用。状态服务首次显示项目时会在后台执行一次 `git fetch`，成功后默认每 5 分钟刷新一次，可以自动提示“云端 落后 N”或分叉状态。刷新失败时会按 15、30、60、120、300 秒逐步重试，并用只读 `git ls-remote` 降级核验：远端引用已变化时显示“云端 有更新”，无法确认时显示“云端 未确认”，不会再把旧跟踪引用误报为“已同步”。错误按网络、凭据、仓库锁、超时等类别显示，并按项目隔离，不会让其他项目一起显示降级。

状态服务会监控当前用户的 Codex 本地会话日志以更新任务状态，并优先通过本机已登录的 Codex App Server 查询实时账户额度。仅当实时查询失败或已有实时快照过期时，才使用最新会话中的 `rate_limits` 作为降级数据，并明确标记为“日志快照”，不会伪装成实时账户查询结果。

```text
Windows: %USERPROFILE%\.codex\sessions
macOS: ~/.codex/sessions
```

服务默认调用 `codex app-server`（默认 stdio 传输）；如 Codex 可执行文件不在 PATH 中，可设置 `CODEX_COMMAND`。皮肤显示 App Server 返回的两个 Codex 额度窗口，并按窗口时长标注（如 5 小时、7 天）；未提供时长时标为主窗口／第二窗口，不固定假设周额度，并在跨日时显示完整重置日期和时间；如果 `account/usage/read` 返回可识别的 Credits 余额，皮肤会自动增加一行，否则保持隐藏。额度查询在独立后台线程执行，同一时间只运行一个查询；重复触发会合并为下一次查询，不会阻塞任务状态监听。除启动和任务成功、异常或中止结束刷新外，服务默认空闲每 15 分钟、忙碌每 2 分钟刷新额度；`USAGE_REFRESH_INTERVAL_SECONDS=0` 关闭定时刷新，`USAGE_BUSY_REFRESH_SECONDS=0` 关闭忙碌加速。Git 统计也在后台生成快照，Rainmeter 请求和任务事件处理不会等待 Git 子进程；联网 Git 子进程同时禁用终端提示和 Git Credential Manager 交互。`ACCOUNT_QUERY_TIMEOUT_SECONDS` 控制整次查询的总超时，Credits 查询失败不会丢弃已经获取到的额度。

缓存接受明确标记来源的实时查询结果与日志快照：优先使用新鲜的 `app_server` 数据；实时查询失败或快照过期时，仅接受时间更新的日志额度作为降级。没有更新数据时保留原缓存，不伪造实时结果。

后台启动后可用内部停止脚本结束。服务会记录自己的 PID，停止脚本会核对进程命令行，只结束本项目的状态服务，不会按端口误杀其它程序：

```text
win\codex_status_server\.internal\stop-server.ps1
```

查看剩余额度接口：

```text
http://127.0.0.1:8767/usage
```

查看服务健康和任务遥测。接口会根据监控心跳、额度查询、缓存新鲜度和 Git 后台统计返回 `ok`、`degraded` 或 `error`：

```text
http://127.0.0.1:8767/health
```


`/health` 会同时返回 `service_version` 和 `protocol_version`。启动器与一键体检只复用版本、协议和服务身份均匹配的实例，避免新皮肤继续连接未重启的旧后端。

主皮肤任务卡片可以点击展开独立的活动任务面板；对应的固定五行纯文本接口为：

```text
http://127.0.0.1:8767/tasks
```

如果是另一台 Windows 读取，就在另一台电脑浏览器打开：

```text
http://运行Codex电脑的IP:8767/status
```

Windows 状态服务会写日志：

```text
win\codex_status_server\.runtime\status-server.log
```

日志只记录启动、停止、异常、认证失败和未知路径，不再记录每秒一次的正常 `/rainmeter` 请求。默认单个日志最大 5 MiB、保留 3 份历史文件；可通过 `LOG_MAX_BYTES` 和 `LOG_BACKUP_COUNT` 调整。如果 Rainmeter 一直显示连接失败，可查看启动或认证错误，再检查 Rainmeter 调试信息和返回内容。

切换状态：

```powershell
.\win\codex_status_server\.internal\set-status.ps1 idle
.\win\codex_status_server\.internal\set-status.ps1 running "Codex 正在执行任务"
.\win\codex_status_server\.internal\set-status.ps1 waiting "等待用户确认"
.\win\codex_status_server\.internal\set-status.ps1 success "任务完成"
.\win\codex_status_server\.internal\set-status.ps1 error "任务失败"
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
启动状态服务.command
```

4. 第一次运行前给中文入口执行权限：

```bash
chmod +x 启动状态服务.command
```

如果提示 `No such file or directory`，说明你还没有进入 `mac/codex_status_server` 这个目录。先重新执行第 2 步的 `cd ...`。

5. 启动服务：

```bash
./启动状态服务.command
```

服务会在后台运行，终端窗口可以关闭；重复启动不会产生第二个实例。

6. 先在 Mac 本机验证服务：

```bash
curl http://127.0.0.1:8767/status
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
http://Mac-IP:8767/status
```

例如：

```text
http://192.168.2.50:8767/status
```

9. 在 Windows Rainmeter 设置页填：

```text
http://Mac-IP:8767/rainmeter
```

例如：

```text
http://192.168.2.50:8767/rainmeter
```

### Mac 端手动切换状态

手动切换前，也要先进入 Mac 服务目录：

```bash
cd ~/Documents/Codex-TrafficLight/mac/codex_status_server
```

然后执行：

```bash
./.internal/set-status.sh idle
./.internal/set-status.sh running "Codex 正在执行任务"
./.internal/set-status.sh waiting "等待用户确认"
./.internal/set-status.sh success "任务完成"
./.internal/set-status.sh error "任务失败"
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
http://运行Codex电脑的IP:8767/rainmeter
```

如果以后需要限制访问，可以选择启用令牌：

1. 复制根目录的 `status-auth.example.json` 为 `status-auth.json`。
2. 把 `access_token` 换成只在你设备间使用的长随机字符串。
3. `status-auth.json` 已加入 `.gitignore`，不要提交或发送给别人。
4. 在 Rainmeter 设置页把地址写成带同一令牌的形式：

```text
http://运行Codex电脑的IP:8767/rainmeter?token=你的令牌
```

也可以不用 JSON，改用环境变量启用令牌：

```text
STATUS_ACCESS_TOKEN=你的令牌
```

如果只想临时隐藏详情，可以单独设置：

```text
EXPOSE_TASK_DETAILS=0
```

配置 `STATUS_ACCESS_TOKEN` 后，局域网请求必须提供正确令牌；本机回环请求继续允许 Rainmeter 和健康检查直接访问。服务日志只记录请求路径，不会记录 URL 查询参数中的令牌。CORS 默认关闭，需要时再显式设置 `ALLOW_CORS=1`。

## 可选任务通知

Windows 和 macOS 均支持等待确认、任务完成与异常通知，默认关闭。Windows Rainmeter 设置页的“任务通知设置”会安全更新本项目私有的 `status-auth.json` 并重启服务；默认静音时段为 `22:00-08:00`。也可以使用 `NOTIFICATIONS_ENABLED`、`NOTIFICATION_QUIET_HOURS`、`NOTIFY_WAITING`、`NOTIFY_SUCCESS` 和 `NOTIFY_ERROR` 环境变量配置。

通知按任务轮次和状态去重，不会因为 Rainmeter 每秒刷新而重复弹出。

## 可调运行参数

状态服务会校验数字、布尔值和枚举参数；无效值不会再导致服务在启动阶段崩溃，而是回退到安全默认值并在终端显示原因。

| 参数 | 默认值 | 作用 |
|---|---:|---|
| `TASK_STATS_SCOPE` | `task` | “本次”统计范围：`turn` 单轮、`task` 整个任务、`service` 本次服务运行期 |
| `GIT_STATS_EXCLUDE` | `.DS_Store` | 不计入 Git 项目数的逗号分隔通配模式；同时匹配相对路径和文件名 |
| `GIT_INCLUDE_MODE_ONLY` | `0` | 是否把仅文件权限变化计入“本次/待推送”项目数 |
| `GIT_CACHE_SECONDS` | `2` | Git 统计缓存秒数，允许 `0` 到 `60` |
| `GIT_TIMEOUT_SECONDS` | `2.5` | 每条 Git 查询的超时秒数，允许 `0.1` 到 `30` |
| `GIT_FETCH_INTERVAL_SECONDS` | `300` | 后台刷新远端跟踪引用的间隔秒数，允许 `0` 到 `86400`；设为 `0` 可关闭联网刷新 |
| `GIT_FETCH_TIMEOUT_SECONDS` | `15` | 单次后台 `git fetch` 的超时秒数，允许 `1` 到 `120` |
| `MONITOR_INTERVAL_SECONDS` | `0.25` | Codex 会话日志轮询间隔，允许 `0.05` 到 `60` |
| `SESSION_DISCOVERY_INTERVAL_SECONDS` | `3` | 递归发现新会话文件的间隔，允许 `0.5` 到 `300`；已发现日志仍按监控间隔读取 |
| `SUCCESS_HOLD_SECONDS` | `45` | 完成绿灯保持时间，允许 `0` 到 `3600` |
| `ERROR_HOLD_SECONDS` | `90` | 异常红灯保持时间，之后自动回到空闲，允许 `0` 到 `3600` |
| `USAGE_REFRESH_INTERVAL_SECONDS` | `900` | 空闲定时刷新额度的间隔秒数，允许 `0` 或 `60` 到 `86400`；`0` 表示关闭全部定时刷新 |
| `USAGE_BUSY_REFRESH_SECONDS` | `120` | 忙碌期间额度刷新间隔，允许 `0` 或 `30` 到 `86400`；`0` 表示不加速 |
| `RUNNING_STALE_SECONDS` | `300` | 多久没有事件后标为长时间无更新，保留活动状态，允许 `5` 到 `86400` |
| `PORT` | `8767` | 状态服务端口，允许 `1` 到 `65535` |

例如，让“本次”只统计当前一轮，同时忽略临时目录和纯权限变化：

```bash
cd mac/codex_status_server
TASK_STATS_SCOPE=turn GIT_STATS_EXCLUDE='.DS_Store,tmp/*' GIT_INCLUDE_MODE_ONLY=0 ./启动状态服务.command
```

Rainmeter 的网络刷新间隔只在 `@Resources/variables.inc` 中配置：

```ini
UpdateInterval=1
```

## 安全说明

状态服务只提供只读 `/status`、`/health`、`/usage`、`/tasks` 和 `/rainmeter` 接口，不提供远程执行命令能力。完整任务遥测不会包含用户提示词全文或完整工作目录；项目只显示目录名。

Windows 中文入口默认只监听本机 `127.0.0.1`；增加 `lan` 参数后允许局域网读取。macOS 中文入口默认监听局域网，便于 Windows Rainmeter 读取；如只允许 Mac 本机访问，可设置 `CODEX_STATUS_HOST=127.0.0.1`。

```text
Windows: win\codex_status_server\启动状态服务.cmd lan
macOS: mac/codex_status_server/启动状态服务.command
```

安装皮肤时，如果目标 Rainmeter 目录里已经有 `@Resources\variables.inc`，安装脚本会先备份并保留它，避免覆盖你已调整的地址、颜色、透明度和尺寸；会迁移旧版默认高度，并且只把旧的本机 `127.0.0.1:8765` 默认地址升级到 8767，自定义远程地址和端口保持不变。安装器还会写入 `ServiceRoot`，供设置页一键体检和通知设置定位本项目。

## 开发与测试

项目运行只依赖 Python 标准库。Git 环境、桌面通知和服务版本元数据已经分别拆分到 `common/git_runtime.py`、`common/notifications.py` 和 `common/service_metadata.py`，额度与 HTTP 层已拆分到独立模块。建议使用项目内环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m ruff check common tests mac/codex_status_server/.internal/server.py win/codex_status_server/.internal/server.py
python -m ruff format --check common tests mac/codex_status_server/.internal/server.py win/codex_status_server/.internal/server.py
PYTHONPATH=common python -m unittest discover -s tests -v
```

Windows PowerShell：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m ruff check common tests mac/codex_status_server/.internal/server.py win/codex_status_server/.internal/server.py
python -m ruff format --check common tests mac/codex_status_server/.internal/server.py win/codex_status_server/.internal/server.py
$env:PYTHONPATH = "common"
python -m unittest discover -s tests -v
```

Rainmeter 的 `.ini` 和 `.inc` 必须保持 UTF-16LE with BOM。提交前还应检查两端 Python 语法、Rainmeter 编码和 `git diff --check`。

## Windows 8767 隐藏后台服务

Windows 根目录只保留一个用户入口：`win\codex_status_server\启动状态服务.cmd`。它会先检查 `http://127.0.0.1:8767/health`，相同服务已运行时直接复用，端口被其他程序占用时拒绝启动。内部维护脚本位于 `.internal`，运行数据位于 `.runtime`。

设置页“体检并修复服务”会验证 8765/8767 监听进程身份、服务版本、协议版本、已安装 Rainmeter 地址和旧运行文件。只有命令行确认属于当前项目时才会停止旧进程；修复过程会迁移旧运行文件，并清理超过 50 MB 的历史轮转日志。也可在 PowerShell 中运行 `.\win\codex_status_server\.internal\service-doctor.ps1` 仅查看报告，增加 `-Repair` 执行修复。

配置访问令牌后，本机回环地址仍可供 Rainmeter 直接读取；局域网客户端必须继续携带正确令牌。

## macOS 8767 后台服务

macOS 根目录只保留一个用户入口：`mac/codex_status_server/启动状态服务.command`。它默认以局域网后台模式启动，相同服务已运行时直接复用，端口被其他程序占用时拒绝启动。内部维护脚本位于 `.internal`，运行数据位于 `.runtime`。

登录自启动使用当前用户的 LaunchAgent `com.codex.trafficlight.status`。后台入口先验证 `/health` 的服务身份；相同服务已运行时直接复用，其他程序占用端口时拒绝启动。

## 0.4 准确性与运行维护

- 超过 `RUNNING_STALE_SECONDS`（默认 300 秒）没有事件时，保留运行／等待确认状态，显示“长时间无更新”，不再直接变为空闲。新活动事件恢复原阶段；明确完成或中止事件结束任务。服务重启后恢复的静默任务也采用这一规则。
- 双额度窗口以返回的 `windowDurationMins` 为准；第二窗口缺失显示 `--`。主额度名称动态显示，第二窗口以紧凑行展示，悬停查看重置时间和来源。解析遵循 [Codex App Server 官方说明](https://learn.chatgpt.com/docs/app-server#6-rate-limits-chatgpt)。
- 百分比差值表示“期间账户变化”，可能包含其他任务或设备的消耗，不能归因到单个任务。任务自身 token 保留在任务卡片。窗口重置、使用量回落或来源切换时重建比较基准。
- 会话发现每次只扫描最近三天目录和最多 100 个索引文件；启动及每 5 分钟补扫全部历史目录。已发现的活动任务单独保留。较老且未被索引的会话恢复，最迟在下一次历史补扫时发现。
- Mac 只读体检：运行 `bash mac/codex_status_server/.internal/health-check.command`；自定义端口可用 `PORT=端口号 bash ...`。检查端口、服务版本、协议、健康状态、PID 所属进程、登录启动配置，并报告日志位置。体检不自动结束进程；异常时使用本项目停止入口和启动入口处理。
- CI 增加 macOS，与 Windows、Linux 一起运行 Python 3.10／3.13／3.14 测试。Mac 还会在临时项目副本和随机端口上验证实际启动、重复启动、体检及安全停止。
- 0.4 版将协议 2 的 Rainmeter 文本接口由 26 字段扩为 28 字段（末尾增加两个窗口名称）；当前 0.5.0 保持这套协议。升级时重新安装皮肤并重启状态服务，避免混用新旧版本。
