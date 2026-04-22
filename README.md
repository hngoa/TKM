# Metro Ethernet MPLS — Mô Phỏng Đa Chi Nhánh

> **Đề tài:** Thiết kế và triển khai mạng Metro Ethernet sử dụng MPLS/VPLS cho kết nối đa chi nhánh doanh nghiệp  
> **Nền tảng:** Mininet + FRRouting (FRR) trên Linux  
> **OS:** Ubuntu 20.04 / 22.04 LTS

---

## 📐 Kiến Trúc Tổng Thể

Project được tổ chức theo hai nguyên tắc kết hợp:

- **Config-Driven Architecture** — tách biệt hoàn toàn giữa cấu trúc (topology) và nội dung cấu hình (YAML)
- **Builder Function Pattern** — mỗi thành phần con (backbone, branch) là một module độc lập, có thể tái sử dụng và compose lại thành mô hình lớn

```
YAML configs (nguồn duy nhất)
       │ loader.get_switches/hosts/links()
       ▼
topology builders (cấu trúc, không hardcode IP)
  backbone.py / branch1_flat.py / branch2_3tier.py / branch3_spineleaf.py
       │ compose vào cùng 1 net object
       ▼
full_topology.py → build_full_topology()
       │ net.start() → loader.apply_all()
       ▼
runner scripts → Mininet Simulation
```

---

## 📁 Cấu Trúc Project

```
Src_Mininet/
├── topologies/                      ← Topology skeleton (khung cấu trúc)
│   ├── backbone.py                  # MPLS Backbone builders + BackboneTopo class
│   ├── branch1_flat.py              # Chi nhánh 1: Flat Network builders
│   ├── branch2_3tier.py             # Chi nhánh 2: Three-Tier builders
│   ├── branch3_spineleaf.py         # Chi nhánh 3: Spine-Leaf DC builders
│   └── full_topology.py             # Compose tất cả builders → full topology
│
├── configs/                         ← Nội dung cấu hình (YAML + FRR conf)
│   ├── branch1/
│   │   ├── ip_plan.yaml             # IP plan: CE01, SW01/02, PC01-04, links, tests
│   │   └── ce01.conf                # FRR config CE01 (do ISP cung cấp)
│   ├── branch2/
│   │   ├── ip_plan.yaml             # IP plan: CE02, 3-tier switches, LAB/ADMIN/GUEST
│   │   └── ce02.conf                # FRR config CE02
│   ├── branch3/
│   │   ├── ip_plan.yaml             # IP plan: CE03, Spine/Leaf, WEB/DNS/DB (/16)
│   │   └── ce03.conf                # FRR config CE03
│   └── backbone/
│       ├── ip_plan.yaml             # IP plan: P01-P04, PE01-PE03, WAN links
│       ├── vpls_policy.yaml         # VPLS pseudowire config (BGP EVPN)
│       └── frr/
│           ├── p01.conf / p02.conf / p03.conf / p04.conf   # OSPF + LDP
│           ├── pe01.conf / pe02.conf / pe03.conf            # OSPF + LDP + BGP + VPLS
│
├── runners/                         ← Script điều phối từng kịch bản
│   ├── run_backbone.py              # Phase 0: Kiểm tra ISP Backbone
│   ├── run_branch1.py               # Phase 1: Test nội bộ Branch 1 (isolated)
│   ├── run_branch2.py               # Phase 1: Test nội bộ Branch 2
│   ├── run_branch3.py               # Phase 1: Test nội bộ Branch 3
│   └── run_full_mpls.py             # Phase 2: Full MPLS + VPLS inter-branch
│
├── tools/
│   ├── node_types.py                # LinuxRouter, MPLSRouter (dùng chung)
│   ├── config_loader.py             # ConfigLoader + BackboneConfigLoader (YAML → Mininet)
│   ├── frr_manager.py               # Deploy FRR daemons + ISP push CE config
│   ├── connectivity_test.py         # Auto ping test + báo cáo
│   ├── measure_performance.py       # Đo throughput/delay/jitter (iperf3)
│   ├── generate_report.py           # Tạo biểu đồ + báo cáo HTML
│   └── quick_test.py                # Kiểm tra kết nối nhanh
│
├── result/                          # Kết quả test (tự động tạo)
├── install.sh                       # Script cài đặt dependencies
└── README.md
```

