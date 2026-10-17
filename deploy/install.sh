#!/usr/bin/env bash
# 一键部署到 Linux 服务器。用 root 或 sudo 运行。
#
#   git clone https://github.com/puppetfreedom895-ui/robot /opt/robot
#   sudo /opt/robot/deploy/install.sh
#
# 环境变量：
#   APP_DIR       安装目录，默认 /opt/robot
#   SERVICE_NAME  systemd 服务名，默认 robot
#   PYTHON_BIN    python 解释器，默认 python3

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/robot}"
SERVICE_NAME="${SERVICE_NAME:-robot}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "==> 检查 Python 版本"
"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 11):
    sys.exit("需要 Python 3.11 或更高，当前是 %s" % sys.version.split()[0])
PY

if [ ! -d "$APP_DIR" ]; then
  echo "找不到 $APP_DIR。先把仓库放过去：" >&2
  echo "  git clone https://github.com/puppetfreedom895-ui/robot $APP_DIR" >&2
  exit 1
fi

cd "$APP_DIR"

echo "==> 建虚拟环境并装依赖"
"$PYTHON_BIN" -m venv .venv
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -e ".[phone]" --quiet

if ! command -v adb >/dev/null 2>&1; then
  echo "==> 提醒：没找到 adb，操作手机需要它"
  echo "    Debian/Ubuntu: sudo apt install -y adb"
fi

if [ ! -f config.toml ]; then
  cp config.example.toml config.toml
  echo "==> 已生成 config.toml（还需填 api_key / owner / token）"
fi

echo "==> 安装 systemd 服务 $SERVICE_NAME"
sed "s|/opt/robot|$APP_DIR|g" deploy/robot.service > "/etc/systemd/system/$SERVICE_NAME.service"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

cat <<EOF

装好了。接下来三步：

  1. 编辑 $APP_DIR/config.toml
       [llm]  api_key   填你的模型密钥
       [life] enabled = true, owner = 你的QQ号, dsh_command = "dsh --profile headless"
       [web]  enabled = true, token = 一串随机字符
  2. 启动：systemctl start $SERVICE_NAME
  3. 看日志：journalctl -u $SERVICE_NAME -f

手机那边记得开「无线调试」，并和服务器用 Tailscale 组网，
再把手机地址填到环境变量 PHONE_SERIAL（写进 .env 或服务配置）。
EOF
