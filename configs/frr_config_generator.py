#!/usr/bin/env python3
"""
frr_config_generator.py
Tạo file cấu hình FRRouting (FRR) cho từng router trong hệ thống.

Cấu trúc cấu hình:
  - P-Routers: OSPF + LDP
  - PE-Routers: OSPF + LDP + MP-BGP (EVPN) + VPLS
  - CE-Routers: OSPF hoặc Static (đơn giản)
"""

import os

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'configs')
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ============================================================
# OSPF + LDP Config cho P-Routers
# ============================================================
P_ROUTER_TEMPLATE = """\
! {name} - Provider Router (P)
! OSPF Area 0 + LDP for MPLS Label Distribution
!
frr defaults traditional
hostname {name}
log syslog informational
!
interface lo
 ip address {loopback}/32
 ip ospf area 0
!
{interfaces}
!
router ospf
 ospf router-id {loopback}
 network {loopback}/32 area 0
{ospf_networks}
!
mpls ldp
 router-id {loopback}
 address-family ipv4
  discovery transport-address {loopback}
{ldp_interfaces}
 exit-address-family
!
line vty
!
"""

# ============================================================
# OSPF + LDP + MP-BGP Config cho PE-Routers
# ============================================================
PE_ROUTER_TEMPLATE = """\
! {name} - Provider Edge Router (PE)
! OSPF + LDP + MP-BGP (EVPN/VPLS)
!
frr defaults traditional
hostname {name}
log syslog informational
!
interface lo
 ip address {loopback}/32
 ip ospf area 0
!
{interfaces}
!
router ospf
 ospf router-id {loopback}
 network {loopback}/32 area 0
{ospf_networks}
!
mpls ldp
 router-id {loopback}
 address-family ipv4
  discovery transport-address {loopback}
{ldp_interfaces}
 exit-address-family
!
router bgp {asn}
 bgp router-id {loopback}
 bgp log-neighbor-changes
{bgp_neighbors}
 !
 address-family l2vpn evpn
{evpn_neighbors}
  advertise-all-vni
 exit-address-family
!
line vty
!
"""

# ============================================================
# Static/OSPF Config cho CE-Routers
# ============================================================
CE_ROUTER_TEMPLATE = """\
! {name} - Customer Edge Router (CE)
! Simple OSPF toward PE + connected LAN routes
!
frr defaults traditional
hostname {name}
log syslog informational
!
interface lo
 ip address {loopback}/32
!
{interfaces}
!
router ospf
 ospf router-id {loopback}
 network {loopback}/32 area 0
{ospf_networks}
 redistribute connected
!
line vty
!
"""


def write_config(filename, content):
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  Đã tạo: {path}")


def generate_p_router(name, loopback, iface_ips, ospf_nets):
    """
    iface_ips: list of (iface_name, ip/prefix)
    ospf_nets: list of (network/prefix, area)
    """
    iface_block = ''
    ldp_block = ''
    ospf_block = ''
    for iface, ip in iface_ips:
        iface_block += f'interface {iface}\n ip address {ip}\n ip ospf area 0\n!\n'
        ldp_block   += f'  interface {iface}\n'
    for net, area in ospf_nets:
        ospf_block  += f'  network {net} area {area}\n'

    config = P_ROUTER_TEMPLATE.format(
        name=name, loopback=loopback,
        interfaces=iface_block.strip(),
        ospf_networks=ospf_block,
        ldp_interfaces=ldp_block
    )
    write_config(f'{name}.conf', config)


def generate_pe_router(name, loopback, asn, iface_ips, ospf_nets, bgp_peers):
    """
    bgp_peers: list of (peer_ip, remote_asn, is_evpn)
    """
    iface_block = ''
    ldp_block   = ''
    ospf_block  = ''
    bgp_n_block = ''
    evpn_block  = ''

    for iface, ip in iface_ips:
        iface_block += f'interface {iface}\n ip address {ip}\n ip ospf area 0\n!\n'
        ldp_block   += f'  interface {iface}\n'
    for net, area in ospf_nets:
        ospf_block  += f'  network {net} area {area}\n'
    for peer, rasn, evpn in bgp_peers:
        bgp_n_block += f' neighbor {peer} remote-as {rasn}\n'
        bgp_n_block += f' neighbor {peer} update-source lo\n'
        if evpn:
            evpn_block += f'  neighbor {peer} activate\n'

    config = PE_ROUTER_TEMPLATE.format(
        name=name, loopback=loopback, asn=asn,
        interfaces=iface_block.strip(),
        ospf_networks=ospf_block,
        ldp_interfaces=ldp_block,
        bgp_neighbors=bgp_n_block,
        evpn_neighbors=evpn_block
    )
    write_config(f'{name}.conf', config)


def generate_ce_router(name, loopback, iface_ips, ospf_nets):
    iface_block = ''
    ospf_block  = ''
    for iface, ip in iface_ips:
        iface_block += f'interface {iface}\n ip address {ip}\n!\n'
    for net, area in ospf_nets:
        ospf_block  += f'  network {net} area {area}\n'

    config = CE_ROUTER_TEMPLATE.format(
        name=name, loopback=loopback,
        interfaces=iface_block.strip(),
        ospf_networks=ospf_block
    )
    write_config(f'{name}.conf', config)


