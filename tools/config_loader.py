#!/usr/bin/env python3
"""
tools/config_loader.py
======================
Config-Driven IP Configuration Loader

Đọc file ip_plan.yaml và apply cấu hình IP vào các Mininet nodes.
Đây là trung tâm của kiến trúc Config-Driven: tách biệt topology và config.

Sử dụng:
    loader = ConfigLoader('configs/branch1/ip_plan.yaml')
    loader.apply_all(net)        # Apply toàn bộ config
    loader.apply_ce(net)         # Chỉ apply CE router config
    loader.apply_hosts(net)      # Chỉ apply host config
"""

import yaml
import os
import sys
from mininet.log import info, warn, error


class ConfigLoader:
    """
    Đọc YAML config và apply IP configuration vào Mininet nodes.
    
    Hỗ trợ:
    - CE router: IP trên các interfaces, loopback, static routes
    - Hosts: IP, mask, default gateway
    - Switches: chế độ standalone (không cần config IP)
    """

    def __init__(self, yaml_path):
        """
        Args:
            yaml_path: đường dẫn tuyệt đối hoặc tương đối đến file ip_plan.yaml
        """
        self.yaml_path = os.path.abspath(yaml_path)
        self.config = self._load_yaml()
        self.branch = self.config.get('branch', 'unknown')

    def _load_yaml(self):
        """Đọc và parse file YAML."""
        if not os.path.exists(self.yaml_path):
            raise FileNotFoundError(
                f"Config file không tồn tại: {self.yaml_path}\n"
                f"Hãy kiểm tra đường dẫn hoặc chạy từ thư mục gốc project."
            )
        with open(self.yaml_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        info(f"*** [ConfigLoader] Loaded: {self.yaml_path}\n")
        return config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply_all(self, net, mode='isolated'):
        """
        Apply toàn bộ config vào net.
        
        Args:
            net: Mininet network object
            mode: 'isolated' = chỉ LAN interfaces của CE
                  'full'     = cả WAN interfaces (dùng trong full topology)
        """
        info(f"\n*** [ConfigLoader] Áp dụng config cho {self.branch} (mode={mode})\n")
        self._apply_ce_router(net, mode)
        self._apply_hosts(net)
        info(f"*** [ConfigLoader] Hoàn tất config {self.branch}\n")

    def apply_all_full(self, net):
        """Apply config đầy đủ cho full topology (bao gồm WAN interfaces)."""
        self.apply_all(net, mode='full')

    def get_test_matrix(self):
        """Trả về test matrix từ config (dùng cho connectivity_test.py)."""
        return self.config.get('tests', {})

    def get_hosts(self):
        """Trả về danh sách host configs."""
        return self.config.get('hosts', [])

    def get_switches(self):
        """Trả về danh sách switch configs."""
        return self.config.get('switches', [])

    def get_ce_config(self):
        """Trả về CE router config."""
        return self.config.get('ce_router', {})

    def get_links(self):
        """Trả về danh sách link definitions."""
        return self.config.get('links', [])

    # ------------------------------------------------------------------
    # Internal: CE Router configuration
    # ------------------------------------------------------------------

    def _apply_ce_router(self, net, mode='isolated'):
        """Apply IP config cho CE router."""
        ce_cfg = self.config.get('ce_router', {})
        if not ce_cfg:
            warn(f"[ConfigLoader] Không tìm thấy ce_router config trong {self.yaml_path}\n")
            return

        ce_name = ce_cfg['name']
        node = net.nameToNode.get(ce_name)
        if node is None:
            warn(f"[ConfigLoader] Node '{ce_name}' không tồn tại trong topology\n")
            return

        info(f"  [+] Configuring CE router: {ce_name}\n")

        # Bật IP forwarding
        if ce_cfg.get('ip_forward', True):
            node.cmd('sysctl -w net.ipv4.ip_forward=1')

        # Bật MPLS nếu cần
        if ce_cfg.get('mpls_enable', False):
            node.cmd('sysctl -w net.mpls.platform_labels=1048575')
            node.cmd('sysctl -w net.mpls.conf.lo.input=1')

        # Cấu hình loopback
        loopback = ce_cfg.get('loopback')
        if loopback:
            node.cmd(f'ip addr add {loopback} dev lo 2>/dev/null || true')
            node.cmd('ip link set lo up')

        # Cấu hình interfaces
        for intf_cfg in ce_cfg.get('interfaces', []):
            intf_name = intf_cfg['name']
            intf_ip   = intf_cfg['ip']
            intf_mode = intf_cfg.get('mode', 'lan')

            # Trong isolated mode, bỏ qua WAN interface (chưa kết nối)
            if mode == 'isolated' and intf_mode == 'wan':
                info(f"     [SKIP] WAN interface {intf_name} (isolated mode)\n")
                continue

            # Kiểm tra interface tồn tại trong node
            intf_list = node.cmd('ip link show').strip()
            if intf_name not in intf_list:
                warn(f"     [WARN] Interface {intf_name} không tìm thấy trên {ce_name}\n")
                continue

            node.cmd(f'ip addr flush dev {intf_name} 2>/dev/null || true')
            node.cmd(f'ip addr add {intf_ip} dev {intf_name}')
            node.cmd(f'ip link set {intf_name} up')
            info(f"     {intf_name}: {intf_ip}\n")

        # Cấu hình static routes
        for route in ce_cfg.get('static_routes', []):
            prefix = route.get('prefix', '')
            via    = route.get('via', '')
            if not prefix:
                continue
            if not via:
                # directly connected, không cần add
                continue
            result = node.cmd(f'ip route add {prefix} via {via} 2>&1')
            if 'RTNETLINK' in result and 'File exists' not in result:
                warn(f"     [WARN] Route {prefix} via {via}: {result.strip()}\n")
            else:
                info(f"     route: {prefix} via {via}\n")

    # ------------------------------------------------------------------
    # Internal: Host configuration
    # ------------------------------------------------------------------

    def _apply_hosts(self, net):
        """
        Apply IP config cho hosts.
        
        Lưu ý: Hosts thường đã có IP từ lúc Mininet khởi tạo (addHost).
        Hàm này đảm bảo default route và interface state đúng.
        """
        for host_cfg in self.config.get('hosts', []):
            name    = host_cfg['name']
            ip      = host_cfg['ip']
            gateway = host_cfg.get('gateway', '')

            node = net.nameToNode.get(name)
            if node is None:
                warn(f"  [WARN] Host '{name}' không tồn tại trong topology\n")
                continue

            # Flush và set lại IP (đảm bảo nhất quán với YAML)
            # Lấy tên interface đầu tiên của host (thường là eth0)
            intf_name = f'{name}-eth0'
            intf_list_raw = node.cmd('ip link show')
            # Tìm interface thực của host
            actual_intf = node.defaultIntf()
            if actual_intf:
                node.cmd(f'ip addr flush dev {actual_intf.name} 2>/dev/null || true')
                node.cmd(f'ip addr add {ip} dev {actual_intf.name}')
                node.cmd(f'ip link set {actual_intf.name} up')

            # Set default route
            if gateway:
                node.cmd('ip route del default 2>/dev/null || true')
                node.cmd(f'ip route add default via {gateway}')

    # ------------------------------------------------------------------
    # Utility: Build Mininet net từ YAML (dùng trong runner scripts)
    # ------------------------------------------------------------------

    def build_net_from_config(self, net, extra_host_params=None):
        """
        Thêm nodes và links vào Mininet net object từ YAML config.
        
        Sử dụng trong runner scripts để build topology config-driven.
        CE router phải được add riêng bởi runner (cần LinuxRouter class).
        
        Args:
            net: Mininet network object (đã tạo với controller=None)
            extra_host_params: dict bổ sung cho addHost (ví dụ: cls=LinuxRouter)
        """
        from mininet.node import OVSSwitch

        # Add switches
        for sw_cfg in self.config.get('switches', []):
            sw_name = sw_cfg['name']
            sw_mode = sw_cfg.get('mode', 'standalone')
            failMode = sw_mode if sw_mode in ('standalone', 'secure') else 'standalone'
            net.addSwitch(sw_name, failMode=failMode)
            info(f"  [+] Switch: {sw_name} (failMode={failMode})\n")

        # Add hosts
        for host_cfg in self.config.get('hosts', []):
            name    = host_cfg['name']
            ip      = host_cfg['ip']
            gateway = host_cfg.get('gateway', '')
            params  = {'ip': ip}
            if gateway:
                params['defaultRoute'] = f'via {gateway}'
            if extra_host_params:
                params.update(extra_host_params)
            net.addHost(name, **params)
            info(f"  [+] Host: {name} ({ip})\n")

        # Add links
        for link_cfg in self.config.get('links', []):
            src      = link_cfg['src']
            dst      = link_cfg['dst']
            src_intf = link_cfg.get('src_intf')
            dst_intf = link_cfg.get('dst_intf')
            bw       = link_cfg.get('bw', 100)
            delay    = link_cfg.get('delay', '1ms')

            link_params = {'bw': bw, 'delay': delay}
            if src_intf:
                link_params['intfName1'] = src_intf
            if dst_intf:
                link_params['intfName2'] = dst_intf

            net.addLink(src, dst, **link_params)
            label = f"{src_intf or src} <-> {dst_intf or dst}"
            info(f"  [+] Link: {label} ({bw}Mbps, {delay})\n")


class BackboneConfigLoader:
    """
    Loader chuyên cho Backbone/ISP config (backbone/ip_plan.yaml).
    
    Xử lý cấu hình IP cho P-Routers và PE-Routers.
    """

    def __init__(self, yaml_path):
        self.yaml_path = os.path.abspath(yaml_path)
        self.config = self._load_yaml()

    def _load_yaml(self):
        if not os.path.exists(self.yaml_path):
            raise FileNotFoundError(f"Backbone config không tồn tại: {self.yaml_path}")
        with open(self.yaml_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def apply_all(self, net):
        """Apply IP config cho tất cả P và PE routers."""
        info('\n*** [BackboneLoader] Cấu hình IP cho MPLS Backbone\n')
        self._apply_loopbacks(net)
        self._apply_p_router_interfaces(net)
        self._apply_pe_router_interfaces(net)
        self._apply_ce_wan_interfaces(net)
        info('*** [BackboneLoader] Backbone IP config hoàn tất\n')

    @staticmethod
    def _get_node(net, name):
        """
        An toàn hơn net.get() — trả về None thay vì raise KeyError
        khi node không tồn tại trong topology (ví dụ: backbone-only mode).
        """
        return net.nameToNode.get(name)

    def _apply_loopbacks(self, net):
        """Apply loopback IPs cho tất cả routers."""
        info('  [*] Cấu hình loopback addresses\n')
        all_routers = (
            self.config.get('p_routers', []) +
            self.config.get('pe_routers', [])
        )
        for router in all_routers:
            name = router['name']
            lo   = router.get('loopback', '')
            if not lo:
                continue
            node = self._get_node(net, name)
            if node is None:
                warn(f"  [WARN] Router {name} not found in topology (skipping)\n")
                continue
            node.cmd(f'ip addr add {lo} dev lo 2>/dev/null || true')
            node.cmd('ip link set lo up')
            # Bật MPLS trên loopback
            lo_dev = lo.split('/')[0]
            node.cmd(f'sysctl -w net.mpls.conf.lo.input=1 2>/dev/null || true')
            info(f"     {name} lo: {lo}\n")

    def _apply_p_router_interfaces(self, net):
        """Apply IP config và static routes cho P-Routers."""
        info('  [*] Cấu hình P-Router interfaces & routes\n')
        for router in self.config.get('p_routers', []):
            name = router['name']
            node = self._get_node(net, name)
            if node is None:
                warn(f'  [WARN] P-Router {name} not found in topology (skipping)\n')
                continue
            node.cmd('sysctl -w net.ipv4.ip_forward=1')
            node.cmd('sysctl -w net.mpls.platform_labels=1048575')

            # Cấu hình interfaces
            for intf in router.get('interfaces', []):
                intf_name = intf['name']
                intf_ip   = intf['ip']
                # Flush IP cũ (Mininet tự assign ngẫu nhiên khi tạo link)
                node.cmd(f'ip addr flush dev {intf_name} 2>/dev/null || true')
                node.cmd(f'ip addr add {intf_ip} dev {intf_name} 2>/dev/null || true')
                node.cmd(f'ip link set {intf_name} up')
                # Bật MPLS input: dùng /proc/sys để tránh vấn đề dấu '-' trong sysctl path
                node.cmd(f'echo 1 > /proc/sys/net/mpls/conf/{intf_name}/input 2>/dev/null || true')
                info(f"     {name} {intf_name}: {intf_ip}\n")

            # Cấu hình static routes (nếu có)
            for route in router.get('static_routes', []):
                prefix = route.get('prefix')
                via    = route.get('via')
                if prefix and via:
                    node.cmd(f'ip route add {prefix} via {via} 2>/dev/null || true')
                    info(f"     {name} route: {prefix} via {via}\n")

    def _apply_pe_router_interfaces(self, net):
        """Apply IP config và static routes cho PE-Routers."""
        info('  [*] Cấu hình PE-Router interfaces & routes\n')
        for router in self.config.get('pe_routers', []):
            name = router['name']
            node = self._get_node(net, name)
            if node is None:
                warn(f'  [WARN] PE-Router {name} not found in topology (skipping)\n')
                continue
            node.cmd('sysctl -w net.ipv4.ip_forward=1')
            node.cmd('sysctl -w net.mpls.platform_labels=1048575')

            # Cấu hình interfaces
            for intf in router.get('interfaces', []):
                intf_name = intf['name']
                intf_ip   = intf['ip']
                # Flush IP cũ (Mininet tự assign ngẫu nhiên khi tạo link)
                node.cmd(f'ip addr flush dev {intf_name} 2>/dev/null || true')
                node.cmd(f'ip addr add {intf_ip} dev {intf_name} 2>/dev/null || true')
                node.cmd(f'ip link set {intf_name} up')
                # Bật MPLS chỉ trên backbone interfaces (không trên AC/WAN port)
                if not intf.get('wan_link', False):
                    node.cmd(f'echo 1 > /proc/sys/net/mpls/conf/{intf_name}/input 2>/dev/null || true')
                info(f"     {name} {intf_name}: {intf_ip}\n")

            # Cấu hình static routes (nếu có)
            for route in router.get('static_routes', []):
                prefix = route.get('prefix')
                via    = route.get('via')
                if prefix and via:
                    node.cmd(f'ip route add {prefix} via {via} 2>/dev/null || true')
                    info(f"     {name} route: {prefix} via {via}\n")

    def _apply_ce_wan_interfaces(self, net):
        """Apply WAN IP cho CE routers (PE side đã xong, giờ apply CE side)."""
        info('  [*] Cấu hình CE WAN interfaces (từ ISP)\n')
        for wan in self.config.get('wan_links', []):
            ce_name  = wan['ce']
            ce_ip    = wan['ce_ip']
            # Tên interface CE-PE theo convention: ce01-pe01
            intf_name = f"{ce_name}-{wan['pe']}"
            node = self._get_node(net, ce_name)
            if node is None:
                info(f'     [SKIP] {ce_name} không có trong topology (backbone-only mode)\n')
                continue
            node.cmd(f'ip addr add {ce_ip} dev {intf_name} 2>/dev/null || true')
            node.cmd(f'ip link set {intf_name} up')
            info(f"     {ce_name} {intf_name}: {ce_ip}\n")

    def get_wan_links(self):
        return self.config.get('wan_links', [])

    def get_backbone_links(self):
        return self.config.get('backbone_links', [])

    def get_pe_p_links(self):
        return self.config.get('pe_p_links', [])
