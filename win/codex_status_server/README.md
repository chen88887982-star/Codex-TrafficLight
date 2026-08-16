# Windows 本机 Codex 状态服务

这个目录用于 Windows 运行状态接口。可以给本机 Rainmeter 读取，也可以给局域网另一台 Windows 的 Rainmeter 读取。

本机读取：

```text
http://127.0.0.1:8765/status
```

另一台电脑读取：

```text
http://这台Windows的局域网IP:8765/status
```

## 启动服务

先打开项目文件夹。如果项目在桌面或下载目录，先在资源管理器里进入：

```text
Codex-TrafficLight
```

本机 Rainmeter 读取时双击：

```text
win\codex_status_server\start-server.cmd
```

如果要让另一台电脑读取，改为双击：

```text
win\codex_status_server\start-server-lan.cmd
```

如果命令窗口保持打开，说明服务正在运行。关闭窗口后服务停止。

服务现在默认使用 Python 标准库 HTTP 服务。Windows 需要能运行 `py -3` 或 `python`。如果提示未找到 Python，请先安装 Python 3，或把 Python 加入 PATH。

第一次允许局域网访问时，Windows 防火墙可能会弹出提示，允许专用网络即可。

服务会自动监听当前用户的 Codex 会话日志：

```text
%USERPROFILE%\.codex\sessions
```

自动状态规则：

- `task_started`：写入 `running`，红灯
- 生成回复、工具调用、工具结果：保持 `running`，红灯
- 等待确认相关事件：写入 `waiting`，黄灯
- 权限审核/审批评估会话：忽略，不影响主皮肤状态
- 最终回复与 `task_complete` 都出现后：写入 `success`，绿灯
- 完成 45 秒后：自动回到 `idle`，灰灯
- 多个任务按会话和轮次分别跟踪，显示最近活动任务和其他任务数量
- 服务中途启动会回看最近日志，恢复仍在运行的任务

项目名、任务标题、Git 变更、token 和模型信息默认直接显示，无需密码。需要限制局域网访问时，可在项目根目录创建 `status-auth.json`，格式参考 `status-auth.example.json`，然后把 Rainmeter 地址设为：

```text
http://运行Codex电脑的IP:8765/rainmeter?token=你的令牌
```

默认每 0.25 秒读取已发现的活动日志，每 3 秒发现一次新会话文件，Rainmeter 默认 1 秒读取一次 `/rainmeter`。Git 统计在后台生成快照，不会阻塞任务事件和 Rainmeter 请求。

额度查询在后台执行，不会阻塞任务事件监听；正常的 `/rainmeter` 轮询不会写入日志。日志默认上限为 5 MiB，并保留 3 份轮转备份。

如果只想手动切换，可以用下面方式关闭自动监听：

```cmd
set AUTO_MONITOR_CODEX=0
start-server.cmd
```

## 切换状态

在 PowerShell 中执行前，先进入这个目录：

```powershell
cd 你的项目路径\Codex-TrafficLight\win\codex_status_server
```

例如项目在桌面：

```powershell
cd $HOME\Desktop\Codex-TrafficLight\win\codex_status_server
```

然后执行：

```powershell
.\set-status.ps1 idle
.\set-status.ps1 running "Codex 正在执行任务"
.\set-status.ps1 waiting "等待用户确认"
.\set-status.ps1 success "任务完成"
.\set-status.ps1 error "任务失败"
```

## 验证

浏览器打开：

```text
http://127.0.0.1:8765/status
```

服务健康与任务数据；健康状态会反映监控心跳、额度查询和缓存是否正常：

```text
http://127.0.0.1:8765/health
```

能看到 JSON 就表示 Rainmeter 可以读取。
