#!/usr/bin/env python3
"""
runners/run_full_mpls.py
========================
Runner: Full Topology — MPLS MAN với VPLS liên chi nhánh

Giai đoạn 2: Test kết nối liên chi nhánh qua MPLS Backbone.

Quy trình chạy:
  1. Load configs từ YAML (backbone + 3 branch) — nguồn duy nhất cho mọi cấu hình
  2. Build full topology qua build_full_topology() — tái sử dụng builders
  3. net.start() → loader.apply_all() trên mỗi loader → IP hoàn toàn từ YAML
  4. Deploy FRR (OSPF + LDP + BGP) hoặc static routes fallback
  5. Setup VPLS, chờ converge, verify, test connectivity

Chạy:
    sudo python3 runners/run_full_mpls.py            # Full run + CLI
    sudo python3 runners/run_full_mpls.py --test     # Auto test only
    sudo python3 runners/run_full_mpls.py --no-frr   # Static routes, không FRR
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
from connectivity_test import ConnectivityTest


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def run(interactive=True, use_frr=True, save_report=True):
    setLogLevel('info')

    # ---- Cleanup stale Mininet state từ lần chạy trước ----
    # Tránh lỗi "RTNETLINK answers: File exists" khi tạo veth pairs
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
        # Backbone: loopbacks, P/PE interfaces, CE WAN interfaces + static routes
        backbone_loader.apply_all(net)
        # Branch LAN: CE LAN interfaces + hosts
        for branch_id, loader in branch_loaders.items():
            info(f'  Applying {branch_id} LAN config...\n')
            loader.apply_all(net, mode='full')

        # Đợi ARP/routing table ổn định sau khi apply IP
        info('\n*** Đang đợi ARP/routing ổn định (3s)...\n')
        time.sleep(3)

        # ---- Quick sanity check: xác nhận IP đã assign đúng ----
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

        if use_frr:
            info('\n*** Phase 2: Triển khai FRR (OSPF + LDP + BGP)\n')
            frr_mgr = FRRManager(net)

            if frr_mgr.frr_available:
                frr_mgr.deploy_backbone()
                frr_mgr.push_ce_configs()

                info('\n*** Phase 3: Setup VPLS\n')
                frr_mgr.setup_vpls_bridge(vpls_config)

                frr_mgr.wait_convergence(timeout=30)

                info('\n*** Phase 4: Verification\n')
                frr_mgr.verify_all()
            else:
                warn('[!] FRR unavailable — chạy với static routes từ YAML\n')
                info('[*] Static routes đã được apply trong Phase 1 (backbone_loader.apply_all)\n')
                info('[*] Để dùng dynamic routing: sudo apt install -y frr frr-pythontools\n')
        else:
            info('\n*** Phase 2: --no-frr mode — Dùng Static Routes từ YAML\n')
            info('    Static routes đã được apply trong Phase 1 (backbone_loader.apply_all)\n')

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

        if save_report:
            tester.save_all_reports(reports, os.path.join(PROJECT_ROOT, 'result'))

        # CLI
        if interactive:
            info('\n*** Entering Mininet CLI\n')
            info('*** Gợi ý inter-branch: pc01 ping lab01 | web01 ping admin01\n')
            info('*** Debug backbone:     p01 ping 10.0.0.2 | pe01 ping 10.0.0.12\n')
            info('*** Debug MPLS:         p01 ip -M route\n')
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
                        help='Bỏ qua FRR (static routes từ YAML ce_router.static_routes)')
    parser.add_argument('--no-report', action='store_true',
                        help='Không lưu báo cáo')
    args = parser.parse_args()

    run(
        interactive=not args.test,
        use_frr=not args.no_frr,
        save_report=not args.no_report,
    )
