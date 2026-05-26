param(
  [ValidateSet("windows", "mac")]
  [string]$Topic = "windows"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms

if ($Topic -eq "mac") {
  $title = "Codex 交通灯 - Mac 使用说明"
  $message = @"
Mac 作为 Codex 状态服务电脑，Windows 作为 Rainmeter 显示电脑。

1. 在 Mac 上找到项目
如果项目在 Documents 里，终端输入：
cd ~/Documents/Codex-TrafficLight/mac/codex_status_server

如果项目在别的位置，把路径换成自己的位置：
cd /你的路径/Codex-TrafficLight/mac/codex_status_server

2. 确认进对目录
终端输入：
ls

正常应该能看到：
server.py
set-status.sh
start.command

3. 第一次运行前授权
终端输入：
chmod +x set-status.sh start.command

如果提示 No such file or directory，说明还没有进入 mac/codex_status_server 目录。先重新执行第 1 步的 cd 命令。

4. 启动服务
启动：
./start.command

终端窗口不要关闭。

5. 先在 Mac 本机验证
终端输入：
curl http://127.0.0.1:8765/status

能看到 JSON，说明 Mac 服务已经启动。

6. 获取 Mac IP
方法 A：系统设置 -> 网络 -> 当前 Wi-Fi 或以太网 -> 查看 IP 地址。
方法 B：终端执行：
ipconfig getifaddr en0

如果 en0 没输出，试：
ipconfig getifaddr en1

7. Windows Rainmeter 填写地址
假设 Mac IP 是 192.168.2.50：
http://192.168.2.50:8765/rainmeter

8. Windows 浏览器验证
Windows 浏览器先打开：
http://192.168.2.50:8765/status

能看到 JSON，Rainmeter 就能读取。

注意：Windows 和 Mac 需要在同一局域网，或通过 Tailscale/ZeroTier/VPN 等方式互通。
"@
} else {
  $title = "Codex 交通灯 - Windows 使用说明"
  $message = @"
Windows 可以作为 Codex 状态服务电脑，也可以作为 Rainmeter 显示电脑。

一、本机 Windows 使用
Codex 和 Rainmeter 在同一台 Windows：

1. 打开项目文件夹 Codex-TrafficLight。

2. 双击启动：
win\codex_status_server\start-server.cmd

3. 黑色命令窗口不要关闭，窗口开着代表服务正在运行。

4. Rainmeter 设置地址填：
http://127.0.0.1:8765/rainmeter

5. 浏览器验证：
http://127.0.0.1:8765/status

二、Win + Win 跨电脑使用
Codex 在 A 电脑，Rainmeter 在 B 电脑：

1. 在 A 电脑打开项目文件夹 Codex-TrafficLight。

2. 在 A 电脑双击启动：
win\codex_status_server\start-server.cmd

3. 在 A 电脑查看 IP：
打开 cmd，输入 ipconfig
找到正在联网网卡的 IPv4 地址，例如 192.168.2.112。

4. 在 B 电脑浏览器验证：
http://192.168.2.112:8765/status

5. 在 B 电脑 Rainmeter 设置地址填：
http://192.168.2.112:8765/rainmeter

三、常见问题
如果跨电脑打不开，检查：
1. 两台电脑是否在同一局域网。
2. Windows 防火墙是否允许 Python/状态服务访问专用网络。
3. Codex 状态服务窗口是否还在运行。
4. 黑色命令窗口是否进入“选择”暂停状态；如果标题出现“选择”，按 Esc。
"@
}

[System.Windows.Forms.MessageBox]::Show(
  $message,
  $title,
  [System.Windows.Forms.MessageBoxButtons]::OK,
  [System.Windows.Forms.MessageBoxIcon]::Information
) | Out-Null
