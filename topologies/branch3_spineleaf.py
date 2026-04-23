#!/usr/bin/env python3
"""
topologies/branch3_spineleaf.py
===============================
Chi nhánh 3: Spine-Leaf (Data Center)

Cấu trúc:
          CE03
           |
         LEAF01 (Border Leaf)
        /        \\
   SPINE01      SPINE02
   /  |  \\      /  |  \\
LEAF02 LEAF03 LEAF04
  |      |      |
WEB   DNS     DB

Subnets (từ YAML):
  WEB: 10.3.10.0/24  (hosts /16 mask)
  DNS: 10.3.20.0/24
  DB:  10.3.30.0/24

Nguyên tắc thiết kế:
  File này CHỈ mô tả cấu trúc (topology skeleton).
  Toàn bộ cấu hình IP, gateway, bw, delay đọc từ YAML qua ConfigLoader.
  Không có hardcoded IP hay config nào trong file này.

Cung cấp:
  - Branch3SpineLeafTopo(Topo): dùng với mn --custom (skeleton)
  - build_branch3_nodes(net, router_cls, loader): thêm CE03 + switches + servers
  - build_branch3_links(net, loader): thêm fabric links từ YAML

Nguồn config:  configs/branch3/ip_plan.yaml
Runner:        runners/run_branch3.py  (isolated)
               runners/run_full_mpls.py (full topology)
"""

from mininet.topo import Topo
from mininet.log import info, warn


# ====================================================================
# Branch3SpineLeafTopo — skeleton, dùng với mn --custom
# ====================================================================
class Branch3SpineLeafTopo(Topo):
    """
    Spine-Leaf Topology skeleton (Chi nhánh 3 - Data Center).
    Chỉ định nghĩa cấu trúc nodes/links, không có IP.
    Dùng với: mn --custom topologies/branch3_spineleaf.py --topo branch3
    """

    def build(self, **opts):
        ce03    = self.addNode('ce03', cls=None)
        spine01 = self.addSwitch('spine01')
        spine02 = self.addSwitch('spine02')
        leaf01  = self.addSwitch('leaf01')
        leaf02  = self.addSwitch('leaf02')
        leaf03  = self.addSwitch('leaf03')
        leaf04  = self.addSwitch('leaf04')
        web01   = self.addHost('web01')
        web02   = self.addHost('web02')
        dns01   = self.addHost('dns01')
        dns02   = self.addHost('dns02')
        db01    = self.addHost('db01')
        db02    = self.addHost('db02')

        self.addLink(ce03, leaf01)
        self.addLink(leaf01, spine01)
        self.addLink(leaf01, spine02)
        self.addLink(leaf02, spine01)
        self.addLink(leaf02, spine02)
        self.addLink(leaf03, spine01)
        self.addLink(leaf03, spine02)
        self.addLink(leaf04, spine01)
        self.addLink(leaf04, spine02)
        self.addLink(leaf02, web01)
        self.addLink(leaf02, web02)
        self.addLink(leaf03, dns01)
        self.addLink(leaf03, dns02)
        self.addLink(leaf04, db01)
        self.addLink(leaf04, db02)


topos = {'branch3': Branch3SpineLeafTopo}


# ====================================================================
# Builder Functions
# ====================================================================

def build_branch3_nodes(net, router_cls, loader):
    """
    Thêm CE03, switches (Spine/Leaf) và servers (WEB/DNS/DB) vào net.

    Toàn bộ thông tin cấu trúc (tên switch, tên server, IP ban đầu)
    đọc từ loader (YAML). Không có giá trị hardcoded.

    Ghi chú về /16 mask:
    Servers dùng IP/16 (ví dụ 10.3.10.11/16) với gateway CE03 (10.3.0.1/16).
    Điều này cho phép mọi rack on-link reachable mà không cần inter-rack routes.
    Giá trị ip và gateway đọc từ YAML — không hardcode.

    Args:
        net:        Mininet object đang được build
        router_cls: Node class cho CE router (LinuxRouter hoặc MPLSRouter)
        loader:     ConfigLoader instance trỏ tới configs/branch3/ip_plan.yaml

    Raises:
        ValueError: nếu loader là None
    """
    if loader is None:
        raise ValueError(
            "[Branch3] loader là bắt buộc. "
            "Truyền ConfigLoader('configs/branch3/ip_plan.yaml')."
        )

    # CE03 — router, IP sẽ được apply bởi loader.apply_all() sau net.start()
    ce_cfg = loader.get_ce_config()
    ce_name = ce_cfg['name']
    if ce_name in net:
        info(f"  [~] Sử dụng CE node đã tồn tại: {ce_name}\n")
    else:
        net.addHost(ce_name, cls=router_cls, ip=None)

    # Spine/Leaf switches — Spine-Leaf có loop qua 2 spine
    # STP=False + standalone: OVS flood/learn mà không bị blocking delay
    # (acceptable trong Mininet lab — không có broadcast storm thực sự)
    for sw_cfg in loader.get_switches():
        sw_mode  = sw_cfg.get('mode', 'standalone')
        failMode = sw_mode if sw_mode in ('standalone', 'secure') else 'standalone'
        net.addSwitch(sw_cfg['name'], failMode=failMode, stp=False)

    # Hosts (servers) — tên và IP từ YAML
    for host_cfg in loader.get_hosts():
        net.addHost(
            host_cfg['name'],
            ip=host_cfg['ip'],
            defaultRoute=f"via {host_cfg['gateway']}"
        )


def build_branch3_links(net, loader):
    """
    Thêm fabric links nội bộ Branch 3 từ YAML config.
    Bỏ qua WAN link (CE03 <-> PE03) — được xử lý bởi backbone builder.

    Args:
        net:    Mininet object
        loader: ConfigLoader instance trỏ tới configs/branch3/ip_plan.yaml

    Raises:
        ValueError: nếu loader là None
    """
    if loader is None:
        raise ValueError(
            "[Branch3] loader là bắt buộc. "
            "Truyền ConfigLoader('configs/branch3/ip_plan.yaml')."
        )

    for link_cfg in loader.get_links():
        src      = link_cfg['src']
        dst      = link_cfg['dst']
        src_intf = link_cfg.get('src_intf')
        dst_intf = link_cfg.get('dst_intf')
        bw       = link_cfg.get('bw', 1000)
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
