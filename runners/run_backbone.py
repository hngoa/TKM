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

from mininet.net import Mininet
from mininet.link import TCLink
from mininet.log import setLogLevel, info, warn
from mininet.cli import CLI

from node_types import MPLSRouter       # dùng chung từ tools/node_types.py
from config_loader import BackboneConfigLoader
from frr_manager import FRRManager
from connectivity_test import ConnectivityTest, TestReport, TestResult


# ----------------------------------------------------------------
# Build Backbone Topology
# ----------------------------------------------------------------
def build_backbone(backbone_loader):
    """
    Xây dựng topology backbone thuần túy: P01-P04, PE01-PE03.
    Không có CE, không có LAN hosts.

    Interface naming convention (khớp với FRR config):
      p01-eth0  (P01 -> P02)
      p01-eth1  (P01 -> P03 diagonal)
      p01-pe01  (P01 -> PE01)
      pe01-p01  (PE01 -> P01)
      pe01-p02  (PE01 -> P02)
    """
    net = Mininet(controller=None, link=TCLink, waitConnected=False)

    # ---- P-Routers (core label switching) ----
    info('*** Tạo P-Routers (Core MPLS)\n')
    for name in ['p01', 'p02', 'p03', 'p04']:
        net.addHost(name, cls=MPLSRouter, ip=None)

    # ---- PE-Routers (edge VPLS endpoints) ----
    info('*** Tạo PE-Routers (Edge MPLS)\n')
    for name in ['pe01', 'pe02', 'pe03']:
        net.addHost(name, cls=MPLSRouter, ip=None)

    # ---- Backbone P-P Links ----
    info('*** Kết nối P-P links (Partial Mesh)\n')
    p_p_links = backbone_loader.get_backbone_links()
    if p_p_links:
        for link_cfg in p_p_links:
            net.addLink(
                link_cfg['src'], link_cfg['dst'],
                bw=link_cfg.get('bw', 1000),
                delay=link_cfg.get('delay', '1ms'),
                intfName1=link_cfg.get('src_intf', ''),
                intfName2=link_cfg.get('dst_intf', ''),
            )
    else:
        # Fallback: dùng interface names theo convention FRR config
        info('  [INFO] Không có backbone_links trong YAML, dùng config mặc định\n')
        _build_default_p_p_links(net)

    # ---- PE-P Links (Dual-homed) ----
    info('*** Kết nối PE-P links (Dual-homed)\n')
    pe_p_links = backbone_loader.get_pe_p_links()
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
        _build_default_pe_p_links(net)

    return net


def _build_default_p_p_links(net):
    """Tạo P-P links với interface names chuẩn (khớp FRR config)."""
    # P01 -- P02
    net.addLink('p01', 'p02',
                bw=1000, delay='1ms',
                intfName1='p01-eth0', intfName2='p02-eth0')
    # P02 -- P03
    net.addLink('p02', 'p03',
                bw=1000, delay='1ms',
                intfName1='p02-eth1', intfName2='p03-eth0')
    # P03 -- P04
    net.addLink('p03', 'p04',
                bw=1000, delay='1ms',
                intfName1='p03-eth1', intfName2='p04-eth0')
    # P01 -- P03 (diagonal)
    net.addLink('p01', 'p03',
                bw=1000, delay='2ms',
                intfName1='p01-eth1', intfName2='p03-eth2')
    # P02 -- P04 (diagonal)
    net.addLink('p02', 'p04',
                bw=1000, delay='2ms',
                intfName1='p02-eth2', intfName2='p04-eth1')


def _build_default_pe_p_links(net):
    """Tạo PE-P links với interface names chuẩn (khớp FRR config)."""
    # PE01 -- P01 (primary)
    net.addLink('pe01', 'p01',
                bw=1000, delay='1ms',
                intfName1='pe01-p01', intfName2='p01-pe01')
    # PE01 -- P02 (alternate/dual-homed)
    net.addLink('pe01', 'p02',
                bw=1000, delay='1ms',
                intfName1='pe01-p02', intfName2='p02-pe01')
    # PE02 -- P02 (primary)
    net.addLink('pe02', 'p02',
                bw=1000, delay='1ms',
                intfName1='pe02-p02', intfName2='p02-pe02')
    # PE02 -- P03 (alternate)
    net.addLink('pe02', 'p03',
                bw=1000, delay='1ms',
                intfName1='pe02-p03', intfName2='p03-pe02')
    # PE03 -- P03 (primary)
    net.addLink('pe03', 'p03',
                bw=1000, delay='1ms',
                intfName1='pe03-p03', intfName2='p03-pe03')
    # PE03 -- P04 (alternate)
    net.addLink('pe03', 'p04',
                bw=1000, delay='1ms',
                intfName1='pe03-p04', intfName2='p04-pe03')


