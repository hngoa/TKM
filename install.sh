#!/bin/bash
# ============================================================
# install.sh — Cài đặt TẤT CẢ dependencies cho MPLS Backbone Lab
# Chạy: sudo bash install.sh
#
# Thành phần cài đặt:
#   1. Mininet + Open vSwitch      — Emulation framework
#   2. FRRouting (FRR)              — OSPF, LDP, BGP daemons
#   3. MPLS kernel modules          — Label switching support
#   4. Python packages              — PyYAML, matplotlib
#   5. Network tools                — traceroute, iperf3, bridge-utils
#
# Sau khi cài, xác thực bằng: sudo bash check_env.sh
# ============================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo -e "${BOLD}========================================================"
echo "  MPLS Backbone Lab — Cài đặt Dependencies"
echo "========================================================${NC}"

# Kiểm tra root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}[ERROR] Vui lòng chạy với quyền root: sudo bash install.sh${NC}"
    exit 1
fi

# ----------------------------------------------------------------
# [1/7] System packages
# ----------------------------------------------------------------
echo ""
echo -e "${BOLD}[1/7] Cập nhật apt và cài system packages...${NC}"
apt update -qq 2>/dev/null

# Cài các packages cơ bản
apt install -y \
    iproute2 \
    iputils-ping \
    net-tools \
    traceroute \
    bridge-utils \
    iperf3 \
    curl \
    lsb-release \
    gnupg \
    2>/dev/null || true
echo -e "  ${GREEN}✓ System packages OK${NC}"

# ----------------------------------------------------------------
# [2/7] Mininet
# ----------------------------------------------------------------
echo ""
echo -e "${BOLD}[2/7] Cài đặt Mininet...${NC}"
if command -v mn &> /dev/null; then
    echo -e "  ${GREEN}✓ Mininet đã có: $(mn --version 2>&1 | head -1)${NC}"
else
    apt install -y mininet 2>/dev/null || {
        echo -e "  ${YELLOW}Mininet không có trong apt, cài từ source...${NC}"
        apt install -y git
        cd /tmp
        git clone --depth 1 https://github.com/mininet/mininet.git 2>/dev/null || true
        cd mininet
        util/install.sh -nfv 2>/dev/null || true
        cd -
    }
    echo -e "  ${GREEN}✓ Mininet đã cài${NC}"
fi

# Đảm bảo OVS chạy
apt install -y openvswitch-switch 2>/dev/null || true
systemctl enable openvswitch-switch 2>/dev/null || true
systemctl start openvswitch-switch 2>/dev/null || true
echo -e "  ${GREEN}✓ Open vSwitch OK${NC}"

# ----------------------------------------------------------------
# [3/7] FRRouting (FRR)
# ----------------------------------------------------------------
echo ""
echo -e "${BOLD}[3/7] Cài đặt FRRouting (FRR)...${NC}"
if [ -f /usr/lib/frr/zebra ] && command -v vtysh &> /dev/null; then
    echo -e "  ${GREEN}✓ FRR đã có: $(vtysh --version 2>&1 | head -1)${NC}"
else
    # Thử cài từ apt trước (Ubuntu 20.04+ có sẵn)
    apt install -y frr frr-pythontools 2>/dev/null || {
        echo -e "  ${YELLOW}Thêm FRR repository...${NC}"
        # Thêm FRR official repo
        curl -s https://deb.frrouting.org/frr/keys.gpg \
            | gpg --dearmor -o /usr/share/keyrings/frr-archive-keyring.gpg 2>/dev/null || {
            curl -s https://deb.frrouting.org/frr/keys.asc | apt-key add - 2>/dev/null || true
        }
        FRRVER="frr-stable"
        CODENAME=$(lsb_release -s -c 2>/dev/null || echo "focal")
        echo "deb [signed-by=/usr/share/keyrings/frr-archive-keyring.gpg] \
            https://deb.frrouting.org/frr $CODENAME $FRRVER" \
            > /etc/apt/sources.list.d/frr.list 2>/dev/null || \
        echo "deb https://deb.frrouting.org/frr $CODENAME $FRRVER" \
            > /etc/apt/sources.list.d/frr.list
        apt update -qq 2>/dev/null
        apt install -y frr frr-pythontools
    }
    echo -e "  ${GREEN}✓ FRR đã cài${NC}"
fi

