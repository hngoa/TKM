#!/usr/bin/env python3
"""
tools/frr_manager.py
====================
FRR (FRRouting) Deployment Manager

Triển khai file cấu hình FRR (.conf) vào các Mininet nodes đang chạy.
Thay thế frr_deploy.py cũ với kiến trúc rõ ràng hơn.

Chức năng chính:
  - deploy_to_node()     : Deploy FRR config vào 1 node
  - deploy_backbone()    : Deploy cho tất cả P + PE routers
  - push_ce_config()     : ISP đẩy CE config xuống chi nhánh
  - wait_convergence()   : Chờ OSPF/LDP hội tụ
  - verify_ospf()        : Kiểm tra OSPF neighbors
  - verify_ldp()         : Kiểm tra LDP sessions
  - verify_bgp()         : Kiểm tra BGP sessions
  - setup_vpls_bridge()  : Setup Linux bridge VPLS (fallback)

Yêu cầu: FRR đã được cài (sudo apt install -y frr frr-pythontools)
"""

import os
import sys
import time
import subprocess
from mininet.log import info, warn, error


# Thư mục gốc của project (parent của tools/)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Danh sách P-Routers (chạy OSPF + LDP)
P_ROUTERS  = ['p01', 'p02', 'p03', 'p04']

# Danh sách PE-Routers (chạy OSPF + LDP + BGP + VPLS)
PE_ROUTERS = ['pe01', 'pe02', 'pe03']

# Danh sách CE-Routers (OSPF + static, config do ISP cung cấp)
CE_ROUTERS = ['ce01', 'ce02', 'ce03']

# Map: router -> file config FRR
BACKBONE_CONFIGS = {
    'p01':  'configs/backbone/frr/p01.conf',
    'p02':  'configs/backbone/frr/p02.conf',
    'p03':  'configs/backbone/frr/p03.conf',
    'p04':  'configs/backbone/frr/p04.conf',
    'pe01': 'configs/backbone/frr/pe01.conf',
    'pe02': 'configs/backbone/frr/pe02.conf',
    'pe03': 'configs/backbone/frr/pe03.conf',
}

CE_CONFIGS = {
    'ce01': 'configs/branch1/ce01.conf',
    'ce02': 'configs/branch2/ce02.conf',
    'ce03': 'configs/branch3/ce03.conf',
}


