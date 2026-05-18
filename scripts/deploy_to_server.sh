#!/bin/bash
#
# Relay Proxy 自托管部署脚本
# 用法: bash scripts/deploy_to_server.sh
#
set -e

RELAY_USER="relay"
APP_DIR="/opt/relay-proxy"


# 颜色
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

echo "=========================================="
echo "  Relay Proxy 自托管部署"
echo "=========================================="

# ---- 1. 创建专用用户 ----
info "创建 relay 用户..."
id relay &>/dev/null || sudo useradd -m -s /bin/bash relay
info "relay 用户就绪"

# ---- 2. 安装依赖 ----
info "安装系统依赖..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip git sshpass > /dev/null

# ---- 3. 克隆/更新代码 ----
if [ -d "$APP_DIR/.git" ]; then
    info "更新代码..."
    cd $APP_DIR && sudo git pull
else
    info "克隆代码仓库..."
    sudo mkdir -p $APP_DIR
    git clone https://github.com/toolazytoname/relay-proxy.git $APP_DIR
fi

# ---- 4. 创建虚拟环境 ----
info "安装 uv..."
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

info "创建虚拟环境..."
uv venv
uv pip install -r requirements.txt
# ---- 5. 创建必要目录 ----
info "创建数据目录..."
sudo mkdir -p $APP_DIR/keys
sudo mkdir -p $APP_DIR/logs
sudo mkdir -p $APP_DIR/tokens
sudo mkdir -p $APP_DIR/config
sudo chown -R relay:relay $APP_DIR

# ---- 6. 配置文件 ----
ENV_FILE="$APP_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    info "创建配置文件..."
    ADMIN_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    cat > /tmp/relay-proxy.env << EOF
# Relay Proxy 环境配置
ADMIN_TOKEN=$ADMIN_TOKEN
MANIFEST_PATH=$APP_DIR/config/permission_manifest.yaml
LOG_DIR=$APP_DIR/logs
TOKEN_STORE_PATH=$APP_DIR/tokens.jsonl
EOF
    sudo mv /tmp/relay-proxy.env $ENV_FILE
    sudo chown relay:relay $ENV_FILE
    sudo chmod 600 $ENV_FILE
    echo ""
    warn "已生成 ADMIN_TOKEN，请记录："
    echo "  $ADMIN_TOKEN"
    echo "（后续通过 'sudo systemctl cat relay-proxy' 查看）"
fi

# ---- 7. 安装 systemd service ----
info "安装 systemd service..."
sudo cp $APP_DIR/deploy/systemd/relay-proxy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable relay-proxy

# ---- 8. 启动 ----
info "启动服务..."
sudo systemctl start relay-proxy
sleep 2

if systemctl is-active --quiet relay-proxy; then
    info "服务已启动！"
    sudo systemctl status relay-proxy --no-pager | head -10
else
    error "服务启动失败，请检查日志：sudo journalctl -u relay-proxy -n 30"
fi

echo ""
echo "=========================================="
info  "部署完成！"
echo "=========================================="
echo "管理命令："
echo "  sudo systemctl start   relay-proxy   # 启动"
echo "  sudo systemctl stop   relay-proxy   # 停止"
echo "  sudo systemctl restart relay-proxy   # 重启"
echo "  sudo systemctl status  relay-proxy   # 状态"
echo "  sudo journalctl -u relay-proxy -f    # 日志"
echo ""
echo "初始化要管理的服务器："
echo "  bash $APP_DIR/scripts/init_target_server.sh --host <目标服务器IP> --relay-url http://你的Relay服务器IP:8000 --password <root密码>"