# ----------------------------------------------------------------
# Apply Static Routes (fallback khi không dùng FRR)
# ----------------------------------------------------------------
def apply_backbone_static_routes(net):
    """
    Static routes cho backbone (để test routing mà không cần FRR).
    Mỗi router cần biết đường đến loopback của các router khác.
    """
    info('\n*** Cấu hình Static Routes cho backbone (--no-frr mode)\n')

    # P01: biết đường đến tất cả loopbacks qua neighbors
    p01 = net.get('p01')
    p01.cmd('ip route add 10.0.0.2/32  via 10.0.10.2')   # P02 qua eth0
    p01.cmd('ip route add 10.0.0.3/32  via 10.0.13.2')   # P03 qua diagonal
    p01.cmd('ip route add 10.0.0.4/32  via 10.0.10.2')   # P04 qua P02
    p01.cmd('ip route add 10.0.0.12/32 via 10.0.10.2')   # PE02 qua P02
    p01.cmd('ip route add 10.0.0.13/32 via 10.0.13.2')   # PE03 qua P03
    p01.cmd('ip route add 10.0.0.11/32 via 10.0.20.1')   # PE01 loopback qua link direct

    # P02: central hub
    p02 = net.get('p02')
    p02.cmd('ip route add 10.0.0.1/32  via 10.0.10.1')
    p02.cmd('ip route add 10.0.0.3/32  via 10.0.11.2')
    p02.cmd('ip route add 10.0.0.4/32  via 10.0.14.2')
    p02.cmd('ip route add 10.0.0.11/32 via 10.0.21.1')   # PE01 via pe01-p02
    p02.cmd('ip route add 10.0.0.12/32 via 10.0.22.1')   # PE02
    p02.cmd('ip route add 10.0.0.13/32 via 10.0.11.2')

    # P03
    p03 = net.get('p03')
    p03.cmd('ip route add 10.0.0.1/32  via 10.0.13.1')
    p03.cmd('ip route add 10.0.0.2/32  via 10.0.11.1')
    p03.cmd('ip route add 10.0.0.4/32  via 10.0.12.2')
    p03.cmd('ip route add 10.0.0.11/32 via 10.0.11.1')
    p03.cmd('ip route add 10.0.0.12/32 via 10.0.23.1')   # PE02
    p03.cmd('ip route add 10.0.0.13/32 via 10.0.24.1')   # PE03

    # P04
    p04 = net.get('p04')
    p04.cmd('ip route add 10.0.0.1/32  via 10.0.14.1')
    p04.cmd('ip route add 10.0.0.2/32  via 10.0.14.1')
    p04.cmd('ip route add 10.0.0.3/32  via 10.0.12.1')
    p04.cmd('ip route add 10.0.0.11/32 via 10.0.14.1')
    p04.cmd('ip route add 10.0.0.12/32 via 10.0.12.1')
    p04.cmd('ip route add 10.0.0.13/32 via 10.0.25.1')   # PE03

    # PE01
    pe01 = net.get('pe01')
    pe01.cmd('ip route add 10.0.0.0/24 via 10.0.20.2')   # tất cả loopbacks qua P01
    pe01.cmd('ip route add 10.0.0.12/32 via 10.0.21.2')  # PE02 path qua P02
    pe01.cmd('ip route add 10.0.0.13/32 via 10.0.21.2')  # PE03 path qua P02

    # PE02
    pe02 = net.get('pe02')
    pe02.cmd('ip route add 10.0.0.0/24  via 10.0.22.2')
    pe02.cmd('ip route add 10.0.0.11/32 via 10.0.22.2')
    pe02.cmd('ip route add 10.0.0.13/32 via 10.0.23.2')

    # PE03
    pe03 = net.get('pe03')
    pe03.cmd('ip route add 10.0.0.0/24  via 10.0.24.2')
    pe03.cmd('ip route add 10.0.0.11/32 via 10.0.24.2')
    pe03.cmd('ip route add 10.0.0.12/32 via 10.0.23.2')

    info('*** Static routes configured\n')


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


