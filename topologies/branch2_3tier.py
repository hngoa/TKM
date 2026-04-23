#!/usr/bin/env python3
"""
topologies/branch2_3tier.py
===========================
Chi nhánh 2: Mạng 3 Lớp (Core-Distribution-Access)

Cấu trúc:
  CE02
   |
  CORE01 -- CORE02
   |    \\  /   |
  DIST01  DIST02
   |         |
 ACCESS01  ACCESS02  ACCESS03
   |           |         |
  LAB       ADMIN     GUEST

VLANs (từ YAML):
  VLAN 10 - LAB    (10.2.10.0/24)
  VLAN 20 - ADMIN  (10.2.20.0/24)
  VLAN 30 - GUEST  (10.2.30.0/24)

Nguyên tắc thiết kế:
  File này CHỈ mô tả cấu trúc (topology skeleton).
  Toàn bộ cấu hình IP, gateway, bw, delay đọc từ YAML qua ConfigLoader.
  Không có hardcoded IP hay config nào trong file này.

Cung cấp:
  - Branch2ThreeTierTopo(Topo): dùng với mn --custom (skeleton)
  - build_branch2_nodes(net, router_cls, loader): thêm CE02 + switches + hosts
  - build_branch2_links(net, loader): thêm LAN links từ YAML

Nguồn config:  configs/branch2/ip_plan.yaml
Runner:        runners/run_branch2.py  (isolated)
               runners/run_full_mpls.py (full topology)
"""

from mininet.topo import Topo
from mininet.log import info, warn


# ====================================================================
# Branch2ThreeTierTopo — skeleton, dùng với mn --custom
# ====================================================================
class Branch2ThreeTierTopo(Topo):
    """
    Three-Tier Network Topology skeleton (Chi nhánh 2).
    Chỉ định nghĩa cấu trúc nodes/links, không có IP.
    Dùng với: mn --custom topologies/branch2_3tier.py --topo branch2
    """

    def build(self, **opts):
        ce02    = self.addNode('ce02', cls=None)
        core01  = self.addSwitch('core01')
        core02  = self.addSwitch('core02')
        dist01  = self.addSwitch('dist01')
        dist02  = self.addSwitch('dist02')
        access01 = self.addSwitch('access01')
        access02 = self.addSwitch('access02')
        access03 = self.addSwitch('access03')
        lab01   = self.addHost('lab01')
        lab02   = self.addHost('lab02')
        admin01 = self.addHost('admin01')
        admin02 = self.addHost('admin02')
        guest01 = self.addHost('guest01')
        guest02 = self.addHost('guest02')

        self.addLink(ce02, core01)
        self.addLink(ce02, core02)
        self.addLink(core01, core02)
        self.addLink(core01, dist01)
        self.addLink(core01, dist02)
        self.addLink(core02, dist01)
        self.addLink(core02, dist02)
        self.addLink(dist01, access01)
        self.addLink(dist01, access02)
        self.addLink(dist02, access02)
        self.addLink(dist02, access03)
        self.addLink(access01, lab01)
        self.addLink(access01, lab02)
        self.addLink(access02, admin01)
        self.addLink(access02, admin02)
        self.addLink(access03, guest01)
        self.addLink(access03, guest02)


topos = {'branch2': Branch2ThreeTierTopo}


# ====================================================================
# Builder Functions
# ====================================================================

def build_branch2_nodes(net, router_cls, loader):
    """
    Thêm CE02, switches (Core/Dist/Access) và hosts (LAB/ADMIN/GUEST) vào net.

    Toàn bộ thông tin cấu trúc (tên switch, tên host, IP ban đầu)
    đọc từ loader (YAML). Không có giá trị hardcoded.

    Args:
        net:        Mininet object đang được build
        router_cls: Node class cho CE router (LinuxRouter hoặc MPLSRouter)
        loader:     ConfigLoader instance trỏ tới configs/branch2/ip_plan.yaml

    Raises:
        ValueError: nếu loader là None
    """
    if loader is None:
        raise ValueError(
            "[Branch2] loader là bắt buộc. "
            "Truyền ConfigLoader('configs/branch2/ip_plan.yaml')."
        )

    # CE02 — router, IP sẽ được apply bởi loader.apply_all() sau net.start()
    ce_cfg = loader.get_ce_config()
    ce_name = ce_cfg['name']
    if ce_name in net:
        info(f"  [~] Sử dụng CE node đã tồn tại: {ce_name}\n")
    else:
        net.addHost(ce_name, cls=router_cls, ip=None)

    # Switches — Branch2 có L2 loop (core-dist mesh)
    # STP=False + standalone mode: OVS sẽ flood/learn đúng mà không cần đợi STP hội tụ
    # (Trong Mininet lab, standalone + no STP đủ để test)
    for sw_cfg in loader.get_switches():
        sw_mode  = sw_cfg.get('mode', 'standalone')
        failMode = sw_mode if sw_mode in ('standalone', 'secure') else 'standalone'
        net.addSwitch(sw_cfg['name'], failMode=failMode, stp=False)

    # Hosts — tên và IP từ YAML
    for host_cfg in loader.get_hosts():
        net.addHost(
            host_cfg['name'],
            ip=host_cfg['ip'],
            defaultRoute=f"via {host_cfg['gateway']}"
        )


def build_branch2_links(net, loader):
    """
    Thêm LAN links nội bộ Branch 2 từ YAML config.
    Bỏ qua WAN link (CE02 <-> PE02) — được xử lý bởi backbone builder.

    Ghi chú: CE02 cần 3 interfaces LAN để đóng vai trò Inter-VLAN Router.
    Cấu trúc này được định nghĩa đầy đủ trong configs/branch2/ip_plan.yaml.

    Args:
        net:    Mininet object
        loader: ConfigLoader instance trỏ tới configs/branch2/ip_plan.yaml

    Raises:
        ValueError: nếu loader là None
    """
    if loader is None:
        raise ValueError(
            "[Branch2] loader là bắt buộc. "
            "Truyền ConfigLoader('configs/branch2/ip_plan.yaml')."
        )

    for link_cfg in loader.get_links():
        src      = link_cfg['src']
        dst      = link_cfg['dst']
        src_intf = link_cfg.get('src_intf')
        dst_intf = link_cfg.get('dst_intf')
        bw       = link_cfg.get('bw', 100)
        delay    = link_cfg.get('delay', '1ms')

        # Bỏ qua WAN link đến PE
        if dst.startswith('pe') or src.startswith('pe'):
            continue

        params = {'bw': bw, 'delay': delay}
        if src_intf:
            params['intfName1'] = src_intf
        if dst_intf:
            params['intfName2'] = dst_intf

        net.addLink(src, dst, **params)
