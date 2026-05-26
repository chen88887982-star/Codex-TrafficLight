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

双击：

```text
start-server.cmd
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
- 工具调用：保持 `running`，红灯
- 等待确认相关事件：写入 `waiting`，黄灯
- `task_complete`：写入 `success`，绿灯
- 完成 45 秒后：自动回到 `idle`，灰灯

如果只想手动切换，可以用下面方式关闭自动监听：

```cmd
set AUTO_MONITOR_CODEX=0
start-server.cmd
```

## 切换状态

在 PowerShell 中执行：

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

能看到 JSON 就表示 Rainmeter 可以读取。
