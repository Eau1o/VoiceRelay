# VoiceRelay · 双语音引擎调度器

在 Windows 上用一个 **右 Alt** 调用 Typeless 或微信输入法的语音输入。调度器按应用记住上次手动选择的引擎。新应用默认使用 Typeless。

例如，在聊天软件中切到微信语音后，再到一个首次使用的编辑器按右 Alt，仍会启动 Typeless。下次打开同一个聊天软件，会沿用上次选的微信语音。

## 本版变化

- 引擎选择完全由用户控制。已取消按周额度切换、额度读取和达限提示监测。
- 切换键限定为 **右 Ctrl + 小键盘减号**。选择按前台程序的进程名保存，同一程序的窗口共用一条记录。
- Typeless 主窗口和托盘由用户照常打开、关闭；按右 Alt 只用于语音输入。

## 运行环境

| 组件 | 要求 |
|---|---|
| 操作系统 | Windows 10 或 11，x64 |
| Python | 64 位 Python 3.12（已测试 3.12.9），使用标准库即可 |
| Windows PowerShell | 系统自带的 `powershell.exe`。后台用它和 .NET Framework 的 `System.Management` 监听 Typeless 重启 |
| 语音引擎 | Typeless 和微信输入法，已测试 Typeless 2.12.0 和微信输入法 3.0.1.35 |

无需额外安装 Node.js、npm、.NET SDK、.NET 6 运行时或 PowerShell 7。日常运行也无需执行 `pip install`。

## 快速开始

### 让 Agent 启动

把下面这段话复制给能在这台 Windows 电脑上执行命令的 Agent：

> 请帮我安装并启动 VoiceRelay。优先使用已有项目，否则从 GitHub 的 Eau1o/VoiceRelay 下载到当前用户可写的目录。按下面的运行环境和快捷键检查设置，在项目目录执行 `python main.py --install`，最后用 `python main.py --status` 确认调度器正在运行。

### 手动启动

1. 下载或克隆本仓库到固定、可写的目录。
2. 启动两款语音软件。Typeless 的语音键设为 **右 Alt**，微信输入法设为 **左 Ctrl + 左 Shift + F12**。两者都设为按一次开始、再按一次结束。
3. 在项目目录打开 PowerShell，执行下面两条命令。第一条立即后台启动并设置当前账户登录自启，第二条检查运行状态。

```powershell
python main.py --install
python main.py --status
```

以后登录 Windows 后，直接在目标程序的输入框按右 Alt 即可。

### 常用快捷键

| 操作 | 效果 |
|---|---|
| 右 Alt | 用当前应用记住的引擎开始或结束录音 |
| 右 Ctrl + 数字小键盘减号 | 切换并保存当前应用的引擎。低音表示微信语音，高音表示 Typeless |
| 右 Alt + 空格、右 Alt + 右 Shift | 使用 Typeless 时保留其原有组合键 |

录音期间调度器忽略切换操作。左 Ctrl + 小键盘减号交给前台应用。主键盘数字行的减号保留原用途。

## 后台运行与退出

| 命令 | 用途 |
|---|---|
| `python main.py` | 立即启动。在此控制台按 Ctrl+C 可退出 |
| `python main.py --install` | 立即后台运行并设置当前用户登录自启。移动项目目录后重新执行 |
| `python main.py --status` | 显示运行状态、各应用的记忆 |
| `python main.py --uninstall` | 停止后台实例并移除登录自启，保留个人设置 |

## 设置

编辑 `config.json` 后重启调度器。个人引擎选择会在第一次使用切换键时自动写入 `overrides.json`。

| 配置项 | 默认值 | 用途 |
|---|---:|---|
| shadow_keys | [162, 160, 123] | 左 Ctrl、左 Shift、F12。若微信配置为左 Ctrl、左 Alt、F12，改用 [162, 164, 123] |

修改快捷键后，先执行 `python main.py --uninstall`，再执行 `python main.py --install` 重新加载配置。原有应用记忆会保留。

## 隐私与本地数据

调度器在本机处理热键和路由，不录制音频、不保存按键内容或转写正文，也不向网络发送这些数据。语音识别由所选输入软件负责，其数据处理方式取决于各软件自身。

| 本地数据 | 包含的信息 |
|---|---|
| `overrides.json` | 手动设置过的应用进程名及对应引擎 |
| `logs/router.log` | 时间戳、运行事件、切换时的进程名及引擎，可能反映使用习惯 |
| quota-cache.db | 旧版本可能留下的额度缓存；当前调度器不读写此文件 |
| Windows 麦克风使用状态 | 后台读取两个引擎的麦克风使用标志，辅助判断录音是否结束 |
| Typeless 数据库 | 文件位于 Typeless 的用户数据目录。当前调度器不打开该库，也不监听它的变化 |

Git 会忽略本地记忆、日志、数据库及 Python 缓存。分享问题报告时，请检查日志摘录、截图以及 `--status` 输出中的应用名和时间。

## 故障排查

- **切换无反应**。先用 `--status` 确认调度器正在运行，再确认使用的是数字小键盘减号，并已结束录音。
- **微信语音浮框没有出现**。在同一输入框直接按微信配置的语音快捷键，核对它与 `shadow_keys` 一致。切换引擎后松开 Ctrl 再轻按右 Alt。日志中的 `wetype_hotkey_sent` 表示组合键已发送，`microphone_start_unconfirmed` 表示随后未确认麦克风启动。
- **日志出现 typeless_pid_monitor**。当普通账户无法订阅 WMI 启动事件时，程序每五秒检查一次 Typeless 进程，发现新进程后延迟两秒恢复钩子。

## 验证

运行 `python s4_browser.py` 可在独立 Edge 测试窗口比较拦截前后的页面缩放。测试期间保持该窗口在前台。

## 逐模块实测方法

| 模块 | 操作与判据 |
|---|---|
| main.py | 启动两次，第二次应提示已运行。运行卸载命令后，首实例退出，右 Alt 恢复原生。WMI 订阅受限时可在日志看到 typeless_pid_monitor。 |
| winapi.py、hook.py | 运行 S4。另在 Typeless 模式分别测试两个右 Alt 组合键，再在微信模式快按右 Alt 五次。每次按下只切换一次，按住无连发。 |
| dispatch.py | 保持微信语音键为左 Ctrl + 左 Shift + F12，在微信路由下开始、结束录音，再用普通字母和菜单确认修饰键释放。 |
| router.py | 给微信和 QQ 分别指定引擎，再打开未记录的程序验证默认走 Typeless。录音中按切换键，记忆应保持原值。 |
| foreground.py | 在两个不同进程间切换并分别按切换热键，用 --status 核对进程名称和各自记录。 |
| overrides.py | 听到确认音后关闭目标应用并重开，再重启调度器，核对相同进程仍走原引擎。 |
| 重启与维护 | 微信路由下退出并重开 Typeless，等待子进程启动后约七秒，检查右 Alt 仍只唤起微信。在任务管理器记录 Python 和 WMI 辅助进程十分钟 CPU 时间差。 |
