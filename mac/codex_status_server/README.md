# Codex 状态服务

这是给 Rainmeter 交通灯读取的 Mac 端只读 HTTP 服务。

## 启动

```bash
chmod +x set-status.sh start.command
./start.command
```

默认端口是 `8765`，接口是：

```text
http://Mac-IP:8765/status
```

也可以指定端口：

```bash
PORT=9000 ./start.command
```

## 切换状态

```bash
./set-status.sh idle
./set-status.sh running "Codex 正在执行任务"
./set-status.sh waiting "等待用户确认"
./set-status.sh success "任务完成"
./set-status.sh error "任务失败"
```

支持状态：

- `idle`
- `running`
- `waiting`
- `success`
- `error`

服务只读取 `status.json`，不会执行远程命令。
