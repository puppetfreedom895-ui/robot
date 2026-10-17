# robot

一个住在服务器上的 QQ 数字生命：**有自己的一部手机、自己的记忆、自己的日程**，你在 QQ 上跟它说话。

它不是一个"你说什么它做什么"的工具，而是持续运行的 agent——会自己醒来、自己决定干什么、无聊了会主动找你。手机是它的手，QQ 是它的嘴，DSH 是它的大脑。

## 三层结构

```
        QQ 小号（NapCat）          管理网页（只读看板）
                │                        │
        ┌───────┴────────────────────────┴──────┐
        │  生命内核（robot/life，常驻）            │
        │  ├ 心跳引擎：每 N 分钟问自己"想干嘛"      │
        │  ├ 自我状态：精力/心情/无聊度/当前关注     │
        │  ├ 记忆：日记 + 长期事实 + 对话上下文      │
        │  └ 自主性护栏：L0 看 / L1 动 / L2 说 / L3 花│
        └───────┬────────────────────────────────┘
                │ JSON-RPC
        ┌───────┴────────────────────────────────┐
        │  DSH runtime（大脑，不自研 agent loop）    │
        │  模型 deepseek-flash（带视觉，最便宜）     │
        └───────┬────────────────────────────────┘
                │ MCP（mcp__phone__*）
        ┌───────┴────────────────────────────────┐
        │  手机层 robot/mcp_phone（已实现）          │
        │  无障碍树 → 编号元素 → 点击/输入/滑动       │
        └───────┬────────────────────────────────┘
                │ ADB over Tailscale
            一部安卓手机（常亮、插电）
```

## 快速开始

```powershell
git clone https://github.com/puppetfreedom895-ui/robot
cd robot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

copy config.example.toml config.toml     # Linux/macOS 用 cp
```

填模型密钥，三种方式任选（优先级从低到高）：

1. 写进 `config.toml` 的 `[llm] api_key`
2. 写进同目录的 `.env`（会**自动加载**）：`ROBOT_API_KEY=sk-...`
3. 直接在 shell 里设：`$env:ROBOT_API_KEY="sk-..."`

先确认模型通：

```powershell
python -m robot chat
```

再确认「发消息它一定回」——假装收到一条私聊，不需要 QQ 也不需要密钥：

```powershell
python scripts/demo_chat.py
# 你发给它：在干嘛
# 它回你：在的，刚刷完手机，咋了
# 它记下的事：['22:14 主人：在干嘛']
```

再让它常驻：把 `config.toml` 里的 `[life] enabled = true`、`owner = 你的QQ号` 打开，然后

```powershell
python -m robot doctor    # 体检：密钥、人设、NapCat、生命内核、管理台、手机
python -m robot live      # 常驻
```

## 当前进度

| 层 | 状态 | 说明 |
| --- | --- | --- |
| 手机层 `robot/mcp_phone` | ✅ 完成 | 10 个 MCP 工具，界面树压缩，增量回执，206 个测试 |
| QQ 层 `robot/adapters/onebot` | ✅ 可用 | OneBot v11 客户端/反连，触发规则，分段回复 |
| 对话记忆 `robot/core/memory` | ✅ 可用 | 短期 + 摘要 + 长期事实 |
| 生命内核 `robot/life` | ✅ 基础版 | 状态、心跳、日记、目标、L3 护栏、DSH 执行器 |
| QQ 出入口接线 | ✅ 完成 | 主动私聊 + 对话联动状态 + `robot live` 常驻 |
| 管理台 `robot/web` | ✅ 完成 | 只读看板：状态、时间线、日记、截图 |
| 部署脚本 `deploy/` | ✅ 完成 | systemd、Docker、一键安装 |
| 部署上线 | 🚧 待你给 SSH | 装到你的云服务器并接上手机 |

## 手机层

把一部安卓机变成结构化、可点的界面。它不把截图喂给模型——那样又贵又容易点错——而是把无障碍树压成几十行编号清单：

```
com.android.settings 12:03｜3 个元素
#1 输入框「搜索设置」
#2 文本「WLAN」
#3 按钮「关闭」
```

模型看到的是 `#3 按钮「关闭」`，操作时说 `tap(index=3)`，由服务端换算成坐标。

### 工具清单

| 工具 | 作用 |
| --- | --- |
| `phone_info` | 机型、前台应用、电量 |
| `screen` | 当前界面的编号元素；`auto` 模式只给变化 |
| `tap` | 按编号 / 文字 / 坐标点击，**回执自带界面变化** |
| `type_text` | 输入文字，可选回车、可选先清空 |
| `swipe` | 四方向滑动 |
| `press` | 返回、桌面、任务列表等 |
| `open_app` | 中文名（微信/设置/B站…）或包名启动应用 |
| `find` | 按文字定位元素，返回编号 |
| `screenshot` | 只返回文件路径，图片不进上下文 |
| `wait` | 等页面加载 |

