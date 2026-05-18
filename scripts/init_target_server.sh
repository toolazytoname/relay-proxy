#!/bin/bash
#
# 目标服务器初始化脚本
# 在你的本地电脑运行
# 用法: bash init_target_server.sh --host <目标服务器IP> --relay-url <Relay服务器URL> --password <root密码> [--server-name <名称>]
#
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

TARGET_HOST=""
RELAY_URL=""
ROOT_PASSWORD=""
SERVER_NAME=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --host) TARGET_HOST="$2"; shift 2 ;;
        --relay-url) RELAY_URL="$2"; shift 2 ;;
        --password) ROOT_PASSWORD="$2"; shift 2 ;;
        --server-name) SERVER_NAME="$2"; shift 2 ;;
        *) shift ;;
    esac
done

[ -z "$TARGET_HOST" ] && error "缺少 --host 参数"
[ -z "$RELAY_URL" ] && error "缺少 --relay-url 参数"
[ -z "$ROOT_PASSWORD" ] && error "缺少 --password 参数"
[ -z "$SERVER_NAME" ] && SERVER_NAME="$TARGET_HOST"

info "为 $SERVER_NAME 生成 SSH 密钥对..."
RESPONSE=$(curl -s -X POST "$RELAY_URL/admin/keys/generate?server_name=$SERVER_NAME")
PUBKEY=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('public_key',''))" 2>/dev/null)

if [ -z "$PUBKEY" ]; then
    error "无法生成密钥：$RESPONSE"
fi
info "密钥对生成成功"

info "初始化目标服务器: $TARGET_HOST"

sshpass -p "$ROOT_PASSWORD" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@$TARGET_HOST bash << 'REMOTE_EOF'
set -e

RELAY_USER="relay"

# 1. 创建 relay 用户
id relay &>/dev/null || useradd -m -s /bin/bash relay

# 2. 配置 SSH 公钥
mkdir -p /home/relay/.ssh
chmod 700 /home/relay/.ssh
echo "$PUBKEY" > /home/relay/.ssh/authorized_keys
chmod 600 /home/relay/.ssh/authorized_keys
chown -R relay:relay /home/relay/.ssh

# 3. 最小 sudoers 权限
cat > /etc/sudoers.d/relay << 'SUDOERSEOF'
relay ALL=(ALL) NOPASSWD: /usr/bin/systemctl status *
relay ALL=(ALL) NOPASSWD: /usr/bin/docker ps
relay ALL=(ALL) NOPASSWD: /usr/bin/docker logs *
relay ALL=(ALL) NOPASSWD: !/usr/bin/passwd
relay ALL=(ALL) NOPASSWD: !/bin/rm -rf /*
SUDOERSEOF
chmod 440 /etc/sudoers.d/relay

echo "✅ 初始化完成"
REMOTE_EOF

info "$TARGET_HOST 初始化成功！"
echo ""
echo "下一步：在 Relay Server 上配置权限清单 /opt/relay-proxy/config/permission_manifest.yaml"
echo "添加："
echo "  - name: $SERVER_NAME"
echo "    host: $TARGET_HOST"
echo "    user: relay"