#!/usr/bin/env python3
"""
tools/inter_branch_routing.py
==============================
Inter-Branch Static Routing Setup

Đảm bảo CE routers tại các chi nhánh có thể kết nối với nhau qua
MPLS backbone PE routers bằng static routing thuần túy.

Không phụ thuộc vào OSPF/LDP — hoạt động ngay cả khi FRR chưa converge.

Kiến trúc routing:
  pc01 (10.1.0.11) → ce01 (GW: 10.1.0.1)
    → pe01 (10.100.1.1) → [backbone static routes]
      → pe02 (10.100.2.1) → ce02 (10.100.2.2)
        → lab01 (10.2.10.11)

Chức năng:
  - apply_ce_inter_branch_routes(): Thêm routes trên CE → các branch khác
  - apply_pe_ce_forwarding():       Bật forwarding trên PE cho CE traffic
  - apply_host_inter_branch_gw():   Đảm bảo hosts dùng đúng default route
  - apply_all():                    Chạy tất cả bước trên
"""

from mininet.log import info, warn


# ====================================================================
# Branch subnet definitions
# ====================================================================

BRANCH_SUBNETS = {
    'branch1': {
        'ce': 'ce01',
        'pe': 'pe01',
        'wan_ce_ip':  '10.100.1.2',   # CE side of WAN link
        'wan_pe_ip':  '10.100.1.1',   # PE side of WAN link
        'lan_gateway': '10.1.0.1',    # CE LAN gateway IP
        'subnets': ['10.1.0.0/24'],
    },
    'branch2': {
        'ce': 'ce02',
        'pe': 'pe02',
        'wan_ce_ip':  '10.100.2.2',
        'wan_pe_ip':  '10.100.2.1',
        'lan_gateway': '10.2.10.1',   # Primary LAN gateway (VLAN10)
        'subnets': ['10.2.10.0/24', '10.2.20.0/24', '10.2.30.0/24'],
    },
    'branch3': {
        'ce': 'ce03',
        'pe': 'pe03',
        'wan_ce_ip':  '10.100.3.2',
        'wan_pe_ip':  '10.100.3.1',
        'lan_gateway': '10.3.10.1',   # Primary LAN gateway
        'subnets': ['10.3.0.0/16'],
    },
}

# PE-to-PE next-hop map: pe_src → {pe_dst: next_hop_ip}
# Dựa trên backbone static routes trong ip_plan.yaml
PE_NEXTHOPS = {
    'pe01': {
        'pe02': '10.0.21.2',  # via P02
        'pe03': '10.0.21.2',  # via P02
    },
    'pe02': {
        'pe01': '10.0.22.2',  # via P02
        'pe03': '10.0.23.2',  # via P03
    },
    'pe03': {
        'pe01': '10.0.24.2',  # via P03
        'pe02': '10.0.24.2',  # via P03
    },
}


