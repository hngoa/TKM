#!/usr/bin/env python3
"""
branch2_3tier.py - Chi nhánh 2: Mạng 3 Lớp (Core-Distribution-Access)
Cấu trúc:
  CE02
   |
  CORE01 -- CORE02
   |    \  /   |
  DIST01  DIST02
   |         |
 ACCESS01  ACCESS02  ACCESS03
   |           |         |
  LAB       ADMIN     GUEST
"""

from mininet.topo import Topo

class Branch2ThreeTierTopo(Topo):
    """
    Three-Tier Network (Chi nhánh 2):
    Core: CORE01, CORE02
    Distribution: DIST01, DIST02
    Access: ACCESS01 (LAB), ACCESS02 (ADMIN), ACCESS03 (GUEST)

    VLANs:
      VLAN 10 - LAB    (10.2.10.0/24)
      VLAN 20 - ADMIN  (10.2.20.0/24)
      VLAN 30 - GUEST  (10.2.30.0/24)
    """

    def build(self, **opts):
        # CE Router
        ce02 = self.addNode('ce02', cls=None)

        # Core layer
        core01 = self.addSwitch('core01')
        core02 = self.addSwitch('core02')

        # Distribution layer
        dist01 = self.addSwitch('dist01')
        dist02 = self.addSwitch('dist02')

        # Access layer
        access01 = self.addSwitch('access01')  # LAB
        access02 = self.addSwitch('access02')  # ADMIN
        access03 = self.addSwitch('access03')  # GUEST

        # Hosts - LAB
        lab01 = self.addHost('lab01', ip='10.2.10.11/24', defaultRoute='via 10.2.10.1')
        lab02 = self.addHost('lab02', ip='10.2.10.12/24', defaultRoute='via 10.2.10.1')

        # Hosts - ADMIN
        admin01 = self.addHost('admin01', ip='10.2.20.11/24', defaultRoute='via 10.2.20.1')
        admin02 = self.addHost('admin02', ip='10.2.20.12/24', defaultRoute='via 10.2.20.1')

        # Hosts - GUEST
        guest01 = self.addHost('guest01', ip='10.2.30.11/24', defaultRoute='via 10.2.30.1')
        guest02 = self.addHost('guest02', ip='10.2.30.12/24', defaultRoute='via 10.2.30.1')

        # CE02 -> Core (dual uplinks)
        self.addLink(ce02, core01, bw=1000, delay='1ms')
        self.addLink(ce02, core02, bw=1000, delay='1ms')

        # Core cross-connect
        self.addLink(core01, core02, bw=1000, delay='1ms')

        # Core -> Distribution (redundant links)
        self.addLink(core01, dist01, bw=1000, delay='1ms')
        self.addLink(core01, dist02, bw=1000, delay='1ms')
        self.addLink(core02, dist01, bw=1000, delay='1ms')
        self.addLink(core02, dist02, bw=1000, delay='1ms')

        # Distribution -> Access
        self.addLink(dist01, access01, bw=100, delay='1ms')
        self.addLink(dist01, access02, bw=100, delay='1ms')
        self.addLink(dist02, access02, bw=100, delay='1ms')
        self.addLink(dist02, access03, bw=100, delay='1ms')

        # Access -> Hosts
        self.addLink(access01, lab01, bw=100, delay='1ms')
        self.addLink(access01, lab02, bw=100, delay='1ms')
        self.addLink(access02, admin01, bw=100, delay='1ms')
        self.addLink(access02, admin02, bw=100, delay='1ms')
        self.addLink(access03, guest01, bw=100, delay='1ms')
        self.addLink(access03, guest02, bw=100, delay='1ms')


topos = {'branch2': Branch2ThreeTierTopo}
