# Metro Ethernet MPLS - Mô Phỏng Đa Chi Nhánh

> **Đề tài:** Thiết kế và triển khai mạng Metro Ethernet sử dụng MPLS cho kết nối đa chi nhánh doanh nghiệp  
> **Nền tảng:** Mininet + FRRouting (FRR) + iperf3  
> **OS:** Ubuntu 20.04 / 22.04 LTS (Linux)

---

## 📁 Cấu Trúc Project

```
mpls_metro/
├── topologies/
│   ├── full_topology.py        # ← Topology tổng hợp (chạy chính)
│   ├── backbone.py             # MPLS Backbone (P01-P04, PE01-PE03)
│   ├── branch1_flat.py         # Chi nhánh 1: Mạng Phẳng
│   ├── branch2_3tier.py        # Chi nhánh 2: Mạng 3 Lớp
│   └── branch3_spineleaf.py    # Chi nhánh 3: Spine-Leaf (DC)
│
├── configs/
│   ├── frr_config_generator.py # Tạo file .conf cho FRR
│   └── frr_deploy.py           # Deploy FRR vào Mininet nodes
│
├── tools/
│   ├── measure_performance.py  # ← Công cụ đo lường chính
│   ├── quick_test.py           # Kiểm tra kết nối nhanh
│   └── generate_report.py      # Tạo biểu đồ + báo cáo HTML
│
├── results/                    # Kết quả đo (tự động tạo)
├── install.sh                  # Script cài đặt dependencies
└── README.md
```

---

## 🏗 Kiến Trúc Hệ Thống

### MPLS Backbone (Partial Mesh)
```
        PE01 ──── CE01 ──── [Chi nhánh 1: Flat]
       /    \
      P01   P02
      |  ╲╱  |
      |  ╱╲  |
      P03   P04
       \    /
        PE02 ──── CE02 ──── [Chi nhánh 2: 3-Tier]
        PE03 ──── CE03 ──── [Chi nhánh 3: Spine-Leaf]
```

| Thiết bị | Loopback IP | Vai Trò |
|----------|-------------|---------|
| P01      | 10.0.0.1    | Core P-Router |
| P02      | 10.0.0.2    | Core P-Router |
| P03      | 10.0.0.3    | Core P-Router |
| P04      | 10.0.0.4    | Core P-Router |
| PE01     | 10.0.0.11   | Provider Edge (Dual-homed P01+P02) |
| PE02     | 10.0.0.12   | Provider Edge (Dual-homed P02+P03) |
| PE03     | 10.0.0.13   | Provider Edge (Dual-homed P03+P04) |

### Chi Nhánh 1 — Mạng Phẳng (Flat)
```
CE01 (GW: 10.1.0.1)
  └── SW01
       ├── PC01 (10.1.0.11)
       ├── PC02 (10.1.0.12)
       └── SW02
            ├── PC03 (10.1.0.13)
            └── PC04 (10.1.0.14)
```

### Chi Nhánh 2 — Mạng 3 Lớp (Core-Distribution-Access)
```
CE02
 ├── CORE01 ──── CORE02
      ├── DIST01 ─ DIST02
           ├── ACCESS01 → LAB   (10.2.10.x)
           ├── ACCESS02 → ADMIN (10.2.20.x)
           └── ACCESS03 → GUEST (10.2.30.x)
```

### Chi Nhánh 3 — Spine-Leaf (Data Center)
```
CE03 → LEAF01 (Border)
        ├── SPINE01 ─── SPINE02
             ├── LEAF02 → WEB (10.3.10.x)
             ├── LEAF03 → DNS (10.3.20.x)
             └── LEAF04 → DB  (10.3.30.x)
```

---

## 🚀 Hướng Dẫn Chạy

### Bước 1: Cài đặt dependencies

```bash
sudo bash install.sh
```

Lệnh này cài đặt: Mininet, FRRouting (FRR), iperf3, Python matplotlib, MPLS kernel modules.

> **Lưu ý:** Cần kết nối Internet. Thời gian khoảng 3-5 phút.

---

### Bước 2: Tạo file cấu hình FRR

```bash
python3 configs/frr_config_generator.py
```

Tạo file `.conf` cho tất cả routers (P01-P04, PE01-PE03, CE01-CE03) trong thư mục `configs/`.

---

### Bước 3: Kiểm tra kết nối nhanh

```bash
sudo python3 tools/quick_test.py
```

Ping 13 cặp host (intra + inter branch). Kết quả mong đợi: **13/13 PASS**.

---

### Bước 4: Đo lường hiệu năng đầy đủ

```bash
# Đo tất cả (intra + inter + stress) — khuyến nghị
sudo python3 tools/measure_performance.py --mode all --duration 10

# Chỉ đo inter-branch (qua MPLS backbone)
sudo python3 tools/measure_performance.py --mode inter

# Chỉ đo intra-branch (nội bộ từng chi nhánh)
sudo python3 tools/measure_performance.py --mode intra

# Chỉ đo stress test (high load)
sudo python3 tools/measure_performance.py --mode stress

# Đo với thời gian iperf3 dài hơn (30 giây/test)
sudo python3 tools/measure_performance.py --mode all --duration 30
```

