#!/bin/bash
# install.sh - Cài đặt tất cả dependencies cho Metro Ethernet MPLS Lab
# Chạy: sudo bash install.sh

set -e

echo "========================================"
echo "  Metro Ethernet MPLS - Cài đặt Dependencies"
echo "========================================"

# Kiểm tra root
if [ "$EUID" -ne 0 ]; then
    echo "[ERROR] Vui lòng chạy với quyền root: sudo bash install.sh"
    exit 1
fi

echo ""
echo "[1/6] Cập nhật apt package list..."
apt update -qq

echo ""
echo "[2/6] Cài đặt Mininet..."
if ! command -v mn &> /dev/null; then
    apt install -y mininet
    echo "      ✓ Mininet đã cài đặt"
else
    echo "      ✓ Mininet đã có sẵn: $(mn --version 2>&1 | head -1)"
fi

echo ""
echo "[3/6] Cài đặt FRRouting (FRR)..."
if ! command -v vtysh &> /dev/null; then
    # Thêm FRR repo
    curl -s https://deb.frrouting.org/frr/keys.asc | apt-key add - 2>/dev/null || true
    FRRVER="frr-stable"
    echo "deb https://deb.frrouting.org/frr $(lsb_release -s -c) $FRRVER" \
        > /etc/apt/sources.list.d/frr.list
    apt update -qq
    apt install -y frr frr-pythontools
    # Bật các daemons cần thiết
    sed -i 's/^ospfd=no/ospfd=yes/' /etc/frr/daemons
    sed -i 's/^ldpd=no/ldpd=yes/'   /etc/frr/daemons
    sed -i 's/^bgpd=no/bgpd=yes/'   /etc/frr/daemons
    echo "      ✓ FRR đã cài đặt"
else
    echo "      ✓ FRR đã có sẵn: $(vtysh --version 2>&1 | head -1)"
fi

echo ""
echo "[4/6] Cài đặt iperf3..."
if ! command -v iperf3 &> /dev/null; then
    apt install -y iperf3
    echo "      ✓ iperf3 đã cài đặt"
else
    echo "      ✓ iperf3 đã có sẵn: $(iperf3 --version 2>&1 | head -1)"
fi

echo ""
echo "[5/6] Cài đặt Python dependencies..."
apt install -y python3-pip python3-matplotlib python3-yaml 2>/dev/null || true
pip3 install matplotlib pyyaml 2>/dev/null || pip install matplotlib pyyaml 2>/dev/null || true
echo "      ✓ Python packages OK (matplotlib, pyyaml)"

echo ""
echo "[6/6] Bật kernel MPLS modules..."
modprobe mpls_router  2>/dev/null && echo "      ✓ mpls_router" || echo "      [WARN] mpls_router không available"
modprobe mpls_gso     2>/dev/null && echo "      ✓ mpls_gso"    || echo "      [WARN] mpls_gso không available"
modprobe mpls_iptunnel 2>/dev/null && echo "      ✓ mpls_iptunnel" || echo "      [WARN] mpls_iptunnel không available"

# Bật MPLS platform labels
sysctl -w net.mpls.platform_labels=1048575 2>/dev/null || true
sysctl -w net.ipv4.ip_forward=1 2>/dev/null || true

# Persist sysctl
cat >> /etc/sysctl.conf << 'EOF'
# MPLS for Metro Ethernet Lab
net.mpls.platform_labels = 1048575
net.ipv4.ip_forward = 1
EOF

echo ""
echo "========================================"
echo "  ✅ Cài đặt hoàn tất!"
echo ""
echo "  Bước tiếp theo:

    [Phase 1 - Test nội bộ từng chi nhánh]
    sudo python3 runners/run_branch1.py --test   # Flat Network
    sudo python3 runners/run_branch2.py --test   # Three-Tier + Inter-VLAN
    sudo python3 runners/run_branch3.py --test   # Spine-Leaf DC

    [Phase 2 - Test liên chi nhánh qua MPLS VPLS]
    sudo python3 runners/run_full_mpls.py        # FRR OSPF+LDP+BGP+VPLS
    sudo python3 runners/run_full_mpls.py --no-frr  # Static routes fallback

    [Đo hiệu năng]
    sudo python3 tools/measure_performance.py --mode all
    python3 tools/generate_report.py             # Tạo báo cáo HTML"
echo "========================================"
