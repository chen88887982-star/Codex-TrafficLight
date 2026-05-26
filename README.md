# Codex 运行状态交通灯 Rainmeter 皮肤

这个项目包含两部分：

- `mac/codex_status_server`：在 Mac 上运行的只读状态接口。
- `rainmeter/CodexTrafficLight`：复制到 Windows Rainmeter `Skins` 目录使用的交通灯皮肤。

## 快速开始

### 1. Mac 端启动状态服务

在 Mac 上进入：

```bash
cd mac/codex_status_server
chmod +x set-status.sh start.command
./start.command
```

服务默认监听：

```text
http://0.0.0.0:8765/status
```

在 Windows 浏览器中访问：

```text
http://Mac-IP:8765/status
```

能看到 JSON 就表示通信正常。

### 2. 切换状态

```bash
./set-status.sh idle
./set-status.sh running "Codex 正在执行任务"
./set-status.sh waiting "等待用户确认"
./set-status.sh success "任务完成"
./set-status.sh error "任务失败"
```

### 3. Windows Rainmeter 端安装

双击运行：

```text
install-rainmeter-skin.cmd
```

或者手动复制：

```text
rainmeter\CodexTrafficLight
```

到：

```text
%USERPROFILE%\Documents\Rainmeter\Skins\CodexTrafficLight
```

然后在 Rainmeter 中刷新皮肤并加载 `CodexTrafficLight.ini`。

### 4. 配置 Mac 地址

编辑：

```text
rainmeter\CodexTrafficLight\@Resources\variables.inc
```

把 `StatusUrl` 改为真实 Mac IP：

```ini
StatusUrl=http://192.168.1.100:8765/status
```

默认每 2 秒刷新一次。

## 状态含义

| 状态 | 含义 | 灯光 |
|---|---|---|
| `idle` | 空闲 | 灰灯 |
| `running` | 正在运行 | 红灯 |
| `waiting` | 等待用户确认 | 黄灯 |
| `success` | 运行完成 | 绿灯 |
| `error` | 运行失败、异常或连接失败 | 红色错误态 |

## 安全说明

Mac 端只提供只读 `/status` 接口，不提供远程执行命令能力。`message` 建议只写简短状态，不要写路径、账号、密钥等敏感内容。
