#!/bin/bash
# ============================================================
# check_env.sh — Kiểm tra môi trường cho MPLS Backbone Lab
# Chạy: sudo bash check_env.sh
# 
# Script này KHÔNG cài đặt gì, chỉ KIỂM TRA và BÁO CÁO.
# Kết quả giúp xác định chính xác thành phần nào đang thiếu.
# ============================================================

set -u

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

PASS=0
FAIL=0
WARN=0

pass() { echo -e "  ${GREEN}[PASS]${NC} $1"; ((PASS++)); }
fail() { echo -e "  ${RED}[FAIL]${NC} $1"; ((FAIL++)); }
warn() { echo -e "  ${YELLOW}[WARN]${NC} $1"; ((WARN++)); }
info() { echo -e "  ${CYAN}[INFO]${NC} $1"; }

echo ""
echo -e "${BOLD}============================================================"
echo "  MPLS Backbone Lab — Kiểm tra môi trường"
echo "============================================================${NC}"
echo ""

# ----------------------------------------------------------------
# [1] Quyền root
# ----------------------------------------------------------------
echo -e "${BOLD}[1/8] Quyền root${NC}"
if [ "$EUID" -ne 0 ]; then
    fail "Cần chạy với quyền root: sudo bash check_env.sh"
    echo -e "       ${YELLOW}→ Một số kiểm tra sẽ bị bỏ qua${NC}"
else
    pass "Đang chạy với quyền root"
fi
echo ""

# ----------------------------------------------------------------
# [2] Hệ điều hành & Kernel
# ----------------------------------------------------------------
echo -e "${BOLD}[2/8] Hệ điều hành & Kernel${NC}"
if [ -f /etc/os-release ]; then
    . /etc/os-release
    info "OS: $PRETTY_NAME"
    
    # Khuyến nghị Ubuntu 20.04/22.04
    case "$ID" in
        ubuntu|debian)
            pass "Hệ điều hành tương thích ($ID $VERSION_ID)"
            ;;
        *)
            warn "OS '$ID' chưa được test — khuyến nghị Ubuntu 20.04/22.04"
            ;;
    esac
else
    warn "Không xác định được hệ điều hành"
fi

KERNEL=$(uname -r)
info "Kernel: $KERNEL"

# Kiểm tra kernel version >= 4.1 (cần cho MPLS)
KMAJOR=$(echo "$KERNEL" | cut -d. -f1)
KMINOR=$(echo "$KERNEL" | cut -d. -f2)
if [ "$KMAJOR" -gt 4 ] || ([ "$KMAJOR" -eq 4 ] && [ "$KMINOR" -ge 1 ]); then
    pass "Kernel >= 4.1 (hỗ trợ MPLS)"
else
    fail "Kernel < 4.1 — MPLS không được hỗ trợ"
fi
echo ""

# ----------------------------------------------------------------
# [3] Mininet
# ----------------------------------------------------------------
echo -e "${BOLD}[3/8] Mininet${NC}"
if command -v mn &> /dev/null; then
    MN_VER=$(mn --version 2>&1 | head -1)
    pass "Mininet đã cài: $MN_VER"
else
    fail "Mininet chưa cài"
    info "Fix: sudo apt install -y mininet"
fi

# Kiểm tra Open vSwitch (Mininet cần)
if command -v ovs-vsctl &> /dev/null; then
    OVS_VER=$(ovs-vsctl --version 2>&1 | head -1)
    pass "Open vSwitch: $OVS_VER"
else
    fail "Open vSwitch chưa cài (Mininet cần)"
    info "Fix: sudo apt install -y openvswitch-switch"
fi

# Kiểm tra OVS service
if [ "$EUID" -eq 0 ]; then
    if systemctl is-active --quiet openvswitch-switch 2>/dev/null; then
        pass "OVS service đang chạy"
    else
        warn "OVS service không chạy"
        info "Fix: sudo systemctl start openvswitch-switch"
    fi
fi
echo ""

# ----------------------------------------------------------------
# [4] FRRouting (FRR)
# ----------------------------------------------------------------
echo -e "${BOLD}[4/8] FRRouting (FRR) — OSPF, LDP, BGP${NC}"

# zebra binary
if [ -f /usr/lib/frr/zebra ]; then
    pass "zebra binary: /usr/lib/frr/zebra"
elif command -v zebra &> /dev/null; then
    pass "zebra binary: $(which zebra)"
else
    fail "FRR zebra chưa cài"
    info "Fix: sudo apt install -y frr frr-pythontools"
fi

# ospfd
if [ -f /usr/lib/frr/ospfd ]; then
    pass "ospfd binary OK"
else
    fail "ospfd không tìm thấy"
fi

# ldpd
if [ -f /usr/lib/frr/ldpd ]; then
    pass "ldpd binary OK"
else
    fail "ldpd không tìm thấy (cần cho MPLS LDP)"
    info "Fix: sudo apt install -y frr"
