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
