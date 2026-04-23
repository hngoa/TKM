# Mô phỏng Mạng MAN MPLS với Mininet + FRR

> **Môn học:** Thiết kế Mạng  
> **Công nghệ:** Mininet · FRR (Free Range Routing) · OSPF · MPLS/LDP · BGP L2VPN EVPN · VPLS

---

## Tổng quan kiến trúc

Bài thực hành xây dựng mô phỏng mạng **Metro Area Network (MAN)** theo mô hình **ISP MPLS backbone** kết nối 3 chi nhánh doanh nghiệp, sử dụng công nghệ VPLS (Virtual Private LAN Service) để tạo kết nối L2 trong suốt qua hạ tầng IP/MPLS của ISP.

```
┌─────────────────────────────────────────────────────┐
│              ISP MPLS Backbone (AS 65000)            │
│                                                      │
│  PE01 ── P01 ── P02 ── PE02                         │
│   |  \    |  \   |      |                           │
│   |   P03─────── P04  PE03                          │
│   |        \         /                               │
│   └──── P02 ─────────┘                              │
└──────────────────────────────────────────────────────┘
     │              │              │
   CE01           CE02           CE03
     │              │              │
  Branch 1       Branch 2       Branch 3
 Flat Network   Three-Tier    Spine-Leaf DC
```

### Phân loại thiết bị

| Ký hiệu | Tên đầy đủ | Số lượng | Vai trò |
|---------|-----------|---------|--------|
| **P** | Provider (Core Router) | 4 (P01–P04) | Label switching thuần túy, không biết customer |
| **PE** | Provider Edge Router | 3 (PE01–PE03) | Điểm biên ISP, kết nối CE, xử lý VPLS |
| **CE** | Customer Edge Router | 3 (CE01–CE03) | Router biên của khách hàng |

---

## Phần 1 — ISP MPLS Backbone

### 1.1 Địa chỉ IP Backbone

Backbone sử dụng không gian địa chỉ riêng, tách biệt hoàn toàn với mạng khách hàng:

| Loại | Dải địa chỉ | Mục đích |
|------|------------|---------|
| Loopback P | `10.0.0.1–4/32` | Router-ID, LDP transport |
| Loopback PE | `10.0.0.11–13/32` | Router-ID, BGP next-hop |
| P–P links | `10.0.10–14.x/30` | Core mesh links |
| PE–P links | `10.0.20–25.x/30` | Dual-homed uplinks |
| PE–CE WAN | `10.100.1–3.x/30` | Handoff link ISP→Customer |

### 1.2 OSPF (Open Shortest Path First) — IGP Backbone

**Mục đích:** Phân phối reachability đến tất cả loopback addresses trong backbone, đây là tiền đề để LDP và BGP hoạt động.

**Cấu hình trên P routers:**
```
router ospf
  ospf router-id 10.0.0.1          ← dùng loopback làm router-id
  network 10.0.0.1/32 area 0       ← quảng bá loopback
  network 10.0.10.0/30 area 0      ← quảng bá P-P links
  network 10.0.20.0/30 area 0      ← quảng bá PE-P links

interface p01-eth0
  ip ospf area 0
  ip ospf network point-to-point   ← tắt DR/BDR election (point-to-point)
  ip ospf hello-interval 1         ← hello nhanh 1s
  ip ospf dead-interval 4          ← dead 4s → phát hiện lỗi nhanh
```

**Lý do dùng `point-to-point`:** Các link P-P và PE-P là kết nối 1-1, không cần bầu DR/BDR, giảm thời gian hội tụ.

**P router KHÔNG quảng bá customer routes** vào OSPF backbone → đảm bảo khả năng mở rộng (scalability), P router không cần lưu routing table của hàng nghìn customer.

### 1.3 MPLS/LDP (Label Distribution Protocol)

**Mục đích:** Sau khi OSPF phân phối routes đến loopbacks, LDP tự động gán và phân phối MPLS labels cho từng FEC (Forwarding Equivalence Class). Cho phép P router forward gói dựa vào **label** thay vì IP lookup.

**Luồng xử lý gói tin MPLS:**