fi

# bgpd
if [ -f /usr/lib/frr/bgpd ]; then
    pass "bgpd binary OK"
else
    fail "bgpd không tìm thấy (cần cho iBGP VPLS)"
fi

# vtysh
if command -v vtysh &> /dev/null; then
    VTYSH_VER=$(vtysh --version 2>&1 | head -1)
    pass "vtysh: $VTYSH_VER"
else
    fail "vtysh chưa cài"
    info "Fix: sudo apt install -y frr"
fi

# Kiểm tra FRR daemons config (/etc/frr/daemons)
if [ -f /etc/frr/daemons ]; then
    info "Kiểm tra /etc/frr/daemons:"
    
    for daemon in ospfd ldpd bgpd; do
        status=$(grep "^${daemon}=" /etc/frr/daemons 2>/dev/null | cut -d= -f2)
        if [ "$status" = "yes" ]; then
            pass "  $daemon=yes (enabled)"
        elif [ "$status" = "no" ]; then
            warn "  $daemon=no (disabled) — cần bật"
            info "  Fix: sudo sed -i 's/^${daemon}=no/${daemon}=yes/' /etc/frr/daemons"
        else
            warn "  $daemon: không tìm thấy trong daemons file"
        fi
    done
else
    warn "/etc/frr/daemons không tồn tại (FRR chưa cài?)"
fi

# Kiểm tra FRR host service status
if [ "$EUID" -eq 0 ]; then
    if systemctl is-active --quiet frr 2>/dev/null; then
        info "FRR host service: ĐANG CHẠY"
        info "(Script sẽ tự stop trước khi deploy per-node daemons)"
    else
        info "FRR host service: không chạy (OK — script sẽ start per-node)"
    fi
fi
echo ""

# ----------------------------------------------------------------
# [5] MPLS Kernel Modules
# ----------------------------------------------------------------
echo -e "${BOLD}[5/8] MPLS Kernel Modules${NC}"

for mod in mpls_router mpls_iptunnel mpls_gso; do
    if lsmod | grep -q "^$mod" 2>/dev/null; then
        pass "$mod: đã load"
    else
        # Thử load
        if [ "$EUID" -eq 0 ]; then
            if modprobe $mod 2>/dev/null; then
                pass "$mod: load thành công"
            else
                fail "$mod: KHÔNG load được"
                info "Kernel có thể chưa compile module này"
                info "Kiểm tra: find /lib/modules/$(uname -r) -name '${mod}*'"
            fi
        else
            warn "$mod: chưa load (cần root để kiểm tra)"
        fi
    fi
done

# Kiểm tra MPLS sysctl
if [ "$EUID" -eq 0 ]; then
    LABELS=$(sysctl -n net.mpls.platform_labels 2>/dev/null || echo "N/A")
    if [ "$LABELS" != "N/A" ] && [ "$LABELS" -gt 0 ] 2>/dev/null; then
        pass "net.mpls.platform_labels = $LABELS"
    else
        warn "net.mpls.platform_labels chưa set hoặc = 0"
        info "Fix: sudo sysctl -w net.mpls.platform_labels=1048575"
    fi
fi

# IP forwarding
IP_FWD=$(sysctl -n net.ipv4.ip_forward 2>/dev/null || echo "0")
if [ "$IP_FWD" = "1" ]; then
    pass "net.ipv4.ip_forward = 1 (enabled)"
else
    warn "net.ipv4.ip_forward = $IP_FWD (disabled)"
    info "Fix: sudo sysctl -w net.ipv4.ip_forward=1"
fi
echo ""

# ----------------------------------------------------------------
# [6] Python Dependencies
# ----------------------------------------------------------------
echo -e "${BOLD}[6/8] Python Dependencies${NC}"

# Python3
if command -v python3 &> /dev/null; then
    PY_VER=$(python3 --version 2>&1)
    pass "Python3: $PY_VER"
else
    fail "Python3 chưa cài"
    info "Fix: sudo apt install -y python3"
fi

# pip
if command -v pip3 &> /dev/null; then
    pass "pip3 available"
else
    warn "pip3 chưa cài"
    info "Fix: sudo apt install -y python3-pip"
fi

# PyYAML
python3 -c "import yaml; print(yaml.__version__)" 2>/dev/null
if [ $? -eq 0 ]; then
    YAML_VER=$(python3 -c "import yaml; print(yaml.__version__)" 2>/dev/null)
    pass "PyYAML: $YAML_VER"
else
    fail "PyYAML chưa cài"
    info "Fix: sudo apt install -y python3-yaml  HOẶC  pip3 install pyyaml"
fi

# Mininet Python module
if python3 -c "from mininet.net import Mininet" 2>/dev/null; then
    pass "Mininet Python module OK"
else
    fail "Mininet Python module không import được"
    info "Fix: sudo apt install -y mininet"
fi

# matplotlib (optional, cho report)
if python3 -c "import matplotlib" 2>/dev/null; then
    pass "matplotlib OK (cho report)"
