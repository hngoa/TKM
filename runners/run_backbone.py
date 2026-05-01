#!/usr/bin/env python3
"""
runners/run_backbone.py
========================
Runner: ISP MPLS Backbone Test (Phase 0)

Kiểm tra kết nối nội bộ MPLS Backbone trước khi triển khai chi nhánh.
Sử dụng Static MPLS labels + GRE VPLS pseudowires.

Quy trình:
  1. Build backbone topology (P01-P04, PE01-PE03)
  2. Áp dụng IP config từ ip_plan.yaml (loopback + interfaces + static routes)
  3. Triển khai Static MPLS (push/swap/pop labels + GRETAP VPLS)
  4. Chạy connectivity tests
  5. Hiển thị MPLS/VPLS verification

Chạy:
    sudo python3 runners/run_backbone.py --test     # Auto test
    sudo python3 runners/run_backbone.py            # Test + CLI

Quy trình kiểm tra đề xuất:
  1. sudo python3 runners/run_backbone.py --test       # Phase 0: ISP Backbone
  2. sudo python3 runners/run_branch1.py  --test       # Phase 1: Branch tests
  3. sudo python3 runners/run_branch2.py  --test
  4. sudo python3 runners/run_branch3.py  --test
  5. sudo python3 runners/run_full_mpls.py --test      # Phase 2: Full MPLS
"""

import sys
import os
import time
import argparse

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'tools'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'topologies'))

from mininet.net import Mininet
from mininet.link import TCLink
from mininet.log import setLogLevel, info, warn
from mininet.cli import CLI

from node_types import MPLSRouter
from config_loader import BackboneConfigLoader
from static_mpls import StaticMPLSManager
from connectivity_test import ConnectivityTest, TestReport, TestResult

# --- Topology builder ---
from backbone import build_backbone_nodes, build_backbone_links


# ----------------------------------------------------------------
# Build Backbone Topology
# ----------------------------------------------------------------
def build_backbone(backbone_loader):
    """
    Xây dựng topology backbone qua builder functions (tái sử dụng).

    P-Routers: p01, p02, p03, p04 (MPLS Core)
    PE-Routers: pe01, pe02, pe03 (Provider Edge)

    Topology:
                     P01 ──── P02
                    / |  ╲   / |  ╲
                PE01  |   ╲ /  |  PE02
                      |   P03  |
                      |  / | ╲ |
                     P04   |  PE03
                           |
                         (diagonal links: P01-P03, P02-P04)
    """
    net = Mininet(
        controller=None,
        link=TCLink,
        waitConnected=False,
    )

    build_backbone_nodes(net, router_cls=MPLSRouter)
    build_backbone_links(net, backbone_loader=backbone_loader)

    return net


