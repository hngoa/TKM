#!/usr/bin/env python3
"""
full_topology.py - Toàn bộ hệ thống Metro Ethernet MPLS
Kết hợp: MPLS Backbone + 3 Chi nhánh

Cấu trúc tổng thể:
  Branch1 (Flat) <-> CE01 <-> PE01 <-+
                                      |-- MPLS Backbone (P01-P04)
  Branch2 (3-Tier) <-> CE02 <-> PE02 -+
                                      |
  Branch3 (Spine-Leaf) <-> CE03 <-> PE03

IP Plan:
  Backbone loopbacks: 10.0.0.x/32
  PE-CE links:
    PE01-CE01: 10.100.1.0/30
    PE02-CE02: 10.100.2.0/30
    PE03-CE03: 10.100.3.0/30
  P-P links:   10.0.1x.0/30
  PE-P links:  10.0.2x.0/30
  Branch1 LAN: 10.1.0.0/24
  Branch2 LANs: 10.2.x.0/24
  Branch3 LANs: 10.3.x.0/24
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from mininet.net import Mininet
from mininet.node import Node, OVSSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel, info
from mininet.cli import CLI


class LinuxRouter(Node):
    """
    Node chạy như một Linux Router.
    Bật IP forwarding để định tuyến gói tin.
    """
    def config(self, **params):
        super(LinuxRouter, self).config(**params)
        self.cmd('sysctl -w net.ipv4.ip_forward=1')
        self.cmd('sysctl -w net.mpls.platform_labels=1048575')
        self.cmd('sysctl -w net.mpls.conf.lo.input=1')

    def terminate(self):
        self.cmd('sysctl -w net.ipv4.ip_forward=0')
        super(LinuxRouter, self).terminate()


def enable_mpls_on_router(router, interfaces):
    """Bật MPLS input trên từng interface của router."""
    for intf in interfaces:
        router.cmd(f'sysctl -w net.mpls.conf.{intf}.input=1')


def build_full_topology():
    """Xây dựng toàn bộ topology và trả về net object."""
    net = Mininet(controller=None, link=TCLink, switch=OVSSwitch)

    info('*** Tạo MPLS Backbone nodes\n')
    # P-Routers
    p01 = net.addHost('p01', cls=LinuxRouter, ip=None)
    p02 = net.addHost('p02', cls=LinuxRouter, ip=None)
    p03 = net.addHost('p03', cls=LinuxRouter, ip=None)
    p04 = net.addHost('p04', cls=LinuxRouter, ip=None)

    # PE-Routers
    pe01 = net.addHost('pe01', cls=LinuxRouter, ip=None)
    pe02 = net.addHost('pe02', cls=LinuxRouter, ip=None)
    pe03 = net.addHost('pe03', cls=LinuxRouter, ip=None)

    info('*** Tạo CE Routers\n')
    ce01 = net.addHost('ce01', cls=LinuxRouter, ip=None)
    ce02 = net.addHost('ce02', cls=LinuxRouter, ip=None)
    ce03 = net.addHost('ce03', cls=LinuxRouter, ip=None)

    info('*** Tạo Branch 1 - Flat Network\n')
    sw01 = net.addSwitch('sw01')
    sw02 = net.addSwitch('sw02')
    pc01 = net.addHost('pc01', ip='10.1.0.11/24', defaultRoute='via 10.1.0.1')
    pc02 = net.addHost('pc02', ip='10.1.0.12/24', defaultRoute='via 10.1.0.1')
    pc03 = net.addHost('pc03', ip='10.1.0.13/24', defaultRoute='via 10.1.0.1')
    pc04 = net.addHost('pc04', ip='10.1.0.14/24', defaultRoute='via 10.1.0.1')

    info('*** Tạo Branch 2 - Three-Tier Network\n')
    core01 = net.addSwitch('core01')
    core02 = net.addSwitch('core02')
    dist01 = net.addSwitch('dist01')
    dist02 = net.addSwitch('dist02')
    access01 = net.addSwitch('access01')
    access02 = net.addSwitch('access02')
    access03 = net.addSwitch('access03')
    lab01   = net.addHost('lab01',   ip='10.2.10.11/24', defaultRoute='via 10.2.10.1')
    lab02   = net.addHost('lab02',   ip='10.2.10.12/24', defaultRoute='via 10.2.10.1')
    admin01 = net.addHost('admin01', ip='10.2.20.11/24', defaultRoute='via 10.2.20.1')
    admin02 = net.addHost('admin02', ip='10.2.20.12/24', defaultRoute='via 10.2.20.1')
    guest01 = net.addHost('guest01', ip='10.2.30.11/24', defaultRoute='via 10.2.30.1')
    guest02 = net.addHost('guest02', ip='10.2.30.12/24', defaultRoute='via 10.2.30.1')

    info('*** Tạo Branch 3 - Spine-Leaf (Data Center)\n')
    spine01 = net.addSwitch('spine01')
    spine02 = net.addSwitch('spine02')
    leaf01  = net.addSwitch('leaf01')
    leaf02  = net.addSwitch('leaf02')
    leaf03  = net.addSwitch('leaf03')
    leaf04  = net.addSwitch('leaf04')
    web01 = net.addHost('web01', ip='10.3.10.11/24', defaultRoute='via 10.3.10.1')
    web02 = net.addHost('web02', ip='10.3.10.12/24', defaultRoute='via 10.3.10.1')
    dns01 = net.addHost('dns01', ip='10.3.20.11/24', defaultRoute='via 10.3.20.1')
    dns02 = net.addHost('dns02', ip='10.3.20.12/24', defaultRoute='via 10.3.20.1')
    db01  = net.addHost('db01',  ip='10.3.30.11/24', defaultRoute='via 10.3.30.1')
    db02  = net.addHost('db02',  ip='10.3.30.12/24', defaultRoute='via 10.3.30.1')

    # ================================================================
    # LINKS - MPLS BACKBONE
    # ================================================================
    info('*** Kết nối MPLS Backbone\n')
    # P-P Partial Mesh
    net.addLink(p01, p02, bw=1000, delay='2ms',
                intfName1='p01-eth0', intfName2='p02-eth0')
    net.addLink(p02, p03, bw=1000, delay='2ms',
                intfName1='p02-eth1', intfName2='p03-eth0')
    net.addLink(p03, p04, bw=1000, delay='2ms',
                intfName1='p03-eth1', intfName2='p04-eth0')
    net.addLink(p01, p03, bw=1000, delay='3ms',
                intfName1='p01-eth1', intfName2='p03-eth2')
    net.addLink(p02, p04, bw=1000, delay='3ms',
                intfName1='p02-eth2', intfName2='p04-eth1')

    # PE01 -> P01, P02 (dual-homed)
    net.addLink(pe01, p01, bw=1000, delay='1ms',
                intfName1='pe01-p01', intfName2='p01-pe01')
    net.addLink(pe01, p02, bw=1000, delay='1ms',
                intfName1='pe01-p02', intfName2='p02-pe01')

    # PE02 -> P02, P03
    net.addLink(pe02, p02, bw=1000, delay='1ms',
                intfName1='pe02-p02', intfName2='p02-pe02')
    net.addLink(pe02, p03, bw=1000, delay='1ms',
                intfName1='pe02-p03', intfName2='p03-pe02')

    # PE03 -> P03, P04
    net.addLink(pe03, p03, bw=1000, delay='1ms',
                intfName1='pe03-p03', intfName2='p03-pe03')
    net.addLink(pe03, p04, bw=1000, delay='1ms',
                intfName1='pe03-p04', intfName2='p04-pe03')

    # ================================================================
    # LINKS - PE to CE (WAN links)
    # ================================================================
    info('*** Kết nối PE-CE (WAN)\n')
    net.addLink(pe01, ce01, bw=100, delay='5ms',
                intfName1='pe01-ce01', intfName2='ce01-pe01')
    net.addLink(pe02, ce02, bw=100, delay='5ms',
                intfName1='pe02-ce02', intfName2='ce02-pe02')
    net.addLink(pe03, ce03, bw=100, delay='5ms',
                intfName1='pe03-ce03', intfName2='ce03-pe03')

    # ================================================================
    # LINKS - BRANCH 1 (Flat)
    # ================================================================
    info('*** Kết nối Branch 1 - Flat Network\n')
    net.addLink(ce01, sw01, bw=100, delay='1ms',
                intfName1='ce01-sw01')
    net.addLink(sw01, sw02, bw=100, delay='1ms')
    net.addLink(sw01, pc01, bw=100, delay='1ms')
    net.addLink(sw01, pc02, bw=100, delay='1ms')
    net.addLink(sw02, pc03, bw=100, delay='1ms')
    net.addLink(sw02, pc04, bw=100, delay='1ms')

    # ================================================================
    # LINKS - BRANCH 2 (3-Tier)
    # ================================================================
    info('*** Kết nối Branch 2 - Three-Tier\n')
    net.addLink(ce02, core01, bw=1000, delay='1ms',
                intfName1='ce02-c01')
    net.addLink(ce02, core02, bw=1000, delay='1ms',
                intfName1='ce02-c02')
    net.addLink(core01, core02, bw=1000, delay='1ms')
    net.addLink(core01, dist01, bw=1000, delay='1ms')
    net.addLink(core01, dist02, bw=1000, delay='1ms')
    net.addLink(core02, dist01, bw=1000, delay='1ms')
    net.addLink(core02, dist02, bw=1000, delay='1ms')
    net.addLink(dist01, access01, bw=100, delay='1ms')
    net.addLink(dist01, access02, bw=100, delay='1ms')
    net.addLink(dist02, access02, bw=100, delay='1ms')
    net.addLink(dist02, access03, bw=100, delay='1ms')
    net.addLink(access01, lab01,   bw=100, delay='1ms')
    net.addLink(access01, lab02,   bw=100, delay='1ms')
    net.addLink(access02, admin01, bw=100, delay='1ms')
    net.addLink(access02, admin02, bw=100, delay='1ms')
    net.addLink(access03, guest01, bw=100, delay='1ms')
    net.addLink(access03, guest02, bw=100, delay='1ms')

    # ================================================================
    # LINKS - BRANCH 3 (Spine-Leaf)
    # ================================================================
    info('*** Kết nối Branch 3 - Spine-Leaf\n')
    net.addLink(ce03, leaf01, bw=1000, delay='1ms',
                intfName1='ce03-leaf01')
    net.addLink(leaf01, spine01, bw=1000, delay='1ms')
    net.addLink(leaf01, spine02, bw=1000, delay='1ms')
    net.addLink(leaf02, spine01, bw=1000, delay='1ms')
    net.addLink(leaf02, spine02, bw=1000, delay='1ms')
    net.addLink(leaf03, spine01, bw=1000, delay='1ms')
    net.addLink(leaf03, spine02, bw=1000, delay='1ms')
    net.addLink(leaf04, spine01, bw=1000, delay='1ms')
    net.addLink(leaf04, spine02, bw=1000, delay='1ms')
    net.addLink(leaf02, web01, bw=1000, delay='1ms')
    net.addLink(leaf02, web02, bw=1000, delay='1ms')
    net.addLink(leaf03, dns01, bw=1000, delay='1ms')
    net.addLink(leaf03, dns02, bw=1000, delay='1ms')
    net.addLink(leaf04, db01,  bw=1000, delay='1ms')
    net.addLink(leaf04, db02,  bw=1000, delay='1ms')

    return net


def configure_ip_addresses(net):
    """
    Gán IP cho tất cả các interface router.
    Theo IP plan trong docstring module.
    """
    info('\n*** Cấu hình IP addresses\n')

    # ---- Loopback (dùng cho OSPF Router-ID và LDP) ----
    lo_map = {
        'p01':  '10.0.0.1',  'p02':  '10.0.0.2',
        'p03':  '10.0.0.3',  'p04':  '10.0.0.4',
        'pe01': '10.0.0.11', 'pe02': '10.0.0.12', 'pe03': '10.0.0.13',
        'ce01': '10.0.0.21', 'ce02': '10.0.0.22', 'ce03': '10.0.0.23',
    }
    for name, ip in lo_map.items():
        node = net.get(name)
        node.cmd(f'ip addr add {ip}/32 dev lo')
        node.cmd('ip link set lo up')

    # ---- P-P Links ----
    # p01-p02: 10.0.10.0/30
    net.get('p01').cmd('ip addr add 10.0.10.1/30 dev p01-eth0')
    net.get('p02').cmd('ip addr add 10.0.10.2/30 dev p02-eth0')
    # p02-p03: 10.0.11.0/30
    net.get('p02').cmd('ip addr add 10.0.11.1/30 dev p02-eth1')
    net.get('p03').cmd('ip addr add 10.0.11.2/30 dev p03-eth0')
    # p03-p04: 10.0.12.0/30
    net.get('p03').cmd('ip addr add 10.0.12.1/30 dev p03-eth1')
    net.get('p04').cmd('ip addr add 10.0.12.2/30 dev p04-eth0')
    # p01-p03: 10.0.13.0/30
    net.get('p01').cmd('ip addr add 10.0.13.1/30 dev p01-eth1')
    net.get('p03').cmd('ip addr add 10.0.13.2/30 dev p03-eth2')
    # p02-p04: 10.0.14.0/30
    net.get('p02').cmd('ip addr add 10.0.14.1/30 dev p02-eth2')
    net.get('p04').cmd('ip addr add 10.0.14.2/30 dev p04-eth1')

    # ---- PE-P Links ----
    # pe01-p01: 10.0.20.0/30
    net.get('pe01').cmd('ip addr add 10.0.20.1/30 dev pe01-p01')
    net.get('p01').cmd('ip addr add 10.0.20.2/30 dev p01-pe01')
    # pe01-p02: 10.0.21.0/30
    net.get('pe01').cmd('ip addr add 10.0.21.1/30 dev pe01-p02')
    net.get('p02').cmd('ip addr add 10.0.21.2/30 dev p02-pe01')
    # pe02-p02: 10.0.22.0/30
    net.get('pe02').cmd('ip addr add 10.0.22.1/30 dev pe02-p02')
    net.get('p02').cmd('ip addr add 10.0.22.2/30 dev p02-pe02')
    # pe02-p03: 10.0.23.0/30
    net.get('pe02').cmd('ip addr add 10.0.23.1/30 dev pe02-p03')
    net.get('p03').cmd('ip addr add 10.0.23.2/30 dev p03-pe02')
    # pe03-p03: 10.0.24.0/30
    net.get('pe03').cmd('ip addr add 10.0.24.1/30 dev pe03-p03')
    net.get('p03').cmd('ip addr add 10.0.24.2/30 dev p03-pe03')
    # pe03-p04: 10.0.25.0/30
    net.get('pe03').cmd('ip addr add 10.0.25.1/30 dev pe03-p04')
    net.get('p04').cmd('ip addr add 10.0.25.2/30 dev p04-pe03')

    # ---- PE-CE Links (WAN) ----
    # pe01-ce01: 10.100.1.0/30
    net.get('pe01').cmd('ip addr add 10.100.1.1/30 dev pe01-ce01')
    net.get('ce01').cmd('ip addr add 10.100.1.2/30 dev ce01-pe01')
    # pe02-ce02: 10.100.2.0/30
    net.get('pe02').cmd('ip addr add 10.100.2.1/30 dev pe02-ce02')
    net.get('ce02').cmd('ip addr add 10.100.2.2/30 dev ce02-pe02')
    # pe03-ce03: 10.100.3.0/30
    net.get('pe03').cmd('ip addr add 10.100.3.1/30 dev pe03-ce03')
    net.get('ce03').cmd('ip addr add 10.100.3.2/30 dev ce03-pe03')

    # ---- CE01 -> Branch1 ----
    net.get('ce01').cmd('ip addr add 10.1.0.1/24 dev ce01-sw01')

    # ---- CE02 -> Branch2 (Inter-VLAN Gateway) ----
    net.get('ce02').cmd('ip addr add 10.2.10.1/24 dev ce02-c01')  # LAB GW
    net.get('ce02').cmd('ip addr add 10.2.20.1/24 dev ce02-c02')  # ADMIN GW
    # GUEST trên sub-interface
    net.get('ce02').cmd('ip addr add 10.2.30.1/24 dev ce02-c01:0 2>/dev/null || true')

    # ---- CE03 -> Branch3 (Border Leaf) ----
    net.get('ce03').cmd('ip addr add 10.3.0.1/16 dev ce03-leaf01')

    info('*** Cấu hình IP hoàn tất\n')


def configure_routing(net):
    """
    Cấu hình static routes cơ bản (fallback nếu không dùng FRR).
    Trong môi trường đầy đủ, thay thế bằng OSPF + LDP + VPLS qua FRR.
    """
    info('*** Cấu hình Static Routes\n')

    # CE01 default route -> PE01
    net.get('ce01').cmd('ip route add default via 10.100.1.1')
    # CE02 default route -> PE02
    net.get('ce02').cmd('ip route add default via 10.100.2.1')
    # CE03 default route -> PE03
    net.get('ce03').cmd('ip route add default via 10.100.3.1')

    # PE01: routes to Branch2/3 via Backbone
    net.get('pe01').cmd('ip route add 10.2.0.0/16 via 10.0.21.2')  # via P02
    net.get('pe01').cmd('ip route add 10.3.0.0/16 via 10.0.21.2')
    net.get('pe01').cmd('ip route add 10.100.2.0/30 via 10.0.21.2')
    net.get('pe01').cmd('ip route add 10.100.3.0/30 via 10.0.20.2')

    # PE02: routes to Branch1/3
    net.get('pe02').cmd('ip route add 10.1.0.0/24 via 10.0.22.2')
    net.get('pe02').cmd('ip route add 10.3.0.0/16 via 10.0.23.2')
    net.get('pe02').cmd('ip route add 10.100.1.0/30 via 10.0.22.2')
    net.get('pe02').cmd('ip route add 10.100.3.0/30 via 10.0.23.2')

    # PE03: routes to Branch1/2
    net.get('pe03').cmd('ip route add 10.1.0.0/24 via 10.0.24.2')
    net.get('pe03').cmd('ip route add 10.2.0.0/16 via 10.0.24.2')
    net.get('pe03').cmd('ip route add 10.100.1.0/30 via 10.0.25.2')
    net.get('pe03').cmd('ip route add 10.100.2.0/30 via 10.0.24.2')

    # P01: forward traffic
    net.get('p01').cmd('ip route add 10.100.1.0/30 via 10.0.20.1')
    net.get('p01').cmd('ip route add 10.100.2.0/30 via 10.0.10.2')
    net.get('p01').cmd('ip route add 10.100.3.0/30 via 10.0.10.2')
    net.get('p01').cmd('ip route add 10.2.0.0/16   via 10.0.21.1')
    net.get('p01').cmd('ip route add 10.3.0.0/16   via 10.0.10.2')
    net.get('p01').cmd('ip route add 10.1.0.0/24   via 10.0.20.1')

    net.get('p02').cmd('ip route add 10.100.1.0/30 via 10.0.10.1')
    net.get('p02').cmd('ip route add 10.100.2.0/30 via 10.0.22.1')
    net.get('p02').cmd('ip route add 10.100.3.0/30 via 10.0.11.2')
    net.get('p02').cmd('ip route add 10.1.0.0/24   via 10.0.21.1')
    net.get('p02').cmd('ip route add 10.2.0.0/16   via 10.0.22.1')
    net.get('p02').cmd('ip route add 10.3.0.0/16   via 10.0.11.2')

    net.get('p03').cmd('ip route add 10.100.1.0/30 via 10.0.11.1')
    net.get('p03').cmd('ip route add 10.100.2.0/30 via 10.0.23.1')
    net.get('p03').cmd('ip route add 10.100.3.0/30 via 10.0.24.1')
    net.get('p03').cmd('ip route add 10.1.0.0/24   via 10.0.11.1')
    net.get('p03').cmd('ip route add 10.2.0.0/16   via 10.0.23.1')
    net.get('p03').cmd('ip route add 10.3.0.0/16   via 10.0.24.1')

    net.get('p04').cmd('ip route add 10.100.1.0/30 via 10.0.14.1')
    net.get('p04').cmd('ip route add 10.100.2.0/30 via 10.0.12.1')
    net.get('p04').cmd('ip route add 10.100.3.0/30 via 10.0.25.1')
    net.get('p04').cmd('ip route add 10.1.0.0/24   via 10.0.14.1')
    net.get('p04').cmd('ip route add 10.2.0.0/16   via 10.0.12.1')
    net.get('p04').cmd('ip route add 10.3.0.0/16   via 10.0.25.1')

    info('*** Routing cấu hình hoàn tất\n')


def run(interactive=True):
    setLogLevel('info')
    net = build_full_topology()
    net.start()
    configure_ip_addresses(net)
    configure_routing(net)

    info('\n*** Topology đã khởi động thành công!\n')
    info('*** Nodes: ', list(net.keys()), '\n')

    if interactive:
        CLI(net)

    net.stop()
    return net


if __name__ == '__main__':
    run()
