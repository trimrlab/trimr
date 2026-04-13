#!/usr/bin/env bash
set -e

TRIMR_DIR="$HOME/.trimr"
TRIMR_REPO="https://github.com/trimrlab/trimr.git"
TRIMR_INSTALL_DIR="$TRIMR_DIR/app"
TRIMR_VENV_DIR="$TRIMR_DIR/venv"
MIN_PYTHON_VERSION="3.10"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[Trimr]${NC} $1"; }
ok()    { echo -e "${GREEN}[Trimr]${NC} $1"; }
fail()  { echo -e "${RED}[Trimr]${NC} $1"; exit 1; }

echo ""
echo -e "${RED}"
echo "  ████████╗██████╗ ██╗███╗   ███╗██████╗ "
echo "  ╚══██╔══╝██╔══██╗██║████╗ ████║██╔══██╗"
echo "     ██║   ██████╔╝██║██╔████╔██║██████╔╝"
echo "     ██║   ██╔══██╗██║██║╚██╔╝██║██╔══██╗"
echo "     ██║   ██║  ██║██║██║ ╚═╝ ██║██║  ██║"
echo "     ╚═╝   ╚═╝  ╚═╝╚═╝╚═╝     ╚═╝╚═╝  ╚═╝"
echo -e "${NC}"
echo "     AI Agent Cost Control Engine  v0.1.0"
echo ""


# ── Detect OS / 检测系统 ─────────────────────────
info "Detecting platform... / 检测系统平台..."

OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Darwin)  PLATFORM="macOS"  ;;
    Linux)   PLATFORM="Linux"  ;;
    MINGW*|MSYS*|CYGWIN*) PLATFORM="Windows" ;;
    *)       fail "Unsupported platform / 不支持的系统: $OS" ;;
esac

ok "Platform / 平台: $PLATFORM ($ARCH)"

# ── Check Python / 检查 Python ───────────────────
info "Checking Python... / 检查 Python 环境..."

PYTHON_CMD=""

for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
        if [ -n "$version" ]; then
            major=$(echo "$version" | cut -d. -f1)
            minor=$(echo "$version" | cut -d. -f2)
            if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
                PYTHON_CMD="$cmd"
                break
            fi
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo ""
    echo "  Python >= $MIN_PYTHON_VERSION not found."
    echo "  未找到 Python >= $MIN_PYTHON_VERSION。"
    echo ""
    echo "  Please install Python first / 请先安装 Python："
    echo ""
    if [ "$PLATFORM" = "macOS" ]; then
        echo "    brew install python@3.12"
    elif [ "$PLATFORM" = "Linux" ]; then
        echo "    sudo apt install python3.12 python3.12-venv   # Debian/Ubuntu"
        echo "    sudo dnf install python3.12                    # Fedora"
    else
        echo "    https://www.python.org/downloads/"
    fi
    echo ""
    fail "Python >= $MIN_PYTHON_VERSION is required. / 需要 Python >= $MIN_PYTHON_VERSION。"
fi

ok "Python: $($PYTHON_CMD --version)"

# ── Check git / 检查 git ─────────────────────────
if ! command -v git &>/dev/null; then
    fail "git is not installed. Please install git first. / 未安装 git，请先安装。"
fi

# ── Setup / 初始化 ───────────────────────────────
info "Setting up... / 初始化目录..."
mkdir -p "$TRIMR_DIR"

# ── Clone or update / 下载或更新 ─────────────────
if [ -d "$TRIMR_INSTALL_DIR/.git" ]; then
    info "Updating... / 更新中..."
    cd "$TRIMR_INSTALL_DIR"
    git pull --quiet
    ok "Updated. / 已更新。"
else
    info "Downloading Trimr... / 下载 Trimr..."
    [ -d "$TRIMR_INSTALL_DIR" ] && rm -rf "$TRIMR_INSTALL_DIR"
    git clone --quiet --depth 1 "$TRIMR_REPO" "$TRIMR_INSTALL_DIR"
    ok "Downloaded. / 下载完成。"
fi

cd "$TRIMR_INSTALL_DIR"

# ── Venv / 虚拟环境 ──────────────────────────────
info "Setting up Python environment... / 配置 Python 环境..."

[ ! -d "$TRIMR_VENV_DIR" ] && "$PYTHON_CMD" -m venv "$TRIMR_VENV_DIR"
source "$TRIMR_VENV_DIR/bin/activate"

# ── Dependencies / 安装依赖 ──────────────────────
info "Installing dependencies... / 安装依赖..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
ok "Dependencies installed. / 依赖安装完成。"

# ── Config / 配置文件 ────────────────────────────
if [ ! -f "$TRIMR_INSTALL_DIR/.env" ]; then
    cat > "$TRIMR_INSTALL_DIR/.env" << 'ENVFILE'
HOST=0.0.0.0
PORT=8000
DEBUG=False

DATABASE_URL=sqlite:///./trimr.db

CLOUD_API_URL=https://alpha.cloud-api.trimrlab.cloud
ENVFILE
    ok "Created config file. / 已创建配置文件。"
fi

# ── Launch script / 启动脚本 ─────────────────────
cat > "$TRIMR_DIR/start.sh" << 'SCRIPT'
#!/usr/bin/env bash
TRIMR_DIR="$HOME/.trimr"
source "$TRIMR_DIR/venv/bin/activate"
cd "$TRIMR_DIR/app"
python main.py
SCRIPT
chmod +x "$TRIMR_DIR/start.sh"

# ── trimr command / 命令行工具 ───────────────────
TRIMR_BIN="$TRIMR_DIR/bin"
mkdir -p "$TRIMR_BIN"

cat > "$TRIMR_BIN/trimr" << WRAPPER
#!/usr/bin/env bash
exec "$HOME/.trimr/start.sh" "\$@"
WRAPPER
chmod +x "$TRIMR_BIN/trimr"

SHELL_RC=""
case "$SHELL" in
    */zsh)  SHELL_RC="$HOME/.zshrc" ;;
    */bash) SHELL_RC="$HOME/.bashrc" ;;
esac

PATH_ADDED=false
if [ -n "$SHELL_RC" ]; then
    if ! grep -q "trimr/bin" "$SHELL_RC" 2>/dev/null; then
        echo "" >> "$SHELL_RC"
        echo "# Trimr" >> "$SHELL_RC"
        echo "export PATH=\"\$HOME/.trimr/bin:\$PATH\"" >> "$SHELL_RC"
        PATH_ADDED=true
    fi
fi

# ── Done / 完成 ──────────────────────────────────
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Trimr installed successfully!${NC}"
echo -e "${GREEN}  Trimr 安装成功！${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "  Install location / 安装位置: $TRIMR_DIR"
echo ""
echo "  To start Trimr / 启动方式:"
echo ""
if [ "$PATH_ADDED" = true ]; then
    echo "    source $SHELL_RC && trimr"
else
    echo "    trimr"
fi
echo ""
echo "  Starting Trimr... / 正在启动 Trimr..."
echo ""

export PATH="$TRIMR_BIN:$PATH"
"$TRIMR_DIR/start.sh" </dev/tty
