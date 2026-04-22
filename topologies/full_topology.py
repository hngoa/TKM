#!/usr/bin/env python3
"""
topologies/full_topology.py
============================
Toàn bộ hệ thống Metro Ethernet MPLS — MPLS Backbone + 3 Chi nhánh

Kiến trúc module (Config-Driven + Builder Pattern):
  ┌─────────────────────────────────────────────────────────┐
  │  YAML configs (nguồn duy nhất cho mọi cấu hình)         │
  │    configs/backbone/ip_plan.yaml → BackboneConfigLoader │
  │    configs/branch1/ip_plan.yaml  → ConfigLoader (b1)   │
  │    configs/branch2/ip_plan.yaml  → ConfigLoader (b2)   │
  │    configs/branch3/ip_plan.yaml  → ConfigLoader (b3)   │
  └────────────────────┬────────────────────────────────────┘
                       │ loader.get_switches/hosts/links()
  ┌────────────────────▼────────────────────────────────────┐
  │  topology builders (cấu trúc, KHÔNG có config)          │
  │    build_backbone_nodes/links() ← backbone.py           │
  │    build_branch1_nodes/links()  ← branch1_flat.py       │
  │    build_branch2_nodes/links()  ← branch2_3tier.py      │
  │    build_branch3_nodes/links()  ← branch3_spineleaf.py  │
  └────────────────────┬────────────────────────────────────┘
                       │ net.start() → loader.apply_all()
  ┌────────────────────▼────────────────────────────────────┐
  │  runner (điều phối)                                      │
  │    runners/run_full_mpls.py (FRR + VPLS)                │
  └─────────────────────────────────────────────────────────┘

Nguyên tắc:
  - File này không chứa bất kỳ hardcoded IP hay config nào
  - build_full_topology() yêu cầu backbone_loader và branch_loaders
  - Mọi cấu hình đến từ YAML thông qua loader tương ứng

Cấu trúc tổng thể:
  Branch1 (Flat) <-> CE01 <-> PE01 <-+
                                      |-- MPLS Backbone (P01-P04)
  Branch2 (3-Tier) <-> CE02 <-> PE02 -+
                                      |
  Branch3 (Spine-Leaf) <-> CE03 <-> PE03
"""

import sys
import os

_THIS_DIR     = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, 'tools'))

from mininet.net import Mininet
from mininet.node import OVSSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel, info
from mininet.cli import CLI

# Node types dùng chung
from node_types import MPLSRouter

# Builder functions từ từng module con
from backbone          import build_backbone_nodes, build_backbone_links, build_wan_links
from branch1_flat      import build_branch1_nodes, build_branch1_links
from branch2_3tier     import build_branch2_nodes, build_branch2_links
from branch3_spineleaf import build_branch3_nodes, build_branch3_links


# ====================================================================
# build_full_topology — compose tất cả thành phần con
# ====================================================================

def build_full_topology(backbone_loader, branch_loaders):
    """
    Xây dựng toàn bộ topology bằng cách gọi lại builder functions
    từ từng module con. File này không chứa bất kỳ node/link nào trực tiếp.

    Quy trình:
      1. Tạo net object
      2. Thêm Backbone nodes (P-Routers + PE-Routers)
      3. Thêm CE Routers (đọc tên từ wan_links trong backbone config)
      4. Thêm Branch nodes (switches + hosts) từng branch qua loader
      5. Thêm Backbone links (P-P + PE-P) từ backbone_loader
      6. Thêm WAN links (PE-CE) từ backbone_loader
      7. Thêm Branch LAN links từng branch qua loader

    Args:
        backbone_loader: BackboneConfigLoader instance
                         (configs/backbone/ip_plan.yaml)
        branch_loaders:  dict bắt buộc:
                         {
                           'branch1': ConfigLoader(.../branch1/ip_plan.yaml),
                           'branch2': ConfigLoader(.../branch2/ip_plan.yaml),
                           'branch3': ConfigLoader(.../branch3/ip_plan.yaml),
                         }

    Returns:
        net: Mininet object đã build xong (chưa start)

    Raises:
        ValueError: nếu backbone_loader hoặc branch_loaders là None/thiếu key
    """
    if backbone_loader is None:
        raise ValueError(
            "[FullTopology] backbone_loader là bắt buộc. "
            "Truyền BackboneConfigLoader('configs/backbone/ip_plan.yaml')."
        )
    for key in ('branch1', 'branch2', 'branch3'):
        if branch_loaders is None or key not in branch_loaders:
            raise ValueError(
                f"[FullTopology] branch_loaders['{key}'] là bắt buộc. "
                f"Truyền ConfigLoader('configs/{key}/ip_plan.yaml')."
            )

    net = Mininet(
        controller=None,
        link=TCLink,
        switch=OVSSwitch,
        waitConnected=False,
    )

    # ---- 1. Backbone nodes: P01-P04 + PE01-PE03 ----
    info('*** [Backbone] Tạo P-Routers và PE-Routers\n')
    build_backbone_nodes(net, router_cls=MPLSRouter)

    # ---- 2. CE Routers (đọc tên từ wan_links trong backbone YAML) ----
    # Tên CE đến từ backbone_loader để đảm bảo nhất quán với WAN link config
    info('*** [CE] Tạo Customer Edge Routers\n')
    for wan in backbone_loader.get_wan_links():
        ce_name = wan['ce']
        net.addHost(ce_name, cls=MPLSRouter, ip=None)

    # ---- 3. Branch 1 nodes ----
    info('*** [Branch 1] Tạo Flat Network nodes\n')
    build_branch1_nodes(net, router_cls=MPLSRouter, loader=branch_loaders['branch1'])

    # ---- 4. Branch 2 nodes ----
    info('*** [Branch 2] Tạo Three-Tier Network nodes\n')
    build_branch2_nodes(net, router_cls=MPLSRouter, loader=branch_loaders['branch2'])

    # ---- 5. Branch 3 nodes ----
    info('*** [Branch 3] Tạo Spine-Leaf DC nodes\n')
    build_branch3_nodes(net, router_cls=MPLSRouter, loader=branch_loaders['branch3'])

    # ---- 6. Backbone links: P-P (Partial Mesh) + PE-P (Dual-homed) ----
    info('*** [Backbone] Kết nối P-P và PE-P links\n')
    build_backbone_links(net, backbone_loader=backbone_loader)

    # ---- 7. WAN links: PE-CE (từ backbone YAML) ----
    info('*** [WAN] Kết nối PE-CE links\n')
    build_wan_links(net, backbone_loader=backbone_loader)

    # ---- 8. Branch LAN links ----
    info('*** [Branch 1] Kết nối Flat Network links\n')
    build_branch1_links(net, loader=branch_loaders['branch1'])

    info('*** [Branch 2] Kết nối Three-Tier links\n')
    build_branch2_links(net, loader=branch_loaders['branch2'])

    info('*** [Branch 3] Kết nối Spine-Leaf fabric links\n')
    build_branch3_links(net, loader=branch_loaders['branch3'])

    return net
