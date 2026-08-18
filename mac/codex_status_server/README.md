# Codex 状态服务

这是给 Rainmeter 交通灯读取的 Mac 端只读 HTTP 服务。

## 启动

打开 Mac 终端后，先进入这个目录。

如果项目在 Documents 里：

```bash
cd ~/Documents/Codex-TrafficLight/mac/codex_status_server
```

如果项目在别的位置，把路径换成你自己的位置：

```bash
cd /你的路径/Codex-TrafficLight/mac/codex_status_server
```

确认当前目录里有脚本文件：

```bash
ls
```

正常应该能看到：

```text
server.py
set-status.sh
start.command
```

第一次运行前，给脚本增加可执行权限：

```bash
chmod +x set-status.sh start.command start-lan.command
```

如果这里提示 `No such file or directory`，说明终端还不在这个目录里。先重新执行上面的 `cd ...`。

仅供 Mac 本机读取时启动：

```bash
./start.command
```

如果要让 Windows Rainmeter 通过局域网读取，启动：

```bash
./start-lan.command
```

默认端口是 `8765`，接口是：

```text
http://Mac-IP:8765/status
```

健康检查：

```text
http://Mac-IP:8765/health
```

服务会恢复正在执行的任务、分别跟踪并行任务，并提供项目、Git 变更和 token 遥测。Git 统计在后台生成快照，不会阻塞任务事件和 Rainmeter 请求。详细任务信息默认直接显示，无需密码；使用 `start-lan.command` 后，Rainmeter 可读取 `http://Mac-IP:8765/rainmeter`。需要限制访问时，可在项目根目录创建已忽略的 `status-auth.json`，配置格式见根目录 `status-auth.example.json`。

日志只记录服务生命周期、异常、认证失败和未知路径，正常的每秒 Rainmeter 请求不会写入日志。默认日志上限为 5 MiB，并保留 3 份轮转备份。

也可以指定端口：

```bash
PORT=9000 ./start.command
```

## 切换状态

切换状态前，也要先进入这个目录：

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

支持状态：

- `idle`
- `running`
- `waiting`
- `success`
- `error`

服务只读取 `status.json`，不会执行远程命令。

## 后台运行、健康检查与登录自启动

以下脚本与原有前台启动方式并存：

```text
./start-background.command
./start-lan-background.command
./health-check.command
./stop.command
./install-login-autostart.command
./uninstall-login-autostart.command
```

`start-background.command` 默认监听 `127.0.0.1:8765`；`start-lan-background.command` 才监听 `0.0.0.0:8765`，先检查 `/health` 的服务身份，相同服务已运行时不会重复启动。`stop.command` 同时核对 PID 和完整 `server.py` 路径。登录启动使用 `~/Library/LaunchAgents/com.codex.trafficlight.status.plist`；卸载脚本只删除 LaunchAgent，当前服务可另用 `stop.command` 停止。
