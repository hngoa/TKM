#!/usr/bin/env python3
"""
runners/debug_ip.py
===================
Debug script: Kiểm tra IP assignment trên backbone nodes.
Dùng để diagnose khi connectivity tests fail.

Chạy:
    sudo python3 runners/debug_ip.py
"""

import sys
import os
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'tools'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'topologies'))

from mininet.net import Mininet
from mininet.link import TCLink
from mininet.log import setLogLevel, info, warn

from node_types import MPLSRouter
from config_loader import BackboneConfigLoader
from backbone import build_backbone_nodes, build_backbone_links


def run():
    setLogLevel('info')

    cfg_path = os.path.join(PROJECT_ROOT, 'configs', 'backbone', 'ip_plan.yaml')
    loader = BackboneConfigLoader(cfg_path)

    net = Mininet(controller=None, link=TCLink, waitConnected=False)
    build_backbone_nodes(net, MPLSRouter)
    build_backbone_links(net, loader)

    try:
        net.start()
        time.sleep(2)

        info('\n*** [Phase 1] Apply IP config\n')
        loader.apply_all(net)
        time.sleep(1)

        info('\n' + '='*60 + '\n')
        info('  IP ASSIGNMENT REPORT\n')
        info('='*60 + '\n')

        # Kiểm tra từng node
        routers = {
            'p01':  ['p01-eth0', 'p01-eth1', 'p01-pe01'],
            'p02':  ['p02-eth0', 'p02-eth1', 'p02-eth2', 'p02-pe01', 'p02-pe02'],
            'p03':  ['p03-eth0', 'p03-eth1', 'p03-eth2', 'p03-pe02', 'p03-pe03'],
            'p04':  ['p04-eth0', 'p04-eth1', 'p04-pe03'],
            'pe01': ['pe01-p01', 'pe01-p02'],
            'pe02': ['pe02-p02', 'pe02-p03'],
            'pe03': ['pe03-p03', 'pe03-p04'],
        }

        all_ok = True
        for name, intfs in routers.items():
            node = net.get(name)
            if not node:
                warn(f'  [MISS] {name}: không tìm thấy trong topology!\n')
                all_ok = False
                continue

            info(f'\n  [{name}]\n')
            # Loopback
            lo_out = node.cmd('ip addr show lo | grep -oP "(?<=inet )[\\d.]+/\\d+" | grep -v "127"').strip()
            info(f'    lo: {lo_out or "NO LOOPBACK!"}\n')
            if not lo_out:
                all_ok = False

            # Interfaces
            for intf in intfs:
                ip_out = node.cmd(f'ip addr show {intf} 2>/dev/null | grep -oP "(?<=inet )[\\d.]+/\\d+"').strip()
                state  = node.cmd(f'ip link show {intf} 2>/dev/null | grep -oP "(?<=state )[A-Z]+"').strip()
                status = '✓' if ip_out else '✗'
                info(f'    {status} {intf}: {ip_out or "NO IP"} [{state or "?"}]\n')
                if not ip_out:
                    all_ok = False

            # Routes
            route_count = node.cmd('ip route show | wc -l').strip()
            info(f'    Routes: {route_count} entries\n')

        info('\n' + '='*60 + '\n')
        if all_ok:
            info('  ✓ Tất cả IPs đã assign đúng!\n')
        else:
            warn('  ✗ Có interface bị thiếu IP! Kiểm tra build_backbone_links và ip_plan.yaml\n')

        # Quick ping test
        info('\n*** [Quick Ping] Kiểm tra directly connected links:\n')
        direct_tests = [
            ('p01', '10.0.10.2', 'P01→P02 (eth0)'),
            ('p02', '10.0.11.2', 'P02→P03 (eth1)'),
            ('pe01', '10.0.20.2', 'PE01→P01 (pe01-p01)'),
            ('pe01', '10.0.21.2', 'PE01→P02 (pe01-p02)'),
            ('pe02', '10.0.22.2', 'PE02→P02 (pe02-p02)'),
        ]
        for router, ip, label in direct_tests:
            node = net.get(router)
            if node:
                result = node.cmd(f'ping -c 3 -W 1 -q {ip} 2>&1 | tail -2')
                ok = '0% packet loss' in result
                icon = '✓' if ok else '✗'
                info(f'  [{icon}] {label} → {ip}: {"PASS" if ok else "FAIL"}\n')
                if not ok:
                    info(f'       {result.strip()}\n')

        info('\n*** Debug IP xong. Nhấn Ctrl+C để thoát.\n')
        input('Press Enter to stop...')

    finally:
        net.stop()


if __name__ == '__main__':
    run()
