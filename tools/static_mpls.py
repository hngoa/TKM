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
        """Deploy đầy đủ: MPLS labels + GRETAP VPLS + inter-branch routes."""
        info('\n*** [StaticMPLS] === Triển khai Static MPLS + GRE VPLS ===\n')
        self._load_mpls_modules()
        self._enable_mpls_interfaces()
        self._setup_mpls_labels()
        self._setup_gre_vpls()
        self._setup_inter_branch_routes()
        self._warmup_connectivity()
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
        Thiết lập VPLS bằng GRETAP tunnels + Linux bridge.

        Quan trọng:
          - Tạo tunnel 2 CHIỀU cho mỗi cặp PE
          - KHÔNG add AC interface (pe-ce) vào bridge — giữ L3 IP cho routing
          - Bridge chỉ chứa GRETAP tunnels (L2 pseudowire demonstration)

        Mô hình:
          PE01: bridge vpls-br = [gre-pe01-pe02] + [gre-pe01-pe03]
          PE02: bridge vpls-br = [gre-pe02-pe01] + [gre-pe02-pe03]
          PE03: bridge vpls-br = [gre-pe03-pe01] + [gre-pe03-pe02]

        Lý do không add AC:
          Khi interface được add vào bridge, Linux xóa IP của nó.
          VD: pe01-ce01 (10.100.1.1/30) mất IP → PE01 mất kết nối CE01 →
          tất cả inter-branch routes 'via 10.100.x.2' bị broken.
          Inter-branch connectivity dùng L3 routing với MPLS encap thay vì L2.
        """
        fallback = self.vpls_config.get('linux_vpls_fallback', {})
        if not fallback.get('enabled', False):
            info('  [4/4] VPLS fallback disabled trong config, bỏ qua\n')
            return

        info('  [4/4] Thiết lập GRETAP VPLS (pseudowire emulation)...\n')
        bridge_name = fallback.get('bridge_name', 'vpls-br')
        tunnels = fallback.get('tunnels', [])

        # Member map: PE → AC interface (for reference/logging only)
        member_map = {}
        for m in self.vpls_config.get('members', []):
            member_map[m['pe']] = m['ac_interface']

        # Theo dõi tunnel names đã tạo trên mỗi PE
        pe_tunnels = {pe: [] for pe in member_map}

        # Tạo GRETAP tunnels (cả 2 chiều)
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
                node.cmd(f'ip link add {tun_name} type gretap '
                         f'local {local_ip} remote {remote_ip} '
                         f'key {gre_key} 2>/dev/null || true')
                node.cmd(f'ip link set {tun_name} up')
                pe_tunnels.setdefault(local_pe, []).append(tun_name)
                info(f'        [{local_pe}] GRETAP: {tun_name} '
                     f'({local_ip} → {remote_ip}, key={gre_key})\n')

            # Chiều ngược: remote_pe → local_pe
            rev_name = f'gre-{remote_pe}-{local_pe}'
            node_rev = self.net.get(remote_pe)
            if node_rev:
                node_rev.cmd(f'ip link add {rev_name} type gretap '
                             f'local {remote_ip} remote {local_ip} '
                             f'key {gre_key} 2>/dev/null || true')
                node_rev.cmd(f'ip link set {rev_name} up')
                pe_tunnels.setdefault(remote_pe, []).append(rev_name)
                info(f'        [{remote_pe}] GRETAP: {rev_name} '
                     f'({remote_ip} → {local_ip}, key={gre_key})\n')

        # Tạo bridge + add chỉ GRETAP tunnels (KHÔNG add AC interface)
        for pe_name in member_map:
            node = self.net.get(pe_name)
            if not node:
                continue

            # Tạo bridge
            node.cmd(f'ip link add {bridge_name} type bridge '
                     f'2>/dev/null || true')
            node.cmd(f'ip link set {bridge_name} up')

            # Add GRETAP tunnels vào bridge (KHÔNG add AC!)
            tun_list = pe_tunnels.get(pe_name, [])
            for tun in tun_list:
                node.cmd(f'ip link set {tun} master {bridge_name} '
                         f'2>/dev/null || true')

            ac_intf = member_map.get(pe_name, 'N/A')
            info(f'        [{pe_name}] Bridge {bridge_name}: '
                 f'tunnels=[{", ".join(tun_list)}] '
                 f'(AC={ac_intf} giữ L3 cho routing)\n')

        info('        VPLS bridge setup hoàn tất\n')

    # ------------------------------------------------------------------
    # Step 5: Inter-branch L3 routes
    # ------------------------------------------------------------------
    def _setup_inter_branch_routes(self):
        """
        Cài đặt routes liên chi nhánh qua MPLS backbone.

        Trả lời câu hỏi: pc01 (10.1.0.11) làm sao ping được lab01 (10.2.10.11)?

        Chuỗi routing:
          pc01 → CE01 → PE01 →[MPLS label 112]→ P02 →[PHP]→ PE02 → CE02 → lab01

        Cần 3 loại routes:
          1. PE routes: remote branch subnets → encap mpls → backbone
          2. PE return: local branch subnets → via CE (plain IP)
          3. CE routes: remote branch subnets → via PE
        """
        routing = self.vpls_config.get('inter_branch_routing', {})
        prefixes = routing.get('advertised_prefixes', {})
        if not prefixes:
            info('  [5/5] Không có inter_branch_routing trong config, bỏ qua\n')
            return

        info('  [5/5] Cài đặt inter-branch L3 routes...\n')

        # PE → branch mapping
        pe_branch = {
            'pe01': {'ce': 'ce01', 'ce_ip': '10.100.1.2', 'pe_ip': '10.100.1.1',
                     'branch': 'branch1'},
            'pe02': {'ce': 'ce02', 'ce_ip': '10.100.2.2', 'pe_ip': '10.100.2.1',
                     'branch': 'branch2'},
            'pe03': {'ce': 'ce03', 'ce_ip': '10.100.3.2', 'pe_ip': '10.100.3.1',
                     'branch': 'branch3'},
        }

        count = 0
        for pe_name, pe_info in pe_branch.items():
            pe_node = self.net.get(pe_name)
            if not pe_node:
                continue
            # CE node chỉ tồn tại trong full topology, không có trong backbone-only
            try:
                ce_node = self.net.get(pe_info['ce'])
            except KeyError:
                ce_node = None
            local_branch = pe_info['branch']

            # Tìm các remote branches và subnets của chúng
            for branch_id, subnets in prefixes.items():
                if branch_id == local_branch:
                    # Local branch: PE → CE (return path, plain IP)
                    if pe_node:
                        for subnet in subnets:
                            pe_node.cmd(
                                f'ip route replace {subnet} '
                                f'via {pe_info["ce_ip"]} 2>/dev/null')
                            count += 1
                    continue

                # Remote branch: tìm PE đích
                remote_pe = None
                for rpe, rinfo in pe_branch.items():
                    if rinfo['branch'] == branch_id:
                        remote_pe = rpe
                        break
                if not remote_pe:
                    continue

                remote_lo = LOOPBACKS.get(remote_pe)
                if not remote_lo:
                    continue
                label = _label_for(remote_lo)

                # Lấy next-hop từ MPLS_PATHS
                path_info = MPLS_PATHS.get(pe_name, {}).get(remote_lo)
                if not path_info:
                    continue
                next_hop, out_intf, _ = path_info

                # 1) PE: route remote subnet → encap mpls → backbone
                if pe_node:
                    for subnet in subnets:
                        pe_node.cmd(
                            f'ip route replace {subnet} '
                            f'encap mpls {label} '
                            f'via {next_hop} dev {out_intf} 2>/dev/null')
                        info(f'        [{pe_name}] {subnet} → mpls {label} '
                             f'via {next_hop}\n')
                        count += 1

                # 2) CE: route remote subnet → via local PE
                if ce_node:
                    for subnet in subnets:
                        ce_node.cmd(
                            f'ip route replace {subnet} '
                            f'via {pe_info["pe_ip"]} 2>/dev/null')
                        count += 1

        info(f'        Tổng: {count} inter-branch routes đã cài đặt\n')

    # ------------------------------------------------------------------
    # Step 6: ARP warmup
    # ------------------------------------------------------------------
    def _warmup_connectivity(self):
        """
        Gửi 1 ping đến các neighbor trực tiếp để populate ARP table.

        Trong full topology với 40+ interfaces, ARP cache trống gây ra
        packet loss 80-100% ở các ping test đầu tiên. Warmup giải quyết
        bằng cách trigger ARP resolution trước khi chạy test.
        """
        import time
        info('  [6/6] Warmup ARP caches...\n')

        # P-P direct links warmup
        warmup_pairs = [
            ('p01', '10.0.10.2'),  ('p02', '10.0.10.1'),
            ('p02', '10.0.11.2'),  ('p03', '10.0.11.1'),
            ('p03', '10.0.12.2'),  ('p04', '10.0.12.1'),
            ('p01', '10.0.13.2'),  ('p03', '10.0.13.1'),
            ('p02', '10.0.14.2'),  ('p04', '10.0.14.1'),
            # PE-P links
            ('pe01', '10.0.20.2'), ('p01', '10.0.20.1'),
            ('pe01', '10.0.21.2'), ('p02', '10.0.21.1'),
            ('pe02', '10.0.22.2'), ('p02', '10.0.22.1'),
            ('pe02', '10.0.23.2'), ('p03', '10.0.23.1'),
            ('pe03', '10.0.24.2'), ('p03', '10.0.24.1'),
            ('pe03', '10.0.25.2'), ('p04', '10.0.25.1'),
            # PE-CE WAN links
            ('pe01', '10.100.1.2'), ('pe02', '10.100.2.2'),
            ('pe03', '10.100.3.2'),
        ]

        for node_name, target_ip in warmup_pairs:
            node = self.net.get(node_name)
            if node:
                node.cmd(f'ping -c 1 -W 1 {target_ip} > /dev/null 2>&1 &')

        # Đợi ARP resolution hoàn thành
        time.sleep(3)
        info('        ARP warmup hoàn tất\n')

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
        """Hiển thị VPLS bridge và GRETAP tunnel status."""
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

            # Hiển thị GRETAP tunnel interfaces
            gre_output = node.cmd('ip -d link show type gretap 2>/dev/null')
            if gre_output.strip():
                for line in gre_output.strip().split('\n'):
                    if 'gretap' in line or 'gre-' in line:
                        info(f'    [gretap] {line.strip()}\n')
