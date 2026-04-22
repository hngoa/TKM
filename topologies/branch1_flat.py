#!/usr/bin/env python3
"""
branch1_flat.py - Chi nhánh 1: Mạng Phẳng (Flat Network)

Cấu trúc:
  CE01 -- SW01 -- SW02
           |         |--- PC03
           |         |--- PC04
           |--- PC01
           |--- PC02

Đặc điểm:
  - Single broadcast domain, không VLAN
  - Daisy-chain switch (SW01 -> SW02)
  - Gateway: CE01 (10.1.0.1/24)
  - Tất cả PCs cùng subnet 10.1.0.0/24

Lưu ý:
  File này là TOPOLOGY SKELETON (khung).
  Cấu hình IP và routing được định nghĩa trong:
    configs/branch1/ip_plan.yaml    (IP plan)
    configs/branch1/ce01.conf       (FRR config do ISP cung cấp)
  Runner script:
    runners/run_branch1.py
"""

from mininet.topo import Topo


class Branch1FlatTopo(Topo):
    """
    Flat Network Topology (Chi nhánh 1):
    - CE01: Customer Edge Router (kết nối lên PE01 qua WAN)
    - SW01: Access Switch 1 (uplink to CE01)
    - SW02: Access Switch 2 (daisy-chain from SW01)
    - PC01-PC04: End hosts

    Subnet: 10.1.0.0/24
    Gateway: CE01 (10.1.0.1)
    """

    def build(self, **opts):
        # CE Router (kết nối lên ISP phía WAN)
        ce01 = self.addNode('ce01', cls=None)

        # Switches (daisy-chain)
        sw01 = self.addSwitch('sw01')
        sw02 = self.addSwitch('sw02')

        # Hosts
        pc01 = self.addHost('pc01', ip='10.1.0.11/24', defaultRoute='via 10.1.0.1')
        pc02 = self.addHost('pc02', ip='10.1.0.12/24', defaultRoute='via 10.1.0.1')
        pc03 = self.addHost('pc03', ip='10.1.0.13/24', defaultRoute='via 10.1.0.1')
        pc04 = self.addHost('pc04', ip='10.1.0.14/24', defaultRoute='via 10.1.0.1')

        # CE01 -- SW01 (LAN interface)
        self.addLink(ce01, sw01, bw=100, delay='1ms')

        # SW01 -- SW02 (daisy-chain uplink)
        self.addLink(sw01, sw02, bw=100, delay='1ms')

        # SW01 access ports
        self.addLink(sw01, pc01, bw=100, delay='1ms')
        self.addLink(sw01, pc02, bw=100, delay='1ms')

        # SW02 access ports
        self.addLink(sw02, pc03, bw=100, delay='1ms')
        self.addLink(sw02, pc04, bw=100, delay='1ms')


topos = {'branch1': Branch1FlatTopo}
