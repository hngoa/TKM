# Mô phỏng Mạng MAN MPLS với Mininet

> **Môn học:** Thiết kế Mạng  
> **Công nghệ:** Mininet · Static MPLS · GRETAP VPLS · Linux Routing

---

## Tổng quan kiến trúc

Bài thực hành xây dựng mô phỏng mạng **Metro Area Network (MAN)** theo mô hình **ISP MPLS backbone** kết nối 3 chi nhánh doanh nghiệp, sử dụng công nghệ VPLS (Virtual Private LAN Service) để tạo kết nối L2 trong suốt qua hạ tầng IP/MPLS của ISP.

```
┌─────────────────────────────────────────────────────┐
│              ISP MPLS Backbone                       │
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
| Loopback P | `10.0.0.1–4/32` | Router-ID, MPLS label endpoints |
| Loopback PE | `10.0.0.11–13/32` | MPLS label endpoints, VPLS tunnel source |
| P–P links | `10.0.10–14.x/30` | Core mesh links |
| PE–P links | `10.0.20–25.x/30` | Dual-homed uplinks |
| PE–CE WAN | `10.100.1–3.x/30` | Handoff link ISP→Customer |

### 1.2 Static Routes — IP Reachability (thay thế OSPF)

Mỗi router được cấu hình static routes đến tất cả loopback addresses trong backbone. Đây là tiền đề để MPLS labels và GRETAP VPLS hoạt động.

Ví dụ routes trên PE01:
```
ip route add 10.0.0.2/32 via 10.0.10.2    # → P02 qua P01
ip route add 10.0.0.12/32 via 10.0.21.2   # → PE02 qua P02
```

### 1.3 MPLS Label Switching (thay thế LDP)

Static MPLS labels được gán cho mỗi PE loopback, sử dụng label = 100 + last_octet:

| Destination | Label | Ý nghĩa |
|-------------|-------|---------|
| PE01 (10.0.0.11) | 111 | "Route đến PE01" |
| PE02 (10.0.0.12) | 112 | "Route đến PE02" |
| PE03 (10.0.0.13) | 113 | "Route đến PE03" |

**Luồng xử lý gói tin MPLS:**

```
CE01 → PE01: gói IP bình thường (10.1.0.11 → 10.2.10.11)
PE01 → P02:  PUSH label 112 → gói có MPLS header
P02  → PE02: PHP (pop label) → trả lại gói IP thuần
PE02 → CE02: forward IP đến CE02
```

3 loại operations trên mỗi router:
- **PUSH** (PE ingress): `ip route replace <dst>/32 encap mpls <label> via <next_hop>`
- **SWAP** (P transit): `ip -M route add <label> as <label> via inet <next_hop>`
- **PHP** (Penultimate Hop Pop): `ip -M route add <label> via inet <next_hop>`

### 1.4 VPLS — GRETAP Pseudowire Emulation

VPLS kết nối 3 CE như thể chúng cùng một switch LAN, dù thực tế đi qua MPLS backbone.

**Triển khai bằng GRETAP tunnels + Linux bridge:**

```
PE01: bridge vpls-br = [pe01-ce01] + [gre-pe01-pe02] + [gre-pe01-pe03]
PE02: bridge vpls-br = [pe02-ce02] + [gre-pe02-pe01] + [gre-pe02-pe03]
PE03: bridge vpls-br = [pe03-ce03] + [gre-pe03-pe01] + [gre-pe03-pe02]
```

- **GRETAP** (không phải GRE): thêm Ethernet header → hoạt động ở L2 → bridge được
- **Tunnel source/dest**: dùng loopback IPs (ổn định, dual-homed)
- **Bridge**: kết nối AC interface + GRETAP tunnels → L2 domain ảo

### 1.5 Inter-Branch L3 Routes

Vì các branch ở subnet khác nhau (10.1.0.0/24, 10.2.10.0/24, 10.3.0.0/16), cần L3 routes:

```
pc01 (10.1.0.11) → CE01 → PE01 →[MPLS 112]→ P02 →[PHP]→ PE02 → CE02 → lab01 (10.2.10.11)
```

3 loại routes cần thiết:
1. **PE → backbone**: remote subnets `encap mpls <label>` qua backbone
2. **PE → CE**: local subnets via CE (return path, plain IP)
3. **CE → PE**: remote subnets via PE (forward path)

### 1.6 Dual-Homed PE — High Availability

PE routers kết nối **2 uplinks** vào backbone:

| PE | Uplink 1 | Uplink 2 |
|----|----------|----------|
| PE01 | P01 (10.0.20.x) | P02 (10.0.21.x) |
| PE02 | P02 (10.0.22.x) | P03 (10.0.23.x) |
| PE03 | P03 (10.0.24.x) | P04 (10.0.25.x) |

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

Mô hình đơn giản nhất: toàn bộ hosts trong **một broadcast domain** (`10.1.0.0/24`).

---

## Phần 3 — Chi nhánh 2: Three-Tier Network (Mạng 3 Lớp)

### VLAN Plan

| VLAN ID | Tên | Subnet | Gateway |
|---------|-----|--------|---------|
| 10 | LAB | 10.2.10.0/24 | 10.2.10.1 |
| 20 | ADMIN | 10.2.20.0/24 | 10.2.20.1 |
| 30 | GUEST | 10.2.30.0/24 | 10.2.30.1 |

Inter-VLAN routing qua CE02 với interface riêng cho mỗi VLAN.

---

## Phần 4 — Chi nhánh 3: Spine-Leaf Data Center

### Server Clusters

| Cluster | Subnet | Leaf | Servers |
|---------|--------|------|---------|
| WEB | 10.3.10.0/24 | LEAF02 | web01, web02 |
| DNS | 10.3.20.0/24 | LEAF03 | dns01, dns02 |
| DB | 10.3.30.0/24 | LEAF04 | db01, db02 |

ECMP (Equal-Cost Multi-Path) qua 2 Spine switches.

---

## Cấu trúc dự án

```
configs/                    ← Nguồn dữ liệu duy nhất (YAML)
  backbone/
    ip_plan.yaml            ← IP plan P/PE, static routes backbone
    vpls_policy.yaml        ← VPLS pseudowire, GRETAP tunnel config
  branch1/
    ip_plan.yaml            ← IP CE01, switches, hosts, test matrix
  branch2/, branch3/        ← Tương tự

