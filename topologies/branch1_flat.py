#!/usr/bin/env python3
"""
topologies/branch1_flat.py
==========================
Chi nhánh 1: Mạng Phẳng (Flat Network)

Cấu trúc:
  CE01 -- SW01 -- SW02
           |         |--- PC03
           |         |--- PC04
           |--- PC01
           |--- PC02

Nguyên tắc thiết kế:
  File này CHỈ mô tả cấu trúc (topology skeleton).
  Toàn bộ cấu hình IP, gateway, bw, delay đọc từ YAML qua ConfigLoader.
  Không có hardcoded IP hay config nào trong file này.

Cung cấp:
  - Branch1FlatTopo(Topo): dùng với mn --custom (skeleton, không có IP)
  - build_branch1_nodes(net, router_cls, loader): thêm CE01 + switches + hosts
  - build_branch1_links(net, loader): thêm LAN links từ YAML

Nguồn config:  configs/branch1/ip_plan.yaml
Runner:        runners/run_branch1.py  (isolated)
               runners/run_full_mpls.py (full topology)
"""

from mininet.topo import Topo


# ====================================================================
# Branch1FlatTopo — skeleton, dùng với mn --custom
# ====================================================================
class Branch1FlatTopo(Topo):
    """
    Flat Network Topology skeleton (Chi nhánh 1).
    Chỉ định nghĩa cấu trúc nodes/links, không có IP.
    Dùng với: mn --custom topologies/branch1_flat.py --topo branch1
    """

    def build(self, **opts):
        ce01 = self.addNode('ce01', cls=None)
        sw01 = self.addSwitch('sw01')
        sw02 = self.addSwitch('sw02')
        pc01 = self.addHost('pc01')
        pc02 = self.addHost('pc02')
        pc03 = self.addHost('pc03')
        pc04 = self.addHost('pc04')

        self.addLink(ce01, sw01)
        self.addLink(sw01, sw02)
        self.addLink(sw01, pc01)
        self.addLink(sw01, pc02)
        self.addLink(sw02, pc03)
        self.addLink(sw02, pc04)


topos = {'branch1': Branch1FlatTopo}


# ====================================================================
# Builder Functions
# ====================================================================

def build_branch1_nodes(net, router_cls, loader):
    """
    Thêm CE01, switches và hosts của Branch 1 vào Mininet net.

    Toàn bộ thông tin cấu trúc (tên switch, tên host, IP ban đầu)
    đọc từ loader (YAML). Không có giá trị hardcoded.

    Args:
        net:        Mininet object đang được build
        router_cls: Node class cho CE router (LinuxRouter hoặc MPLSRouter)
        loader:     ConfigLoader instance trỏ tới configs/branch1/ip_plan.yaml

    Raises:
        ValueError: nếu loader là None
    """
    if loader is None:
        raise ValueError(
            "[Branch1] loader là bắt buộc. "
            "Truyền ConfigLoader('configs/branch1/ip_plan.yaml')."
        )

    # CE01 — router, IP sẽ được apply bởi loader.apply_all() sau net.start()
    ce_cfg = loader.get_ce_config()
    net.addHost(ce_cfg['name'], cls=router_cls, ip=None)

    # Switches — tên và mode từ YAML
    for sw_cfg in loader.get_switches():
        sw_mode  = sw_cfg.get('mode', 'standalone')
        failMode = sw_mode if sw_mode in ('standalone', 'secure') else 'standalone'
        # Branch1: cây thẳng, không có loop → tắt STP để port up ngay
        net.addSwitch(sw_cfg['name'], failMode=failMode, stp=False)

    # Hosts — tên và IP từ YAML; IP được gán ngay để Mininet track
    for host_cfg in loader.get_hosts():
        net.addHost(
            host_cfg['name'],
            ip=host_cfg['ip'],
            defaultRoute=f"via {host_cfg['gateway']}"
        )


def build_branch1_links(net, loader):
    """
    Thêm LAN links nội bộ Branch 1 từ YAML config.
    Bỏ qua WAN link (CE01 <-> PE01) — được xử lý bởi backbone builder.

    Args:
        net:    Mininet object
        loader: ConfigLoader instance trỏ tới configs/branch1/ip_plan.yaml

    Raises:
        ValueError: nếu loader là None
    """
    if loader is None:
        raise ValueError(
            "[Branch1] loader là bắt buộc. "
            "Truyền ConfigLoader('configs/branch1/ip_plan.yaml')."
        )

    for link_cfg in loader.get_links():
        src      = link_cfg['src']
        dst      = link_cfg['dst']
        src_intf = link_cfg.get('src_intf')
        dst_intf = link_cfg.get('dst_intf')
        bw       = link_cfg.get('bw', 100)
        delay    = link_cfg.get('delay', '1ms')

        # Bỏ qua WAN link đến PE (chỉ tồn tại trong full topology)
        if dst.startswith('pe') or src.startswith('pe'):
            continue

        params = {'bw': bw, 'delay': delay}
        if src_intf:
            params['intfName1'] = src_intf
        if dst_intf:
            params['intfName2'] = dst_intf

        net.addLink(src, dst, **params)