### 省 token 的四个内建设计

1. **结构化优先**：一张截图对模型是上千 token 且要猜坐标；压缩后的界面树通常 300–500 token 且精确。
2. **动作自带回执**：`tap` 返回"点了 #3。\n界面已变化\n#1 输入框…"，一步一次调用，不用额外再查一次屏。
3. **增量优先**：界面没变就只说"界面没有变化"，变了只列增删。
4. **预算硬上限**：单次界面输出默认 2000 字符，超了截断并注明还剩几个元素。

### 本地试跑（不需要手机）

```powershell
python -m robot.mcp_phone                        # 默认要连真机
$env:PHONE_FAKE="1"; python -m robot.mcp_phone   # 用假设备，验证协议
```

### 接真机

1. 手机开「开发者选项 → 无线调试」，和服务器用 Tailscale 组网。
2. 装依赖：`pip install -e ".[phone]"`。
3. 配置环境变量 `PHONE_SERIAL=100.x.x.x:5555`（Tailscale 里手机的地址）。

### 挂进 DSH

在 cordis 配置里加一条 MCP 客户端：

```yaml
- id: mcp-phone
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: phone
    transport: stdio
    command: python
    args: ['-m', 'robot.mcp_phone']
    env:
      PHONE_SERIAL: 100.64.0.7:5555
```

挂上之后模型会看到 `mcp__phone__screen`、`mcp__phone__tap` 等工具。

## 生命内核

没人理它的时候，它自己也在跑：

```
20:00  💤 什么也没干
22:00  🎬 做事：刷会儿手机
         └ 我打开 B 站，刷了会儿视频
01:00  😴 睡觉
```

五个部件各管一件事：

| 部件 | 文件 | 干什么 |
| --- | --- | --- |
| 状态 | `life/state.py` | 精力、无聊、心情、最近琢磨的事。做事掉精力，闲着涨无聊 |
| 心跳 | `life/loop.py` | 每 N 分钟醒一次；夜里和太累时**直接睡，不调模型** |
| 决策 | `life/brain.py` | 一次普通对话，约 300 token，只回一个 JSON |
| 护栏 | `life/policy.py` | L3 意图在执行前拒绝，并主动告诉你 |
| 执行 | `life/runner.py` | 真决定做事时才启动 DSH，带着手机工具去点 |

自己跑一遍（零成本，不碰手机）：

```powershell
python -m robot.life --ticks 12 --step 20 --start 20:00 --dsh "python scripts/fake_dsh.py"
```

- `--model`：换成真实模型做决定（需 `config.toml` 里的密钥）
- `--dsh "dsh --profile headless"`：换成真的 DSH 去操作手机
- `--budget 20000`：当天 token 额度，超了就只待着

实测每次心跳约 320 token，一天 144 次 ≈ 4.6 万 token。

## 常驻运行

```powershell
python -m robot live
```

一个进程干三件事：收 QQ 消息并回话、每 N 分钟自己醒一次、决定做事时调 DSH 操作手机。

配置在 `config.toml` 的 `[life]`：

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `enabled` | `false` | 不开它 `live` 会直接拒绝启动 |
| `owner` | `0` | 你的 QQ 号，它主动说话发到这里 |
| `heartbeat_minutes` | `10` | 醒的间隔；10 分钟约 4.6 万 token/天 |
| `timezone` | 空 | 免打扰和日记按这个时区算；云服务器多是 UTC，国内建议写 `Asia/Shanghai` |
| `quiet_start` / `quiet_end` | `1` / `7` | 免打扰时段，**这段不调模型，零成本** |
| `daily_budget_tokens` | `0` | 每天上限，超了它只发呆不动手 |
| `brain` | `offline` | `offline` 规则版不花钱；`model` 用真模型做决定 |
| `dsh_command` | 空 | 如 `dsh --profile headless`，空表示只演示不碰手机 |

双向联动：它主动说的话走私聊发给你；你在 QQ 跟它聊天时，它的无聊度会下降、精力会掉一点——状态跟真实互动挂钩，不是自己空转。

## QQ 层

