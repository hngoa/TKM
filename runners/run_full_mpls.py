#!/usr/bin/env python3
"""
runners/run_full_mpls.py
========================
Runner: Full Topology — MPLS MAN với VPLS liên chi nhánh

Giai đoạn 2: Test kết nối liên chi nhánh qua MPLS Backbone.

Quy trình chạy:
  1. Build full topology (P01-P04, PE01-PE03, CE01-CE03, tất cả branches)
  2. Apply IP config từ backbone/ip_plan.yaml + branch configs
  3. Deploy FRR cho Backbone (P + PE routers): OSPF + LDP + BGP
  4. ISP push CE configs xuống CE01, CE02, CE03 (OSPF + static)
  5. Setup VPLS (FRR native hoặc Linux Bridge GRE fallback)
  6. Chờ OSPF/LDP converge (~30s)
  7. Verify: OSPF neighbors, LDP sessions, BGP sessions
  8. Test Phase 1: Backbone connectivity (P-P, PE-P, PE loopbacks)
  9. Test Phase 2: Inter-branch connectivity qua VPLS

Chạy:
    sudo python3 runners/run_full_mpls.py            # Full run + CLI
    sudo python3 runners/run_full_mpls.py --test     # Auto test only
    sudo python3 runners/run_full_mpls.py --no-frr   # Dùng static routes, không FRR
"""

import sys
import os
import argparse
import yaml

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'tools'))

from mininet.net import Mininet
from mininet.node import Node, OVSSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel, info, warn
from mininet.cli import CLI

from config_loader import ConfigLoader, BackboneConfigLoader
from frr_manager import FRRManager
from connectivity_test import ConnectivityTest


# ----------------------------------------------------------------
# LinuxRouter
# ----------------------------------------------------------------
class LinuxRouter(Node):
    """Router node với IP forwarding và MPLS support."""
    def config(self, **params):
        super().config(**params)
        self.cmd('sysctl -w net.ipv4.ip_forward=1')
        self.cmd('sysctl -w net.mpls.platform_labels=1048575')
        self.cmd('sysctl -w net.mpls.conf.lo.input=1')

    def terminate(self):
        self.cmd('sysctl -w net.ipv4.ip_forward=0')
        super().terminate()


