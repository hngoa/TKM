#!/usr/bin/env python3
"""
runners/run_branch1.py
======================
Runner: Kiểm tra nội bộ Chi nhánh 1 — Flat Network (Isolated Test)

Giai đoạn 1: Test nội bộ topology (không có MPLS backbone).
Mục tiêu: Xác nhận kết nối trong cùng subnet 10.1.0.0/24 hoạt động.

Topology (isolated):
    CE01 (LinuxRouter, gateway 10.1.0.1)
      └─ SW01 (OVS standalone)
           ├─ pc01 (10.1.0.11)
           ├─ pc02 (10.1.0.12)
           └─ SW02
                ├─ pc03 (10.1.0.13)
                └─ pc04 (10.1.0.14)

Chạy:
    sudo python3 runners/run_branch1.py          # Interactive CLI
    sudo python3 runners/run_branch1.py --test   # Auto test only
"""

import sys
import os
import time
import argparse

# Thêm thư mục gốc và tools vào Python path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'tools'))

from mininet.net import Mininet
from mininet.node import Node, OVSSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel, info
from mininet.cli import CLI

from config_loader import ConfigLoader
from connectivity_test import ConnectivityTest


# ----------------------------------------------------------------
# LinuxRouter class (chạy IP forwarding trên Mininet node)
# ----------------------------------------------------------------
class LinuxRouter(Node):
    """Mininet node với IP forwarding bật sẵn."""
    def config(self, **params):
        super().config(**params)
        self.cmd('sysctl -w net.ipv4.ip_forward=1')

    def terminate(self):
        self.cmd('sysctl -w net.ipv4.ip_forward=0')
        super().terminate()


# ----------------------------------------------------------------
# Hàm build topology Branch 1 (isolated)
# ----------------------------------------------------------------
def build_branch1_isolated(loader):
    """
    Xây dựng topology Branch 1 từ config YAML.
    
    - CE01: LinuxRouter (gateway LAN, không cần WAN trong isolated mode)
    - SW01, SW02: OVSSwitch standalone
    - PC01-PC04: Hosts với IP từ config YAML
    """
    net = Mininet(controller=None, link=TCLink, switch=OVSSwitch,
                  waitConnected=False)

    ce_cfg = loader.get_ce_config()

    # --- CE Router ---
    info('*** Thêm CE Router (LinuxRouter)\n')
    net.addHost('ce01', cls=LinuxRouter, ip=None)

    # --- Switches (from YAML config) ---
    info('*** Thêm Switches\n')
    for sw_cfg in loader.get_switches():
        # failMode=standalone: MAC-learning switch, không cần controller
        # stp=False: branch1 không có loop → tắt STP để port up ngay lập tức
        net.addSwitch(sw_cfg['name'], failMode='standalone', stp=False)

    # --- Hosts (from YAML config) ---
    info('*** Thêm Hosts\n')
    for host_cfg in loader.get_hosts():
        net.addHost(
            host_cfg['name'],
            ip=host_cfg['ip'],
            defaultRoute=f"via {host_cfg['gateway']}"
        )

    # --- Links (from YAML config, bỏ qua WAN link) ---
    info('*** Kết nối links\n')
    for link_cfg in loader.get_links():
        src      = link_cfg['src']
        dst      = link_cfg['dst']
        src_intf = link_cfg.get('src_intf')
        bw       = link_cfg.get('bw', 100)
        delay    = link_cfg.get('delay', '1ms')

        params = {'bw': bw, 'delay': delay}
        if src_intf:
            params['intfName1'] = src_intf

        net.addLink(src, dst, **params)

    return net


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def run(interactive=True, save_report=True):
    setLogLevel('info')

    # Load config
    config_path = os.path.join(PROJECT_ROOT, 'configs', 'branch1', 'ip_plan.yaml')
    info(f'*** Loading config: {config_path}\n')
    loader = ConfigLoader(config_path)

    # Build topology
    info('\n*** Xây dựng topology Branch 1 (Flat Network - Isolated)\n')
    net = build_branch1_isolated(loader)

    try:
        net.start()

        # Branch 1: cây thẳng (không có loop) → tắt STP, port up ngay
        info('*** Điều chỉnh STP cho switches...\n')
        for sw in net.switches:
            sw.cmd(f'ovs-vsctl set bridge {sw.name} stp_enable=false 2>/dev/null || true')
        time.sleep(1)  # [đợi switches khởi động]

        # Apply IP config (isolated mode: bỏ qua WAN interface)
        info('\n*** Áp dụng cấu hình IP từ YAML\n')
        loader.apply_all(net, mode='isolated')

        # Run connectivity tests
        info('\n*** Bắt đầu kiểm tra connectivity nội bộ Branch 1\n')
        tester = ConnectivityTest(net)
        report = tester.test_intra_branch('branch1', loader)
        tester.print_summary(report)

        # Save report
        if save_report:
            report_dir = os.path.join(PROJECT_ROOT, 'result')
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            report_path = os.path.join(report_dir, f'branch1_isolated_{timestamp}.log')
            tester.save_report(report, report_path)

        # CLI
        if interactive:
            info('\n*** Entering Mininet CLI (type "exit" to quit)\n')
            info('*** Gợi ý: pc01 ping pc03 | pc01 ping 10.1.0.1\n')
            CLI(net)

    finally:
        net.stop()
        info('*** Topology Branch 1 đã tắt\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Runner: Branch 1 Flat Network (Isolated Test)'
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
        save_report=not args.no_report
    )
