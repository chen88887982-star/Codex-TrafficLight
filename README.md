# Codex 运行状态交通灯 Rainmeter 皮肤

这个项目是一套通用 Rainmeter 交通灯方案。Rainmeter 固定运行在 Windows 上，Codex 可以运行在同一台 Windows、另一台 Windows，或者一台 Mac。

## 组合方式

| 装备组合 | 状态服务运行位置 | Rainmeter 配置 |
|---|---|---|
| Win + Win 同一台电脑 | 本机 Windows | `http://127.0.0.1:8765/status` |
| Win + 另一台 Win | 运行 Codex 的 Windows | `http://对方Windows-IP:8765/status` |
| Win + Mac | 运行 Codex 的 Mac | `http://Mac-IP:8765/status` |

Rainmeter 只负责读取 `StatusUrl`。所以两套装备通用的关键就是：哪台电脑运行 Codex，就在哪台电脑启动状态服务。

## Windows 端安装皮肤

在 Rainmeter 所在的 Windows 上双击：

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

## 配置 Rainmeter 读取地址

安装后编辑：

```text
%USERPROFILE%\Documents\Rainmeter\Skins\CodexTrafficLight\@Resources\variables.inc
```

同一台 Windows 使用默认值：

```ini
StatusUrl=http://127.0.0.1:8765/status
```

跨电脑时改成运行 Codex 那台电脑的局域网 IP：

```ini
StatusUrl=http://192.168.1.100:8765/status
```

保存后，在 Rainmeter 管理器里刷新这个皮肤。

## Codex 在 Windows 时

在运行 Codex 的 Windows 上双击：

```text
win\codex_status_server\start-server.cmd
```

浏览器打开：

```text
http://127.0.0.1:8765/status
```

如果是另一台 Windows 读取，就在另一台电脑浏览器打开：

```text
http://运行Codex电脑的IP:8765/status
```

切换状态：

```powershell
.\win\codex_status_server\set-status.ps1 idle
.\win\codex_status_server\set-status.ps1 running "Codex 正在执行任务"
.\win\codex_status_server\set-status.ps1 waiting "等待用户确认"
.\win\codex_status_server\set-status.ps1 success "任务完成"
.\win\codex_status_server\set-status.ps1 error "任务失败"
```

## Codex 在 Mac 时

把这个目录复制到 Mac：

```text
mac/codex_status_server
```

在 Mac 终端执行：

```bash
chmod +x set-status.sh start.command
./start.command
```

切换状态：

```bash
./set-status.sh idle
./set-status.sh running "Codex 正在执行任务"
./set-status.sh waiting "等待用户确认"
./set-status.sh success "任务完成"
./set-status.sh error "任务失败"
```

Windows 浏览器打开：

```text
http://Mac-IP:8765/status
```

能看到 JSON 后，Rainmeter 就能自动变灯。

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
