#!/usr/bin/env python3
"""
runners/run_full_mpls.py
========================
Runner: Full Topology — MPLS MAN với VPLS liên chi nhánh

Giai đoạn 2: Test kết nối liên chi nhánh qua MPLS Backbone.

Quy trình chạy:
  1. Load configs từ YAML (backbone + 3 branch) — nguồn duy nhất cho mọi cấu hình
  2. Build full topology qua build_full_topology() — tái sử dụng builders
  3. net.start() → loader.apply_all() — IP hoàn toàn từ YAML
  4. Deploy MPLS:
     - Mặc định: Static MPLS labels + GRE VPLS (reliable)
     - --frr:    FRR daemons OSPF + LDP + BGP (experimental)
  5. Test connectivity: backbone + inter-branch

Chạy:
    sudo python3 runners/run_full_mpls.py            # Static MPLS + CLI
    sudo python3 runners/run_full_mpls.py --test     # Auto test only
    sudo python3 runners/run_full_mpls.py --frr      # FRR daemons (experimental)
"""

import sys
import os
import time
import argparse
import subprocess
import yaml

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'tools'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'topologies'))

from mininet.log import setLogLevel, info, warn
from mininet.cli import CLI
from mininet.clean import cleanup as mn_cleanup

# Topology builder — tái sử dụng từ topologies/, không tự viết lại
from full_topology import build_full_topology

