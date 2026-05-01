#!/usr/bin/env python3
"""
runners/run_backbone.py
=======================
Runner: Kiểm tra hệ thống ISP Backbone (MPLS Core) — Giai đoạn 0

Mục đích:
  Kiểm tra toàn bộ hạ tầng ISP hoạt động đúng TRƯỚC KHI triển khai
  cấu hình xuống các chi nhánh. Đây là bước bắt buộc trong quy trình:

    [Phase 0] Backbone ISP test  ← file này
    [Phase 1] Branch isolated tests (run_branch1/2/3.py)
    [Phase 2] Full inter-branch MPLS VPLS (run_full_mpls.py)

Topology (backbone only, không có CE stubs):
    P01 ──1ms── P02 ──1ms── P03 ──1ms── P04
     └──2ms── P03    └──2ms── P04
    PE01 (dual: P01+P02)
    PE02 (dual: P02+P03)
    PE03 (dual: P03+P04)

Kiểm tra thực hiện:
  Test 1 — Link Connectivity:
    - Ping trực tiếp giữa các P-P interfaces (10.0.10.x/30...)
    - Ping PE-P interfaces (10.0.20.x/30...)

  Test 2 — Loopback Reachability (end-to-end backbone):
    - PE01 ping PE02 loopback (10.0.0.12)
    - PE01 ping PE03 loopback (10.0.0.13)
    - PE02 ping PE03 loopback (10.0.0.13)
    Đây là test quan trọng nhất: xác nhận OSPF học đúng routes

  Test 3 — FRR Protocol Verification (nếu FRR có sẵn):
    - OSPF neighbors (tất cả ở trạng thái Full)
    - LDP sessions (label exchange đã xảy ra)
    - BGP sessions PE-PE (Established cho VPLS signaling)
    - MPLS label table (labels đã được phân phối)

  Test 4 — MPLS Label Switching (data plane):
    - Trace MPLS path từ PE01 đến PE03 xem qua mấy hops
    - Verify labeled packet forwarding

Chạy:
  sudo python3 runners/run_backbone.py              # FRR + CLI
  sudo python3 runners/run_backbone.py --no-frr     # Static routes (debug)
  sudo python3 runners/run_backbone.py --test       # Auto test, không CLI
  sudo python3 runners/run_backbone.py --test --no-frr
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
from frr_manager import FRRManager
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
    """
    net = Mininet(controller=None, link=TCLink, waitConnected=False)

    # ---- Thêm Nodes (P + PE) ----
    info('\n*** Tạo Backbone Nodes (P + PE)\n')
    build_backbone_nodes(net, MPLSRouter)

    # ---- Thêm Links (P-P + PE-P) ----
    info('*** Kết nối Backbone Links (Core Mesh + Dual-homed)\n')
    build_backbone_links(net, backbone_loader)

    return net