def run_frr_verification(net):
    """
    Test 4: Kiểm tra FRR protocol state.
    Chạy vtysh commands để verify OSPF/LDP/BGP.
    """
    info('\n*** [Test 4] FRR Protocol Verification\n')
    info('    (Kiểm tra OSPF neighbors, LDP sessions, BGP state)\n')

    frr_mgr = FRRManager(net)
    if not frr_mgr.frr_available:
        warn('    [SKIP] FRR không khả dụng trên hệ thống này\n')
        return

    # OSPF neighbors
    info('\n  [4a] OSPF Neighbors:\n')
    all_routers = ['p01', 'p02', 'p03', 'p04', 'pe01', 'pe02', 'pe03']
    ospf_ok = True
    for rname in all_routers:
        node = net.get(rname)
        if node is None:
            continue
        result = node.cmd('vtysh -c "show ip ospf neighbor" 2>/dev/null '
                          '|| echo "OSPF daemon not running"')
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
    for rname in ['p01', 'p02', 'p03', 'p04', 'pe01', 'pe02', 'pe03']:
        node = net.get(rname)
        if node is None:
            continue
        result = node.cmd('vtysh -c "show mpls ldp neighbor" 2>/dev/null '
                          '|| echo "LDP daemon not running"')
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
        result = node.cmd(
            'vtysh -c "show bgp l2vpn evpn summary" 2>/dev/null || '
            'vtysh -c "show bgp summary" 2>/dev/null || '
            'echo "BGP not running"'
        )
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
def run(interactive=True, use_frr=True, save_report=True):
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
        backbone_loader.apply_all(net)

        # ---- Phase 0b: Deploy FRR hoặc Static Routes ----
        if use_frr:
            info('\n*** [Phase 0b] Triển khai FRR (OSPF + LDP + BGP)\n')
            frr_mgr = FRRManager(net)
            if frr_mgr.frr_available:
                frr_mgr.deploy_backbone()
                info('\n*** Chờ OSPF + LDP hội tụ (30 giây)...\n')
                frr_mgr.wait_convergence(timeout=30)
            else:
                warn('[!] FRR không khả dụng, dùng static routes\n')
                apply_backbone_static_routes(net)
        else:
            info('\n*** [Phase 0b] Cấu hình Static Routes (--no-frr mode)\n')
            apply_backbone_static_routes(net)

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
            warn('     Kiểm tra routing/FRR trước khi chạy full MPLS.\n')
        else:
            warn('  ✗  BACKBONE CÓ VẤN ĐỀ NGHIÊM TRỌNG!\n')
            warn('     KHÔNG nên chạy run_full_mpls.py cho đến khi sửa.\n')

        # ---- Phase 0d: FRR Verification (nếu dùng FRR) ----
        if use_frr:
            run_frr_verification(net)

        # Save reports
        if save_report:
            tester.save_all_reports(reports, os.path.join(PROJECT_ROOT, 'result'))

        # CLI
        if interactive:
            info('\n*** Entering Mininet CLI (ISP Backbone)\n')
            info('*** Debug OSPF: pe01 vtysh -c "show ip ospf neighbor"\n')
            info('*** Debug LDP:  p01  vtysh -c "show mpls ldp neighbor"\n')
            info('*** Debug BGP:  pe01 vtysh -c "show bgp l2vpn evpn summary"\n')
            info('*** Ping test:  pe01 ping 10.0.0.12  (PE01->PE02 loopback)\n')
            info('*** MPLS:       p01  ip -M route\n')
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
        '--no-frr', action='store_true',
        help='Dùng static routes thay vì FRR (để debug IP layer trước)'
    )
    parser.add_argument(
        '--no-report', action='store_true',
        help='Không lưu file report'
    )
    args = parser.parse_args()

    run(
        interactive=not args.test,
        use_frr=not args.no_frr,
        save_report=not args.no_report,
    )
