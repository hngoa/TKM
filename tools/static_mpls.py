#!/usr/bin/env python3
"""
tools/static_mpls.py
====================
Static MPLS Label Switching + GRE VPLS

Thay thế FRR daemons bằng cấu hình tĩnh:
  - Static routes:  IP reachability  (thay OSPF)
  - Static MPLS:    push/swap/pop    (thay LDP)
  - GRE + Bridge:   pseudowire       (thay VPLS signaling)

Ưu điểm:
  ✓ 100% reliable — không phụ thuộc daemon startup
  ✓ Transparent — labels hiển thị tường minh
  ✓ Fast — không cần chờ 30s convergence
  ✓ Educational — từng bước MPLS rõ ràng

Chạy: sudo python3 runners/run_backbone.py --test
"""

import os
import subprocess
import yaml
from mininet.log import info, warn

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# ================================================================
# MPLS Label Plan
#   Label = 100 + last octet of loopback IP
#   VD: PE01 (10.0.0.11) → label 111
#       PE02 (10.0.0.12) → label 112
# ================================================================
LOOPBACKS = {
    'p01': '10.0.0.1',   'p02': '10.0.0.2',
    'p03': '10.0.0.3',   'p04': '10.0.0.4',
    'pe01': '10.0.0.11',  'pe02': '10.0.0.12',  'pe03': '10.0.0.13',
}

def _label_for(loopback_ip):
    """Tính label từ loopback IP. VD: 10.0.0.13 → 113"""
    last = int(loopback_ip.split('.')[-1])
    return 100 + last

# ================================================================
# Next-hop table: cho mỗi router, đường đến mỗi PE loopback
# Format: NEXT_HOP[router][dest_loopback] = (next_hop_ip, out_intf, role)
#   role: 'php' = penultimate hop pop, 'transit' = swap, 'push' = ingress
# ================================================================
MPLS_PATHS = {
    # --- P01 ---
    'p01': {
        '10.0.0.11': ('10.0.20.1', 'p01-pe01', 'php'),    # P01→PE01 direct
        '10.0.0.12': ('10.0.10.2', 'p01-eth0', 'transit'), # P01→P02→PE02
        '10.0.0.13': ('10.0.13.2', 'p01-eth1', 'transit'), # P01→P03→PE03
    },
    # --- P02 ---
    'p02': {
        '10.0.0.11': ('10.0.21.1', 'p02-pe01', 'php'),    # P02→PE01 direct
        '10.0.0.12': ('10.0.22.1', 'p02-pe02', 'php'),    # P02→PE02 direct
        '10.0.0.13': ('10.0.11.2', 'p02-eth1', 'transit'), # P02→P03→PE03
    },
    # --- P03 ---
    'p03': {
        '10.0.0.11': ('10.0.13.1', 'p03-eth2', 'transit'), # P03→P01→PE01
        '10.0.0.12': ('10.0.23.1', 'p03-pe02', 'php'),    # P03→PE02 direct
        '10.0.0.13': ('10.0.24.1', 'p03-pe03', 'php'),    # P03→PE03 direct
    },
    # --- P04 ---
    'p04': {
        '10.0.0.11': ('10.0.14.1', 'p04-eth1', 'transit'), # P04→P02→PE01
        '10.0.0.12': ('10.0.14.1', 'p04-eth1', 'transit'), # P04→P02→PE02
        '10.0.0.13': ('10.0.25.1', 'p04-pe03', 'php'),    # P04→PE03 direct
    },
    # --- PE01 (ingress) ---
    'pe01': {
        '10.0.0.12': ('10.0.21.2', 'pe01-p02', 'push'),   # PE01→P02→PE02
        '10.0.0.13': ('10.0.20.2', 'pe01-p01', 'push'),   # PE01→P01→P03→PE03
    },
    # --- PE02 (ingress) ---
    'pe02': {
        '10.0.0.11': ('10.0.22.2', 'pe02-p02', 'push'),   # PE02→P02→PE01
        '10.0.0.13': ('10.0.23.2', 'pe02-p03', 'push'),   # PE02→P03→PE03
    },
    # --- PE03 (ingress) ---
    'pe03': {
        '10.0.0.11': ('10.0.24.2', 'pe03-p03', 'push'),   # PE03→P03→P01→PE01
        '10.0.0.12': ('10.0.24.2', 'pe03-p03', 'push'),   # PE03→P03→PE02
    },
}


