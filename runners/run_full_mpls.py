#!/usr/bin/env python3
"""
runners/run_full_mpls.py
========================
Runner: Full Topology — MPLS MAN với VPLS liên chi nhánh

Giai đoạn 2: Test kết nối liên chi nhánh qua MPLS Backbone.

Quy trình:
  1. Build full topology (backbone + 3 branches)
  2. Áp dụng IP config từ YAML (backbone + branches)
  3. Triển khai Static MPLS + GRE VPLS + inter-branch routes
  4. Test: backbone connectivity + inter-branch connectivity
  5. MPLS/VPLS verification

Chạy:
    sudo python3 runners/run_full_mpls.py            # Full run + CLI
    sudo python3 runners/run_full_mpls.py --test     # Auto test only
"""

import sys
import os
import time
import argparse
import yaml

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'tools'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'topologies'))

from mininet.log import setLogLevel, info, warn
from mininet.cli import CLI
from mininet.clean import cleanup as mn_cleanup

# Topology builder
from full_topology import build_full_topology

# Tools
from config_loader import ConfigLoader, BackboneConfigLoader
from static_mpls import StaticMPLSManager
from connectivity_test import ConnectivityTest


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def run(interactive=True, save_report=True):
    setLogLevel('info')

    # ---- Cleanup stale Mininet state ----
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

    # ---- Build topology ----
    info('\n*** Xây dựng Full Topology (MPLS Backbone + 3 Chi nhánh)\n')
    net = build_full_topology(
        backbone_loader=backbone_loader,
        branch_loaders=branch_loaders,
    )

    try:
        net.start()
        info('\n*** Đang đợi interfaces sẵn sàng (5s)...\n')
        time.sleep(5)

        # ---- Phase 1: Apply IP Configuration ----
        info('\n*** Phase 1: Áp dụng IP Configuration (từ YAML)\n')
        backbone_loader.apply_all(net, skip_routes=False)

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

        # ---- Phase 2: Deploy Static MPLS + GRE VPLS ----
        info('\n*** Phase 2: Triển khai Static MPLS + GRE VPLS\n')
        info('    (MPLS labels + GRETAP pseudowires + inter-branch routes)\n')
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
        mpls_mgr.verify_mpls()
        mpls_mgr.verify_vpls()

        if save_report:
            tester.save_all_reports(reports, os.path.join(PROJECT_ROOT, 'result'))

        # CLI
        if interactive:
            info('\n*** Entering Mininet CLI\n')
            info('*** MPLS labels:    p01  ip -M route\n')
            info('*** VPLS bridge:    pe01 brctl show vpls-br\n')
            info('*** GRE tunnels:    pe01 ip -d link show type gretap\n')
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
Ví dụ:
  sudo python3 runners/run_full_mpls.py --test     # Auto test
  sudo python3 runners/run_full_mpls.py            # Test + CLI
        """
    )
    parser.add_argument('--test', action='store_true',
                        help='Chỉ chạy auto test, không mở CLI')
    parser.add_argument('--no-report', action='store_true',
                        help='Không lưu báo cáo')
    args = parser.parse_args()

    run(
        interactive=not args.test,
        save_report=not args.no_report,
    )