```
CE01 → PE01: gói IP bình thường (10.1.0.11 → 10.2.10.11)
PE01 → P01:  PUSH label {32 (PE02 FEC)} → gói có MPLS header
P01  → P02:  SWAP label {32 → 28}       → P không xem IP, chỉ swap label
P02  → PE02: POP label (PHP)             → trả lại gói IP thuần
PE02 → CE02: forward IP đến CE02
```

**Cấu hình LDP:**
```
mpls ldp
  router-id 10.0.0.1                      ← dùng loopback
  address-family ipv4
    discovery transport-address 10.0.0.1  ← LDP hello qua loopback
    interface p01-eth0                    ← bật LDP trên P-P links
    interface p01-pe01                    ← bật LDP trên PE-P links
```

**LDP Transport Address = Loopback:** Đảm bảo LDP session không bị drop khi một interface vật lý bị down (dual-homed PE vẫn có đường khác).

**PE router:** LDP bật trên backbone interfaces (pe01-p01, pe01-p02), **không** bật trên AC interface (pe01-ce01) vì CE không chạy MPLS.

**MPLS enable trên interfaces:**
```
interface p01-eth0
  mpls enable    ← bật MPLS label switching trên interface này
```

### 1.4 BGP L2VPN EVPN — VPLS Signaling

**Mục đích:** Trao đổi thông tin VPLS (MAC addresses, pseudowire endpoints) giữa các PE routers để thiết lập VPLS service tự động.

**iBGP full-mesh giữa PE01–PE02–PE03 (AS 65000):**
```
router bgp 65000
  bgp router-id 10.0.0.11
  no bgp default ipv4-unicast          ← chỉ dùng L2VPN, không IPv4 unicast

  neighbor 10.0.0.12 remote-as 65000  ← iBGP đến PE02 (dùng loopback)
  neighbor 10.0.0.12 update-source lo ← source từ loopback (ổn định)
  neighbor 10.0.0.12 next-hop-self

  address-family l2vpn evpn
    neighbor 10.0.0.12 activate
    advertise-all-vni                  ← quảng bá VNI (VPLS instances)
```

**Tại sao dùng loopback cho BGP next-hop?** PE loopbacks được OSPF quảng bá, đảm bảo BGP session ổn định dù link vật lý nào bị down.

### 1.5 VPLS (Virtual Private LAN Service)

**Mục đích:** Tạo L2 domain ảo kết nối 3 CE như thể chúng cùng một switch LAN vật lý, dù thực tế đi qua MPLS backbone.

**Mô hình Full-Mesh Pseudowire:**
```
PE01 ←── PW id=100 ──→ PE02
PE01 ←── PW id=101 ──→ PE03
PE02 ←── PW id=102 ──→ PE03
```

**Cấu hình VPLS trên PE01:**
```
l2vpn BRANCH-VPLS vpls
  bridge-group vpls-br
  member pseudowire pe01-pw-pe02
    neighbor 10.0.0.12 pw-id 100     ← PW đến PE02, dùng loopback làm endpoint
  member pseudowire pe01-pw-pe03
    neighbor 10.0.0.13 pw-id 101
  member interface pe01-ce01         ← Attachment Circuit (cổng kết nối CE01)
```

**Attachment Circuit (AC):** Interface `pe01-ce01` là điểm kết nối vật lý giữa ISP và khách hàng. Traffic từ CE01 vào AC sẽ được đóng gói vào MPLS pseudowire và chuyển đến PE đích.

**Fallback GRE Bridge:** Nếu FRR version không hỗ trợ VPLS native, runner script tự động tạo GRE tunnel + Linux bridge để mô phỏng chức năng tương đương.

### 1.6 Dual-Homed PE — High Availability

PE routers kết nối **2 uplinks** vào backbone để đảm bảo không có single point of failure:

| PE | Uplink 1 | Uplink 2 |
|----|----------|----------|
| PE01 | P01 (10.0.20.x) | P02 (10.0.21.x) |
| PE02 | P02 (10.0.22.x) | P03 (10.0.23.x) |
| PE03 | P03 (10.0.24.x) | P04 (10.0.25.x) |

OSPF sẽ tự động chọn đường tốt nhất (theo cost) và failover khi một link bị down.

---

## Phần 2 — Chi nhánh 1: Flat Network (Mạng Phẳng)

### Topology

