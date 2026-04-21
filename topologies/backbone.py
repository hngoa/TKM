#!/usr/bin/env python3
"""
backbone.py - MPLS Backbone Topology
Cấu trúc: 4 P-Router (P01-P04) + 3 PE-Router (PE01-PE03)
Mô hình Partial Mesh với Dual-homed PE
"""

from mininet.topo import Topo

class BackboneTopo(Topo):
    """
    MPLS Backbone Topology:
    - P01, P02, P03, P04: Core Provider Routers (Label Switching only)
    - PE01, PE02, PE03: Provider Edge Routers (VPLS endpoints)

    Kết nối Partial Mesh:
      P01 -- P02 -- P03 -- P04
       |      |      |      |
      PE01  PE01   PE02   PE03
             PE02  PE03

    Dual-homed:
      PE01 -> P01, P02
      PE02 -> P02, P03
      PE03 -> P03, P04
    """

    def build(self, **opts):
        # ---- P-Router nodes (core) ----
        p01 = self.addNode('p01', cls=None)
        p02 = self.addNode('p02', cls=None)
        p03 = self.addNode('p03', cls=None)
        p04 = self.addNode('p04', cls=None)

        # ---- PE-Router nodes (edge) ----
        pe01 = self.addNode('pe01', cls=None)
        pe02 = self.addNode('pe02', cls=None)
        pe03 = self.addNode('pe03', cls=None)

        # ---- P-P Links (Partial Mesh core) ----
        self.addLink(p01, p02, bw=1000, delay='1ms')
        self.addLink(p02, p03, bw=1000, delay='1ms')
        self.addLink(p03, p04, bw=1000, delay='1ms')
        self.addLink(p01, p03, bw=1000, delay='2ms')
        self.addLink(p02, p04, bw=1000, delay='2ms')

        # ---- PE-P Links (Dual-homed) ----
        # PE01 -> P01, P02
        self.addLink(pe01, p01, bw=1000, delay='1ms')
        self.addLink(pe01, p02, bw=1000, delay='1ms')

        # PE02 -> P02, P03
        self.addLink(pe02, p02, bw=1000, delay='1ms')
        self.addLink(pe02, p03, bw=1000, delay='1ms')

        # PE03 -> P03, P04
        self.addLink(pe03, p03, bw=1000, delay='1ms')
        self.addLink(pe03, p04, bw=1000, delay='1ms')


topos = {'backbone': BackboneTopo}