class FRRManager:
    """
    Quản lý triển khai FRR vào Mininet nodes.
    
    Sử dụng:
        mgr = FRRManager(net)
        mgr.deploy_backbone()           # Triển khai P + PE routers
        mgr.push_ce_configs()           # ISP đẩy config xuống CE
        mgr.wait_convergence(timeout=30)
        mgr.verify_all()
    """

    def __init__(self, net, configs_root=None):
        """
        Args:
            net         : Mininet network object
            configs_root: Thư mục gốc chứa configs/ (mặc định = PROJECT_ROOT)
        """
        self.net = net
        self.configs_root = configs_root or PROJECT_ROOT
        self._node_run_dir = {}  # node_name -> per-node runtime directory
        self._check_frr_installed()

    def _check_frr_installed(self):
        """Kiểm tra FRR đã cài đặt chưa."""
        result = subprocess.run(['which', 'zebra'], capture_output=True)
        if result.returncode != 0:
            result2 = subprocess.run(
                ['ls', '/usr/lib/frr/zebra'], capture_output=True
            )
            if result2.returncode != 0:
                warn(
                    "[FRRManager] FRR chưa được cài đặt!\n"
                    "             Chạy: sudo apt install -y frr frr-pythontools\n"
                    "             Tiếp tục với static routes fallback...\n"
                )
                self.frr_available = False
                return
        self.frr_available = True
        info("[FRRManager] FRR detected OK\n")

    # ------------------------------------------------------------------
    # Pre-deployment: Stop host FRR + Load MPLS modules
    # ------------------------------------------------------------------

    def _stop_host_frr(self):
        """
        Dừng FRR service của host và kill tất cả FRR processes còn sót.

        Tại sao cần:
          Mininet nodes chia sẻ PID namespace với host.
          Nếu host FRR đang chạy, per-node daemons sẽ bị conflict:
          - Socket paths bị chiếm bởi host zebra
          - ps aux hiển thị host daemons, gây nhầm lẫn
          - vtysh kết nối vào host daemon thay vì per-node daemon
        """
        info('  [*] Dừng host FRR service (tránh conflict với per-node daemons)...\n')
        subprocess.run(['systemctl', 'stop', 'frr'], capture_output=True)
        time.sleep(0.5)

        # Kill mọi FRR process còn sót lại
        for daemon in ['zebra', 'ospfd', 'ldpd', 'bgpd', 'staticd', 'bfdd']:
            subprocess.run(['pkill', '-9', '-f', f'/usr/lib/frr/{daemon}'],
                           capture_output=True)
        time.sleep(0.5)

        # Xoá stale socket/pid files
        subprocess.run(['rm', '-f',
                        '/var/run/frr/zserv.api',
                        '/var/run/frr/*.pid',
                        '/var/run/frr/*.vty'],
                       capture_output=True)
        info('  [OK] Host FRR đã dừng\n')

    def _load_mpls_modules(self):
        """
        Load MPLS kernel modules (cần cho LDP label switching).

        Modules:
          mpls_router    — core MPLS forwarding
          mpls_iptunnel  — MPLS tunnel encapsulation
          mpls_gso       — GSO segmentation cho MPLS
        """
        info('  [*] Loading MPLS kernel modules...\n')
        loaded = []
        for mod in ['mpls_router', 'mpls_iptunnel', 'mpls_gso']:
            result = subprocess.run(['modprobe', mod], capture_output=True)
            if result.returncode == 0:
                loaded.append(mod)
        if loaded:
            info(f'  [OK] Loaded: {", ".join(loaded)}\n')
        else:
            warn('  [WARN] Không load được MPLS modules — LDP sẽ không hoạt động\n')
            warn('         Kernel có thể chưa hỗ trợ MPLS (cần kernel >= 4.1)\n')

    # ------------------------------------------------------------------
    # Core: Deploy FRR to a single node
    # ------------------------------------------------------------------

    def deploy_to_node(self, node_name, conf_path):
        """
        Deploy FRR config vào một Mininet node.

        Mininet nodes CHIA SẾ filesystem nhưng có network namespace riêng.
        => Mỗi node phải dùng:
          - Config file riêng: /tmp/frr_<node>.conf
          - Runtime dir riêng: /var/run/frr/<node>/
          - Socket riêng:     /var/run/frr/<node>/zserv.api
        Không dùng /etc/frr/frr.conf (shared — bị node sau ghi đè).

        Args:
            node_name: tên node trong Mininet (ví dụ: 'p01')
            conf_path: đường dẫn đến file .conf (tương đối từ configs_root)
        """
        if not self.frr_available:
            warn(f"  [SKIP] FRR unavailable, skipping {node_name}\n")
            return False

        full_conf_path = os.path.join(self.configs_root, conf_path)
        if not os.path.exists(full_conf_path):
            warn(f"  [SKIP] Config không tồn tại: {full_conf_path}\n")
            return False

        node = self.net.get(node_name)
        if node is None:
            warn(f"  [SKIP] Node {node_name} không tồn tại trong topology\n")
            return False

        info(f"  [FRR] Deploying to {node_name}...\n")

        # Per-node paths — tránh conflict với các nodes khác
        conf_file = f'/tmp/frr_{node_name}.conf'
        run_dir   = f'/var/run/frr/{node_name}'
        sock      = f'{run_dir}/zserv.api'
        log_file  = f'/var/log/frr_{node_name}.log'

        # Đọc config content từ host filesystem và ghi vào per-node path
        with open(full_conf_path, 'r') as f:
            conf_content = f.read()
        with open(conf_file, 'w') as f:
            f.write(conf_content)
        node.cmd(f'chmod 644 {conf_file}')

        # Tạo runtime directory riêng cho node này
        node.cmd(f'mkdir -p {run_dir} /var/log/frr')
        node.cmd(f'chmod 755 {run_dir}')

        # Lưu run_dir để vtysh sử dụng sau (--vty_socket cần directory)
        self._node_run_dir[node_name] = run_dir

        # Khởi động daemons
        return self._start_frr_daemons(node, node_name, conf_file, run_dir, sock, log_file)

    def _get_daemons_config(self, node_name):
        """Trả về nội dung file /etc/frr/daemons phù hợp với loại router."""
        base = (
            "zebra=yes\n"
            "bgpd=no\n"
            "ospfd=yes\n"
            "ospf6d=no\n"
            "ripd=no\n"
            "ripngd=no\n"
            "isisd=no\n"
            "ldpd=yes\n"
            "nhrpd=no\n"
            "eigrpd=no\n"
            "sharpd=no\n"
            "staticd=yes\n"
            "pbrd=no\n"
            "bfdd=no\n"
            "fabricd=no\n"
            "vrrpd=no\n"
            "vtysh_enable=yes\n"
        )
        if node_name in PE_ROUTERS:
            # PE cần thêm BGP
            return base.replace("bgpd=no", "bgpd=yes")
        if node_name in CE_ROUTERS:
            # CE không cần LDP
            return base.replace("ldpd=yes", "ldpd=no")
        return base  # P routers: OSPF + LDP

    def _start_frr_daemons(self, node, node_name, conf_file, run_dir, sock, log_file):
        """
        Khởi động FRR daemons trong network namespace của node.

        Quan trọng:
          - Phải dùng --vty_socket <run_dir> cho MỌI daemon
            để VTY sockets (*.vty) nằm trong thư mục per-node,
            tránh conflict giữa các nodes.
          - -z <sock> chỉ định zserv API socket (ospfd/ldpd/bgpd
            kết nối vào zebra qua socket này).
          - Host FRR phải đã được stop trước (xem _stop_host_frr).
        """
        info(f"     [INFO] Starting FRR daemons for {node_name}...\n")

        # Zebra trước — các daemon khác kết nối vào socket của zebra
        node.cmd(
            f'/usr/lib/frr/zebra -d '
            f'-f {conf_file} '
            f'-i {run_dir}/zebra.pid '
            f'-z {sock} '
            f'--vty_socket {run_dir} '
            f'--log file:{log_file} '
            f'2>/dev/null'
        )
        time.sleep(1.5)  # Đợi zebra tạo zserv socket

        # Kiểm tra zebra socket ngay sau khi start
        check = node.cmd(f'ls {sock} 2>/dev/null').strip()
        if sock not in check and check != sock:
            warn(f"     [WARN] {node_name}: zebra socket chưa tạo, thử chờ thêm...\n")
            time.sleep(2.0)
            check = node.cmd(f'ls {sock} 2>/dev/null').strip()
            if sock not in check and check != sock:
                # In lỗi chi tiết
                err = node.cmd(
                    f'/usr/lib/frr/zebra '
                    f'-f {conf_file} -z {sock} --vty_socket {run_dir} '
                    f'2>&1; echo EXIT_CODE=$?'
                )
                warn(f"     [ERROR] zebra trên {node_name} KHÔNG start được!\n")
                warn(f"     [DEBUG] {err.strip()}\n")
                return False
        info(f"     [OK] zebra ready (sock={sock})\n")

        # OSPF daemon
        node.cmd(
            f'/usr/lib/frr/ospfd -d '
            f'-f {conf_file} '
            f'-i {run_dir}/ospfd.pid '
            f'-z {sock} '
            f'--vty_socket {run_dir} '
            f'2>/dev/null'
        )

        # LDP daemon (P + PE routers)
        if node_name in P_ROUTERS or node_name in PE_ROUTERS:
            node.cmd(
                f'/usr/lib/frr/ldpd -d '
                f'-f {conf_file} '
                f'-i {run_dir}/ldpd.pid '
                f'-z {sock} '
                f'--vty_socket {run_dir} '
                f'2>/dev/null'
            )

        # BGP daemon (PE routers only)
        if node_name in PE_ROUTERS:
            node.cmd(
                f'/usr/lib/frr/bgpd -d '
                f'-f {conf_file} '
                f'-i {run_dir}/bgpd.pid '
                f'-z {sock} '
                f'--vty_socket {run_dir} '
                f'2>/dev/null'
            )

        time.sleep(0.5)

        # Verify bằng PID files (chính xác hơn ps aux vì PID namespace shared)
        expected = ['zebra', 'ospfd']
        if node_name in P_ROUTERS or node_name in PE_ROUTERS:
            expected.append('ldpd')
        if node_name in PE_ROUTERS:
            expected.append('bgpd')

        running = []
        for daemon in expected:
            pid_file = f'{run_dir}/{daemon}.pid'
            pid = node.cmd(f'cat {pid_file} 2>/dev/null').strip()
            if pid and pid.isdigit():
                alive = node.cmd(f'kill -0 {pid} 2>&1; echo $?').strip()
                if alive.endswith('0'):
                    running.append(daemon)
        info(f"     [INFO] Daemons verified on {node_name}: {', '.join(running)}\n")

        missing = set(expected) - set(running)
        if missing:
            warn(f"     [WARN] {node_name}: missing daemons: {', '.join(missing)}\n")
        return True

    # ------------------------------------------------------------------
    # High-level: Deploy groups
    # ------------------------------------------------------------------

    def deploy_backbone(self):
        """Deploy FRR cho tất cả P và PE routers trong backbone."""
        info('\n*** [FRRManager] === Triển khai FRR Backbone ===\n')

        # Bước 0: Dọn dẹp host FRR + Load MPLS modules
        self._stop_host_frr()
        self._load_mpls_modules()

        # Deploy P-Routers trước
        info('  [*] P-Routers (OSPF + LDP):\n')
        for router in P_ROUTERS:
            conf = BACKBONE_CONFIGS.get(router)
            if conf:
                self.deploy_to_node(router, conf)

        # Deploy PE-Routers
        info('  [*] PE-Routers (OSPF + LDP + BGP + VPLS):\n')
        for router in PE_ROUTERS:
            conf = BACKBONE_CONFIGS.get(router)
            if conf:
                self.deploy_to_node(router, conf)

        info('*** [FRRManager] Backbone deployment hoàn tất\n')

    def push_ce_configs(self):
        """
        ISP đẩy cấu hình FRR xuống CE routers tại các chi nhánh.
        
        Đây là bước mô phỏng quy trình ISP cung cấp dịch vụ:
        PE router biết CE config → deploy config xuống CE → CE tự động
        thiết lập kết nối OSPF với PE → quảng bá LAN subnets lên backbone.
        """
        info('\n*** [FRRManager] === ISP Push CE Configs ===\n')
        info('    (Mô phỏng ISP triển khai config xuống thiết bị CE tại chi nhánh)\n')

        for ce_name, conf_path in CE_CONFIGS.items():
            info(f'  [ISP -> {ce_name}] Deploying customer edge config...\n')
            self.deploy_to_node(ce_name, conf_path)

        info('*** [FRRManager] CE config deployment hoàn tất\n')

    # ------------------------------------------------------------------
    # VPLS: Linux Bridge fallback (khi FRR VPLS không khả dụng)
    # ------------------------------------------------------------------

    def setup_vpls_bridge(self, vpls_config):
        """
        Thiết lập VPLS bằng GRE tunnel + Linux bridge trên PE routers.
        
        Phương án fallback khi FRR không hỗ trợ native VPLS.
        Mỗi PE tạo GRE tunnel đến PE khác, bridge lại với AC interface.
        
        Args:
            vpls_config: dict từ vpls_policy.yaml
        """
        if not vpls_config.get('linux_vpls_fallback', {}).get('enabled', False):
            info('[FRRManager] Linux VPLS fallback disabled, skipping\n')
            return

        info('\n*** [FRRManager] === Setup Linux Bridge VPLS ===\n')
        fallback_cfg = vpls_config['linux_vpls_fallback']
        bridge_name  = fallback_cfg.get('bridge_name', 'vpls-br')

        # VPLS member map: pe_name -> ac_interface
        member_map = {
            m['pe']: m['ac_interface']
            for m in vpls_config.get('members', [])
        }

        # Tạo GRE tunnels và bridge trên mỗi PE
        for tunnel_cfg in fallback_cfg.get('tunnels', []):
            local_pe  = tunnel_cfg['local_pe']
            remote_pe = tunnel_cfg['remote_pe']
            local_ip  = tunnel_cfg['local_ip']
            remote_ip = tunnel_cfg['remote_ip']
            gre_key   = tunnel_cfg.get('key', 100)
            tun_name  = tunnel_cfg['name']

            node = self.net.get(local_pe)
            if node is None:
                continue

            info(f'  [+] GRE tunnel: {local_pe} -> {remote_pe} (key={gre_key})\n')

            # Tạo GRE tunnel interface
            node.cmd(f'ip tunnel add {tun_name} mode gre '
                     f'local {local_ip} remote {remote_ip} key {gre_key} 2>/dev/null || true')
            node.cmd(f'ip link set {tun_name} up')

        # Tạo bridge và add interfaces trên mỗi PE
        for pe_name, ac_intf in member_map.items():
            node = self.net.get(pe_name)
            if node is None:
                continue

            info(f'  [+] Bridge {bridge_name} on {pe_name} (AC: {ac_intf})\n')

            # Tạo Linux bridge
            node.cmd(f'ip link add {bridge_name} type bridge 2>/dev/null || true')
            node.cmd(f'ip link set {bridge_name} up')

            # Add AC interface vào bridge
            node.cmd(f'ip link set {ac_intf} master {bridge_name} 2>/dev/null || true')

            # Add GRE tunnels vào bridge
            for tunnel_cfg in fallback_cfg.get('tunnels', []):
                if tunnel_cfg['local_pe'] == pe_name:
                    tun_name = tunnel_cfg['name']
                    node.cmd(f'ip link set {tun_name} master {bridge_name} 2>/dev/null || true')
                    info(f"       Added tunnel {tun_name} to bridge\n")

        info('*** [FRRManager] VPLS Bridge setup hoàn tất\n')

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def wait_convergence(self, timeout=30):
        """Chờ OSPF và LDP hội tụ."""
        info(f'\n*** [FRRManager] Chờ OSPF/LDP hội tụ ({timeout}s)...\n')
        for remaining in range(timeout, 0, -5):
            info(f'    ... {remaining}s còn lại\n')
            time.sleep(5)
        info('*** [FRRManager] Done waiting\n')

    def _vtysh(self, node, node_name, cmd):
        """
        Chạy vtysh command trên node, dùng per-node VTY socket directory.

        --vty_socket nhận DIRECTORY (không phải file) chứa *.vty sockets.
        Các daemon đã tạo VTY sockets tại run_dir nhờ --vty_socket khi start.
        """
        run_dir = self._node_run_dir.get(node_name)
        if run_dir:
            result = node.cmd(
                f'vtysh --vty_socket {run_dir} -c "{cmd}" 2>/dev/null'
            )
            if ('unrecognized option' not in result
                    and 'invalid option' not in result
                    and result.strip()):
                return result
        # Fallback: vtysh mặc định (khi không có per-node socket)
        return node.cmd(f'vtysh -c "{cmd}" 2>/dev/null || echo "vtysh_fallback"')

    def verify_ospf(self, router_names=None):
        """Kiểm tra OSPF neighbors trên các routers."""
        routers = router_names or (P_ROUTERS + PE_ROUTERS)
        info('\n  [4a] OSPF Neighbors:\n')
        all_ok = True
        for name in routers:
            node = self.net.get(name)
            if node is None:
                continue
            result = self._vtysh(node, name, 'show ip ospf neighbor')
            full_count = result.count('Full')
            info(f'  [{name}] Full neighbors: {full_count}\n')
            for line in result.strip().split('\n'):
                if line.strip():
                    info(f'    {line}\n')
            if full_count == 0:
                warn(f'  [WARN] {name}: Không có OSPF neighbor ở trạng thái Full\n')
                all_ok = False
        return all_ok

    def verify_ldp(self, router_names=None):
        """Kiểm tra LDP sessions."""
        routers = router_names or (P_ROUTERS + PE_ROUTERS)
        info('\n  [4b] LDP Sessions:\n')
        all_ok = True
        for name in routers:
            node = self.net.get(name)
            if node is None:
                continue
            result = self._vtysh(node, name, 'show mpls ldp neighbor')
            session_count = result.count('OPERATIONAL')
            info(f'  [{name}] LDP sessions: {session_count}\n')
            for line in result.strip().split('\n'):
                if line.strip() and 'vtysh' not in line:
                    info(f'    {line}\n')
            if session_count == 0:
                all_ok = False
        return all_ok

    def verify_bgp(self, pe_names=None):
        """Kiểm tra BGP sessions giữa PE routers."""
        pes = pe_names or PE_ROUTERS
        info('\n  [4c] BGP Sessions (PE-PE iBGP for VPLS):\n')
        all_ok = True
        for name in pes:
            node = self.net.get(name)
            if node is None:
                continue
            result = self._vtysh(node, name, 'show bgp l2vpn evpn summary')
            if 'not running' in result.lower() or 'vtysh error' in result.lower():
                result = self._vtysh(node, name, 'show bgp summary')
            established = result.count('Established')
            info(f'  [{name}] BGP Established sessions: {established}\n')
            for line in result.strip().split('\n'):
                if line.strip() and 'vtysh' not in line:
                    info(f'    {line}\n')
            if established == 0:
                warn(f'  [WARN] {name}: BGP chưa Established\n')
                all_ok = False
        return all_ok

    def verify_mpls_labels(self, router_names=None):
        """Kiểm tra MPLS label table."""
        routers = router_names or (P_ROUTERS + PE_ROUTERS)
        info('\n*** [FRRManager] === Kiểm tra MPLS Labels ===\n')
        for name in routers:
            node = self.net.get(name)
            if node is None:
                continue
            result = node.cmd('ip -M route 2>/dev/null || echo "MPLS not available"')
            info(f'  [{name}] MPLS routes:\n')
            for line in result.strip().split('\n')[:5]:  # Show first 5 lines
                if line.strip():
                    info(f'    {line}\n')

    def verify_all(self):
        """Chạy tất cả verification checks."""
        info('\n*** [FRRManager] === Verification Report ===\n')
        ospf_ok = self.verify_ospf()
        ldp_ok  = self.verify_ldp()
        bgp_ok  = self.verify_bgp()
        self.verify_mpls_labels()

        info('\n*** [FRRManager] Summary:\n')
        info(f'    OSPF: {"OK" if ospf_ok else "FAIL"}\n')
        info(f'    LDP:  {"OK" if ldp_ok  else "FAIL"}\n')
        info(f'    BGP:  {"OK" if bgp_ok  else "FAIL"}\n')
        return ospf_ok and ldp_ok and bgp_ok
