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

1. 在 Mac 上准备服务
把项目里的 mac/codex_status_server 文件夹复制到 Mac。

2. 启动服务
打开终端，进入该目录：
cd /你的路径/codex_status_server

第一次运行前授权：
chmod +x start.command set-status.sh

启动：
./start.command

终端窗口不要关闭。

3. 获取 Mac IP
方法 A：系统设置 -> 网络 -> 当前 Wi-Fi 或以太网 -> 查看 IP 地址。
方法 B：终端执行：
ipconfig getifaddr en0

如果 en0 没输出，试：
ipconfig getifaddr en1

4. Windows Rainmeter 填写地址
假设 Mac IP 是 192.168.2.50：
http://192.168.2.50:8765/rainmeter

5. 浏览器验证
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

1. 双击启动：
win\codex_status_server\start-server.cmd

2. Rainmeter 设置地址填：
http://127.0.0.1:8765/rainmeter

3. 浏览器验证：
http://127.0.0.1:8765/status

二、Win + Win 跨电脑使用
Codex 在 A 电脑，Rainmeter 在 B 电脑：

1. 在 A 电脑启动：
win\codex_status_server\start-server.cmd

2. 在 A 电脑查看 IP：
打开 cmd，输入 ipconfig
找到正在联网网卡的 IPv4 地址，例如 192.168.2.112。

3. 在 B 电脑浏览器验证：
http://192.168.2.112:8765/status

4. 在 B 电脑 Rainmeter 设置地址填：
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