else
    warn "matplotlib chưa cài (optional — dùng cho generate_report)"
    info "Fix: pip3 install matplotlib"
fi
echo ""

# ----------------------------------------------------------------
# [7] Network Tools
# ----------------------------------------------------------------
echo -e "${BOLD}[7/8] Network Tools${NC}"

for tool in ping traceroute iperf3 ip brctl; do
    if command -v $tool &> /dev/null; then
        pass "$tool available"
    else
        case $tool in
            traceroute)
                warn "$tool chưa cài"
                info "Fix: sudo apt install -y traceroute"
                ;;
            iperf3)
                warn "$tool chưa cài (optional — dùng cho performance test)"
                info "Fix: sudo apt install -y iperf3"
                ;;
            brctl)
                warn "$tool chưa cài"
                info "Fix: sudo apt install -y bridge-utils"
                ;;
            *)
                fail "$tool chưa cài"
                info "Fix: sudo apt install -y iproute2"
                ;;
        esac
    fi
done
echo ""

# ----------------------------------------------------------------
# [8] Project Files
# ----------------------------------------------------------------
echo -e "${BOLD}[8/8] Project Files${NC}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
info "Project root: $SCRIPT_DIR"

# Kiểm tra các file quan trọng
REQUIRED_FILES=(
    "runners/run_backbone.py"
    "tools/frr_manager.py"
    "tools/config_loader.py"
    "tools/node_types.py"
    "tools/connectivity_test.py"
    "topologies/backbone.py"
    "configs/backbone/ip_plan.yaml"
    "configs/backbone/frr/p01.conf"
    "configs/backbone/frr/pe01.conf"
)

for f in "${REQUIRED_FILES[@]}"; do
    if [ -f "$SCRIPT_DIR/$f" ]; then
        pass "$f"
    else
        fail "$f — THIẾU!"
    fi
done

# Kiểm tra tất cả FRR config files
FRR_CONFIGS=(p01 p02 p03 p04 pe01 pe02 pe03)
for router in "${FRR_CONFIGS[@]}"; do
    conf="configs/backbone/frr/${router}.conf"
    if [ -f "$SCRIPT_DIR/$conf" ]; then
        # Kiểm tra config có đúng router-id không
        RID=$(grep "router-id" "$SCRIPT_DIR/$conf" | head -1 | awk '{print $NF}')
        if [ -n "$RID" ]; then
            pass "$conf (router-id: $RID)"
        else
            warn "$conf — không tìm thấy router-id"
        fi
    else
        fail "$conf — THIẾU!"
    fi
done
echo ""

# ----------------------------------------------------------------
# Summary
# ----------------------------------------------------------------
echo -e "${BOLD}============================================================"
echo "  KẾT QUẢ KIỂM TRA"
echo "============================================================${NC}"
echo ""
TOTAL=$((PASS + FAIL + WARN))
echo -e "  ${GREEN}PASS: $PASS${NC}  |  ${RED}FAIL: $FAIL${NC}  |  ${YELLOW}WARN: $WARN${NC}  |  Total: $TOTAL"
echo ""

if [ $FAIL -eq 0 ]; then
    echo -e "  ${GREEN}${BOLD}✅ Môi trường SẴN SÀNG!${NC}"
    echo "     Chạy: sudo python3 runners/run_backbone.py --test"
elif [ $FAIL -le 3 ]; then
    echo -e "  ${YELLOW}${BOLD}⚠  Cần sửa $FAIL lỗi trước khi chạy${NC}"
    echo "     Xem các dòng [FAIL] ở trên và chạy lệnh Fix tương ứng"
    echo "     Hoặc chạy: sudo bash install.sh"
else
    echo -e "  ${RED}${BOLD}✗  Có $FAIL lỗi nghiêm trọng${NC}"
    echo "     Khuyến nghị chạy: sudo bash install.sh"
fi

echo ""
echo -e "${BOLD}  Quick Fix (cài tất cả):${NC}"
echo "     sudo bash install.sh"
echo ""
echo -e "${BOLD}  Manual Fix từng bước:${NC}"
echo "     1. sudo apt update"
echo "     2. sudo apt install -y mininet openvswitch-switch"
echo "     3. sudo apt install -y frr frr-pythontools"
echo "     4. sudo sed -i 's/^ospfd=no/ospfd=yes/' /etc/frr/daemons"
echo "     5. sudo sed -i 's/^ldpd=no/ldpd=yes/' /etc/frr/daemons"
echo "     6. sudo sed -i 's/^bgpd=no/bgpd=yes/' /etc/frr/daemons"
echo "     7. sudo modprobe mpls_router mpls_iptunnel mpls_gso"
echo "     8. sudo sysctl -w net.mpls.platform_labels=1048575"
echo "     9. sudo apt install -y python3-yaml traceroute bridge-utils iperf3"
echo "============================================================"