# ----------------------------------------------------------------
# Backbone Specific Tests
# ----------------------------------------------------------------
def run_backbone_tests(net, tester):
    """
    Chạy đầy đủ backbone test suite.
    Trả về danh sách reports.
    """
    reports = []

    # =============================================
    # Test 1: P-P Direct Links
    # =============================================
    info('\n*** [Test 1] P-P Direct Link Connectivity\n')
    report1 = TestReport(
        name='Test 1 - P-P Direct Links',
        description='Ping trực tiếp giữa các P-Router qua P-P interfaces'
    )

    p_p_tests = [
        ('p01', '10.0.10.2', 'P01 → P02 (eth0)'),
        ('p02', '10.0.10.1', 'P02 → P01 (reverse)'),
        ('p02', '10.0.11.2', 'P02 → P03'),
        ('p03', '10.0.12.2', 'P03 → P04'),
        ('p01', '10.0.13.2', 'P01 → P03 diagonal'),
        ('p02', '10.0.14.2', 'P02 → P04 diagonal'),
    ]
    for router, target_ip, label in p_p_tests:
        result = tester._ping_ip(router, target_ip, label)
        report1.add(result)
        info(f'  {result}\n')
    report1.finish()
    reports.append(report1)

    # =============================================
    # Test 2: PE-P Links
    # =============================================
    info('\n*** [Test 2] PE-P Link Connectivity\n')
    report2 = TestReport(
        name='Test 2 - PE-P Links',
        description='Ping giữa PE và P routers qua WAN uplinks'
    )

    pe_p_tests = [
        ('pe01', '10.0.20.2', 'PE01 → P01 (primary)'),
        ('p01',  '10.0.20.1', 'P01 → PE01 (reverse)'),
        ('pe01', '10.0.21.2', 'PE01 → P02 (alternate)'),
        ('pe02', '10.0.22.2', 'PE02 → P02 (primary)'),
        ('pe02', '10.0.23.2', 'PE02 → P03 (alternate)'),
        ('pe03', '10.0.24.2', 'PE03 → P03 (primary)'),
        ('pe03', '10.0.25.2', 'PE03 → P04 (alternate)'),
    ]
    for router, target_ip, label in pe_p_tests:
        result = tester._ping_ip(router, target_ip, label)
        report2.add(result)
        info(f'  {result}\n')
    report2.finish()
    reports.append(report2)

    # =============================================
    # Test 3: PE Loopback Reachability (End-to-End)
    # =============================================
    info('\n*** [Test 3] PE Loopback Reachability (End-to-End Backbone)\n')
    info('    (Xác nhận OSPF/routing đã học đúng full-mesh path)\n')
    report3 = TestReport(
        name='Test 3 - PE Loopback Reachability',
        description='PE-to-PE loopback ping — xác nhận full-mesh OSPF/routing'
    )

    loopback_tests = [
        ('pe01', '10.0.0.12', 'PE01 → PE02 loopback (B1→B2 path)'),
        ('pe01', '10.0.0.13', 'PE01 → PE03 loopback (B1→B3 path)'),
        ('pe02', '10.0.0.11', 'PE02 → PE01 loopback (B2→B1 path)'),
        ('pe02', '10.0.0.13', 'PE02 → PE03 loopback (B2→B3 path)'),
        ('pe03', '10.0.0.11', 'PE03 → PE01 loopback (B3→B1 path)'),
        ('pe03', '10.0.0.12', 'PE03 → PE02 loopback (B3→B2 path)'),
        # P-to-PE loopback (P phải biết route đến PE loopbacks)
        ('p01',  '10.0.0.12', 'P01 → PE02 loopback'),
        ('p02',  '10.0.0.13', 'P02 → PE03 loopback'),
        ('p04',  '10.0.0.11', 'P04 → PE01 loopback'),
    ]
    for router, target_ip, label in loopback_tests:
        result = tester._ping_ip(router, target_ip, label)
        report3.add(result)
        info(f'  {result}\n')
    report3.finish()
    reports.append(report3)

    return reports


