# Metro Ethernet MPLS — Mô Phỏng Đa Chi Nhánh

> **Đề tài:** Thiết kế và triển khai mạng Metro Ethernet sử dụng MPLS/VPLS cho kết nối đa chi nhánh doanh nghiệp  
> **Nền tảng:** Mininet + FRRouting (FRR) trên Linux  
> **OS:** Ubuntu 20.04 / 22.04 LTS

---

## 📐 Kiến Trúc Config-Driven

Project được tổ chức theo mô hình **Config-Driven Architecture** — tách biệt hoàn toàn giữa khung mạng và nội dung cấu hình:

```
Topology skeleton (.py)  +  Config files (.yaml / .conf)
                ↓
          Runner script  →  Mininet Simulation
```

- **Topology files** → chỉ định nghĩa nodes và links (không embed IP cứng)
- **Config files** → toàn bộ IP plan, FRR config (dễ sửa, dễ debug)
- **Runner scripts** → chạy từng kịch bản kiểm tra độc lập
- **ISP Backbone** → không chỉ tự cấu hình mà còn **đẩy config xuống CE chi nhánh**

---

## 📁 Cấu Trúc Project

```
Src_Mininet/
├── topologies/                      ← Topology skeleton (khung)
│   ├── branch1_flat.py              # Chi nhánh 1: Mạng Phẳng
│   ├── branch2_3tier.py             # Chi nhánh 2: Mạng 3 Lớp
│   ├── branch3_spineleaf.py         # Chi nhánh 3: Spine-Leaf DC
│   ├── backbone.py                  # MPLS Backbone (P01-P04, PE01-PE03)
│   └── full_topology.py             # Topology tổng hợp đầy đủ
│
├── configs/                         ← Nội dung cấu hình
│   ├── branch1/
│   │   ├── ip_plan.yaml             # IP plan Branch 1 (hosts, CE, links, tests)
│   │   └── ce01.conf                # FRR config CE01 (do ISP cung cấp)
│   ├── branch2/
│   │   ├── ip_plan.yaml             # IP plan Branch 2 + VLAN plan
│   │   └── ce02.conf                # FRR config CE02 (do ISP cung cấp)
│   ├── branch3/
│   │   ├── ip_plan.yaml             # IP plan Branch 3 (Spine-Leaf /16)
│   │   └── ce03.conf                # FRR config CE03 (do ISP cung cấp)
│   └── backbone/
│       ├── ip_plan.yaml             # IP plan đầy đủ P/PE routers + WAN links
│       ├── vpls_policy.yaml         # VPLS service config (pseudowires, BGP EVPN)
│       └── frr/
│           ├── p01.conf             # FRR: OSPF + LDP
│           ├── p02.conf
│           ├── p03.conf
│           ├── p04.conf
│           ├── pe01.conf            # FRR: OSPF + LDP + BGP + VPLS
│           ├── pe02.conf
│           └── pe03.conf
│
├── runners/                         ← Script chạy từng kịch bản
│   ├── run_branch1.py               # Phase 1: Test nội bộ Branch 1 (isolated)
│   ├── run_branch2.py               # Phase 1: Test nội bộ Branch 2
│   ├── run_branch3.py               # Phase 1: Test nội bộ Branch 3
│   └── run_full_mpls.py             # Phase 2: Full MPLS + VPLS inter-branch
│
├── tools/
│   ├── config_loader.py             # Đọc YAML → apply IP vào Mininet nodes
│   ├── frr_manager.py               # Deploy FRR + ISP push CE config
│   ├── connectivity_test.py         # Auto ping test + báo cáo
│   ├── measure_performance.py       # Đo throughput, delay, jitter (iperf3)
│   ├── generate_report.py           # Tạo biểu đồ + báo cáo HTML
│   └── quick_test.py                # Kiểm tra kết nối nhanh
│
├── result/                          # Kết quả test (tự động tạo)
├── install.sh                       # Script cài đặt dependencies
└── README.md
```

---

## 🏗 Kiến Trúc Hệ Thống

### MPLS MAN Backbone (Partial Mesh + Dual-homed PE)

```
Chi nhánh 1 (Flat)        Chi nhánh 2 (3-Tier)      Chi nhánh 3 (Spine-Leaf)
  PC01-PC04                LAB/ADMIN/GUEST             WEB/DNS/DB servers
     │                          │                            │
    CE01                       CE02                         CE03
     │  WAN 10.100.1.0/30       │  WAN 10.100.2.0/30         │  WAN 10.100.3.0/30
    PE01 ─── P01 ─── P02 ─── PE02                           │
     └────── P02 ─── P03 ─── PE02                           │
                     P03 ─── P04 ─── PE03 ───────────────────┘
                     P01 ─── P03  (diagonal)
                     P02 ─── P04  (diagonal)

Tất cả P/PE: OSPF Area 0 + LDP (MPLS label distribution)
PE01-PE02-PE03: iBGP full-mesh (VPLS signaling)
```