---

## 🏗 Kiến Trúc Hệ Thống Mạng

### MPLS MAN Backbone — Partial Mesh + Dual-homed PE

```
Chi nhánh 1 (Flat)        Chi nhánh 2 (3-Tier)      Chi nhánh 3 (Spine-Leaf DC)
  PC01-PC04                LAB / ADMIN / GUEST         WEB / DNS / DB servers
     │                            │                            │
    CE01                         CE02                         CE03
     │  10.100.1.0/30             │  10.100.2.0/30             │  10.100.3.0/30
    PE01 ──────── P01 ── P02 ── PE02                           │
     └──────────── P02 ── P03 ── PE02                          │
                         P03 ── P04 ── PE03 ────────────────────┘
                         P01 ── P03  (diagonal, 3ms)
                         P02 ── P04  (diagonal, 3ms)

P01-P04 : OSPF Area 0 + LDP (MPLS label switching only)
PE01-PE03: OSPF + LDP + iBGP full-mesh (VPLS signaling)
```

### Chi Nhánh 1 — Flat Network (10.1.0.0/24)

```
CE01 (GW: 10.1.0.1/24)
  └─ SW01 ──────────── SW02
       ├─ PC01 (10.1.0.11)   ├─ PC03 (10.1.0.13)
       └─ PC02 (10.1.0.12)   └─ PC04 (10.1.0.14)

Đặc điểm: Single broadcast domain, không VLAN, không STP loop
```

### Chi Nhánh 2 — Three-Tier Network (Inter-VLAN)

```
CE02 (Inter-VLAN Router — 3 LAN interfaces)
  ├─ ce02-c01 (10.2.10.1/24) → CORE01 → DIST01 → ACCESS01 → LAB01, LAB02
  ├─ ce02-c02 (10.2.20.1/24) → CORE02 → DIST01 → ACCESS02 → ADMIN01, ADMIN02
  └─ ce02-c03 (10.2.30.1/24) → DIST02  ────────→ ACCESS03 → GUEST01, GUEST02

CORE01 ↔ CORE02 (cross-connect, redundant mesh → RSTP)
CORE01 → DIST01, DIST02  |  CORE02 → DIST01, DIST02
```

### Chi Nhánh 3 — Spine-Leaf Data Center

```
CE03 (DC Border Router: 10.3.0.1/16 — supernet gateway)
  └─ LEAF01 (Border Leaf)
       ├─ SPINE01 ─┬─ LEAF02 → WEB01 (10.3.10.11/16), WEB02 (10.3.10.12/16)
       │            ├─ LEAF03 → DNS01 (10.3.20.11/16), DNS02 (10.3.20.12/16)
       │            └─ LEAF04 → DB01  (10.3.30.11/16), DB02  (10.3.30.12/16)
       └─ SPINE02 ─┴─ (ECMP fabric — 2 equal-cost paths mỗi leaf)

Ghi chú /16 mask: Tất cả servers dùng /16 → on-link reachable qua CE03
mà không cần inter-rack routes thêm.
```

---

## 🔄 Luồng Hoạt Động Của Code

### 1. Khởi tạo — Load YAML Config

```python
# Runner load YAML trước khi build topology
backbone_loader = BackboneConfigLoader('configs/backbone/ip_plan.yaml')
loader1 = ConfigLoader('configs/branch1/ip_plan.yaml')
```

`ConfigLoader` đọc YAML và cung cấp:
- `get_switches()` → danh sách switch {name, mode}
- `get_hosts()` → danh sách host {name, ip, gateway}
- `get_links()` → danh sách link {src, dst, src_intf, bw, delay}
- `get_ce_config()` → CE router {name, interfaces[], static_routes[]}

### 2. Build Topology — Builder Function Pattern

