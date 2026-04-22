#!/usr/bin/env python3
"""
topologies/backbone.py
======================
MPLS Backbone Topology — 4 P-Routers + 3 PE-Routers

Cấu trúc Partial Mesh + Dual-homed PE:
  P01 -- P02 -- P03 -- P04
   \\           /      /
    +-----------  ---+
  PE01(P01+P02) PE02(P02+P03) PE03(P03+P04)

Cung cấp:
  - BackboneTopo(Topo): dùng với Mininet CLI (mn --topo backbone)
  - build_backbone_nodes(net): builder function thêm P/PE nodes vào net có sẵn
  - build_backbone_links(net, backbone_loader): thêm P-P và PE-P links từ YAML

Interface naming (khớp FRR config):
  p01-eth0  (P01 -> P02),  p01-eth1  (P01 -> P03 diagonal)
  p01-pe01  (P01 -> PE01), pe01-p01  (PE01 -> P01)
  pe01-p02  (PE01 -> P02)
"""

from mininet.topo import Topo


# ====================================================================
# BackboneTopo — giữ lại để tương thích với mn --custom
# ====================================================================
class BackboneTopo(Topo):
    """
    MPLS Backbone Topology (dùng với Mininet CLI):
      mn --custom topologies/backbone.py --topo backbone

    Ghi chú: File này chỉ là skeleton topology (không có IP/routing).
    Để chạy đầy đủ với IP + FRR, dùng: runners/run_backbone.py
    """

    def build(self, **opts):
        # ---- P-Router nodes (core) ----
        p01 = self.addNode('p01', cls=None)
        p02 = self.addNode('p02', cls=None)
        p03 = self.addNode('p03', cls=None)
        p04 = self.addNode('p04', cls=None)

        # ---- PE-Router nodes (edge) ----
        pe01 = self.addNode('pe01', cls=None)
        pe02 = self.addNode('pe02', cls=None)
        pe03 = self.addNode('pe03', cls=None)

        # ---- P-P Links (Partial Mesh core) ----
        self.addLink(p01, p02, bw=1000, delay='2ms')
        self.addLink(p02, p03, bw=1000, delay='2ms')
        self.addLink(p03, p04, bw=1000, delay='2ms')
        self.addLink(p01, p03, bw=1000, delay='3ms')   # diagonal
        self.addLink(p02, p04, bw=1000, delay='3ms')   # diagonal

        # ---- PE-P Links (Dual-homed) ----
        self.addLink(pe01, p01, bw=1000, delay='1ms')
        self.addLink(pe01, p02, bw=1000, delay='1ms')
        self.addLink(pe02, p02, bw=1000, delay='1ms')
        self.addLink(pe02, p03, bw=1000, delay='1ms')
        self.addLink(pe03, p03, bw=1000, delay='1ms')
        self.addLink(pe03, p04, bw=1000, delay='1ms')


topos = {'backbone': BackboneTopo}


# ====================================================================
# Builder Functions — dùng để compose vào full topology
# ====================================================================

def build_backbone_nodes(net, router_cls):
    """
    Thêm P-Routers và PE-Routers vào một Mininet net đã tạo sẵn.

    Args:
        net: Mininet object đang được build
        router_cls: Node class dùng cho routers (MPLSRouter hoặc LinuxRouter)

    Returns:
        dict với keys 'p_routers' và 'pe_routers' là list tên nodes
    """
    p_routers  = ['p01', 'p02', 'p03', 'p04']
    pe_routers = ['pe01', 'pe02', 'pe03']

    for name in p_routers:
        net.addHost(name, cls=router_cls, ip=None)

    for name in pe_routers:
        net.addHost(name, cls=router_cls, ip=None)

    return {'p_routers': p_routers, 'pe_routers': pe_routers}