### Chi Nhánh 1 — Flat Network

```
CE01 (10.1.0.1/24)
  └─ SW01 ─── SW02
       ├─ PC01 (10.1.0.11)    ├─ PC03 (10.1.0.13)
       └─ PC02 (10.1.0.12)    └─ PC04 (10.1.0.14)
```

### Chi Nhánh 2 — Three-Tier Network

```
CE02 (Inter-VLAN Router)
  ├─ 10.2.10.1 → CORE01 → DIST01 → ACCESS01 → LAB   (VLAN 10)
  ├─ 10.2.20.1 → CORE02 → DIST01 → ACCESS02 → ADMIN (VLAN 20)
  └─ 10.2.30.1 → DIST02 ──────── → ACCESS03 → GUEST (VLAN 30)
```

### Chi Nhánh 3 — Spine-Leaf Data Center

```
CE03 (10.3.0.1/16 — DC supernet gateway)
  └─ LEAF01 (Border)
       ├─ SPINE01 ─┬─ LEAF02 → WEB01, WEB02 (10.3.10.x)
       │            ├─ LEAF03 → DNS01, DNS02 (10.3.20.x)
       │            └─ LEAF04 → DB01,  DB02  (10.3.30.x)
       └─ SPINE02 ─┴─ (ECMP fabric)
```

---

## 🚀 Hướng Dẫn Chạy

### Bước 1: Cài đặt dependencies

```bash
sudo bash install.sh
```

Cài đặt: Mininet, FRRouting (FRR), iperf3, Python matplotlib, MPLS kernel modules.

---

### Phase 1 — Test Nội Bộ Từng Chi Nhánh (Isolated)

Chạy riêng từng branch để xác nhận cấu hình nội bộ hoạt động trước khi kết nối MPLS.

```bash
# Chi nhánh 1: Flat Network
sudo python3 runners/run_branch1.py

# Chi nhánh 2: Three-Tier + Inter-VLAN Routing
sudo python3 runners/run_branch2.py

# Chi nhánh 3: Spine-Leaf Data Center
sudo python3 runners/run_branch3.py

# Chạy auto test (không mở CLI)
sudo python3 runners/run_branch1.py --test
sudo python3 runners/run_branch2.py --test
sudo python3 runners/run_branch3.py --test
```

**Kết quả mong đợi Phase 1:**

| Branch | Test | Kỳ vọng |
|--------|------|---------|
| Branch 1 | PC01 ↔ PC04 | ✅ PASS (same subnet /24) |
| Branch 2 | LAB ↔ ADMIN | ✅ PASS (inter-VLAN qua CE02) |
| Branch 3 | WEB ↔ DB | ✅ PASS (cross-rack qua Spine) |

---

### Phase 2 — Test Kết Nối Liên Chi Nhánh (MPLS VPLS)

```bash
# Full topology với FRR (OSPF + LDP + BGP + VPLS)
sudo python3 runners/run_full_mpls.py

# Dùng static routes (nếu FRR chưa cài đặt)
sudo python3 runners/run_full_mpls.py --no-frr

# Auto test only
sudo python3 runners/run_full_mpls.py --test
```

**Quy trình bên trong `run_full_mpls.py`:**

1. Build full topology (tất cả nodes)
2. Apply IP config từ YAML (backbone + 3 branches)
3. Deploy FRR → P01-P04 (OSPF + LDP)
4. Deploy FRR → PE01-PE03 (OSPF + LDP + BGP)
5. **ISP push CE config** → CE01, CE02, CE03 (OSPF + static)
6. Setup VPLS bridge (GRE tunnel + Linux bridge)
7. Chờ OSPF/LDP converge (~30s)
8. Verify: OSPF neighbors, LDP sessions, BGP sessions
9. **Test Phase 1:** Backbone connectivity
10. **Test Phase 2:** Inter-branch ping qua VPLS

---

### Đo Lường Hiệu Năng

```bash
# Đo tất cả (intra + inter + stress)
sudo python3 tools/measure_performance.py --mode all --duration 10

# Chỉ đo inter-branch (qua MPLS backbone)
sudo python3 tools/measure_performance.py --mode inter

# Stress test (high load, 4 luồng song song)
sudo python3 tools/measure_performance.py --mode stress

# Tạo báo cáo HTML + biểu đồ
python3 tools/generate_report.py
```

