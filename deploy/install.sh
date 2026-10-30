#!/usr/bin/env bash
# ugnas-bridge 安装/卸载脚本（systemd）
# 用法：
#   sudo ./install.sh --host 0.0.0.0 --port 8770 [--dest /opt/ugnas-bridge] [--run-user root] [--key <32位口令>] [--no-start]
#   sudo ./install.sh --uninstall
# 说明：
#   - 只依赖 python3(>=3.9) + 标准库；不创建 Docker、不改动其它服务。
#   - NAS 密码从当前 shell 的 UGNAS_BRIDGE_PASS 注入 /etc/ugnas-bridge.env（0600）。
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="/opt/ugnas-bridge"
BIND="0.0.0.0"
PORT="8770"
RUN_USER="root"
LOGDIR="/var/log/ugnas-bridge"
ENVFILE="/etc/ugnas-bridge.env"
UNIT="/etc/systemd/system/ugnas-bridge.service"
DO_START=1
UNINSTALL=0
ACCESS_KEY="${UGNAS_BRIDGE_KEY:-}"
PASS_ENV="UGNAS_BRIDGE_PASS"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest) DEST="$2"; shift 2;;
    --host) BIND="$2"; shift 2;;
    --port) PORT="$2"; shift 2;;
    --run-user) RUN_USER="$2"; shift 2;;
    --log-dir) LOGDIR="$2"; shift 2;;
    --no-start) DO_START=0; shift;;
    --key) ACCESS_KEY="$2"; shift 2;;
    --pass-env) PASS_ENV="$2"; shift 2;;
    --uninstall) UNINSTALL=1; shift;;
    -h|--help) sed -n '2,12p' "$0"; exit 0;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

if [[ $EUID -ne 0 ]]; then echo "需要 root 运行" >&2; exit 1; fi

if [[ $UNINSTALL -eq 1 ]]; then
  systemctl disable --now ugnas-bridge 2>/dev/null || true
  rm -f "$UNIT"; systemctl daemon-reload
  echo "已卸载 unit；保留 $DEST 与日志（如需清理请手动 rm -rf $DEST $LOGDIR $ENVFILE）"
  exit 0
fi

command -v python3 >/dev/null || { echo "缺少 python3" >&2; exit 1; }
python3 - <<'PY' || { echo "python3 版本需 >=3.9" >&2; exit 1; }
import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)
PY

install -d "$DEST" "$LOGDIR"
# 只同步运行所需；若安装目录就是源码目录（原地安装），跳过拷贝避免自删
if [[ "$(cd "$DEST" && pwd)" != "$(cd "$SRC_DIR" && pwd)" ]]; then
  rm -rf "$DEST/poc" "$DEST/tools" "$DEST/docs" "$DEST/deploy"
  cp -a "$SRC_DIR/poc" "$SRC_DIR/tools" "$SRC_DIR/docs" "$SRC_DIR/deploy" "$DEST"/
else
  echo "in-place install: skip copy ($DEST)"
fi

# 参数化 unit：替换占位（保持文件本身可读）
sed -e "s#^Environment=UGNAS_BRIDGE_HOST=.*#Environment=UGNAS_BRIDGE_HOST=${BIND}#" \
    -e "s#^Environment=UGNAS_BRIDGE_PORT=.*#Environment=UGNAS_BRIDGE_PORT=${PORT}#" \
    -e "s#^Environment=UGNAS_BRIDGE_LOG=.*#Environment=UGNAS_BRIDGE_LOG=${LOGDIR}/bridge.log#" \
    -e "s#^ExecStart=.*#ExecStart=/usr/bin/python3 ${DEST}/poc/ugnas_bridge.py#" \
    -e "s#^WorkingDirectory=.*#WorkingDirectory=${DEST}#" \
    -e "s#^ReadWritePaths=.*#ReadWritePaths=${LOGDIR}#" \
    "$SRC_DIR/deploy/ugnas-bridge.service" > "$UNIT"

if [[ "$RUN_USER" != "root" ]]; then
  id "$RUN_USER" >/dev/null 2>&1 || { echo "用户不存在: $RUN_USER" >&2; exit 1; }
  sed -i "/^\[Service\]/a User=${RUN_USER}\nGroup=$(id -gn "$RUN_USER")" "$UNIT"
  chown -R "$RUN_USER":"$(id -gn "$RUN_USER")" "$LOGDIR"
fi

# 密钥单独落 0600（NAS 密码 + 访问口令）
umask 077
: > "$ENVFILE"
if [[ -z "$ACCESS_KEY" ]]; then
  ACCESS_KEY="$(python3 -c 'import secrets,string;print("".join(secrets.choice(string.ascii_letters+string.digits) for _ in range(32)))')"
  echo "已生成访问口令（32 位）：写入 $ENVFILE 的 UGNAS_BRIDGE_KEY，用 sudo cat $ENVFILE 查看"
fi
printf 'UGNAS_BRIDGE_KEY=%s\n' "$ACCESS_KEY" >> "$ENVFILE"
if [[ -n "${!PASS_ENV:-}" ]]; then
  printf '%s=%s\n' "$PASS_ENV" "${!PASS_ENV}" >> "$ENVFILE"
else
  echo "警告：当前环境无 $PASS_ENV；请事后写入 $ENVFILE" >&2
fi
chmod 600 "$ENVFILE"

systemctl daemon-reload
systemctl enable ugnas-bridge >/dev/null
if [[ $DO_START -eq 1 ]]; then
  systemctl restart ugnas-bridge
  sleep 3
  systemctl --no-pager --lines=15 status ugnas-bridge || true
  curl -sS --max-time 5 "http://127.0.0.1:${PORT}/health" || true
  echo
else
  echo "已安装并设为开机自启（未启动）。启动：systemctl start ugnas-bridge"
fi

echo "安装目录: $DEST  监听: ${BIND}:${PORT}  日志: ${LOGDIR}/bridge.log"
