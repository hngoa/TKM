#!/usr/bin/env python3
"""
branch3_spineleaf.py - Chi nhánh 3: Spine-Leaf (Data Center)
Cấu trúc:
          CE03
           |
         LEAF01 (Border Leaf)
        /        \
   SPINE01      SPINE02
   /  |  \      /  |  \
LEAF02 LEAF03 LEAF04
  |      |      |
WEB  DNS01/02  DB
"""

from mininet.topo import Topo

class Branch3SpineLeafTopo(Topo):
    """
    Spine-Leaf Topology (Chi nhánh 3 - Data Center):
    - SPINE01, SPINE02: Spine switches (no inter-spine link)
    - LEAF01: Border Leaf (uplink to CE03)
    - LEAF02: WEB servers (web01, web02)
    - LEAF03: DNS servers (dns01, dns02)
    - LEAF04: DB servers  (db01, db02)

    L3 routing (OSPF/BGP) + ECMP on all fabric links
    Subnets:
      WEB: 10.3.10.0/24
      DNS: 10.3.20.0/24
      DB:  10.3.30.0/24
    """

    def build(self, **opts):
        # CE Router
        ce03 = self.addNode('ce03', cls=None)

        # Spine layer (no inter-spine link by design)
        spine01 = self.addSwitch('spine01')
        spine02 = self.addSwitch('spine02')

        # Leaf layer
        leaf01 = self.addSwitch('leaf01')   # Border Leaf
        leaf02 = self.addSwitch('leaf02')   # WEB
        leaf03 = self.addSwitch('leaf03')   # DNS
        leaf04 = self.addSwitch('leaf04')   # DB

        # Servers - WEB
        web01 = self.addHost('web01', ip='10.3.10.11/24', defaultRoute='via 10.3.10.1')
        web02 = self.addHost('web02', ip='10.3.10.12/24', defaultRoute='via 10.3.10.1')

        # Servers - DNS
        dns01 = self.addHost('dns01', ip='10.3.20.11/24', defaultRoute='via 10.3.20.1')
        dns02 = self.addHost('dns02', ip='10.3.20.12/24', defaultRoute='via 10.3.20.1')

        # Servers - DB
        db01 = self.addHost('db01', ip='10.3.30.11/24', defaultRoute='via 10.3.30.1')
        db02 = self.addHost('db02', ip='10.3.30.12/24', defaultRoute='via 10.3.30.1')

        # CE03 -> Border Leaf (LEAF01)
        self.addLink(ce03, leaf01, bw=1000, delay='1ms')

        # Border Leaf -> Spines (ECMP uplinks)
        self.addLink(leaf01, spine01, bw=1000, delay='1ms')
        self.addLink(leaf01, spine02, bw=1000, delay='1ms')

        # LEAF02 -> Spines (ECMP - 2 hops to any leaf)
        self.addLink(leaf02, spine01, bw=1000, delay='1ms')
        self.addLink(leaf02, spine02, bw=1000, delay='1ms')

        # LEAF03 -> Spines
        self.addLink(leaf03, spine01, bw=1000, delay='1ms')
        self.addLink(leaf03, spine02, bw=1000, delay='1ms')

        # LEAF04 -> Spines
        self.addLink(leaf04, spine01, bw=1000, delay='1ms')
        self.addLink(leaf04, spine02, bw=1000, delay='1ms')

        # Leaf -> Servers
        self.addLink(leaf02, web01, bw=1000, delay='1ms')
        self.addLink(leaf02, web02, bw=1000, delay='1ms')
        self.addLink(leaf03, dns01, bw=1000, delay='1ms')
        self.addLink(leaf03, dns02, bw=1000, delay='1ms')
        self.addLink(leaf04, db01, bw=1000, delay='1ms')
        self.addLink(leaf04, db02, bw=1000, delay='1ms')


topos = {'branch3': Branch3SpineLeafTopo}
