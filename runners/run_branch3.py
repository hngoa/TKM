#!/usr/bin/env python3
"""
runners/run_branch3.py
======================
Runner: Kiểm tra nội bộ Chi nhánh 3 — Spine-Leaf Data Center (Isolated)

Giai đoạn 1: Test nội bộ topology (không có MPLS backbone).
Mục tiêu:
  - Intra-rack: web01 <-> web02, dns01 <-> dns02, db01 <-> db02
  - Inter-rack: web01 -> dns01 (qua spine, 2 hops)
  - Gateway: tất cả servers ping được CE03 (10.3.0.1)

Topology (isolated):
    CE03 (LinuxRouter, 10.3.0.1/16 - gateway toàn bộ DC subnets)
      └─ LEAF01 (Border Leaf)
           ├─ SPINE01 <-> LEAF02 (WEB), LEAF03 (DNS), LEAF04 (DB)
           └─ SPINE02 <-> LEAF02, LEAF03, LEAF04  (ECMP)

Chạy:
    sudo python3 runners/run_branch3.py          # Interactive CLI
    sudo python3 runners/run_branch3.py --test   # Auto test only
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


def build_branch3_isolated(loader):
    """
    Xây dựng topology Spine-Leaf từ YAML config.
    
    Lưu ý quan trọng về /16 mask:
    Tất cả server dùng IP/16 (10.3.x.x/16) với gateway 10.3.0.1
    Điều này cho phép servers trong mọi rack (/24) đều on-link reachable
    qua cùng một gateway CE03 mà không cần thêm routes.
    """
    net = Mininet(controller=None, link=TCLink, switch=OVSSwitch,
                  waitConnected=False)

    # --- CE Router (Border Gateway) ---
    info('*** Thêm CE03 (LinuxRouter - Data Center Border Router)\n')
    net.addHost('ce03', cls=LinuxRouter, ip=None)

    # --- Spine/Leaf Switches ---
    info('*** Thêm Spine/Leaf switches\n')
    for sw_cfg in loader.get_switches():
        # Spine-Leaf fabric: mỗi leaf nối với cả spine01 và spine02 (L2 loop)
        # RSTP sẽ được bật sau khi start
        net.addSwitch(sw_cfg['name'], failMode='standalone')

    # --- Server Hosts ---
    info('*** Thêm Server Hosts (WEB/DNS/DB)\n')
    for host_cfg in loader.get_hosts():
        net.addHost(
            host_cfg['name'],
            ip=host_cfg['ip'],           # e.g., 10.3.10.11/16
            defaultRoute=f"via {host_cfg['gateway']}"
        )

    # --- Links ---
    info('*** Kết nối links Spine-Leaf fabric\n')
    for link_cfg in loader.get_links():
        src      = link_cfg['src']
        dst      = link_cfg['dst']
        src_intf = link_cfg.get('src_intf')
        bw       = link_cfg.get('bw', 1000)
        delay    = link_cfg.get('delay', '1ms')

        # Bỏ qua WAN link
        if dst == 'pe03' or src == 'pe03':
            info(f'  [SKIP] WAN link {src} <-> {dst} (isolated mode)\n')
            continue

        params = {'bw': bw, 'delay': delay}
        if src_intf:
            params['intfName1'] = src_intf

        net.addLink(src, dst, **params)

    return net


def run(interactive=True, save_report=True):
    setLogLevel('info')

    config_path = os.path.join(PROJECT_ROOT, 'configs', 'branch3', 'ip_plan.yaml')
    info(f'*** Loading config: {config_path}\n')
    loader = ConfigLoader(config_path)

    info('\n*** Xây dựng topology Branch 3 (Spine-Leaf DC - Isolated)\n')
    net = build_branch3_isolated(loader)

    try:
        net.start()

        # Spine-Leaf có loop: leaf02/03/04 mỗi cái nối cả spine01 lẫn spine02
        # Bật RSTP để hội tụ nhanh (~2s thay vì STP 30s)
        info('*** Bật RSTP trên các Spine/Leaf switches...\n')
        for sw in net.switches:
            result = sw.cmd(f'ovs-vsctl set bridge {sw.name} rstp_enable=true 2>&1')
            if 'error' in result.lower() or 'unknown' in result.lower():
                sw.cmd(f'ovs-vsctl set bridge {sw.name} stp_enable=true 2>/dev/null || true')
                info(f'  [{sw.name}] Fallback to STP\n')
            else:
                info(f'  [{sw.name}] RSTP OK\n')
        info('*** Chờ RSTP hội tụ...\n')
        time.sleep(5)

        info('\n*** Áp dụng cấu hình IP (/16 supernet)\n')
        loader.apply_all(net, mode='isolated')

        info('\n*** Bắt đầu kiểm tra connectivity nội bộ Branch 3\n')
        tester = ConnectivityTest(net)
        report = tester.test_intra_branch('branch3', loader)
        tester.print_summary(report)

        if save_report:
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            report_path = os.path.join(
                PROJECT_ROOT, 'result', f'branch3_isolated_{timestamp}.log'
            )
            tester.save_report(report, report_path)

        if interactive:
            info('\n*** Entering Mininet CLI\n')
            info('*** Gợi ý: web01 ping db01 | dns01 ping 10.3.0.1\n')
            info('*** Inter-rack: web01 ping 10.3.30.11 (db01) via Spine\n')
            CLI(net)

    finally:
        net.stop()
        info('*** Topology Branch 3 đã tắt\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Runner: Branch 3 Spine-Leaf DC (Isolated Test)'
    )
    parser.add_argument('--test', action='store_true',
                        help='Chỉ chạy auto test')
    parser.add_argument('--no-report', action='store_true',
                        help='Không lưu file report')
    args = parser.parse_args()
    run(interactive=not args.test, save_report=not args.no_report)
