#!/usr/bin/env bash
# ugnas-bridge v2 裸机安装（systemd + venv）。用法：sudo bash deploy/install.sh
set -euo pipefail
PREFIX=/opt/ugnas-bridge
SERVICE=ugnas-bridge
PORT="${UGNAS_BRIDGE_PORT:-8770}"
SRC="$(cd "$(dirname "$0")/.." && pwd)"

[ "$(id -u)" = "0" ] || { echo "请用 root 运行"; exit 1; }
command -v python3 >/dev/null || { echo "需要 python3"; exit 1; }
python3 -c 'import venv' 2>/dev/null || { echo "需要 python3-venv"; exit 1; }

id -u ugnas >/dev/null 2>&1 || useradd -r -s /usr/sbin/nologin ugnas
mkdir -p "$PREFIX" /etc/ugnas-bridge
cp -r "$SRC"/. "$PREFIX"/
mkdir -p "$PREFIX/state" "$PREFIX/logs"
python3 -m venv "$PREFIX/.venv"
"$PREFIX/.venv/bin/pip" install -q --upgrade pip
"$PREFIX/.venv/bin/pip" install -q -r "$PREFIX/requirements.txt"
chown -R ugnas:ugnas "$PREFIX"

if [ ! -f /etc/ugnas-bridge.env ]; then
  KEY=$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)
  umask 077
  printf 'UGNAS_BRIDGE_KEY=%s\nUGNAS_BRIDGE_PORT=%s\nUGNAS_HEALTH_INTERVAL=300\n' "$KEY" "$PORT" > /etc/ugnas-bridge.env
  echo "已生成口令，见 /etc/ugnas-bridge.env（请自行备份）"
fi

cat >/etc/systemd/system/${SERVICE}.service <<EOF
[Unit]
Description=ugnas-bridge v2 (UGOS bridge + Sun-Panel sync)
After=network-online.target
Wants=network-online.target
[Service]
User=ugnas
WorkingDirectory=$PREFIX
EnvironmentFile=/etc/ugnas-bridge.env
Environment=UGNAS_BRIDGE_DB=$PREFIX/state/ugnas_bridge.db
Environment=UGNAS_LOG_DIR=$PREFIX/logs
ExecStart=$PREFIX/.venv/bin/uvicorn web.app:app --host 0.0.0.0 --port \${UGNAS_BRIDGE_PORT}
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now "$SERVICE"
sleep 2
curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null && echo "安装完成：http://<本机>:${PORT}/" || echo "服务已启动，但健康检查未通过，请查看 journalctl -u $SERVICE"