# ----------------------------------------------------------------
# Build Full Topology
# ----------------------------------------------------------------
def build_full_topology(backbone_loader):
    """
    Xây dựng toàn bộ topology: Backbone + 3 Chi nhánh.
    
    Tất cả routers (P, PE, CE) dùng LinuxRouter.
    Tất cả switches dùng OVSSwitch standalone.
    """
    net = Mininet(controller=None, link=TCLink, switch=OVSSwitch,
                  waitConnected=False)

    # ---- MPLS Backbone Routers ----
    info('*** Tạo MPLS Backbone (P-Routers)\n')
    for router in ['p01', 'p02', 'p03', 'p04']:
        net.addHost(router, cls=LinuxRouter, ip=None)

    info('*** Tạo Provider Edge Routers (PE)\n')
    for router in ['pe01', 'pe02', 'pe03']:
        net.addHost(router, cls=LinuxRouter, ip=None)

    info('*** Tạo Customer Edge Routers (CE)\n')
    for router in ['ce01', 'ce02', 'ce03']:
        net.addHost(router, cls=LinuxRouter, ip=None)

    # ---- Branch 1: Flat Network ----
    info('*** Tạo Branch 1 - Flat Network\n')
    net.addSwitch('sw01', failMode='standalone')
    net.addSwitch('sw02', failMode='standalone')
    net.addHost('pc01', ip='10.1.0.11/24', defaultRoute='via 10.1.0.1')
    net.addHost('pc02', ip='10.1.0.12/24', defaultRoute='via 10.1.0.1')
    net.addHost('pc03', ip='10.1.0.13/24', defaultRoute='via 10.1.0.1')
    net.addHost('pc04', ip='10.1.0.14/24', defaultRoute='via 10.1.0.1')

    # ---- Branch 2: Three-Tier ----
    info('*** Tạo Branch 2 - Three-Tier\n')
    for sw in ['core01', 'core02', 'dist01', 'dist02', 'access01', 'access02', 'access03']:
        net.addSwitch(sw, failMode='standalone')
    net.addHost('lab01',   ip='10.2.10.11/24', defaultRoute='via 10.2.10.1')
    net.addHost('lab02',   ip='10.2.10.12/24', defaultRoute='via 10.2.10.1')
    net.addHost('admin01', ip='10.2.20.11/24', defaultRoute='via 10.2.20.1')
    net.addHost('admin02', ip='10.2.20.12/24', defaultRoute='via 10.2.20.1')
    net.addHost('guest01', ip='10.2.30.11/24', defaultRoute='via 10.2.30.1')
    net.addHost('guest02', ip='10.2.30.12/24', defaultRoute='via 10.2.30.1')

    # ---- Branch 3: Spine-Leaf ----
    info('*** Tạo Branch 3 - Spine-Leaf DC\n')
    for sw in ['spine01', 'spine02', 'leaf01', 'leaf02', 'leaf03', 'leaf04']:
        net.addSwitch(sw, failMode='standalone')
    net.addHost('web01', ip='10.3.10.11/16', defaultRoute='via 10.3.0.1')
    net.addHost('web02', ip='10.3.10.12/16', defaultRoute='via 10.3.0.1')
    net.addHost('dns01', ip='10.3.20.11/16', defaultRoute='via 10.3.0.1')
    net.addHost('dns02', ip='10.3.20.12/16', defaultRoute='via 10.3.0.1')
    net.addHost('db01',  ip='10.3.30.11/16', defaultRoute='via 10.3.0.1')
    net.addHost('db02',  ip='10.3.30.12/16', defaultRoute='via 10.3.0.1')

    # ---- Backbone Links (P-P) ----
    info('*** Kết nối Backbone P-P links\n')
    for link_cfg in backbone_loader.get_backbone_links():
        params = {
            'bw': link_cfg.get('bw', 1000),
            'delay': link_cfg.get('delay', '2ms'),
            'intfName1': link_cfg['src_intf'],
            'intfName2': link_cfg['dst_intf'],
        }
        net.addLink(link_cfg['src'], link_cfg['dst'], **params)

    # ---- PE-P Links ----
    info('*** Kết nối PE-P links (dual-homed)\n')
    for link_cfg in backbone_loader.get_pe_p_links():
        params = {
            'bw': link_cfg.get('bw', 1000),
            'delay': link_cfg.get('delay', '1ms'),
            'intfName1': link_cfg['src_intf'],
            'intfName2': link_cfg['dst_intf'],
        }
        net.addLink(link_cfg['src'], link_cfg['dst'], **params)

    # ---- PE-CE WAN Links ----
    info('*** Kết nối PE-CE WAN links\n')
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

    # ---- Branch 1 LAN Links ----
    info('*** Kết nối Branch 1 LAN\n')
    net.addLink('ce01', 'sw01', intfName1='ce01-sw01', bw=100, delay='1ms')
    net.addLink('sw01', 'sw02', bw=100, delay='1ms')
    net.addLink('sw01', 'pc01', bw=100, delay='1ms')
    net.addLink('sw01', 'pc02', bw=100, delay='1ms')
    net.addLink('sw02', 'pc03', bw=100, delay='1ms')
    net.addLink('sw02', 'pc04', bw=100, delay='1ms')

    # ---- Branch 2 LAN Links ----
    info('*** Kết nối Branch 2 LAN\n')
    net.addLink('ce02', 'core01', intfName1='ce02-c01', bw=1000, delay='1ms')
    net.addLink('ce02', 'core02', intfName1='ce02-c02', bw=1000, delay='1ms')
    net.addLink('ce02', 'dist02', intfName1='ce02-c03', bw=100,  delay='1ms')
    net.addLink('core01', 'core02', bw=1000, delay='1ms')
    net.addLink('core01', 'dist01', bw=1000, delay='1ms')
    net.addLink('core01', 'dist02', bw=1000, delay='1ms')
    net.addLink('core02', 'dist01', bw=1000, delay='1ms')
    net.addLink('core02', 'dist02', bw=1000, delay='1ms')
    net.addLink('dist01', 'access01', bw=100, delay='1ms')
    net.addLink('dist01', 'access02', bw=100, delay='1ms')
    net.addLink('dist02', 'access02', bw=100, delay='1ms')
    net.addLink('dist02', 'access03', bw=100, delay='1ms')
    net.addLink('access01', 'lab01',   bw=100, delay='1ms')
    net.addLink('access01', 'lab02',   bw=100, delay='1ms')
    net.addLink('access02', 'admin01', bw=100, delay='1ms')
    net.addLink('access02', 'admin02', bw=100, delay='1ms')
    net.addLink('access03', 'guest01', bw=100, delay='1ms')
    net.addLink('access03', 'guest02', bw=100, delay='1ms')

    # ---- Branch 3 LAN Links ----
    info('*** Kết nối Branch 3 LAN (Spine-Leaf fabric)\n')
    net.addLink('ce03', 'leaf01', intfName1='ce03-leaf01', bw=1000, delay='1ms')
    net.addLink('leaf01', 'spine01', bw=1000, delay='1ms')
    net.addLink('leaf01', 'spine02', bw=1000, delay='1ms')
    net.addLink('leaf02', 'spine01', bw=1000, delay='1ms')
    net.addLink('leaf02', 'spine02', bw=1000, delay='1ms')
    net.addLink('leaf03', 'spine01', bw=1000, delay='1ms')
    net.addLink('leaf03', 'spine02', bw=1000, delay='1ms')
    net.addLink('leaf04', 'spine01', bw=1000, delay='1ms')
    net.addLink('leaf04', 'spine02', bw=1000, delay='1ms')
    net.addLink('leaf02', 'web01', bw=1000, delay='1ms')
    net.addLink('leaf02', 'web02', bw=1000, delay='1ms')
    net.addLink('leaf03', 'dns01', bw=1000, delay='1ms')
    net.addLink('leaf03', 'dns02', bw=1000, delay='1ms')
    net.addLink('leaf04', 'db01',  bw=1000, delay='1ms')
    net.addLink('leaf04', 'db02',  bw=1000, delay='1ms')

    return net