```python
# full_topology.py — compose các builder con
net = Mininet(controller=None, link=TCLink, switch=OVSSwitch)

build_backbone_nodes(net, MPLSRouter)          # P01-P04, PE01-PE03
# CE01/CE02/CE03 từ wan_links trong backbone YAML
build_branch1_nodes(net, MPLSRouter, loader1)  # CE01, SW01, SW02, PC01-04
build_branch2_nodes(net, MPLSRouter, loader2)  # CE02, Core/Dist/Access, hosts
build_branch3_nodes(net, MPLSRouter, loader3)  # CE03, Spine/Leaf, servers

build_backbone_links(net, backbone_loader)     # P-P + PE-P links từ YAML
build_wan_links(net, backbone_loader)          # PE01-CE01, PE02-CE02, PE03-CE03
build_branch1_links(net, loader1)              # CE01-SW01, SW01-SW02, ...
build_branch2_links(net, loader2)              # CE02-Core, Core-Dist, ...
build_branch3_links(net, loader3)              # CE03-LEAF01, Spine-Leaf fabric
```

**Nguyên tắc quan trọng:**
- Topology builders **KHÔNG có hardcoded IP**
- Loader là **bắt buộc** (raise `ValueError` nếu `None`)
- Mỗi builder bỏ qua WAN links (`if dst.startswith('pe'): continue`)

### 3. Khởi động — net.start() + Apply Config từ YAML

```python
net.start()

# Backbone: loopbacks, P/PE interfaces, CE WAN side
backbone_loader.apply_all(net)

# Branch LAN: CE LAN interfaces + hosts IP + default routes
loader1.apply_all(net, mode='full')   # full = bao gồm WAN interface CE
loader2.apply_all(net, mode='full')
loader3.apply_all(net, mode='full')
```

`apply_all()` chạy các lệnh shell trên Mininet nodes:
```bash
ip addr add 10.1.0.1/24 dev ce01-sw01
ip addr add 10.1.0.11/24 dev pc01-eth0
ip route add default via 10.1.0.1
```

### 4. Deploy FRR (nếu có)

```python
frr_mgr = FRRManager(net)
frr_mgr.deploy_backbone()    # Copy frr/*.conf → P/PE nodes, khởi động daemons
frr_mgr.push_ce_configs()    # ISP copy ce*.conf → CE01/02/03
frr_mgr.setup_vpls_bridge()  # Tạo GRE tunnels + Linux bridge cho VPLS
frr_mgr.wait_convergence(30) # Chờ OSPF/LDP hội tụ
```

### 5. Test & Báo Cáo

```python
tester = ConnectivityTest(net)
report = tester.test_backbone_connectivity()  # P-P, PE-P, loopbacks
report = tester.test_inter_branch(vpls_config) # PC01 ping LAB01, WEB01 ping DB01
tester.save_all_reports(reports, 'result/')
```

---

## 📋 IP Address Plan

| Vùng | Subnet | Chi tiết |
|------|--------|---------|
| P-Router loopbacks | `10.0.0.1–4/32` | P01=.1, P02=.2, P03=.3, P04=.4 |
| PE-Router loopbacks | `10.0.0.11–13/32` | PE01=.11, PE02=.12, PE03=.13 |
| CE loopbacks | `10.0.0.21–23/32` | CE01=.21, CE02=.22, CE03=.23 |
| P-P links | `10.0.10–14.x/30` | Core mesh (2–3ms delay) |
| PE-P links | `10.0.20–25.x/30` | Dual-homed edge (1ms) |
| WAN PE-CE | `10.100.1–3.x/30` | ISP handoff (5ms) |
| Branch 1 LAN | `10.1.0.0/24` | PC01–04, GW=10.1.0.1 |
| Branch 2 LAB | `10.2.10.0/24` | VLAN 10, GW=10.2.10.1 |
| Branch 2 ADMIN | `10.2.20.0/24` | VLAN 20, GW=10.2.20.1 |
| Branch 2 GUEST | `10.2.30.0/24` | VLAN 30, GW=10.2.30.1 |
| Branch 3 DC | `10.3.0.0/16` | Supernet, GW=10.3.0.1 |

---