```
CE01 (10.1.0.1/24)
  └── SW01 (L2 Access)
        ├── PC01 (10.1.0.11)
        ├── PC02 (10.1.0.12)
        └── SW02 (L2 Daisy-chain)
              ├── PC03 (10.1.0.13)
              └── PC04 (10.1.0.14)
```

### Kiến thức cấu hình

**Mô hình Flat Network** là dạng đơn giản nhất: toàn bộ hosts nằm trong **một broadcast domain duy nhất** (`10.1.0.0/24`), không có VLAN phân đoạn.

| Thành phần | Cấu hình | Lý do |
|-----------|---------|-------|
| Switches SW01, SW02 | `mode: standalone` (không controller) | Chỉ cần L2 forwarding, không cần SDN |
| CE01 LAN interface | `10.1.0.1/24` | Default gateway cho tất cả PC |
| CE01 WAN interface | `10.100.1.2/30` | Kết nối lên ISP PE01 |
| Default route CE01 | `0.0.0.0/0 via 10.100.1.1` | PE01 là next-hop mặc định ra Internet/WAN |
| PC hosts | Gateway `10.1.0.1` | CE01 là router duy nhất trong chi nhánh |

**Daisy-chain switches:** SW02 kết nối vào SW01 (không phải trực tiếp vào CE01) để mô phỏng việc mở rộng coverage mà không cần thêm cổng trên CE. Lưu ý: cấu trúc này tạo thêm 1 hop L2, cần chú ý **STP convergence** khi có redundant links.

**CE01 chạy OSPF** phía WAN (interface ce01-pe01) để quảng bá subnet `10.1.0.0/24` về phía ISP. CE01 **không** cần OSPF phía LAN (hosts dùng static default gateway).

---

## Phần 3 — Chi nhánh 2: Three-Tier Network (Mạng 3 Lớp)

### Topology

```
CE02 (Inter-VLAN Router)
  ├── ce02-c01 (10.2.10.1/24) → CORE01 → DIST01 → ACCESS01 → LAB01, LAB02
  ├── ce02-c02 (10.2.20.1/24) → CORE02 → DIST01 → ACCESS02 → ADMIN01, ADMIN02
  └── ce02-c03 (10.2.30.1/24) → DIST02  → ACCESS03 → GUEST01, GUEST02
```

### VLAN Plan

| VLAN ID | Tên | Subnet | Gateway | Mục đích |
|---------|-----|--------|---------|---------|
| 10 | LAB | 10.2.10.0/24 | 10.2.10.1 | Phòng thực hành |
| 20 | ADMIN | 10.2.20.0/24 | 10.2.20.1 | Phòng quản trị |
| 30 | GUEST | 10.2.30.0/24 | 10.2.30.1 | Mạng khách |

### Kiến thức cấu hình

**Mô hình Three-Tier (Core/Distribution/Access)** là kiến trúc chuẩn cho campus network quy mô vừa, phân tầng rõ ràng để dễ quản lý và mở rộng.

| Tầng | Thiết bị | Chức năng |
|------|---------|---------|
| **Core** | CORE01, CORE02 | Uplink tốc độ cao đến CE02, cross-connect redundancy |
| **Distribution** | DIST01, DIST02 | Kết nối Core với Access, policy enforcement |
| **Access** | ACCESS01–03 | Kết nối trực tiếp đến end-devices |

**Inter-VLAN Routing qua CE02:**

CE02 đóng vai trò **router chính** cho toàn bộ chi nhánh. Mỗi VLAN có một interface riêng trên CE02:

```yaml
interfaces:
  - name: ce02-c01
    ip: 10.2.10.1/24     # gateway VLAN 10 (LAB)
  - name: ce02-c02
    ip: 10.2.20.1/24     # gateway VLAN 20 (ADMIN)
  - name: ce02-c03
    ip: 10.2.30.1/24     # gateway VLAN 30 (GUEST)
```

**Lý do thiết kế này:** Thay vì dùng trunk port + sub-interfaces (router-on-a-stick), mỗi VLAN có interface vật lý riêng đến CE02. Đơn giản hơn khi cấu hình và dễ kiểm soát bandwidth per-VLAN.