# Tools
from config_loader import ConfigLoader, BackboneConfigLoader
from frr_manager import FRRManager
from static_mpls import StaticMPLSManager
from connectivity_test import ConnectivityTest


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def run(interactive=True, use_frr=False, save_report=True):
    setLogLevel('info')

    # ---- Cleanup stale Mininet state từ lần chạy trước ----
    info('*** Cleaning up stale Mininet state...\n')
    try:
        mn_cleanup()
    except Exception as e:
        warn(f'[!] Cleanup warning (non-fatal): {e}\n')
    info('*** Cleanup done\n')

    # ---- Load configs (YAML là nguồn duy nhất) ----
    backbone_cfg_path = os.path.join(PROJECT_ROOT, 'configs', 'backbone', 'ip_plan.yaml')
    vpls_cfg_path     = os.path.join(PROJECT_ROOT, 'configs', 'backbone', 'vpls_policy.yaml')

    info(f'*** Loading backbone config: {backbone_cfg_path}\n')
    backbone_loader = BackboneConfigLoader(backbone_cfg_path)

    with open(vpls_cfg_path, 'r', encoding='utf-8') as f:
        vpls_config = yaml.safe_load(f)

    branch_loaders = {
        'branch1': ConfigLoader(os.path.join(PROJECT_ROOT, 'configs', 'branch1', 'ip_plan.yaml')),
        'branch2': ConfigLoader(os.path.join(PROJECT_ROOT, 'configs', 'branch2', 'ip_plan.yaml')),
        'branch3': ConfigLoader(os.path.join(PROJECT_ROOT, 'configs', 'branch3', 'ip_plan.yaml')),
    }

    # ---- Build topology — tái sử dụng builder functions từ topologies/ ----
    info('\n*** Xây dựng Full Topology (MPLS Backbone + 3 Chi nhánh)\n')
    net = build_full_topology(
        backbone_loader=backbone_loader,
        branch_loaders=branch_loaders,
    )

    try:
        net.start()
        info('\n*** Đang đợi interfaces sẵn sàng (5s)...\n')
        time.sleep(5)

        # ---- Phase 1: Apply IP Configuration từ YAML ----
        info('\n*** Phase 1: Áp dụng IP Configuration (từ YAML)\n')
        # Backbone: loopbacks, P/PE interfaces, CE WAN
        # Khi dùng static MPLS: cần static routes (skip_routes=False)
        # Khi dùng FRR: OSPF quản lý routes (skip_routes=True)
        backbone_loader.apply_all(net, skip_routes=use_frr)

        # Branch LAN: CE LAN interfaces + hosts
        for branch_id, loader in branch_loaders.items():
            info(f'  Applying {branch_id} LAN config...\n')
            loader.apply_all(net, mode='full')

        info('\n*** Đang đợi ARP/routing ổn định (3s)...\n')
        time.sleep(3)

        # ---- Sanity check ----
        info('\n*** [Sanity] Kiểm tra IP trên backbone key nodes:\n')
        for node_name, intf_name in [
            ('pe01', 'pe01-p01'), ('pe01', 'pe01-p02'),
            ('pe02', 'pe02-p02'), ('pe03', 'pe03-p03'),
            ('p01',  'p01-pe01'), ('p02',  'p02-pe01'),
        ]:
            node = net.get(node_name)
            if node:
                ip_out = node.cmd(f'ip addr show {intf_name} 2>/dev/null | grep -oP "(?<=inet )[\\d.]+/\\d+"').strip()
                info(f'  {node_name} {intf_name}: {ip_out or "NO IP!"}\n')

        # ---- Phase 2: Deploy MPLS ----
        frr_mgr = None
        mpls_mgr = None

        if use_frr:
            # FRR Daemons mode (experimental)
            info('\n*** Phase 2: Triển khai FRR Daemons (experimental)\n')
            frr_mgr = FRRManager(net)
            if frr_mgr.frr_available:
                frr_mgr.deploy_backbone()
                frr_mgr.push_ce_configs()
                info('\n*** Phase 2b: Setup VPLS (FRR bridge)\n')
                frr_mgr.setup_vpls_bridge(vpls_config)
                frr_mgr.wait_convergence(timeout=30)
                info('\n*** Phase 2c: FRR Verification\n')
                frr_mgr.verify_all()
            else:
                warn('[!] FRR không khả dụng — fallback về Static MPLS\n')
                backbone_loader.apply_all(net, skip_routes=False)
                mpls_mgr = StaticMPLSManager(net)
                mpls_mgr.deploy_all()
        else:
            # Static MPLS mode (default — reliable)
            info('\n*** Phase 2: Triển khai Static MPLS + GRE VPLS\n')
            info('    (Static routes + MPLS labels + GRE pseudowires)\n')
            mpls_mgr = StaticMPLSManager(net)
            mpls_mgr.deploy_all()

        # ---- Phase 3: Connectivity Tests ----
        info('\n*** Phase 3: Connectivity Tests\n')
        tester = ConnectivityTest(net)
        reports = []

        backbone_report = tester.test_backbone_connectivity()
        tester.print_summary(backbone_report)
        reports.append(backbone_report)

        inter_report = tester.test_inter_branch(vpls_config)
        tester.print_summary(inter_report)
        reports.append(inter_report)

        # ---- Phase 4: MPLS/VPLS Verification ----
        if mpls_mgr:
            mpls_mgr.verify_mpls()
            mpls_mgr.verify_vpls()

        if save_report:
            tester.save_all_reports(reports, os.path.join(PROJECT_ROOT, 'result'))

        # CLI
        if interactive:
            info('\n*** Entering Mininet CLI\n')
            info('*** MPLS labels:    p01  ip -M route\n')
            info('*** VPLS bridge:    pe01 brctl show vpls-br\n')
            info('*** GRE tunnels:    pe01 ip tunnel show\n')
            info('*** Inter-branch:   pc01 ping 10.2.10.11 (lab01 B2)\n')
            info('***                 lab01 ping 10.3.10.11 (web01 B3)\n')
            info('*** PE loopback:    pe01 ping 10.0.0.12\n')
            info('*** Traceroute:     pe01 traceroute -n 10.0.0.13\n')
            CLI(net)

    finally:
        net.stop()
        info('*** Full MPLS Topology đã tắt\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Runner: Full MPLS MAN Topology (Backbone + 3 Branches)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Mặc định: Static MPLS + GRE VPLS (reliable, không cần FRR daemons)
Thêm --frr để dùng FRR OSPF+LDP+BGP (experimental)

Ví dụ:
  sudo python3 runners/run_full_mpls.py --test     # Auto test
  sudo python3 runners/run_full_mpls.py --frr      # FRR daemons
        """
    )
    parser.add_argument('--test', action='store_true',
                        help='Chỉ chạy auto test, không mở CLI')
    parser.add_argument('--frr', action='store_true',
                        help='Dùng FRR daemons (OSPF+LDP+BGP) thay vì Static MPLS')
    parser.add_argument('--no-frr', action='store_true',
                        help='[Legacy] Giống mặc định (Static MPLS)')
    parser.add_argument('--no-report', action='store_true',
                        help='Không lưu báo cáo')
    args = parser.parse_args()

    run(
        interactive=not args.test,
        use_frr=args.frr,
        save_report=not args.no_report,
    )