## 🚀 Hướng Dẫn Cài Đặt & Thực Thi

### Bước 1: Cài đặt dependencies

```bash
git clone https://github.com/hngoa/TKM.git
cd TKM
sudo bash install.sh
```

Script tự động cài đặt:
- Mininet (network emulator)
- FRRouting — FRR (OSPF, LDP, BGP daemons)
- iperf3 (đo hiệu năng)
- Python packages: PyYAML, matplotlib
- Kernel MPLS modules: `mpls_router`, `mpls_gso`, `mpls_iptunnel`

---

### Phase 0 — Kiểm Tra ISP Backbone (Bắt Buộc Trước)

Kiểm tra hạ tầng MPLS core hoạt động trước khi triển khai xuống chi nhánh.

```bash
# Đầy đủ: OSPF + LDP + BGP (khuyến nghị)
sudo python3 runners/run_backbone.py

# Chỉ IP layer (debug — không cần FRR)
sudo python3 runners/run_backbone.py --no-frr

# Auto test, không mở CLI
sudo python3 runners/run_backbone.py --test --no-frr
```

**Topology backbone (isolated — không có CE/branch):**
```
P01 ──2ms── P02 ──2ms── P03 ──2ms── P04
 └──3ms──── P03          └──3ms──── P02

PE01 (dual: P01+P02)  PE02 (dual: P02+P03)  PE03 (dual: P03+P04)
```

**Tests thực hiện:**

| Test | Nội dung | Pass khi |
|------|----------|---------|
| Test 1: P-P Links | Ping giữa P-P interfaces | 100% |
| Test 2: PE-P Links | Ping PE→P trên mọi uplinks | 100% |
| Test 3: Loopback (E2E) | PE01→PE02, PE01→PE03 loopback | OSPF đúng |
| Test 4: FRR Verify | OSPF Full, LDP Operational, BGP Established | Protocols up |

> ✅ Backbone OK → tiếp tục Phase 1  
> ❌ Backbone FAIL → dừng lại, debug IP/OSPF trước

---

### Phase 1 — Test Nội Bộ Từng Chi Nhánh (Isolated)

Chạy riêng từng branch, không có MPLS backbone, để xác nhận cấu hình LAN đúng.

```bash
# Chi nhánh 1: Flat Network
sudo python3 runners/run_branch1.py          # Interactive CLI
sudo python3 runners/run_branch1.py --test   # Auto test only

# Chi nhánh 2: Three-Tier + Inter-VLAN Routing
sudo python3 runners/run_branch2.py
sudo python3 runners/run_branch2.py --test

# Chi nhánh 3: Spine-Leaf Data Center
sudo python3 runners/run_branch3.py
sudo python3 runners/run_branch3.py --test
```

**Kết quả mong đợi:**

| Branch | Test | Điều kiện pass |
|--------|------|---------------|
| Branch 1 | PC01 ↔ PC04 | Cùng subnet /24 qua SW01-SW02 |
| Branch 1 | PC01 ping 10.1.0.1 | Gateway CE01 reachable |
| Branch 2 | LAB01 ↔ LAB02 | Intra-VLAN 10 |
| Branch 2 | LAB01 ping ADMIN01 | Inter-VLAN qua CE02 |
| Branch 3 | WEB01 ↔ DB01 | Cross-rack qua SPINE (2 hops) |
| Branch 3 | WEB01 ping 10.3.0.1 | Gateway CE03 reachable |

**Lưu ý STP/RSTP:**
- Branch 1: STP tắt (cây thẳng, không loop) → port up ngay
- Branch 2 & 3: RSTP bật (có redundant links) → hội tụ ~2–5 giây

---

### Phase 2 — Full MPLS Topology (Liên Chi Nhánh)

```bash
# Đầy đủ: FRR OSPF + LDP + BGP + VPLS
sudo python3 runners/run_full_mpls.py

# Bỏ qua FRR (IP đã cấu hình qua YAML, static routes từ ce*.conf)
sudo python3 runners/run_full_mpls.py --no-frr

# Auto test, không mở CLI, không lưu báo cáo
sudo python3 runners/run_full_mpls.py --test --no-report
```