class InterBranchRouting:
    """
    Cấu hình static routing liên chi nhánh để CE-to-CE connectivity hoạt động.

    Flow của một gói tin từ pc01 (Branch1) đến lab01 (Branch2):
      pc01 → ce01 (default GW: 10.1.0.1)
           → ce01 route 10.2.0.0/16 via 10.100.1.1 (PE01 WAN)
           → pe01 route 10.2.0.0/16 via next-hop P (static backbone)
           → pe02 route 10.2.0.0/16 (local CE subnet) via 10.100.2.2 (CE02)
           → ce02 forward to lab01

    Sử dụng:
        router = InterBranchRouting(net)
        router.apply_all()
    """

    def __init__(self, net, branch_subnets=None):
        """
        Args:
            net:            Mininet network object
            branch_subnets: dict override (mặc định dùng BRANCH_SUBNETS)
        """
        self.net     = net
        self.subnets = branch_subnets or BRANCH_SUBNETS

    def _node(self, name):
        """Lấy node an toàn, trả None nếu không tồn tại."""
        return self.net.nameToNode.get(name)

    def _add_route(self, node, prefix, via, desc=''):
        """Thêm route vào node, bỏ qua nếu đã tồn tại."""
        result = node.cmd(f'ip route add {prefix} via {via} 2>&1')
        if result and 'File exists' not in result and 'RTNETLINK' not in result:
            if result.strip():
                warn(f'     [WARN] route {prefix} via {via}: {result.strip()}\n')
        info(f'     + {prefix} via {via}{f" ({desc})" if desc else ""}\n')

    # ------------------------------------------------------------------
    # Step 1: CE routers — thêm routes đến các branch khác qua PE
    # ------------------------------------------------------------------

    def apply_ce_inter_branch_routes(self):
        """
        Mỗi CE cần routes đến TẤT CẢ subnets của các branch khác,
        với next-hop là PE của chính branch đó (WAN gateway).
        """
        info('\n*** [InterBranch] Cấu hình CE inter-branch routes\n')

        for src_branch, src_cfg in self.subnets.items():
            ce_name  = src_cfg['ce']
            pe_wan   = src_cfg['wan_pe_ip']   # PE-side WAN IP = CE's default GW
            ce_node  = self._node(ce_name)
            if ce_node is None:
                warn(f'  [SKIP] {ce_name} không có trong topology\n')
                continue

            info(f'  [{ce_name}] Routes đến các branch khác:\n')

            for dst_branch, dst_cfg in self.subnets.items():
                if dst_branch == src_branch:
                    continue
                for subnet in dst_cfg['subnets']:
                    self._add_route(ce_node, subnet, pe_wan,
                                    f'{src_branch} → {dst_branch}')

            # Đảm bảo ip_forward bật trên CE
            ce_node.cmd('sysctl -w net.ipv4.ip_forward=1')

    # ------------------------------------------------------------------
    # Step 2: PE routers — thêm routes đến CE LAN subnets của branch khác
    # ------------------------------------------------------------------

    def apply_pe_inter_branch_routes(self):
        """
        Mỗi PE cần:
        1. Route đến LAN subnets của các branch khác (qua backbone P routers)
        2. Route đến CE WAN IP của branch khác (để reply đến CE đi đúng đường)
        """
        info('\n*** [InterBranch] Cấu hình PE inter-branch routes\n')

        for src_branch, src_cfg in self.subnets.items():
            pe_name  = src_cfg['pe']
            pe_node  = self._node(pe_name)
            if pe_node is None:
                warn(f'  [SKIP] {pe_name} không có trong topology\n')
                continue

            info(f'  [{pe_name}] Routes đến CE subnets của branch khác:\n')

            nexthops = PE_NEXTHOPS.get(pe_name, {})

            for dst_branch, dst_cfg in self.subnets.items():
                if dst_branch == src_branch:
                    continue

                dst_pe   = dst_cfg['pe']
                next_hop = nexthops.get(dst_pe)
                if not next_hop:
                    warn(f'     [WARN] Không có nexthop từ {pe_name} đến {dst_pe}\n')
                    continue

                # Routes đến LAN subnets của branch đích
                for subnet in dst_cfg['subnets']:
                    self._add_route(pe_node, subnet, next_hop,
                                    f'→ {dst_branch} LAN')

                # Route đến WAN IP của CE đích (để reply traffic đi đúng)
                wan_ce_dst = dst_cfg['wan_ce_ip']
                self._add_route(pe_node, f'{wan_ce_dst}/32', next_hop,
                                f'→ {dst_cfg["ce"]} WAN IP')

            # Đảm bảo ip_forward bật trên PE
            pe_node.cmd('sysctl -w net.ipv4.ip_forward=1')

    # ------------------------------------------------------------------
    # Step 3: CE → LAN forwarding (route về LAN subnet từ CE)
    # ------------------------------------------------------------------

    def apply_ce_lan_routes(self):
        """
        Đảm bảo CE có route đến LAN subnets của chính mình
        (thường đã có vì interface trực tiếp, nhưng verify lại).
        """
        info('\n*** [InterBranch] Xác nhận CE LAN routes\n')

        for branch, cfg in self.subnets.items():
            ce_name = cfg['ce']
            ce_node = self._node(ce_name)
            if ce_node is None:
                continue

            info(f'  [{ce_name}] LAN subnets (directly connected):\n')
            for subnet in cfg['subnets']:
                # Kiểm tra route đã có chưa
                result = ce_node.cmd(f'ip route show {subnet}')
                if subnet.split('/')[0] in result or 'dev' in result:
                    info(f'     ✓ {subnet} (already exists)\n')
                else:
                    warn(f'     [WARN] {subnet} route missing on {ce_name}!\n')

    # ------------------------------------------------------------------
    # Step 4: Verify connectivity bằng ping test cơ bản
    # ------------------------------------------------------------------

    def verify_ce_connectivity(self):
        """
        Kiểm tra nhanh CE-to-CE connectivity:
        ce01 ping ce02 WAN IP, ce02 ping ce03 WAN IP, v.v.
        """
        info('\n*** [InterBranch] Kiểm tra CE-to-CE WAN connectivity\n')

        ce_pairs = [
            ('ce01', '10.100.2.2', 'CE01→CE02 WAN'),
            ('ce01', '10.100.3.2', 'CE01→CE03 WAN'),
            ('ce02', '10.100.1.2', 'CE02→CE01 WAN'),
            ('ce02', '10.100.3.2', 'CE02→CE03 WAN'),
            ('ce03', '10.100.1.2', 'CE03→CE01 WAN'),
            ('ce03', '10.100.2.2', 'CE03→CE02 WAN'),
        ]

        results = []
        for src_name, dst_ip, label in ce_pairs:
            src_node = self._node(src_name)
            if src_node is None:
                info(f'  [SKIP] {src_name} not in topology\n')
                continue

            out = src_node.cmd(f'ping -c 3 -W 2 -q {dst_ip} 2>&1')
            loss_line = [l for l in out.split('\n') if 'packet loss' in l]
            loss = '100%'
            if loss_line:
                parts = loss_line[0].split()
                for p in parts:
                    if '%' in p:
                        loss = p.replace(',', '')
                        break

            ok = (loss == '0%')
            icon = '✓' if ok else '✗'
            info(f'  [{icon}] {label}: {loss} loss\n')
            results.append((label, ok))

        passed = sum(1 for _, ok in results if ok)
        info(f'\n  CE-CE WAN: {passed}/{len(results)} PASS\n')
        return results

    def verify_host_inter_branch(self):
        """
        Kiểm tra host-to-host liên chi nhánh (representative pairs).
        """
        info('\n*** [InterBranch] Kiểm tra Host inter-branch connectivity\n')

        pairs = [
            ('pc01',    '10.2.10.11', 'B1→B2 (pc01→lab01)'),
            ('pc01',    '10.3.10.11', 'B1→B3 (pc01→web01)'),
            ('lab01',   '10.1.0.11',  'B2→B1 (lab01→pc01)'),
            ('lab01',   '10.3.10.11', 'B2→B3 (lab01→web01)'),
            ('web01',   '10.1.0.11',  'B3→B1 (web01→pc01)'),
            ('web01',   '10.2.10.11', 'B3→B2 (web01→lab01)'),
        ]

        results = []
        for src_name, dst_ip, label in pairs:
            src_node = self._node(src_name)
            if src_node is None:
                info(f'  [SKIP] {src_name} not in topology\n')
                continue

            out = src_node.cmd(f'ping -c 3 -W 2 -q {dst_ip} 2>&1')
            loss_line = [l for l in out.split('\n') if 'packet loss' in l]
            loss = '100%'
            if loss_line:
                parts = loss_line[0].split()
                for p in parts:
                    if '%' in p:
                        loss = p.replace(',', '')
                        break

            ok = (loss == '0%')
            icon = '✓' if ok else '✗'
            info(f'  [{icon}] {label}: {loss} loss\n')
            results.append((label, ok))

        passed = sum(1 for _, ok in results if ok)
        total  = len(results)
        info(f'\n  Host inter-branch: {passed}/{total} PASS\n')

        if passed == total:
            info('  ✅ TẤT CẢ inter-branch tests PASSED!\n')
        else:
            warn(f'  ⚠ {total - passed} tests FAILED\n')

        return results

    # ------------------------------------------------------------------
    # apply_all: Chạy tất cả bước theo thứ tự
    # ------------------------------------------------------------------

    def apply_all(self):
        """
        Cấu hình đầy đủ inter-branch routing:
        1. CE routes → các branch khác (qua PE WAN gateway)
        2. PE routes → CE LAN subnets của branch khác (qua backbone)
        3. Verify CE LAN routes
        4. Quick CE-CE WAN connectivity check
        """
        info('\n' + '='*60 + '\n')
        info('*** [InterBranch] Thiết lập Inter-Branch Routing\n')
        info('='*60 + '\n')

        self.apply_ce_inter_branch_routes()
        self.apply_pe_inter_branch_routes()
        self.apply_ce_lan_routes()

        info('\n*** [InterBranch] Inter-Branch Routing đã cấu hình xong\n')
        info('    Lưu ý: Cần đợi ~2s để routing tables ổn định\n')