def build_backbone_links(net, backbone_loader=None):
    """
    Thêm P-P và PE-P links vào net.
    Ưu tiên đọc từ backbone_loader (YAML); fallback về hardcoded defaults.

    Args:
        net: Mininet object
        backbone_loader: BackboneConfigLoader instance (có thể None)
    """
    # ---- P-P Links ----
    if backbone_loader is not None:
        p_p_links = backbone_loader.get_backbone_links()
    else:
        p_p_links = []

    if p_p_links:
        for link_cfg in p_p_links:
            net.addLink(
                link_cfg['src'], link_cfg['dst'],
                bw=link_cfg.get('bw', 1000),
                delay=link_cfg.get('delay', '2ms'),
                intfName1=link_cfg.get('src_intf', ''),
                intfName2=link_cfg.get('dst_intf', ''),
            )
    else:
        _add_default_p_p_links(net)

    # ---- PE-P Links ----
    if backbone_loader is not None:
        pe_p_links = backbone_loader.get_pe_p_links()
    else:
        pe_p_links = []

    if pe_p_links:
        for link_cfg in pe_p_links:
            net.addLink(
                link_cfg['src'], link_cfg['dst'],
                bw=link_cfg.get('bw', 1000),
                delay=link_cfg.get('delay', '1ms'),
                intfName1=link_cfg.get('src_intf', ''),
                intfName2=link_cfg.get('dst_intf', ''),
            )
    else:
        _add_default_pe_p_links(net)


def build_wan_links(net, backbone_loader):
    """
    Thêm PE-CE WAN links vào net từ backbone_loader.
    Gọi sau khi CE nodes đã được thêm vào net.

    Args:
        net: Mininet object
        backbone_loader: BackboneConfigLoader instance
    """
    for wan in backbone_loader.get_wan_links():
        pe_name = wan['pe']
        ce_name = wan['ce']
        net.addLink(
            pe_name, ce_name,
            bw=wan.get('bw', 100),
            delay=wan.get('delay', '5ms'),
            intfName1=f'{pe_name}-{ce_name}',
            intfName2=f'{ce_name}-{pe_name}',
        )


# ====================================================================
# Fallback defaults (nếu YAML không có link config)
# ====================================================================

def _add_default_p_p_links(net):
    """P-P links với interface names chuẩn (khớp FRR config)."""
    net.addLink('p01', 'p02', bw=1000, delay='2ms',
                intfName1='p01-eth0', intfName2='p02-eth0')
    net.addLink('p02', 'p03', bw=1000, delay='2ms',
                intfName1='p02-eth1', intfName2='p03-eth0')
    net.addLink('p03', 'p04', bw=1000, delay='2ms',
                intfName1='p03-eth1', intfName2='p04-eth0')
    net.addLink('p01', 'p03', bw=1000, delay='3ms',
                intfName1='p01-eth1', intfName2='p03-eth2')
    net.addLink('p02', 'p04', bw=1000, delay='3ms',
                intfName1='p02-eth2', intfName2='p04-eth1')


def _add_default_pe_p_links(net):
    """PE-P links với interface names chuẩn (khớp FRR config)."""
    net.addLink('pe01', 'p01', bw=1000, delay='1ms',
                intfName1='pe01-p01', intfName2='p01-pe01')
    net.addLink('pe01', 'p02', bw=1000, delay='1ms',
                intfName1='pe01-p02', intfName2='p02-pe01')
    net.addLink('pe02', 'p02', bw=1000, delay='1ms',
                intfName1='pe02-p02', intfName2='p02-pe02')
    net.addLink('pe02', 'p03', bw=1000, delay='1ms',
                intfName1='pe02-p03', intfName2='p03-pe02')
    net.addLink('pe03', 'p03', bw=1000, delay='1ms',
                intfName1='pe03-p03', intfName2='p03-pe03')
    net.addLink('pe03', 'p04', bw=1000, delay='1ms',
                intfName1='pe03-p04', intfName2='p04-pe03')