**Quy trình bên trong `run_full_mpls.py`:**

```
1. Load YAML configs (backbone + branch1 + branch2 + branch3)
2. build_full_topology(backbone_loader, branch_loaders)
   └─ compose builders từ topologies/*.py
3. net.start()
4. backbone_loader.apply_all(net)     → IP backbone từ YAML
5. loader1/2/3.apply_all(net, 'full') → IP branch từ YAML
6. [FRR mode] frr_mgr.deploy_backbone()   → P/PE daemons
              frr_mgr.push_ce_configs()   → CE01/02/03 config
              frr_mgr.setup_vpls_bridge() → GRE + Linux bridge
              frr_mgr.wait_convergence(30s)
7. Test backbone connectivity
8. Test inter-branch qua VPLS
9. Lưu báo cáo vào result/
10. Mở Mininet CLI (nếu interactive)
```

**Kết quả mong đợi Phase 2:**

| Test | Source → Destination | Pass khi |
|------|---------------------|---------|
| Backbone E2E | PE01 → PE02 loopback | OSPF routes |
| MPLS label | P01 ip -M route | Labels > 0 |
| Inter-branch | PC01 (B1) → LAB01 (B2) | VPLS tunnel OK |
| Inter-branch | WEB01 (B3) → ADMIN01 (B2) | VPLS OK |
| Inter-branch | PC01 (B1) → DB01 (B3) | Full path |

---

### Đo Lường Hiệu Năng

```bash
# Đo tất cả (intra + inter + stress test)
sudo python3 tools/measure_performance.py --mode all --duration 10

# Chỉ đo liên chi nhánh (qua MPLS backbone)
sudo python3 tools/measure_performance.py --mode inter

# Stress test (4 luồng song song)
sudo python3 tools/measure_performance.py --mode stress

# Tạo báo cáo HTML + biểu đồ
python3 tools/generate_report.py
```

| Chỉ số | Công cụ | Mô tả |
|--------|---------|-------|
| Throughput | iperf3 TCP | Băng thông (Mbps) |
| Delay RTT | ping | Độ trễ khứ hồi (ms) |
| Packet Loss | ping + iperf3 | Tỷ lệ mất gói (%) |
| Jitter | iperf3 UDP | Biến thiên delay (ms) |
| Hop Count | traceroute | Số bước qua backbone |

---

### Lệnh Hữu Ích Trong Mininet CLI

```bash
mininet> pingall                              # Ping tất cả cặp
mininet> pc01 ping 10.2.10.11                # B1 → B2 (lab01)
mininet> pc01 ping 10.3.10.11                # B1 → B3 (web01)
mininet> web01 ping 10.2.20.11               # B3 → B2 (admin01)

# Debug routing
mininet> pe01 ip route
mininet> p01  ip -M route                    # MPLS label table
mininet> ce01 ip route

# Debug FRR protocols
mininet> pe01 vtysh -c "show ip ospf neighbor"
mininet> p01  vtysh -c "show mpls ldp neighbor"
mininet> pe01 vtysh -c "show bgp l2vpn evpn summary"
mininet> pe01 vtysh -c "show mpls ldp binding"

# Traceroute liên chi nhánh
mininet> pc01 traceroute 10.3.10.11          # B1 → B3 (qua MPLS)

# Thông tin topology
mininet> nodes                               # Liệt kê tất cả nodes
mininet> dump                                # Chi tiết từng node
mininet> links                               # Tất cả links
```

---

## 🔧 Chỉnh Sửa Cấu Hình

Tất cả cấu hình nằm trong `configs/` — **không cần sửa topology files**.

| Muốn thay đổi | Sửa file |
|---------------|----------|
| IP địa chỉ Branch 1 | `configs/branch1/ip_plan.yaml` |
| Thêm host vào Branch 2 | `configs/branch2/ip_plan.yaml` (hosts + links) |
| OSPF/static routes trên CE01 | `configs/branch1/ce01.conf` |
| OSPF + LDP trên P02 | `configs/backbone/frr/p02.conf` |
| BGP EVPN trên PE01 | `configs/backbone/frr/pe01.conf` |
| VPLS pseudowire config | `configs/backbone/vpls_policy.yaml` |
| Thêm branch mới | Tạo YAML mới + viết builder function mới |