topologies/                 ← Builder functions (skeleton topology)
  backbone.py               ← Build P/PE nodes + links
  branch1_flat.py           ← Build branch 1 (switches + hosts)
  branch2_3tier.py          ← Build branch 2
  branch3_spineleaf.py      ← Build branch 3
  full_topology.py          ← Compose tất cả

tools/                      ← Business logic
  config_loader.py          ← Đọc YAML → apply IP vào Mininet nodes
  static_mpls.py            ← Static MPLS labels + GRETAP VPLS + inter-branch routes
  connectivity_test.py      ← Ping test suite + báo cáo
  node_types.py             ← MPLSRouter class (Linux IP forwarding + MPLS)

runners/                    ← Entry points
  run_backbone.py           ← Phase 0: Test ISP backbone
  run_branch1/2/3.py        ← Phase 1: Test từng chi nhánh
  run_full_mpls.py          ← Phase 2: Full MPLS MAN
```

---

## Hướng dẫn chạy

### Yêu cầu

```bash
sudo apt install -y mininet python3-yaml
```

### Quy trình kiểm tra từng bước

```bash
# Bước 1: Kiểm tra ISP backbone (MPLS labels + VPLS)
sudo python3 runners/run_backbone.py --test

# Bước 2: Kiểm tra từng chi nhánh độc lập
sudo python3 runners/run_branch1.py --test
sudo python3 runners/run_branch2.py --test
sudo python3 runners/run_branch3.py --test

# Bước 3: Chạy full MPLS MAN (kết hợp tất cả)
sudo python3 runners/run_full_mpls.py --test
```

### Debug trong Mininet CLI

```bash
# Kiểm tra MPLS label table
p01 ip -M route

# Kiểm tra MPLS push routes trên PE
pe01 ip route show | grep mpls

# Kiểm tra VPLS bridge
pe01 brctl show vpls-br

# Kiểm tra GRETAP tunnels
pe01 ip -d link show type gretap

# Test inter-branch connectivity
pc01 ping 10.2.10.11    # Branch 1 → Branch 2
lab01 ping 10.3.10.11   # Branch 2 → Branch 3

# Traceroute qua MPLS backbone
pe01 traceroute -n 10.0.0.13
```

---

## Kiến thức tổng kết

| Công nghệ | Áp dụng ở đâu | Mục đích |
|-----------|--------------|---------| 
| **Static MPLS** | Toàn bộ backbone P+PE | Label push/swap/pop, data plane forwarding |
| **GRETAP VPLS** | PE01 ↔ PE02 ↔ PE03 | L2 pseudowire emulation qua IP backbone |
| **Inter-branch routing** | PE + CE routers | L3 routes với MPLS encap cho cross-branch connectivity |
| **Static Routes** | Tất cả routers | IP reachability (thay thế OSPF IGP) |
| **Dual-homed PE** | PE01–PE02–PE03 | High availability, không single point of failure |
| **Flat Network** | Branch 1 | Cấu hình đơn giản, single broadcast domain |
| **Three-Tier** | Branch 2 | Campus network, inter-VLAN routing qua CE |
| **Spine-Leaf** | Branch 3 | Data center, ECMP, low and uniform latency |
| **Config-Driven (YAML)** | Toàn bộ project | Tách biệt topology (code) và config (data) |
