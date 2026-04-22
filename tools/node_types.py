#!/usr/bin/env python3
"""
tools/node_types.py
===================
Module chứa các Mininet node class dùng chung cho toàn bộ project.

Tránh định nghĩa lại LinuxRouter / MPLSRouter ở nhiều file.
Import từ đây:
    from node_types import LinuxRouter, MPLSRouter
"""

from mininet.node import Node


class LinuxRouter(Node):
    """
    Mininet node chạy như một Linux Router.
    Bật IP forwarding để cho phép forward packets giữa các interface.

    Dùng cho: CE routers trong isolated branch tests.
    """
    def config(self, **params):
        super().config(**params)
        self.cmd('sysctl -w net.ipv4.ip_forward=1')

    def terminate(self):
        self.cmd('sysctl -w net.ipv4.ip_forward=0')
        super().terminate()


class MPLSRouter(Node):
    """
    Linux Router với MPLS support đầy đủ.
    Bật IP forwarding + MPLS platform labels + MPLS input trên loopback.

    Dùng cho: P-Routers và PE-Routers trong MPLS Backbone và Full topology.
    """
    def config(self, **params):
        super().config(**params)
        # IP forwarding
        self.cmd('sysctl -w net.ipv4.ip_forward=1')
        # MPLS label space (max labels)
        self.cmd('sysctl -w net.mpls.platform_labels=1048575')
        # Bật MPLS input trên loopback (cần cho LDP/OSPF Router-ID)
        self.cmd('sysctl -w net.mpls.conf.lo.input=1 2>/dev/null || true')

    def terminate(self):
        self.cmd('sysctl -w net.ipv4.ip_forward=0')
        super().terminate()


def enable_mpls_on_interfaces(router, interfaces):
    """
    Bật MPLS input trên danh sách interface của một router.

    Args:
        router: Mininet node object
        interfaces: list of interface name strings (e.g. ['eth0', 'eth1'])
    """
    for intf in interfaces:
        router.cmd(f'sysctl -w net.mpls.conf.{intf}.input=1 2>/dev/null || true')