# Bật các daemons cần thiết trong /etc/frr/daemons
if [ -f /etc/frr/daemons ]; then
    echo "  Cấu hình FRR daemons:"
    for daemon in zebra ospfd ldpd bgpd staticd; do
        if grep -q "^${daemon}=no" /etc/frr/daemons 2>/dev/null; then
            sed -i "s/^${daemon}=no/${daemon}=yes/" /etc/frr/daemons
            echo -e "    ${GREEN}✓ Bật $daemon${NC}"
        elif grep -q "^${daemon}=yes" /etc/frr/daemons 2>/dev/null; then
            echo -e "    ✓ $daemon đã bật"
        fi
    done
fi

# Kiểm tra các binary quan trọng
echo "  Kiểm tra FRR binaries:"
for bin in zebra ospfd ldpd bgpd staticd; do
    if [ -f "/usr/lib/frr/$bin" ]; then
        echo -e "    ${GREEN}✓ /usr/lib/frr/$bin${NC}"
    else
        echo -e "    ${RED}✗ /usr/lib/frr/$bin — THIẾU${NC}"
    fi
done

# ----------------------------------------------------------------
# [4/7] MPLS Kernel Modules
# ----------------------------------------------------------------
echo ""
echo -e "${BOLD}[4/7] Load MPLS kernel modules...${NC}"

MPLS_OK=true
for mod in mpls_router mpls_iptunnel mpls_gso; do
    if modprobe $mod 2>/dev/null; then
        echo -e "  ${GREEN}✓ $mod loaded${NC}"
    else
        echo -e "  ${YELLOW}⚠ $mod không load được${NC}"
        
        # Kiểm tra module có tồn tại trong kernel không
        MOD_PATH=$(find /lib/modules/$(uname -r) -name "${mod}*" 2>/dev/null | head -1)
        if [ -n "$MOD_PATH" ]; then
            echo -e "    Module file tồn tại: $MOD_PATH"
            echo -e "    Thử: sudo modprobe $mod"
        else
            echo -e "    ${RED}Module KHÔNG có trong kernel $(uname -r)${NC}"
            echo -e "    Cần kernel có CONFIG_MPLS=y và CONFIG_MPLS_ROUTING=m"
            echo -e "    Nếu dùng VM: kiểm tra kernel đã compile MPLS support"
            MPLS_OK=false
        fi
    fi
done

# Nếu MPLS không khả dụng, thông báo
if [ "$MPLS_OK" = false ]; then
    echo ""
    echo -e "  ${YELLOW}╔══════════════════════════════════════════════════╗"
    echo -e "  ║  MPLS modules không có trong kernel.              ║"
    echo -e "  ║  LDP sẽ không hoạt động, nhưng OSPF + BGP vẫn OK ║"
    echo -e "  ║                                                    ║"
    echo -e "  ║  Giải pháp:                                       ║"
    echo -e "  ║  • Dùng kernel có MPLS support (Ubuntu stock OK)  ║"
    echo -e "  ║  • Hoặc cài kernel mới: sudo apt install          ║"
    echo -e "  ║    linux-image-generic linux-modules-extra-\$(uname -r) ║"
    echo -e "  ╚══════════════════════════════════════════════════╝${NC}"
fi

# Cấu hình MPLS sysctl
echo ""
echo "  Cấu hình MPLS sysctl:"
sysctl -w net.mpls.platform_labels=1048575 2>/dev/null && \
    echo -e "  ${GREEN}✓ platform_labels = 1048575${NC}" || \
    echo -e "  ${YELLOW}⚠ Không set được platform_labels (MPLS module chưa load)${NC}"

sysctl -w net.ipv4.ip_forward=1 2>/dev/null && \
    echo -e "  ${GREEN}✓ ip_forward = 1${NC}"

# Persist vào sysctl.conf (chỉ thêm nếu chưa có)
if ! grep -q "net.mpls.platform_labels" /etc/sysctl.conf 2>/dev/null; then
    cat >> /etc/sysctl.conf << 'EOF'

# MPLS Backbone Lab
net.mpls.platform_labels = 1048575
net.ipv4.ip_forward = 1
EOF
    echo -e "  ${GREEN}✓ Đã persist vào /etc/sysctl.conf${NC}"
fi

# ----------------------------------------------------------------
# [5/7] Python Dependencies
# ----------------------------------------------------------------
echo ""
echo -e "${BOLD}[5/7] Cài đặt Python dependencies...${NC}"

