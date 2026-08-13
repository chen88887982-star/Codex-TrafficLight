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
chmod +x set-status.sh start.command
```

如果这里提示 `No such file or directory`，说明终端还不在这个目录里。先重新执行上面的 `cd ...`。

启动服务：

```bash
./start.command
```

默认端口是 `8765`，接口是：

```text
http://Mac-IP:8765/status
```

健康检查：

```text
http://Mac-IP:8765/health
```

服务会恢复正在执行的任务、分别跟踪并行任务，并提供项目、Git 变更和 token 遥测。详细任务信息默认处于隐私模式；跨电脑显示详情时，在项目根目录创建已忽略的 `status-auth.json`，并让 Rainmeter 使用 `http://Mac-IP:8765/rainmeter?token=你的令牌`。配置格式见根目录 `status-auth.example.json`。

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