---

### Mininet CLI (Interactive)

```bash
# Chạy từng branch
sudo python3 runners/run_branch1.py    # Mở CLI sau khi test

# Full topology
sudo python3 runners/run_full_mpls.py  # Mở CLI sau khi test
```

Các lệnh hữu ích trong CLI:
```
mininet> pingall                        # Ping tất cả cặp
mininet> pc01 ping 10.2.10.11          # Ping từ B1 đến B2 (lab01)
mininet> pe01 vtysh -c "show ip ospf neighbor"
mininet> p01  vtysh -c "show mpls ldp neighbor"
mininet> pe01 vtysh -c "show bgp l2vpn evpn summary"
mininet> pc01 traceroute 10.3.10.11    # Trace path B1 -> B3
mininet> nodes                          # Liệt kê tất cả nodes
mininet> dump                           # Thông tin chi tiết
```

---

## 📋 IP Address Plan

| Vùng | Subnet | Ghi Chú |
|------|--------|---------|
| Loopbacks P/PE | `10.0.0.1–13/32` | Router-ID, LDP transport |
| P-P links | `10.0.10–14.x/30` | Backbone core mesh |
| PE-P links | `10.0.20–25.x/30` | Dual-homed edge links |
| WAN PE-CE | `10.100.1–3.x/30` | ISP handoff |
| Branch 1 LAN | `10.1.0.0/24` | PC01–PC04, GW=CE01 |
| Branch 2 LAB | `10.2.10.0/24` | VLAN 10, GW=CE02 |
| Branch 2 ADMIN | `10.2.20.0/24` | VLAN 20, GW=CE02 |
| Branch 2 GUEST | `10.2.30.0/24` | VLAN 30, GW=CE02 |
| Branch 3 DC | `10.3.0.0/16` | Supernet, GW=CE03 (10.3.0.1) |

---

## 🔧 Chỉnh Sửa Cấu Hình

Tất cả cấu hình nằm trong `configs/` — **không cần sửa topology files**.

| Muốn thay đổi | Sửa file |
|---------------|----------|
| IP địa chỉ Branch 1 | `configs/branch1/ip_plan.yaml` |
| VLAN plan Branch 2 | `configs/branch2/ip_plan.yaml` |
| OSPF/static trên CE01 | `configs/branch1/ce01.conf` |
| OSPF + LDP trên P02 | `configs/backbone/frr/p02.conf` |
| VPLS pseudowire config | `configs/backbone/vpls_policy.yaml` |
| BGP EVPN trên PE01 | `configs/backbone/frr/pe01.conf` |

---

## 📊 Metrics Đo Lường

| Chỉ Số | Công Cụ | Mô Tả |
|--------|---------|-------|
| Throughput | iperf3 TCP/UDP | Băng thông (Mbps) |
| Delay (RTT) | ping | Độ trễ khứ hồi (ms) |
| Packet Loss | ping + iperf3 | Tỷ lệ mất gói (%) |
| Jitter | iperf3 UDP | Biến thiên độ trễ (ms) |
| Hop Count | traceroute | Số bước qua backbone |

---

## ❗ Troubleshooting

**MPLS kernel module chưa load:**
```bash
sudo modprobe mpls_router
sudo modprobe mpls_gso
sudo sysctl -w net.mpls.platform_labels=1048575
```

**Mininet còn dữ liệu cũ:**
```bash
sudo mn -c
```

**iperf3 server bận:**
```bash
sudo pkill -f iperf3
```

**FRR chưa cài:**
```bash
sudo apt install -y frr frr-pythontools
# Bật các daemons cần thiết trong /etc/frr/daemons
```

**Inter-branch ping fail (static routes mode):**
```bash
# Kiểm tra routing table trên PE
pe01 ip route
pe01 ip -M route    # MPLS labels
p02  ip route       # P-router forwarding
```

---

## 📦 Requirements

| Package | Phiên bản | Mục đích |
|---------|-----------|---------|
| Python | ≥ 3.8 | Runtime |
| Mininet | ≥ 2.3.0 | Network emulation |
| FRRouting | ≥ 8.x | OSPF, LDP, BGP daemons |
| PyYAML | ≥ 5.x | Đọc file config YAML |
| iperf3 | ≥ 3.x | Đo throughput |
| matplotlib | ≥ 3.x | Vẽ biểu đồ (optional) |

---

*Đại học Tôn Đức Thắng — Khoa Mạng Máy Tính và Truyền Thông Dữ Liệu*