# ----------------------------------------------------------------
# Apply Static Routes (fallback khi không dùng FRR)
# ----------------------------------------------------------------
def apply_static_routes(net):
    """
    Cấu hình static routes fallback giống full_topology.py cũ.
    Dùng khi FRR không khả dụng.
    """
    info('\n*** Cấu hình Static Routes (FRR fallback)\n')
    # CE default routes
    net.get('ce01').cmd('ip route add default via 10.100.1.1')
    net.get('ce02').cmd('ip route add default via 10.100.2.1')
    net.get('ce03').cmd('ip route add default via 10.100.3.1')

    # PE01 routes
    pe01 = net.get('pe01')
    pe01.cmd('ip route add 10.1.0.0/24   via 10.100.1.2')
    pe01.cmd('ip route add 10.2.0.0/16   via 10.0.21.2')
    pe01.cmd('ip route add 10.3.0.0/16   via 10.0.21.2')
    pe01.cmd('ip route add 10.100.2.0/30 via 10.0.21.2')
    pe01.cmd('ip route add 10.100.3.0/30 via 10.0.21.2')

    # PE02 routes
    pe02 = net.get('pe02')
    pe02.cmd('ip route add 10.2.0.0/16   via 10.100.2.2')
    pe02.cmd('ip route add 10.1.0.0/24   via 10.0.22.2')
    pe02.cmd('ip route add 10.3.0.0/16   via 10.0.23.2')
    pe02.cmd('ip route add 10.100.1.0/30 via 10.0.22.2')
    pe02.cmd('ip route add 10.100.3.0/30 via 10.0.23.2')

    # PE03 routes
    pe03 = net.get('pe03')
    pe03.cmd('ip route add 10.3.0.0/16   via 10.100.3.2')
    pe03.cmd('ip route add 10.1.0.0/24   via 10.0.24.2')
    pe03.cmd('ip route add 10.2.0.0/16   via 10.0.24.2')
    pe03.cmd('ip route add 10.100.1.0/30 via 10.0.24.2')
    pe03.cmd('ip route add 10.100.2.0/30 via 10.0.24.2')

    # P01 routes
    p01 = net.get('p01')
    p01.cmd('ip route add 10.1.0.0/24   via 10.0.20.1')
    p01.cmd('ip route add 10.100.1.0/30 via 10.0.20.1')
    p01.cmd('ip route add 10.2.0.0/16   via 10.0.10.2')
    p01.cmd('ip route add 10.100.2.0/30 via 10.0.10.2')
    p01.cmd('ip route add 10.3.0.0/16   via 10.0.13.2')
    p01.cmd('ip route add 10.100.3.0/30 via 10.0.13.2')

    # P02 routes
    p02 = net.get('p02')
    p02.cmd('ip route add 10.1.0.0/24   via 10.0.21.1')
    p02.cmd('ip route add 10.100.1.0/30 via 10.0.21.1')
    p02.cmd('ip route add 10.2.0.0/16   via 10.0.22.1')
    p02.cmd('ip route add 10.100.2.0/30 via 10.0.22.1')
    p02.cmd('ip route add 10.3.0.0/16   via 10.0.11.2')
    p02.cmd('ip route add 10.100.3.0/30 via 10.0.11.2')

    # P03 routes
    p03 = net.get('p03')
    p03.cmd('ip route add 10.1.0.0/24   via 10.0.11.1')
    p03.cmd('ip route add 10.100.1.0/30 via 10.0.11.1')
    p03.cmd('ip route add 10.2.0.0/16   via 10.0.23.1')
    p03.cmd('ip route add 10.100.2.0/30 via 10.0.23.1')
    p03.cmd('ip route add 10.3.0.0/16   via 10.0.24.1')
    p03.cmd('ip route add 10.100.3.0/30 via 10.0.24.1')

    # P04 routes
    p04 = net.get('p04')
    p04.cmd('ip route add 10.1.0.0/24   via 10.0.14.1')
    p04.cmd('ip route add 10.100.1.0/30 via 10.0.14.1')
    p04.cmd('ip route add 10.2.0.0/16   via 10.0.12.1')
    p04.cmd('ip route add 10.100.2.0/30 via 10.0.12.1')
    p04.cmd('ip route add 10.3.0.0/16   via 10.0.25.1')
    p04.cmd('ip route add 10.100.3.0/30 via 10.0.25.1')

    info('*** Static routes configured (FRR fallback)\n')


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def run(interactive=True, use_frr=True, save_report=True):
    setLogLevel('info')

    # Load configs
    backbone_cfg_path = os.path.join(PROJECT_ROOT, 'configs', 'backbone', 'ip_plan.yaml')
    vpls_cfg_path     = os.path.join(PROJECT_ROOT, 'configs', 'backbone', 'vpls_policy.yaml')

    info(f'*** Loading backbone config: {backbone_cfg_path}\n')
    backbone_loader = BackboneConfigLoader(backbone_cfg_path)

    with open(vpls_cfg_path, 'r', encoding='utf-8') as f:
        vpls_config = yaml.safe_load(f)

    # Loaders cho từng chi nhánh (dùng để apply LAN config)
    branch_loaders = {
        'branch1': ConfigLoader(os.path.join(PROJECT_ROOT, 'configs', 'branch1', 'ip_plan.yaml')),
        'branch2': ConfigLoader(os.path.join(PROJECT_ROOT, 'configs', 'branch2', 'ip_plan.yaml')),
        'branch3': ConfigLoader(os.path.join(PROJECT_ROOT, 'configs', 'branch3', 'ip_plan.yaml')),
    }

    # Build topology
    info('\n*** Xây dựng Full Topology (MPLS Backbone + 3 Chi nhánh)\n')
    net = build_full_topology(backbone_loader)

    try:
        net.start()

        # Phase 1: Apply IP config
        info('\n*** Phase 1: Áp dụng IP Configuration\n')
        backbone_loader.apply_all(net)
        for branch_id, loader in branch_loaders.items():
            info(f'  Applying {branch_id} LAN config...\n')
            loader.apply_all(net, mode='full')

        # Phase 2: FRR hoặc Static Routes
        if use_frr:
            info('\n*** Phase 2: Triển khai FRR (OSPF + LDP + BGP)\n')
            frr_mgr = FRRManager(net)

            if frr_mgr.frr_available:
                # Deploy backbone routers
                frr_mgr.deploy_backbone()

                # ISP push CE configs
                frr_mgr.push_ce_configs()

                # Setup VPLS
                info('\n*** Phase 3: Setup VPLS\n')
                frr_mgr.setup_vpls_bridge(vpls_config)

                # Chờ convergence
                frr_mgr.wait_convergence(timeout=30)

                # Verify
                info('\n*** Phase 4: Verification\n')
                frr_mgr.verify_all()
            else:
                warn('[!] FRR unavailable, falling back to static routes\n')
                apply_static_routes(net)
        else:
            info('\n*** Phase 2: Cấu hình Static Routes (--no-frr mode)\n')
            apply_static_routes(net)

        # Phase 5: Connectivity Tests
        info('\n*** Phase 5: Connectivity Tests\n')
        tester = ConnectivityTest(net)
        reports = []

        # 5a: Backbone test
        backbone_report = tester.test_backbone_connectivity()
        tester.print_summary(backbone_report)
        reports.append(backbone_report)

        # 5b: Inter-branch test
        inter_report = tester.test_inter_branch(vpls_config)
        tester.print_summary(inter_report)
        reports.append(inter_report)

        # Save all reports
        if save_report:
            tester.save_all_reports(reports, os.path.join(PROJECT_ROOT, 'result'))

        # CLI
        if interactive:
            info('\n*** Entering Mininet CLI\n')
            info('*** Gợi ý inter-branch: pc01 ping lab01 | web01 ping admin01\n')
            info('*** Debug backbone: p01 ping 10.0.0.2 | pe01 ping 10.0.0.12\n')
            info('*** Debug MPLS: p01 ip -M route | pe01 vtysh -c "show mpls ldp neighbor"\n')
            CLI(net)

    finally:
        net.stop()
        info('*** Full MPLS Topology đã tắt\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Runner: Full MPLS MAN Topology (Backbone + 3 Branches)'
    )
    parser.add_argument('--test', action='store_true',
                        help='Chỉ chạy auto test')
    parser.add_argument('--no-frr', action='store_true',
                        help='Dùng static routes thay vì FRR')
    parser.add_argument('--no-report', action='store_true',
                        help='Không lưu báo cáo')
    args = parser.parse_args()

    run(
        interactive=not args.test,
        use_frr=not args.no_frr,
        save_report=not args.no_report,
    )