# ----------------------------------------------------------------
# Backbone Tests
# ----------------------------------------------------------------
def run_backbone_tests(net, tester):
    """Chạy 3 bộ test backbone: P-P links, PE-P links, PE loopback."""
    reports = []

    # Test 1: P-P Direct links (5 links)
    report1 = TestReport(name='Test 1: P-P Links',
                         description='Kiểm tra kết nối trực tiếp giữa P-Routers')
    p_tests = [
        ('p01', '10.0.10.2', 'P01→P02'),
        ('p02', '10.0.11.2', 'P02→P03'),
        ('p03', '10.0.12.2', 'P03→P04'),
        ('p01', '10.0.13.2', 'P01→P03 diagonal'),
        ('p02', '10.0.14.2', 'P02→P04 diagonal'),
    ]
    info('\n*** [Test 1] P-P Direct Links\n')
    for router, ip, label in p_tests:
        result = tester._ping_ip(router, ip, label)
        report1.add(result)
        icon = '✓' if result.status == 'PASS' else '✗'
        info(f'  [{icon}] {label}: {result.status}\n')
    report1.finish()
    reports.append(report1)

    # Test 2: PE-P links (6 links)
    report2 = TestReport(name='Test 2: PE-P Links',
                         description='Kiểm tra kết nối PE→P (dual-homed)')
    pe_tests = [
        ('pe01', '10.0.20.2', 'PE01→P01'),
        ('pe01', '10.0.21.2', 'PE01→P02'),
        ('pe02', '10.0.22.2', 'PE02→P02'),
        ('pe02', '10.0.23.2', 'PE02→P03'),
        ('pe03', '10.0.24.2', 'PE03→P03'),
        ('pe03', '10.0.25.2', 'PE03→P04'),
    ]
    info('\n*** [Test 2] PE-P Links (Dual-Homed)\n')
    for router, ip, label in pe_tests:
        result = tester._ping_ip(router, ip, label)
        report2.add(result)
        icon = '✓' if result.status == 'PASS' else '✗'
        info(f'  [{icon}] {label}: {result.status}\n')
    report2.finish()
    reports.append(report2)

    # Test 3: PE Loopback reachability (qua backbone)
    report3 = TestReport(name='Test 3: PE Loopback Reachability',
                         description='Kiểm tra PE loopback qua MPLS backbone')
    lo_tests = [
        ('pe01', '10.0.0.2',  'PE01→P02 lo'),
        ('pe01', '10.0.0.3',  'PE01→P03 lo'),
        ('pe01', '10.0.0.4',  'PE01→P04 lo'),
        ('pe01', '10.0.0.12', 'PE01→PE02 lo'),
        ('pe01', '10.0.0.13', 'PE01→PE03 lo'),
        ('pe02', '10.0.0.11', 'PE02→PE01 lo'),
        ('pe02', '10.0.0.13', 'PE02→PE03 lo'),
        ('pe03', '10.0.0.11', 'PE03→PE01 lo'),
        ('pe03', '10.0.0.12', 'PE03→PE02 lo'),
        ('p01',  '10.0.0.4',  'P01→P04 lo'),
        ('p04',  '10.0.0.1',  'P04→P01 lo'),
    ]
    info('\n*** [Test 3] PE Loopback Reachability\n')
    for router, ip, label in lo_tests:
        result = tester._ping_ip(router, ip, label)
        report3.add(result)
        icon = '✓' if result.status == 'PASS' else '✗'
        info(f'  [{icon}] {label}: {result.status}\n')
    report3.finish()
    reports.append(report3)

    return reports


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def run(interactive=True, save_report=True):
    setLogLevel('info')

    # Load backbone config
    cfg_path = os.path.join(PROJECT_ROOT, 'configs', 'backbone', 'ip_plan.yaml')
    info(f'*** Loading backbone config: {cfg_path}\n')
    backbone_loader = BackboneConfigLoader(cfg_path)

    # Build topology
    info('\n*** Xây dựng Backbone Topology (MPLS Core ISP)\n')
    net = build_backbone(backbone_loader)

    try:
        net.start()
        time.sleep(1)  # Đợi interfaces khởi động

        # ---- Phase 0a: Apply IP Config ----
        info('\n*** [Phase 0a] Áp dụng cấu hình IP backbone\n')
        backbone_loader.apply_all(net, skip_routes=False)

        # ---- Phase 0b: Deploy Static MPLS ----
        info('\n*** [Phase 0b] Triển khai Static MPLS + GRE VPLS\n')
        info('    (Static routes + MPLS labels + GRETAP pseudowires)\n')
        mpls_mgr = StaticMPLSManager(net)
        mpls_mgr.deploy_all()

        # ---- Phase 0c: Connectivity Tests ----
        info('\n*** [Phase 0c] Chạy Backbone Connectivity Tests\n')
        tester = ConnectivityTest(net)
        reports = run_backbone_tests(net, tester)

        # Print summaries
        info('\n' + '='*60 + '\n')
        info('  BACKBONE TEST SUMMARY\n')
        info('='*60 + '\n')
        total_pass = sum(r.passed for r in reports)
        total_all  = sum(r.total  for r in reports)
        for rep in reports:
            icon = '✓' if rep.pass_rate == 100 else ('~' if rep.pass_rate >= 50 else '✗')
            info(f'  [{icon}] {rep.name}: {rep.passed}/{rep.total} PASS '
                 f'({rep.pass_rate:.0f}%)\n')

        info(f'\n  Tổng: {total_pass}/{total_all} tests PASSED\n')

        if total_pass == total_all:
            info('  ✅ ISP BACKBONE OK — Sẵn sàng triển khai config xuống chi nhánh!\n')
            info('     Bước tiếp: sudo python3 runners/run_branch1.py --test\n')
        elif total_pass >= total_all * 0.7:
            warn('  ⚠  Backbone cơ bản hoạt động nhưng còn một số lỗi.\n')
        else:
            warn('  ✗  BACKBONE CÓ VẤN ĐỀ NGHIÊM TRỌNG!\n')

        # ---- Phase 0d: MPLS/VPLS Verification ----
        mpls_mgr.verify_mpls()
        mpls_mgr.verify_vpls()

        # Save reports
        if save_report:
            tester.save_all_reports(reports, os.path.join(PROJECT_ROOT, 'result'))

        # CLI
        if interactive:
            info('\n*** Entering Mininet CLI (ISP Backbone)\n')
            info('*** MPLS labels:  p01  ip -M route\n')
            info('*** VPLS bridge:  pe01 brctl show vpls-br\n')
            info('*** Ping PE:      pe01 ping 10.0.0.12\n')
            info('*** Traceroute:   pe01 traceroute -n 10.0.0.13\n')
            CLI(net)

    finally:
        net.stop()
        info('*** Backbone topology đã tắt\n')


# ----------------------------------------------------------------
# Entrypoint
# ----------------------------------------------------------------
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Runner: ISP MPLS Backbone Test (Phase 0)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Quy trình kiểm tra:
  1. sudo python3 runners/run_backbone.py --test       # Backbone
  2. sudo python3 runners/run_branch1.py  --test       # Branch 1
  3. sudo python3 runners/run_branch2.py  --test       # Branch 2
  4. sudo python3 runners/run_branch3.py  --test       # Branch 3
  5. sudo python3 runners/run_full_mpls.py --test      # Full MPLS
        """
    )
    parser.add_argument(
        '--test', action='store_true',
        help='Chỉ chạy auto test, không mở CLI'
    )
    parser.add_argument(
        '--no-report', action='store_true',
        help='Không lưu file report'
    )
    args = parser.parse_args()

    run(
        interactive=not args.test,
        save_report=not args.no_report,
    )