Kết quả lưu vào: `results/results_YYYYMMDD_HHMMSS.json` và `results/summary_*.csv`

---

### Bước 5: Tạo biểu đồ và báo cáo HTML

```bash
python3 tools/generate_report.py
# Mở báo cáo trong browser:
xdg-open results/report_*/report.html
```

---

### Chạy Interactive Mininet CLI (tùy chọn)

```bash
sudo python3 topologies/full_topology.py
```

Trong Mininet CLI:
```
mininet> pingall               # Ping tất cả cặp hosts
mininet> pc01 ping 10.3.10.11  # Ping từ PC01 đến web01
mininet> xterm pc01            # Mở terminal cho pc01
mininet> nodes                 # Liệt kê tất cả nodes
mininet> links                 # Liệt kê tất cả links
mininet> dump                  # Thông tin chi tiết
```

---

## 📊 Các Chỉ Số Được Đo

| Chỉ Số | Công Cụ | Mô Tả |
|--------|---------|-------|
| **Throughput** | iperf3 TCP/UDP | Băng thông thực tế (Mbps) |
| **Delay (RTT)** | ping | Độ trễ khứ hồi (ms) |
| **Packet Loss** | ping + iperf3 UDP | Tỷ lệ mất gói (%) |
| **Jitter** | ping mdev + iperf3 UDP | Biến thiên độ trễ (ms) |
| **Hop Count** | traceroute | Số bước nhảy qua backbone |
| **Retransmits** | iperf3 TCP | Số lần truyền lại TCP |

### Test Cases

**Intra-Branch (9 tests):**
- Branch 1: same switch, daisy-chain
- Branch 2: same VLAN, inter-VLAN routing
- Branch 3: same leaf, cross-leaf (2 hops)

**Inter-Branch qua MPLS (9 tests):**
- B1 ↔ B2, B1 ↔ B3, B2 ↔ B3 (cả hai chiều)

**Stress Tests (3 tests):**
- 4 luồng UDP song song x 15 giây

---

## 🔧 Triển Khai MPLS với FRR (Tùy Chọn Nâng Cao)

Để chạy OSPF + LDP thực sự thay vì static routes:

```bash
# 1. Khởi động topology (không thoát)
sudo python3 -c "
from topologies.full_topology import build_full_topology, configure_ip_addresses
from configs.frr_deploy import deploy_all
net = build_full_topology()
net.start()
configure_ip_addresses(net)
deploy_all(net)
import time; time.sleep(15)  # Chờ OSPF converge
from mininet.cli import CLI
CLI(net)
net.stop()
"
```

Sau khi OSPF hội tụ (~10-15s), kiểm tra:
```bash
# Trong Mininet CLI, trên node pe01:
pe01 vtysh -c "show ospf neighbor"
pe01 vtysh -c "show mpls ldp neighbor"
pe01 vtysh -c "show bgp l2vpn evpn summary"
```

---

## 📋 IP Address Plan

| Vùng | Dải IP | Mô Tả |
|------|--------|-------|
| Backbone Loopbacks | 10.0.0.0/24 | Router IDs |
| P-P Links | 10.0.10.0/21 | Core mesh links (/30 each) |
| PE-P Links | 10.0.20.0/21 | Edge links (/30 each) |
| WAN PE-CE | 10.100.x.0/30 | ISP to Customer links |
| Branch 1 | 10.1.0.0/24 | Flat LAN |
| Branch 2 LAB | 10.2.10.0/24 | VLAN 10 |
| Branch 2 ADMIN | 10.2.20.0/24 | VLAN 20 |
| Branch 2 GUEST | 10.2.30.0/24 | VLAN 30 |
| Branch 3 WEB | 10.3.10.0/24 | WEB servers |
| Branch 3 DNS | 10.3.20.0/24 | DNS servers |
| Branch 3 DB | 10.3.30.0/24 | DB servers |

---

## ❗ Troubleshooting

**Lỗi: `RTNETLINK answers: Operation not permitted`**
```bash
sudo modprobe mpls_router
sudo sysctl -w net.mpls.platform_labels=1048575
```

**Lỗi: `iperf3: error - the server is busy`**
```bash
sudo pkill -f iperf3
```

**Ping thất bại inter-branch:**
```bash
# Kiểm tra routing table trên PE
sudo python3 -c "
from topologies.full_topology import build_full_topology, configure_ip_addresses, configure_routing
net = build_full_topology(); net.start()
configure_ip_addresses(net); configure_routing(net)
net.get('pe01').cmd('ip route')  # In routing table
"
```

**Mininet không xóa sạch:**
```bash
sudo mn -c  # Clean up Mininet state
```

---

## 📦 Requirements

| Package | Phiên bản | Mục đích |
|---------|-----------|---------|
| Python | ≥ 3.8 | Runtime |
| Mininet | ≥ 2.3.0 | Network emulation |
| FRRouting | ≥ 8.x | OSPF, LDP, BGP daemons |
| iperf3 | ≥ 3.x | Throughput measurement |
| matplotlib | ≥ 3.x | Chart generation (optional) |

---

*Đại học Tôn Đức Thắng — Khoa Mạng Máy Tính và Truyền Thông Dữ Liệu*