def run_frr_verification(net, frr_mgr=None):
    """
    Test 4: Kiểm tra FRR protocol state.
    Dùng per-node socket (nếu có) để chạy vtysh commands.
    """
    info('\n*** [Test 4] FRR Protocol Verification\n')
    info('    (Kiểm tra OSPF neighbors, LDP sessions, BGP state)\n')

    if frr_mgr is None:
        frr_mgr = FRRManager(net)
    if not frr_mgr.frr_available:
        warn('    [SKIP] FRR không khả dụng trên hệ thống này\n')
        return

    all_routers = ['p01', 'p02', 'p03', 'p04', 'pe01', 'pe02', 'pe03']

    # [4-pre] Kiểm tra FRR daemons thực sự chạy
    info('\n  [4-pre] FRR Daemon Process Check:\n')
    for rname in all_routers:
        node = net.get(rname)
        if node is None:
            continue
        procs = node.cmd('ps aux 2>/dev/null | grep -E "(zebra|ospfd|ldpd|bgpd)" | grep -v grep')
        running = []
        for daemon in ['zebra', 'ospfd', 'ldpd', 'bgpd']:
            if daemon in procs:
                running.append(daemon)
        if running:
            info(f'  [{rname}] Running: {", ".join(running)}\n')
        else:
            warn(f'  [{rname}] WARNING: Không có FRR daemon nào đang chạy!\n')

    # OSPF neighbors
    info('\n  [4a] OSPF Neighbors:\n')
    ospf_ok = True
    for rname in all_routers:
        node = net.get(rname)
        if node is None:
            continue
        result = frr_mgr._vtysh(node, rname, 'show ip ospf neighbor')
        full_count = result.count('Full')
        info(f'  [{rname}] Full neighbors: {full_count}\n')
        for line in result.strip().split('\n'):
            if 'Full' in line or 'neighbor' in line.lower():
                info(f'    {line}\n')
        if full_count == 0:
            warn(f'  [WARN] {rname}: Không có OSPF neighbor ở trạng thái Full\n')
            ospf_ok = False

    # LDP sessions
    info('\n  [4b] LDP Sessions:\n')
    for rname in all_routers:
        node = net.get(rname)
        if node is None:
            continue
        result = frr_mgr._vtysh(node, rname, 'show mpls ldp neighbor')
        info(f'  [{rname}] LDP:\n')
        for line in result.strip().split('\n')[:4]:
            if line.strip():
                info(f'    {line}\n')

    # BGP (PE only)
    info('\n  [4c] BGP Sessions (PE-PE iBGP for VPLS):\n')
    for rname in ['pe01', 'pe02', 'pe03']:
        node = net.get(rname)
        if node is None:
            continue
        result = frr_mgr._vtysh(node, rname, 'show bgp l2vpn evpn summary')
        if 'not running' in result.lower() or 'vtysh' in result.lower():
            result = frr_mgr._vtysh(node, rname, 'show bgp summary')
        established = result.count('Established')
        info(f'  [{rname}] BGP Established sessions: {established}\n')
        for line in result.strip().split('\n'):
            if 'Established' in line or 'Summary' in line or 'Neighbor' in line:
                info(f'    {line}\n')

    # MPLS labels
    info('\n  [4d] MPLS Label Table (mẫu):\n')
    for rname in ['p01', 'pe01']:
        node = net.get(rname)
        if node is None:
            continue
        result = node.cmd('ip -M route 2>/dev/null || echo "MPLS not available"')
        info(f'  [{rname}] MPLS routes (5 dòng đầu):\n')
        for line in result.strip().split('\n')[:5]:
            if line.strip():
                info(f'    {line}\n')

    # Traceroute backbone (P01 -> PE03 qua MPLS)
    info('\n  [4e] Traceroute P01 → PE03 (kiểm tra path):\n')
    p01 = net.get('p01')
    if p01:
        trace = p01.cmd('traceroute -n -m 8 10.0.0.13 2>/dev/null || '
                        'traceroute -n -m 8 -w 1 10.0.0.13')
        for line in trace.strip().split('\n'):
            if line.strip():
                info(f'    {line}\n')


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def run(interactive=True, use_frr=False, save_report=True):
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
        # Khi dùng static MPLS: cần static routes cho IP reachability
        # Khi dùng FRR: OSPF sẽ quản lý routes
        backbone_loader.apply_all(net, skip_routes=use_frr)

        # ---- Phase 0b: Deploy MPLS ----
        frr_mgr = None
        mpls_mgr = None

        if use_frr:
            # FRR Daemons mode (experimental)
            info('\n*** [Phase 0b] Triển khai FRR Daemons (experimental)\n')
            frr_mgr = FRRManager(net)
            if frr_mgr.frr_available:
                frr_mgr.deploy_backbone()
                info('\n*** Chờ OSPF + LDP hội tụ (30 giây)...\n')
                frr_mgr.wait_convergence(timeout=30)
            else:
                warn('[!] FRR không khả dụng — fallback về Static MPLS\n')
                backbone_loader.apply_all(net, skip_routes=False)
                mpls_mgr = StaticMPLSManager(net)
                mpls_mgr.deploy_all()
        else:
            # Static MPLS mode (default — reliable)
            info('\n*** [Phase 0b] Triển khai Static MPLS + GRE VPLS\n')
            info('    (Static routes + MPLS labels + GRE pseudowires)\n')
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

        # ---- Phase 0d: MPLS/FRR Verification ----
        if use_frr and frr_mgr:
            run_frr_verification(net, frr_mgr=frr_mgr)
        elif mpls_mgr:
            mpls_mgr.verify_mpls()
            mpls_mgr.verify_vpls()

        # Save reports
        if save_report:
            tester.save_all_reports(reports, os.path.join(PROJECT_ROOT, 'result'))

        # CLI
        if interactive:
            info('\n*** Entering Mininet CLI (ISP Backbone)\n')
            info('*** MPLS labels:  p01  ip -M route\n')
            info('*** VPLS bridge:  pe01 bridge link show\n')
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
Quy trình kiểm tra đề xuất:
  1. sudo python3 runners/run_backbone.py --test       # Phase 0: ISP
  2. sudo python3 runners/run_branch1.py  --test       # Phase 1: Branch
  3. sudo python3 runners/run_branch2.py  --test
  4. sudo python3 runners/run_branch3.py  --test
  5. sudo python3 runners/run_full_mpls.py             # Phase 2: Full MPLS
        """
    )
    parser.add_argument(
        '--test', action='store_true',
        help='Chỉ chạy auto test, không mở CLI'
    )
    parser.add_argument(
        '--frr', action='store_true',
        help='Dùng FRR daemons (OSPF+LDP+BGP) thay vì Static MPLS'
    )
    parser.add_argument(
        '--no-frr', action='store_true',
        help='[Legacy] Giống mặc định (Static MPLS)'
    )
    parser.add_argument(
        '--no-report', action='store_true',
        help='Không lưu file report'
    )
    args = parser.parse_args()

    run(
        interactive=not args.test,
        use_frr=args.frr,
        save_report=not args.no_report,
    )