OneBot v11，对接 [NapCat](https://github.com/NapNeko/NapCatQQ)。用专用小号，别用主号。

- `mode = "client"`：连 NapCat 的 WebSocket 服务端（端口 3001）
- `mode = "server"`：让 NapCat 反连本项目

群聊默认只在被 @ 或喊唤醒词时说话，可设冷却、白名单、随机接话概率。

## 自主性护栏

"做什么都可以"必须有刹车，否则一次 bug 就会把手机搞废。

| 层 | 行为 | 谁决定 |
| --- | --- | --- |
| L0 看 | 看屏幕、看消息、搜索 | 它自己 |
| L1 动 | 开关设置、启动应用、看视频、记笔记 | 它自己 |
| L2 说 | 主动私聊、群里说话、发动态 | 它自己，事后报告 |
| L3 花 | 花钱、删数据、加好友、改密码、注册 | **硬编码拦截**，必须问你 |

L3 不靠提示词约束——提示词在长对话里迟早被绕过——而是在工具层直接拒绝。

## 成本

按 `deepseek-flash`（缓存命中 0.02 元/M，未命中 1 元/M，空闲时段半价）：

| 项目 | 频次 | 单次 | 日消耗 |
| --- | --- | --- | --- |
| 心跳 | 144 次/天 | ~320 | ~46k |
| 操作手机 | 10–20 次 | ~30k | ~300–600k |
| 聊天 | ~50 条 | ~2k | ~100k |

约 **0.45–0.75M token/天**，折合 15–40 元/月。三条压缩手段：心跳极简（便宜模型、关思考、只给状态摘要）、平时休眠做事才升级、夜间降频（顺带半价）。

## 管理台

只读，没有任何写操作：

```
http://127.0.0.1:8787/?t=你的token
```

四样东西：它此刻的状态（精力/无聊/心情/在琢磨什么）、今天做过什么、日记、手机截图。

接口：`/api/snapshot`、`/api/shots`、`/api/shot/<名字>`、`/healthz`。

默认只绑 `127.0.0.1`。**放公网必须配 `[web] token`**，否则谁打开都能看到它的生活。

## 部署

目标：agent 跑在云服务器，手机在家里，两者用 Tailscale 组网。

### 1. 服务器准备

```bash
sudo apt update && sudo apt install -y python3.12 python3.12-venv git adb npm
curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up
```

### 2. 装 DSH 大脑

机器人自己只做决定，真正操作手机的是 DSH。服务器上装 npm 版 CLI（不是桌面版封装）：

```bash
sudo npm i -g @deepseek-ai/dsh
dsh --version          # 能打印版本就对了
```

Node 要 22 以上；系统自带的太旧就先装 NodeSource 或 nvm。

### 3. 拉代码并安装

```bash
sudo git clone https://github.com/puppetfreedom895-ui/robot /opt/robot
sudo /opt/robot/deploy/install.sh
```

脚本会建虚拟环境、装依赖、生成 `config.toml`、装好 systemd 服务。

### 4. 改配置

```toml
[llm]
api_key = "sk-..."

[life]
enabled = true
owner = 你的QQ号
dsh_command = "dsh --profile headless"

[web]
enabled = true
token = "一串随机字符"
```

### 5. 手机接进来

1. 手机装 Tailscale，用同一个账号登录。
2. 开发者选项 → 无线调试 → 打开，记下端口。
3. 服务器上 `adb connect 100.x.x.x:5555`（Tailscale 里手机的地址）。
4. 把 `PHONE_SERIAL=100.x.x.x:5555` 写进 `/opt/robot/.env`。

### 6. 启动

```bash
sudo systemctl start robot
sudo journalctl -u robot -f
```

### 7. 看管理台

```bash
ssh -L 8787:127.0.0.1:8787 你的服务器
# 然后浏览器打开 http://127.0.0.1:8787/?t=你的token
```

不要把 8787 直接暴露公网，要看就 SSH 转发。

### Docker 方式

```bash
cd deploy
cp ../config.example.toml ../config.toml   # 把 [onebot] url 改成 ws://napcat:3001
docker compose up -d
```

NapCat 的 WebUI 在 `http://服务器:6099`，扫码登录后加一个 WebSocket 服务器（端口 3001）。

## 风险与边界

1. **NapCat 是非官方接入**，用专用小号，别用主号。
2. **App 会检测自动化**：微信、支付宝、银行类可能黑屏截图或拒绝无障碍。适合"改设置、查信息、点到结算页"，不适合抢购刷单。
3. **手机要常亮插电**，断网会自动重连 ADB。
4. **它不会真的有意识**：状态 + 记忆 + 调度 + 人格一致性，表现上像，本质是可观测、可暂停、可接管的程序。

## 开发

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest              # 206 个测试，全部离线
ruff check .
```

## 目录

```
robot/
├── robot/
│   ├── phone/           # 设备抽象、uiautomator2 实现、界面树压缩
│   ├── mcp_phone/       # MCP stdio 服务端（挂给 DSH 用）
│   ├── life/            # 生命内核：状态、心跳、护栏、执行器、QQ 通知
│   ├── web/             # 只读管理台
│   ├── adapters/onebot/ # QQ 接入
│   ├── core/            # 事件、总线、上下文、人设、记忆
│   ├── llm/             # OpenAI 兼容 Provider
│   ├── store/           # SQLite
│   └── plugins/         # 插件机制与内置插件
├── deploy/              # systemd、Docker、一键安装
├── scripts/             # 演示与冒烟用配置
├── tests/               # 全部离线可跑
├── config.example.toml
└── persona.md
```

## License

MIT