def main():
    print("=== Tạo cấu hình FRR cho tất cả routers ===\n")
    ASN = 65000   # Internal AS cho MPLS backbone

    # ---- P01 ----
    generate_p_router('p01', '10.0.0.1',
        iface_ips=[
            ('p01-eth0', '10.0.10.1/30'),
            ('p01-eth1', '10.0.13.1/30'),
            ('p01-pe01', '10.0.20.2/30'),
        ],
        ospf_nets=[
            ('10.0.10.0/30', '0'), ('10.0.13.0/30', '0'), ('10.0.20.0/30', '0'),
        ]
    )

    # ---- P02 ----
    generate_p_router('p02', '10.0.0.2',
        iface_ips=[
            ('p02-eth0', '10.0.10.2/30'),
            ('p02-eth1', '10.0.11.1/30'),
            ('p02-eth2', '10.0.14.1/30'),
            ('p02-pe01', '10.0.21.2/30'),
            ('p02-pe02', '10.0.22.2/30'),
        ],
        ospf_nets=[
            ('10.0.10.0/30','0'),('10.0.11.0/30','0'),('10.0.14.0/30','0'),
            ('10.0.21.0/30','0'),('10.0.22.0/30','0'),
        ]
    )

    # ---- P03 ----
    generate_p_router('p03', '10.0.0.3',
        iface_ips=[
            ('p03-eth0', '10.0.11.2/30'),
            ('p03-eth1', '10.0.12.1/30'),
            ('p03-eth2', '10.0.13.2/30'),
            ('p03-pe02', '10.0.23.2/30'),
            ('p03-pe03', '10.0.24.2/30'),
        ],
        ospf_nets=[
            ('10.0.11.0/30','0'),('10.0.12.0/30','0'),('10.0.13.0/30','0'),
            ('10.0.23.0/30','0'),('10.0.24.0/30','0'),
        ]
    )

    # ---- P04 ----
    generate_p_router('p04', '10.0.0.4',
        iface_ips=[
            ('p04-eth0', '10.0.12.2/30'),
            ('p04-eth1', '10.0.14.2/30'),
            ('p04-pe03', '10.0.25.2/30'),
        ],
        ospf_nets=[
            ('10.0.12.0/30','0'),('10.0.14.0/30','0'),('10.0.25.0/30','0'),
        ]
    )

    # ---- PE01 ----
    generate_pe_router('pe01', '10.0.0.11', ASN,
        iface_ips=[
            ('pe01-p01', '10.0.20.1/30'),
            ('pe01-p02', '10.0.21.1/30'),
            ('pe01-ce01','10.100.1.1/30'),
        ],
        ospf_nets=[
            ('10.0.20.0/30','0'),('10.0.21.0/30','0'),('10.100.1.0/30','0'),
        ],
        bgp_peers=[
            ('10.0.0.12', ASN, True),  # PE02
            ('10.0.0.13', ASN, True),  # PE03
        ]
    )

    # ---- PE02 ----
    generate_pe_router('pe02', '10.0.0.12', ASN,
        iface_ips=[
            ('pe02-p02', '10.0.22.1/30'),
            ('pe02-p03', '10.0.23.1/30'),
            ('pe02-ce02','10.100.2.1/30'),
        ],
        ospf_nets=[
            ('10.0.22.0/30','0'),('10.0.23.0/30','0'),('10.100.2.0/30','0'),
        ],
        bgp_peers=[
            ('10.0.0.11', ASN, True),
            ('10.0.0.13', ASN, True),
        ]
    )

    # ---- PE03 ----
    generate_pe_router('pe03', '10.0.0.13', ASN,
        iface_ips=[
            ('pe03-p03', '10.0.24.1/30'),
            ('pe03-p04', '10.0.25.1/30'),
            ('pe03-ce03','10.100.3.1/30'),
        ],
        ospf_nets=[
            ('10.0.24.0/30','0'),('10.0.25.0/30','0'),('10.100.3.0/30','0'),
        ],
        bgp_peers=[
            ('10.0.0.11', ASN, True),
            ('10.0.0.12', ASN, True),
        ]
    )

    # ---- CE01 ----
    generate_ce_router('ce01', '10.0.0.21',
        iface_ips=[
            ('ce01-pe01', '10.100.1.2/30'),
            ('ce01-sw01', '10.1.0.1/24'),
        ],
        ospf_nets=[
            ('10.100.1.0/30','0'),('10.1.0.0/24','0'),
        ]
    )

    # ---- CE02 ----
    generate_ce_router('ce02', '10.0.0.22',
        iface_ips=[
            ('ce02-pe02', '10.100.2.2/30'),
            ('ce02-c01',  '10.2.10.1/24'),
            ('ce02-c02',  '10.2.20.1/24'),
        ],
        ospf_nets=[
            ('10.100.2.0/30','0'),('10.2.10.0/24','0'),
            ('10.2.20.0/24','0'),('10.2.30.0/24','0'),
        ]
    )

    # ---- CE03 ----
    generate_ce_router('ce03', '10.0.0.23',
        iface_ips=[
            ('ce03-pe03',   '10.100.3.2/30'),
            ('ce03-leaf01', '10.3.0.1/16'),
        ],
        ospf_nets=[
            ('10.100.3.0/30','0'),('10.3.0.0/16','0'),
        ]
    )

    print(f"\n=== Hoàn tất! Configs tại: {os.path.abspath(OUTPUT_DIR)} ===")


if __name__ == '__main__':
    main()