class StaticMPLSManager:
    """
    Triển khai MPLS tĩnh + VPLS bằng GRE bridge.

    Mô hình:
      PE01 --[push label]--> P01 --[swap/php]--> P03 --[pop]--> PE03
                                                        |
                                          GRE tunnel (pseudowire)
                                                        |
                                              Linux bridge (vpls-br)
                                                        |
                                                   AC interface
    """

    def __init__(self, net, vpls_config_path=None):
        self.net = net
        self.vpls_config = self._load_vpls_config(vpls_config_path)

    def _load_vpls_config(self, path=None):
        vpls_path = path or os.path.join(
            PROJECT_ROOT, 'configs', 'backbone', 'vpls_policy.yaml')
        if os.path.exists(vpls_path):
            with open(vpls_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        return {}

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def deploy_all(self):
        """Deploy đầy đủ: MPLS labels + GRE VPLS."""
        info('\n*** [StaticMPLS] === Triển khai Static MPLS + GRE VPLS ===\n')
        self._load_mpls_modules()
        self._enable_mpls_interfaces()
        self._setup_mpls_labels()
        self._setup_gre_vpls()
        info('*** [StaticMPLS] Deployment hoàn tất\n')

    # ------------------------------------------------------------------
    # Step 1: Load MPLS kernel modules
    # ------------------------------------------------------------------
    def _load_mpls_modules(self):
        info('  [1/4] Loading MPLS kernel modules...\n')
        loaded = []
        for mod in ['mpls_router', 'mpls_iptunnel', 'mpls_gso']:
            r = subprocess.run(['modprobe', mod], capture_output=True)
            if r.returncode == 0:
                loaded.append(mod)
        if loaded:
            info(f'        Loaded: {", ".join(loaded)}\n')
        else:
            warn('        MPLS modules không load được — labels sẽ không hoạt động\n')

    # ------------------------------------------------------------------
    # Step 2: Enable MPLS input on all interfaces
    # ------------------------------------------------------------------
    def _enable_mpls_interfaces(self):
        info('  [2/4] Bật MPLS trên tất cả backbone interfaces...\n')
        all_routers = ['p01', 'p02', 'p03', 'p04', 'pe01', 'pe02', 'pe03']
        for rname in all_routers:
            node = self.net.get(rname)
            if not node:
                continue
            # Set platform labels
            node.cmd('sysctl -w net.mpls.platform_labels=1048575 2>/dev/null')
            node.cmd('sysctl -w net.mpls.conf.lo.input=1 2>/dev/null')
            # Enable MPLS on all interfaces
            intfs = node.cmd("ip -o link show | awk -F': ' '{print $2}'").strip().split('\n')
            for intf in intfs:
                intf = intf.strip().split('@')[0]  # Remove @ifXX suffix
                if intf and intf != 'lo':
                    node.cmd(f'echo 1 > /proc/sys/net/mpls/conf/{intf}/input 2>/dev/null')
        info('        Done\n')

    # ------------------------------------------------------------------
    # Step 3: Setup static MPLS label entries
    # ------------------------------------------------------------------
    def _setup_mpls_labels(self):
        """
        Cài đặt MPLS label entries tĩnh trên mỗi router.

        3 loại operations (tương đương chức năng LDP):
          PUSH  — PE ingress: đính label vào packet trước khi gửi vào backbone
          SWAP  — P transit: đổi label, forward tiếp
          PHP   — Penultimate Hop Popping: bóc label ở hop áp chót
        """
        info('  [3/4] Cấu hình MPLS Label Table (static)...\n')
        info('        Label Plan: label = 100 + loopback_last_octet\n')

        pe_loopbacks = ['10.0.0.11', '10.0.0.12', '10.0.0.13']
        count = 0

        for rname, paths in MPLS_PATHS.items():
            node = self.net.get(rname)
            if not node:
                continue

            for dest_lo, (next_hop, out_intf, role) in paths.items():
                label = _label_for(dest_lo)

                if role == 'push':
                    # INGRESS PE: push label onto IP packet
                    # ip route replace <dst>/32 encap mpls <label> via <next_hop>
                    node.cmd(
                        f'ip route replace {dest_lo}/32 '
                        f'encap mpls {label} via {next_hop} dev {out_intf} '
                        f'2>/dev/null'
                    )
                    info(f'        [{rname}] PUSH label {label} → {dest_lo} '
                         f'via {next_hop}\n')
                    count += 1

                elif role == 'transit':
                    # TRANSIT P: swap label (same label in this scheme)
                    # ip -M route add <label> as <label> via inet <next_hop>
                    node.cmd(
                        f'ip -M route add {label} as {label} '
                        f'via inet {next_hop} dev {out_intf} '
                        f'2>/dev/null'
                    )
                    info(f'        [{rname}] SWAP label {label} → {label} '
                         f'via {next_hop}\n')
                    count += 1

                elif role == 'php':
                    # PENULTIMATE HOP: pop label, forward as plain IP
                    # ip -M route add <label> via inet <next_hop>
                    node.cmd(
                        f'ip -M route add {label} '
                        f'via inet {next_hop} dev {out_intf} '
                        f'2>/dev/null'
                    )
                    info(f'        [{rname}] PHP  label {label} → pop → '
                         f'{next_hop}\n')
                    count += 1

        info(f'        Tổng: {count} MPLS entries đã cài đặt\n')

    # ------------------------------------------------------------------
    # Step 4: GRE VPLS (pseudowire emulation)
    # ------------------------------------------------------------------
    def _setup_gre_vpls(self):
        """
        Thiết lập VPLS bằng GRE tunnels + Linux bridge.

        Quan trọng: Tạo tunnel 2 CHIỀU cho mỗi cặp PE.
        YAML chỉ define 1 chiều (pe01→pe02), code tự tạo chiều ngược (pe02→pe01).

        Mô hình:
          PE01: bridge vpls-br = [pe01-ce01] + [gre-pe01-pe02] + [gre-pe01-pe03]
          PE02: bridge vpls-br = [pe02-ce02] + [gre-pe02-pe01] + [gre-pe02-pe03]
          PE03: bridge vpls-br = [pe03-ce03] + [gre-pe03-pe01] + [gre-pe03-pe02]
        """
        fallback = self.vpls_config.get('linux_vpls_fallback', {})
        if not fallback.get('enabled', False):
            info('  [4/4] VPLS fallback disabled trong config, bỏ qua\n')
            return

        info('  [4/4] Thiết lập GRE VPLS (pseudowire emulation)...\n')
        bridge_name = fallback.get('bridge_name', 'vpls-br')
        tunnels = fallback.get('tunnels', [])

        # Member map: PE → AC interface
        member_map = {}
        for m in self.vpls_config.get('members', []):
            member_map[m['pe']] = m['ac_interface']

        # Theo dõi tunnel names đã tạo trên mỗi PE
        pe_tunnels = {pe: [] for pe in member_map}  # pe_name -> [tun_name, ...]

        # Tạo GRE tunnels (cả 2 chiều)
        for tcfg in tunnels:
            local_pe = tcfg['local_pe']
            remote_pe = tcfg['remote_pe']
            local_ip = tcfg['local_ip']
            remote_ip = tcfg['remote_ip']
            gre_key = tcfg.get('key', 100)
            tun_name = tcfg['name']

            # Chiều thuận: local_pe → remote_pe
            node = self.net.get(local_pe)
            if node:
                node.cmd(f'ip tunnel add {tun_name} mode gre '
                         f'local {local_ip} remote {remote_ip} '
                         f'key {gre_key} 2>/dev/null || true')
                node.cmd(f'ip link set {tun_name} up')
                pe_tunnels.setdefault(local_pe, []).append(tun_name)
                info(f'        [{local_pe}] GRE: {tun_name} '
                     f'({local_ip} → {remote_ip}, key={gre_key})\n')

            # Chiều ngược: remote_pe → local_pe
            rev_name = f'gre-{remote_pe}-{local_pe}'
            node_rev = self.net.get(remote_pe)
            if node_rev:
                node_rev.cmd(f'ip tunnel add {rev_name} mode gre '
                             f'local {remote_ip} remote {local_ip} '
                             f'key {gre_key} 2>/dev/null || true')
                node_rev.cmd(f'ip link set {rev_name} up')
                pe_tunnels.setdefault(remote_pe, []).append(rev_name)
                info(f'        [{remote_pe}] GRE: {rev_name} '
                     f'({remote_ip} → {local_ip}, key={gre_key})\n')

        # Tạo bridge + add interfaces trên mỗi PE
        for pe_name, ac_intf in member_map.items():
            node = self.net.get(pe_name)
            if not node:
                continue

            # Tạo bridge
            node.cmd(f'ip link add {bridge_name} type bridge '
                     f'2>/dev/null || true')
            node.cmd(f'ip link set {bridge_name} up')

            # Add AC interface
            node.cmd(f'ip link set {ac_intf} master {bridge_name} '
                     f'2>/dev/null || true')

            # Add tất cả GRE tunnels của PE này vào bridge
            tun_list = pe_tunnels.get(pe_name, [])
            for tun in tun_list:
                node.cmd(f'ip link set {tun} master {bridge_name} '
                         f'2>/dev/null || true')

            info(f'        [{pe_name}] Bridge {bridge_name}: '
                 f'AC={ac_intf}, tunnels=[{", ".join(tun_list)}]\n')

        info('        VPLS bridge setup hoàn tất\n')

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------
    def verify_mpls(self):
        """Hiển thị MPLS label table trên P routers và MPLS encap routes trên PE."""
        info('\n*** [StaticMPLS] === MPLS Label Verification ===\n')

        # P routers: hiển thị MPLS label table (swap/php entries)
        for rname in ['p01', 'p02', 'p03', 'p04']:
            node = self.net.get(rname)
            if not node:
                continue
            result = node.cmd('ip -M route 2>/dev/null')
            lines = [l for l in result.strip().split('\n') if l.strip()]
            info(f'  [{rname}] MPLS label table: {len(lines)} entries\n')
            for line in lines:
                info(f'    {line}\n')

        # PE routers: hiển thị MPLS encap routes (push entries)
        for rname in ['pe01', 'pe02', 'pe03']:
            node = self.net.get(rname)
            if not node:
                continue
            result = node.cmd('ip route show 2>/dev/null | grep mpls')
            lines = [l for l in result.strip().split('\n') if l.strip()]
            info(f'  [{rname}] MPLS push routes: {len(lines)} entries\n')
            for line in lines:
                info(f'    {line}\n')

    def verify_vpls(self):
        """Hiển thị VPLS bridge và GRE tunnel status."""
        info('\n*** [StaticMPLS] === VPLS Bridge Verification ===\n')
        for rname in ['pe01', 'pe02', 'pe03']:
            node = self.net.get(rname)
            if not node:
                continue

            # Hiển thị bridge members
            br_output = node.cmd('brctl show vpls-br 2>/dev/null || '
                                 'bridge link show 2>/dev/null')
            info(f'  [{rname}] Bridge vpls-br:\n')
            for line in br_output.strip().split('\n'):
                if line.strip():
                    info(f'    {line}\n')

            # Hiển thị GRE tunnel interfaces
            gre_output = node.cmd('ip tunnel show 2>/dev/null | grep gre')
            if gre_output.strip():
                for line in gre_output.strip().split('\n'):
                    if line.strip():
                        info(f'    [tunnel] {line}\n')
