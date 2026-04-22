#!/usr/bin/env python3
"""
runners/run_branch2.py
======================
Runner: Kiểm tra nội bộ Chi nhánh 2 — Three-Tier Network (Isolated Test)

Giai đoạn 1: Test nội bộ topology (không có MPLS backbone).
Mục tiêu:
  - Kết nối intra-VLAN: lab01 <-> lab02, admin01 <-> admin02, guest01 <-> guest02
  - Kết nối inter-VLAN: qua CE02 đóng vai trò Inter-VLAN Router

Topology (isolated):
    CE02 (LinuxRouter, 3 LAN interfaces)
      ├─ ce02-c01 (10.2.10.1/24) -> core01 -> dist01 -> access01 -> lab01, lab02
      ├─ ce02-c02 (10.2.20.1/24) -> core02 -> dist01/02 -> access02 -> admin01, admin02
      └─ ce02-c03 (10.2.30.1/24) -> dist02 -> access03 -> guest01, guest02

Chạy:
    sudo python3 runners/run_branch2.py          # Interactive CLI
    sudo python3 runners/run_branch2.py --test   # Auto test only
"""

import sys
import os
import time
import argparse

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'tools'))

from mininet.net import Mininet
from mininet.node import OVSSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel, info
from mininet.cli import CLI

from node_types import LinuxRouter      # dùng chung từ tools/node_types.py
from config_loader import ConfigLoader
from connectivity_test import ConnectivityTest


def build_branch2_isolated(loader):
    """
    Xây dựng topology Branch 2 Three-Tier từ YAML config.
    
    CE02 cần 3 LAN interfaces (1 per VLAN) để hoạt động như Inter-VLAN router.
    Sử dụng addLink với intfName để đặt tên interface khớp với YAML.
    """
    net = Mininet(controller=None, link=TCLink, switch=OVSSwitch,
                  waitConnected=False)

    # --- CE Router ---
    info('*** Thêm CE02 (LinuxRouter - Inter-VLAN Router)\n')
    net.addHost('ce02', cls=LinuxRouter, ip=None)

    # --- Switches ---
    info('*** Thêm Switches (3-Tier: Core/Dist/Access)\n')
    for sw_cfg in loader.get_switches():
        # Branch 2 có mesh giữa core-dist (có loop L2)
        # STP sẽ được bật sau khi start → dùng RSTP (hội tụ ~2s thay vì 30s)
        net.addSwitch(sw_cfg['name'], failMode='standalone')

    # --- Hosts ---
    info('*** Thêm Hosts (LAB/ADMIN/GUEST)\n')
    for host_cfg in loader.get_hosts():
        net.addHost(
            host_cfg['name'],
            ip=host_cfg['ip'],
            defaultRoute=f"via {host_cfg['gateway']}"
        )

    # --- Links (from YAML, bỏ qua WAN link) ---
    info('*** Kết nối links (bỏ qua WAN ce02-pe02)\n')
    for link_cfg in loader.get_links():
        src      = link_cfg['src']
        dst      = link_cfg['dst']
        src_intf = link_cfg.get('src_intf')
        bw       = link_cfg.get('bw', 100)
        delay    = link_cfg.get('delay', '1ms')

        # Phát hiện và bỏ qua WAN link (peer = pe02)
        if dst == 'pe02' or src == 'pe02':
            info(f'  [SKIP] WAN link {src} <-> {dst} (isolated mode)\n')
            continue

        params = {'bw': bw, 'delay': delay}
        if src_intf:
            params['intfName1'] = src_intf

        net.addLink(src, dst, **params)

    return net


def run(interactive=True, save_report=True):
    setLogLevel('info')

    config_path = os.path.join(PROJECT_ROOT, 'configs', 'branch2', 'ip_plan.yaml')
    info(f'*** Loading config: {config_path}\n')
    loader = ConfigLoader(config_path)

    info('\n*** Xây dựng topology Branch 2 (Three-Tier - Isolated)\n')
    net = build_branch2_isolated(loader)

    try:
        net.start()

        # Branch 2 có redundant links giữa core-dist (L2 loop)
        # Bật RSTP (Rapid STP): hội tụ trong ~1-2s thay vì 802.1D STP 30s
        info('*** Bật RSTP trên các switches (Rapid STP, hội tụ ~2s)...\n')
        for sw in net.switches:
            result = sw.cmd(f'ovs-vsctl set bridge {sw.name} rstp_enable=true 2>&1')
            if 'error' in result.lower() or 'unknown' in result.lower():
                # Fallback: STP thường (chậm hơn)
                sw.cmd(f'ovs-vsctl set bridge {sw.name} stp_enable=true 2>/dev/null || true')
                info(f'  [{sw.name}] Fallback to STP (RSTP không khả dụng)\n')
            else:
                info(f'  [{sw.name}] RSTP OK\n')
        info('*** Chờ RSTP hội tụ...\n')
        time.sleep(5)  # RSTP ~2s, chờ 5s để đảm bảo

        info('\n*** Áp dụng cấu hình IP\n')
        loader.apply_all(net, mode='isolated')

        info('\n*** Bắt đầu kiểm tra connectivity nội bộ Branch 2\n')
        tester = ConnectivityTest(net)
        report = tester.test_intra_branch('branch2', loader)
        tester.print_summary(report)

        if save_report:
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            report_path = os.path.join(
                PROJECT_ROOT, 'result', f'branch2_isolated_{timestamp}.log'
            )
            tester.save_report(report, report_path)

        if interactive:
            info('\n*** Entering Mininet CLI\n')
            info('*** Gợi ý: lab01 ping admin01 | lab01 ping 10.2.10.1\n')
            info('*** Inter-VLAN: lab01 ping 10.2.20.11 (admin01)\n')
            CLI(net)

    finally:
        net.stop()
        info('*** Topology Branch 2 đã tắt\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Runner: Branch 2 Three-Tier Network (Isolated Test)'
    )
    parser.add_argument('--test', action='store_true',
                        help='Chỉ chạy auto test')
    parser.add_argument('--no-report', action='store_true',
                        help='Không lưu file report')
    args = parser.parse_args()
    run(interactive=not args.test, save_report=not args.no_report)