### Cấu trúc ip_plan.yaml (branch)

```yaml
branch: branch1
ce_router:
  name: ce01
  interfaces:
    - name: ce01-sw01   # interface name phải khớp với link trong mục links
      ip: 10.1.0.1/24
      mode: lan
    - name: ce01-pe01
      ip: 10.100.1.2/30
      mode: wan          # bỏ qua trong isolated mode
  static_routes:
    - prefix: 0.0.0.0/0
      via: 10.100.1.1

switches:
  - name: sw01
    mode: standalone

hosts:
  - name: pc01
    ip: 10.1.0.11/24
    gateway: 10.1.0.1

links:
  - src: ce01
    dst: sw01
    src_intf: ce01-sw01   # đặt tên interface rõ ràng
    bw: 100
    delay: 1ms
```

---

## ❗ Troubleshooting

**MPLS kernel module chưa load:**
```bash
sudo modprobe mpls_router
sudo modprobe mpls_gso
sudo sysctl -w net.mpls.platform_labels=1048575
```

**Mininet còn dữ liệu cũ (cần cleanup):**
```bash
sudo mn -c
```

**KeyError node khi apply config:**
```
Nguyên nhân: Node trong YAML không tồn tại trong topology
Kiểm tra: Tên CE trong wan_links YAML phải khớp với tên trong branch ip_plan.yaml
```

**Inter-branch ping fail:**
```bash
# Kiểm tra routing trên từng tầng
mininet> ce01 ip route            # CE biết route về B2/B3 chưa?
mininet> pe01 ip route            # PE có route về 10.2.x và 10.3.x?
mininet> p02  ip route            # P-router forward đúng chưa?
mininet> p01  ip -M route         # MPLS labels đã có chưa?
```

**FRR daemon không khởi động:**
```bash
sudo systemctl status frr
# Kiểm tra syntax config
sudo vtysh -f configs/backbone/frr/p01.conf --dry-run
```

**RSTP chưa hội tụ (Branch 2/3 mất kết nối sau vài giây):**
```bash
# Tăng thời gian chờ trong runner (mặc định 5s)
time.sleep(8)  # trong run_branch2.py / run_branch3.py
```

---

## 📦 Requirements

| Package | Phiên bản | Mục đích |
|---------|-----------|---------|
| Python | ≥ 3.8 | Runtime |
| Mininet | ≥ 2.3.0 | Network emulation |
| FRRouting (FRR) | ≥ 8.x | OSPF, LDP, BGP daemons |
| PyYAML | ≥ 5.x | Đọc file config YAML |
| iperf3 | ≥ 3.x | Đo throughput |
| matplotlib | ≥ 3.x | Vẽ biểu đồ (optional) |
| Linux kernel | ≥ 4.15 | MPLS module support |

---

## 🗂 Quy Trình Kiểm Tra Đề Xuất

```
[Bước 0] Cài đặt
  sudo bash install.sh

[Phase 0] Kiểm tra ISP Backbone
  sudo python3 runners/run_backbone.py --test --no-frr    ← IP layer trước
  sudo python3 runners/run_backbone.py --test             ← FRR OSPF+LDP+BGP

[Phase 1] Kiểm tra nội bộ từng chi nhánh
  sudo python3 runners/run_branch1.py --test
  sudo python3 runners/run_branch2.py --test
  sudo python3 runners/run_branch3.py --test

[Phase 2] Kiểm tra liên chi nhánh qua MPLS VPLS
  sudo python3 runners/run_full_mpls.py --test --no-frr   ← IP layer
  sudo python3 runners/run_full_mpls.py                   ← Full FRR + CLI

[Đo hiệu năng]
  sudo python3 tools/measure_performance.py --mode all
  python3 tools/generate_report.py
```

---

*Đại học Tôn Đức Thắng — Khoa Mạng Máy Tính và Truyền Thông Dữ Liệu*