**Traffic path inter-VLAN:**
```
LAB01 → ACCESS01 → DIST01 → CORE01 → CE02 → CORE02 → DIST01 → ACCESS02 → ADMIN01
                                      ↑
                              IP routing tại CE02
```

**Default route tất cả hosts:** `0.0.0.0/0 via 10.100.2.1` (PE02 WAN gateway), để traffic liên chi nhánh đi qua ISP MPLS backbone.

---

## Phần 4 — Chi nhánh 3: Spine-Leaf Data Center

### Topology

```
CE03 (Border Router)
  └── LEAF01 (Border Leaf)
        ├── SPINE01 ──┬── LEAF02 → WEB01, WEB02  (10.3.10.x)
        │             ├── LEAF03 → DNS01, DNS02  (10.3.20.x)
        │             └── LEAF04 → DB01,  DB02   (10.3.30.x)
        └── SPINE02 ──┴── (same as above - ECMP)
```

### Kiến thức cấu hình

**Spine-Leaf Architecture** là kiến trúc tiêu chuẩn cho Data Center hiện đại, thiết kế để đạt **low latency** và **ECMP (Equal-Cost Multi-Path)** tự nhiên.

**Nguyên tắc thiết kế:**
- **Leaf** kết nối trực tiếp với end-device (servers)
- **Spine** kết nối với tất cả Leaf (full-mesh giữa Leaf và Spine)
- **Không có inter-spine links** và **không có inter-leaf links** — traffic luôn đi qua Spine
- Mọi cặp Leaf đều cách nhau **đúng 2 hops** qua Spine → latency đồng nhất, dễ dự đoán

**ECMP — Equal Cost Multi-Path:**

Mỗi Leaf có 2 uplinks lên 2 Spine → hệ thống có thể phân tải (load balance) traffic theo nhiều đường có cost bằng nhau:

```
WEB01 → LEAF02 → SPINE01 → LEAF03 → DNS01  (path 1)
WEB01 → LEAF02 → SPINE02 → LEAF03 → DNS01  (path 2, equal cost)
```

**Subnet design `/16` supernet:**

CE03 dùng `10.3.0.0/16` làm supernet thay vì advertise từng `/24` riêng lẻ:

```yaml
ce_router:
  interfaces:
    - name: ce03-leaf01
      ip: 10.3.0.1/16    # một route bao toàn bộ server farm
```

**Lý do:** Giảm số lượng routes cần quảng bá lên ISP backbone từ 3 routes (`10.3.10.0/24`, `10.3.20.0/24`, `10.3.30.0/24`) xuống còn 1 route (`10.3.0.0/16`) — route summarization.

**Server clusters theo rack:**

| Cluster | Subnet | Leaf | Servers |
|---------|--------|------|---------|
| WEB | 10.3.10.0/24 | LEAF02 | web01, web02 |
| DNS | 10.3.20.0/24 | LEAF03 | dns01, dns02 |
| DB | 10.3.30.0/24 | LEAF04 | db01, db02 |

---

## Phần 5 — Kiến trúc phần mềm (Mininet Simulation)

### Config-Driven Architecture

Toàn bộ cấu hình IP, routing, và topology được định nghĩa trong **YAML files**, code Python chỉ đọc và apply — không hard-code IP hay link params trong code.

```
configs/                    ← Nguồn dữ liệu duy nhất (YAML)
  backbone/
    ip_plan.yaml            ← IP plan P/PE, static routes backbone
    vpls_policy.yaml        ← VPLS pseudowire, GRE tunnel fallback
    frr/
      p01.conf … pe03.conf  ← FRR config OSPF+LDP+BGP từng router
  branch1/
    ip_plan.yaml            ← IP CE01, switches, hosts, test matrix
    ce01.conf               ← FRR OSPF config cho CE01
  branch2/, branch3/        ← Tương tự

topologies/                 ← Builder functions (skeleton topology)
  backbone.py               ← Build P/PE nodes + links
  branch1_flat.py           ← Build branch 1 (switches + hosts)
  branch2_3tier.py          ← Build branch 2
  branch3_spineleaf.py      ← Build branch 3
  full_topology.py          ← Compose tất cả

tools/                      ← Business logic
  config_loader.py          ← Đọc YAML → apply IP vào Mininet nodes
  frr_manager.py            ← Deploy FRR per-node (OSPF/LDP/BGP)
  connectivity_test.py      ← Ping test suite + báo cáo
  node_types.py             ← MPLSRouter class (Linux IP forwarding)

runners/                    ← Entry points
  run_backbone.py           ← Phase 0: Test ISP backbone
  run_branch1/2/3.py        ← Phase 1: Test từng chi nhánh
  run_full_mpls.py          ← Phase 2: Full MPLS MAN
```