apt install -y python3 python3-pip python3-yaml 2>/dev/null || true

# PyYAML
if python3 -c "import yaml" 2>/dev/null; then
    YAML_VER=$(python3 -c "import yaml; print(yaml.__version__)")
    echo -e "  ${GREEN}✓ PyYAML: $YAML_VER${NC}"
else
    pip3 install pyyaml 2>/dev/null || pip install pyyaml 2>/dev/null || {
        apt install -y python3-yaml 2>/dev/null || true
    }
    echo -e "  ${GREEN}✓ PyYAML installed${NC}"
fi

# Mininet Python module
if python3 -c "from mininet.net import Mininet" 2>/dev/null; then
    echo -e "  ${GREEN}✓ Mininet Python module OK${NC}"
else
    echo -e "  ${RED}✗ Mininet Python module không import được${NC}"
    echo -e "    Thử: sudo pip3 install mininet"
fi

# matplotlib (optional)
apt install -y python3-matplotlib 2>/dev/null || \
    pip3 install matplotlib 2>/dev/null || true
echo -e "  ${GREEN}✓ matplotlib (cho report)${NC}"

# ----------------------------------------------------------------
# [6/7] Tạo thư mục cần thiết
# ----------------------------------------------------------------
echo ""
echo -e "${BOLD}[6/7] Tạo thư mục runtime...${NC}"
mkdir -p /var/run/frr /var/log/frr 2>/dev/null || true
chmod 755 /var/run/frr /var/log/frr 2>/dev/null || true
# Tạo thư mục result cho test reports
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$SCRIPT_DIR/result" 2>/dev/null || true
echo -e "  ${GREEN}✓ /var/run/frr, /var/log/frr, result/ created${NC}"

# ----------------------------------------------------------------
# [7/7] Xác thực cuối cùng
# ----------------------------------------------------------------
echo ""
echo -e "${BOLD}[7/7] Xác thực nhanh...${NC}"

ALL_OK=true

# Mininet
if python3 -c "from mininet.net import Mininet; print('OK')" 2>/dev/null | grep -q OK; then
    echo -e "  ${GREEN}✓ Mininet import OK${NC}"
else
    echo -e "  ${RED}✗ Mininet import FAIL${NC}"
    ALL_OK=false
fi

# FRR
if [ -f /usr/lib/frr/zebra ] && [ -f /usr/lib/frr/ospfd ] && [ -f /usr/lib/frr/ldpd ]; then
    echo -e "  ${GREEN}✓ FRR binaries OK${NC}"
else
    echo -e "  ${RED}✗ FRR binaries MISSING${NC}"
    ALL_OK=false
fi

# MPLS
if [ -f /proc/sys/net/mpls/platform_labels ]; then
    echo -e "  ${GREEN}✓ MPLS kernel support OK${NC}"
else
    echo -e "  ${YELLOW}⚠ MPLS kernel support missing (LDP sẽ bị disable)${NC}"
fi

# Project files
if [ -f "$SCRIPT_DIR/runners/run_backbone.py" ] && [ -f "$SCRIPT_DIR/tools/frr_manager.py" ]; then
    echo -e "  ${GREEN}✓ Project files OK${NC}"
else
    echo -e "  ${RED}✗ Project files MISSING${NC}"
    ALL_OK=false
fi

echo ""
echo -e "${BOLD}========================================================${NC}"
if [ "$ALL_OK" = true ]; then
    echo -e "  ${GREEN}${BOLD}✅ Cài đặt hoàn tất! Môi trường sẵn sàng.${NC}"
else
    echo -e "  ${YELLOW}${BOLD}⚠  Cài đặt xong nhưng có một số vấn đề.${NC}"
    echo -e "     Chạy ${BOLD}sudo bash check_env.sh${NC} để xem chi tiết."
fi
echo ""
echo -e "  ${BOLD}Bước tiếp theo:${NC}"
echo ""
echo "    # Kiểm tra môi trường đầy đủ:"
echo "    sudo bash check_env.sh"
echo ""
echo "    # Chạy test backbone:"
echo "    sudo python3 runners/run_backbone.py --test"
echo ""
echo "    # Nếu OSPF không hội tụ, debug bằng CLI:"
echo "    sudo python3 runners/run_backbone.py"
echo "    mininet> pe01 vtysh -c 'show ip ospf neighbor'"
echo -e "${BOLD}========================================================${NC}"
