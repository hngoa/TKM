#!/usr/bin/env python3
"""
quick_test.py - Kiểm tra nhanh kết nối giữa tất cả chi nhánh
Dùng để verify topology trước khi chạy full measurement
"""

import sys
import os
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from mininet.log import setLogLevel


TEST_PAIRS = [
    # (src, dst_ip, description)
    ('pc01',    '10.1.0.12',   'B1: pc01 -> pc02 [same subnet]'),
    ('pc01',    '10.1.0.14',   'B1: pc01 -> pc04 [daisy-chain]'),
    ('lab01',   '10.2.10.12',  'B2: lab01 -> lab02 [LAB subnet]'),
    ('lab01',   '10.2.20.11',  'B2: LAB -> ADMIN [inter-VLAN]'),
    ('admin01', '10.2.30.11',  'B2: ADMIN -> GUEST [inter-VLAN]'),
    ('web01',   '10.3.10.12',  'B3: web01 -> web02 [same leaf]'),
    ('web01',   '10.3.20.11',  'B3: WEB -> DNS [spine-leaf 2hop]'),
    ('web01',   '10.3.30.11',  'B3: WEB -> DB [spine-leaf 2hop]'),
    # Inter-branch
    ('pc01',    '10.2.10.11',  '★ B1 -> B2 [MPLS backbone]'),
    ('pc01',    '10.3.10.11',  '★ B1 -> B3 [MPLS backbone]'),
    ('lab01',   '10.3.10.11',  '★ B2 -> B3 [MPLS backbone]'),
    ('web01',   '10.1.0.11',   '★ B3 -> B1 [MPLS backbone]'),
    ('db01',    '10.2.20.11',  '★ B3 -> B2 [MPLS backbone]'),
]


def run_quick_test():
    setLogLevel('warning')

    from topologies.full_topology import build_full_topology, configure_ip_addresses, configure_routing

    print("="*55)
    print("  METRO ETHERNET MPLS - QUICK CONNECTIVITY TEST")
    print("="*55)
    print("[*] Khởi động topology...")

    net = build_full_topology()
    net.start()
    configure_ip_addresses(net)
    configure_routing(net)
    time.sleep(2)

    print("[*] Bắt đầu ping tests...\n")

    passed = 0
    failed = 0
    results = []

    for src_name, dst_ip, description in TEST_PAIRS:
        src = net.get(src_name)
        if src is None:
            print(f"  [SKIP] {description}")
            continue

        output = src.cmd(f'ping -c 3 -W 2 -q {dst_ip}')

        # Parse
        import re
        loss_match = re.search(r'(\d+)% packet loss', output)
        rtt_match  = re.search(r'rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)', output)

        loss = int(loss_match.group(1)) if loss_match else 100
        rtt  = float(rtt_match.group(2)) if rtt_match else None
        ok   = loss < 50

        status = '✓ PASS' if ok else '✗ FAIL'
        rtt_str = f'{rtt:.1f}ms' if rtt else 'N/A'
        loss_str = f'loss={loss}%'

        print(f"  [{status}] {description:<45} RTT={rtt_str:<10} {loss_str}")
        results.append({'ok': ok, 'desc': description, 'rtt': rtt, 'loss': loss})

        if ok:
            passed += 1
        else:
            failed += 1

    print(f"\n{'='*55}")
    print(f"  Kết quả: {passed} PASS / {failed} FAIL / {len(TEST_PAIRS)} total")

    if failed == 0:
        print("  ✅ Tất cả kết nối hoạt động! Sẵn sàng chạy full measurement.")
    elif failed <= 3:
        print("  ⚠️  Một số kết nối thất bại. Kiểm tra routing configuration.")
    else:
        print("  ❌ Nhiều kết nối thất bại. Kiểm tra lại topology và IP config.")

    print("="*55)

    net.stop()
    return passed, failed


if __name__ == '__main__':
    if os.geteuid() != 0:
        print("[ERROR] Cần chạy với quyền root: sudo python3 tools/quick_test.py")
        sys.exit(1)
    run_quick_test()