### FRR Per-Node Isolation

**Vấn đề quan trọng khi chạy FRR trong Mininet:** Tất cả Mininet nodes chia sẻ cùng filesystem nhưng có network namespace riêng. Nếu dùng đường dẫn mặc định `/etc/frr/frr.conf` và `/var/run/frr/zserv.api`, các daemons sẽ conflict.

**Giải pháp:** Mỗi node dùng paths riêng biệt:

```python
conf_file = f'/tmp/frr_{node_name}.conf'          # config riêng
sock      = f'/var/run/frr/{node_name}/zserv.api'  # socket riêng
run_dir   = f'/var/run/frr/{node_name}/'           # pid files riêng

node.cmd(f'/usr/lib/frr/zebra -d -f {conf_file} -z {sock} ...')
node.cmd(f'/usr/lib/frr/ospfd -d -f {conf_file} -z {sock} ...')
node.cmd(f'/usr/lib/frr/ldpd  -d -f {conf_file} -z {sock} ...')
node.cmd(f'/usr/lib/frr/bgpd  -d -f {conf_file} -z {sock} ...')
```

---

## Hướng dẫn chạy

### Yêu cầu

```bash
sudo apt install -y mininet frr frr-pythontools python3-yaml
```

### Quy trình kiểm tra từng bước

```bash
# Bước 1: Kiểm tra ISP backbone (OSPF + LDP + BGP)
sudo python3 runners/run_backbone.py --test

# Bước 2: Kiểm tra từng chi nhánh độc lập
sudo python3 runners/run_branch1.py --test
sudo python3 runners/run_branch2.py --test
sudo python3 runners/run_branch3.py --test

# Bước 3: Chạy full MPLS MAN (kết hợp tất cả)
sudo python3 runners/run_full_mpls.py
```

### Debug trong Mininet CLI

```bash
# Kiểm tra OSPF neighbors
pe01 vtysh -c "show ip ospf neighbor"

# Kiểm tra LDP label bindings
p01 vtysh -c "show mpls ldp neighbor"
p01 vtysh -c "show mpls ldp binding"

# Kiểm tra MPLS label table (data plane)
p01 ip -M route

# Kiểm tra BGP EVPN (VPLS signaling)
pe01 vtysh -c "show bgp l2vpn evpn summary"

# Test inter-branch connectivity
pc01 ping 10.2.10.11    # Branch 1 → Branch 2
lab01 ping 10.3.10.11   # Branch 2 → Branch 3
```

---

## Kiến thức tổng kết

| Công nghệ | Áp dụng ở đâu | Mục đích |
|-----------|--------------|---------|
| **OSPF Area 0** | Toàn bộ backbone P+PE | Phân phối loopback reachability, tiền đề cho LDP |
| **MPLS/LDP** | P-P và PE-P links | Label distribution, cho phép P router chỉ swap label |
| **BGP L2VPN EVPN** | PE01 ↔ PE02 ↔ PE03 | VPLS control plane, trao đổi MAC/VNI thông tin |
| **VPLS Full-Mesh** | PE01/PE02/PE03 | Tạo L2 domain ảo liên chi nhánh |
| **Dual-homed PE** | PE01–PE02–PE03 | High availability, không single point of failure |
| **Flat Network** | Branch 1 | Cấu hình đơn giản, single broadcast domain |
| **Three-Tier** | Branch 2 | Campus network, inter-VLAN routing qua CE |
| **Spine-Leaf** | Branch 3 | Data center, ECMP, low and uniform latency |
| **Route Summarization** | CE03 → ISP | Giảm số routes quảng bá (10.3.0.0/16 thay vì 3×/24) |
| **Config-Driven (YAML)** | Toàn bộ project | Tách biệt topology (code) và config (data) |
