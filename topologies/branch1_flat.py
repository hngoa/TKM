#!/usr/bin/env python3
"""
branch1_flat.py - Chi nhánh 1: Mạng Phẳng (Flat Network)
Cấu trúc:
  CE01 -- SW01 -- SW02
                   |--- PC01
                   |--- PC02
          |--- PC03
          |--- PC04
Daisy-chain, single broadcast domain, no VLAN
"""

from mininet.topo import Topo

class Branch1FlatTopo(Topo):
    """
    Flat Network Topology (Chi nhánh 1):
    - CE01: Customer Edge Router (kết nối lên PE01)
    - SW01: Access Switch 1
    - SW02: Access Switch 2 (mở rộng cổng)
    - PC01-PC04: End hosts

    Subnet: 10.1.0.0/24
    Gateway: CE01 (10.1.0.1)
    """

    def build(self, **opts):
        # CE Router
        ce01 = self.addNode('ce01', cls=None)

        # Switches (daisy-chain)
        sw01 = self.addSwitch('sw01')
        sw02 = self.addSwitch('sw02')

        # Hosts
        pc01 = self.addHost('pc01', ip='10.1.0.11/24', defaultRoute='via 10.1.0.1')
        pc02 = self.addHost('pc02', ip='10.1.0.12/24', defaultRoute='via 10.1.0.1')
        pc03 = self.addHost('pc03', ip='10.1.0.13/24', defaultRoute='via 10.1.0.1')
        pc04 = self.addHost('pc04', ip='10.1.0.14/24', defaultRoute='via 10.1.0.1')

        # CE01 -- SW01
        self.addLink(ce01, sw01, bw=100, delay='1ms')

        # SW01 -- SW02 (daisy-chain uplink)
        self.addLink(sw01, sw02, bw=100, delay='1ms')

        # SW01 hosts
        self.addLink(sw01, pc01, bw=100, delay='1ms')
        self.addLink(sw01, pc02, bw=100, delay='1ms')

        # SW02 hosts
        self.addLink(sw02, pc03, bw=100, delay='1ms')
        self.addLink(sw02, pc04, bw=100, delay='1ms')


topos = {'branch1': Branch1FlatTopo}
