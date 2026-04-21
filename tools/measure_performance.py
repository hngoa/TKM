#!/usr/bin/env python3
"""
measure_performance.py - Công cụ đo lường hiệu năng mạng
======================================================
Đo các chỉ số: Throughput, Delay (RTT), Packet Loss, Jitter
Giữa tất cả cặp chi nhánh và trong nội bộ từng chi nhánh.

Sử dụng:
  sudo python3 tools/measure_performance.py
  sudo python3 tools/measure_performance.py --mode all
  sudo python3 tools/measure_performance.py --mode inter --duration 30
"""

import argparse
import json
import os
import sys
import time
import datetime
import subprocess
import re
import threading
from collections import defaultdict

# Thêm thư mục cha vào path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

RESULTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)

# ============================================================
# Định nghĩa Test Cases
# ============================================================

# Host đại diện cho mỗi chi nhánh (dùng cho inter-branch tests)
BRANCH_REPS = {
    'branch1_flat':       'pc01',
    'branch2_3tier_lab':  'lab01',
    'branch2_3tier_admin':'admin01',
    'branch2_3tier_guest':'guest01',
    'branch3_web':        'web01',
    'branch3_dns':        'dns01',
    'branch3_db':         'db01',
}

# Tất cả hosts trong hệ thống
ALL_HOSTS = {
    # Branch 1
    'pc01':    '10.1.0.11',
    'pc02':    '10.1.0.12',
    'pc03':    '10.1.0.13',
    'pc04':    '10.1.0.14',
    # Branch 2 - LAB
    'lab01':   '10.2.10.11',
    'lab02':   '10.2.10.12',
    # Branch 2 - ADMIN
    'admin01': '10.2.20.11',
    'admin02': '10.2.20.12',
    # Branch 2 - GUEST
    'guest01': '10.2.30.11',
    'guest02': '10.2.30.12',
    # Branch 3 - WEB
    'web01':   '10.3.10.11',
    'web02':   '10.3.10.12',
    # Branch 3 - DNS
    'dns01':   '10.3.20.11',
    'dns02':   '10.3.20.12',
    # Branch 3 - DB
    'db01':    '10.3.30.11',
    'db02':    '10.3.30.12',
}

# Nhóm test: inter-branch pairs
INTER_BRANCH_TESTS = [
    # (src_host, dst_host, label)
    ('pc01',    'lab01',   'Branch1 -> Branch2 (LAB)'),
    ('pc01',    'admin01', 'Branch1 -> Branch2 (ADMIN)'),
    ('pc01',    'web01',   'Branch1 -> Branch3 (WEB)'),
    ('pc01',    'db01',    'Branch1 -> Branch3 (DB)'),
    ('lab01',   'web01',   'Branch2 -> Branch3 (WEB)'),
    ('lab01',   'db01',    'Branch2 -> Branch3 (DB)'),
    ('admin01', 'dns01',   'Branch2 -> Branch3 (DNS)'),
    ('web01',   'pc01',    'Branch3 -> Branch1'),
    ('db01',    'lab01',   'Branch3 -> Branch2 (LAB)'),
]

# Nhóm test: intra-branch (nội bộ từng chi nhánh)
INTRA_BRANCH_TESTS = [
    # Branch 1
    ('pc01', 'pc02', 'B1: pc01->pc02 (same switch)'),
    ('pc01', 'pc03', 'B1: pc01->pc03 (daisy-chain)'),
    ('pc01', 'pc04', 'B1: pc01->pc04 (daisy-chain)'),
    # Branch 2
    ('lab01',   'lab02',   'B2: lab01->lab02 (same VLAN)'),
    ('lab01',   'admin01', 'B2: LAB->ADMIN (inter-VLAN)'),
    ('admin01', 'guest01', 'B2: ADMIN->GUEST (inter-VLAN)'),
    # Branch 3
    ('web01', 'web02',  'B3: web01->web02 (same leaf)'),
    ('web01', 'dns01',  'B3: WEB->DNS (cross leaf 2 hops)'),
    ('web01', 'db01',   'B3: WEB->DB (cross leaf 2 hops)'),
    ('dns01', 'db01',   'B3: DNS->DB (cross leaf 2 hops)'),
]


# ============================================================
# Measurement Functions
# ============================================================

class NetworkMeasurer:
    """Lớp thực hiện đo lường hiệu năng mạng trong Mininet."""

    def __init__(self, net, duration=10, iperf_port=5201):
        self.net = net
        self.duration = duration
        self.iperf_port = iperf_port
        self.results = defaultdict(dict)

    # ---- PING (Delay + Packet Loss + Jitter) ----
    def measure_ping(self, src_name, dst_ip, count=20, interval=0.5):
        """
        Đo RTT, packet loss, và jitter bằng ping.
        Returns: dict với min/avg/max/mdev latency và packet loss (%)
        """
        src = self.net.get(src_name)
        if src is None:
            return {'error': f'Host {src_name} không tìm thấy'}

        cmd = f'ping -c {count} -i {interval} -q {dst_ip}'
        output = src.cmd(cmd)
        return self._parse_ping(output, src_name, dst_ip)

    def _parse_ping(self, output, src, dst):
        result = {
            'src': src, 'dst': dst,
            'min_ms': None, 'avg_ms': None,
            'max_ms': None, 'jitter_ms': None,
            'packet_loss_pct': None, 'reachable': False
        }

        # Parse packet loss
        loss_match = re.search(r'(\d+)% packet loss', output)
        if loss_match:
            result['packet_loss_pct'] = float(loss_match.group(1))

        # Parse RTT statistics
        rtt_match = re.search(
            r'rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)', output
        )
        if rtt_match:
            result['min_ms']     = float(rtt_match.group(1))
            result['avg_ms']     = float(rtt_match.group(2))
            result['max_ms']     = float(rtt_match.group(3))
            result['jitter_ms']  = float(rtt_match.group(4))  # mdev ≈ jitter
            result['reachable']  = True

        if result['packet_loss_pct'] == 100:
            result['reachable'] = False

        return result

    # ---- IPERF3 (Throughput) ----
    def measure_throughput(self, src_name, dst_name, dst_ip, protocol='tcp'):
        """
        Đo throughput bằng iperf3.
        Returns: dict với throughput (Mbps) và retransmits (TCP)
        """
        dst = self.net.get(dst_name)
        src = self.net.get(src_name)
        if dst is None or src is None:
            return {'error': 'Host không tìm thấy'}

        # Khởi động iperf3 server
        dst.cmd(f'iperf3 -s -p {self.iperf_port} -D --logfile /tmp/iperf3_server.log')
        time.sleep(0.5)

        # Chạy iperf3 client
        flags = '-J'  # JSON output
        if protocol == 'udp':
            flags += ' -u -b 100M'
        client_cmd = f'iperf3 -c {dst_ip} -p {self.iperf_port} -t {self.duration} {flags}'
        output = src.cmd(client_cmd)

        # Dừng server
        dst.cmd(f'pkill -f "iperf3 -s"')

        return self._parse_iperf3(output, src_name, dst_name, protocol)

    def _parse_iperf3(self, output, src, dst, protocol):
        result = {
            'src': src, 'dst': dst, 'protocol': protocol,
            'throughput_mbps': None, 'retransmits': None,
            'jitter_ms': None, 'packet_loss_pct': None
        }
        try:
            data = json.loads(output)
            if protocol == 'tcp':
                end = data.get('end', {})
                streams = end.get('sum_sent', {})
                result['throughput_mbps'] = round(
                    streams.get('bits_per_second', 0) / 1e6, 3)
                result['retransmits'] = streams.get('retransmits', 0)
            else:  # UDP
                end  = data.get('end', {})
                recv = end.get('sum', {})
                result['throughput_mbps'] = round(
                    recv.get('bits_per_second', 0) / 1e6, 3)
                result['jitter_ms']       = recv.get('jitter_ms', None)
                result['packet_loss_pct'] = round(
                    recv.get('lost_percent', 0), 2)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            result['error'] = f'Parse error: {e}\nOutput: {output[:300]}'
        return result

    # ---- TRACEROUTE (Hop Count + Path) ----
    def measure_traceroute(self, src_name, dst_ip):
        """
        Đo hop count và đường đi của gói tin.
        Returns: dict với hop count và danh sách hops
        """
        src = self.net.get(src_name)
        if src is None:
            return {'error': f'Host {src_name} không tìm thấy'}

        output = src.cmd(f'traceroute -n -w 2 -q 1 -m 20 {dst_ip}')
        return self._parse_traceroute(output, src_name, dst_ip)

    def _parse_traceroute(self, output, src, dst):
        hops = []
        for line in output.strip().split('\n')[1:]:
            match = re.match(r'\s*(\d+)\s+([\d.]+|\*)', line)
            if match:
                hop_num = int(match.group(1))
                hop_ip  = match.group(2)
                # Extract latency
                lat_match = re.search(r'([\d.]+)\s+ms', line)
                lat = float(lat_match.group(1)) if lat_match else None
                hops.append({'hop': hop_num, 'ip': hop_ip, 'latency_ms': lat})
        return {
            'src': src, 'dst': dst,
            'hop_count': len(hops),
            'hops': hops
        }

    # ---- STRESS TEST (High Load) ----
    def stress_test(self, src_name, dst_name, dst_ip, parallel=4, duration=15):
        """
        Chạy nhiều luồng iperf song song để kiểm tra packet loss dưới tải cao.
        """
        dst = self.net.get(dst_name)
        src = self.net.get(src_name)
        if dst is None or src is None:
            return {'error': 'Host không tìm thấy'}

        # Server
        dst.cmd(f'iperf3 -s -p {self.iperf_port} -D --logfile /tmp/iperf3_stress.log')
        time.sleep(0.5)

        # Client với parallel streams
        cmd = (f'iperf3 -c {dst_ip} -p {self.iperf_port} '
               f'-t {duration} -P {parallel} -J -u -b 50M')
        output = src.cmd(cmd)
        dst.cmd('pkill -f "iperf3 -s"')

        result = self._parse_iperf3(output, src_name, dst_name, 'udp')
        result['parallel_streams'] = parallel
        result['test_type'] = 'stress'
        return result


# ============================================================
# Test Runner
# ============================================================

class TestRunner:
    """Orchestrates all measurement tests và tạo báo cáo."""

    def __init__(self, net, args):
        self.net = net
        self.args = args
        self.measurer = NetworkMeasurer(net, duration=args.duration)
        self.all_results = {
            'metadata': {
                'timestamp': datetime.datetime.now().isoformat(),
                'duration_per_test': args.duration,
                'mode': args.mode,
            },
            'ping': [],
            'throughput_tcp': [],
            'throughput_udp': [],
            'traceroute': [],
            'stress': [],
        }

    def run_all(self):
        """Chạy toàn bộ test suite."""
        mode = self.args.mode

        print("\n" + "="*60)
        print("  METRO ETHERNET MPLS - NETWORK PERFORMANCE MEASUREMENT")
        print("="*60)

        if mode in ('all', 'intra'):
            self._run_test_set('INTRA-BRANCH', INTRA_BRANCH_TESTS)

        if mode in ('all', 'inter'):
            self._run_test_set('INTER-BRANCH (qua MPLS Backbone)', INTER_BRANCH_TESTS)

        if mode in ('all', 'stress'):
            self._run_stress_tests()

        self._save_results()
        self._print_summary()

    def _run_test_set(self, label, test_list):
        print(f"\n{'─'*60}")
        print(f"  {label} TESTS")
        print(f"{'─'*60}")

        for src_name, dst_name, description in test_list:
            dst_ip = ALL_HOSTS.get(dst_name)
            if dst_ip is None:
                print(f"  [SKIP] {description}: IP không xác định")
                continue

            print(f"\n  [{description}]")

            # 1. PING
            print(f"    > Ping {src_name} -> {dst_ip} ...", end='', flush=True)
            ping_r = self.measurer.measure_ping(src_name, dst_ip)
            self.all_results['ping'].append({**ping_r, 'label': description})
            if ping_r.get('reachable'):
                print(f" RTT={ping_r['avg_ms']:.2f}ms  Loss={ping_r['packet_loss_pct']}%"
                      f"  Jitter={ping_r['jitter_ms']:.2f}ms")
            else:
                print(f" UNREACHABLE (loss={ping_r.get('packet_loss_pct')}%)")

            # 2. Throughput TCP
            print(f"    > iperf3 TCP {src_name} -> {dst_name} ...", end='', flush=True)
            tcp_r = self.measurer.measure_throughput(src_name, dst_name, dst_ip, 'tcp')
            self.all_results['throughput_tcp'].append({**tcp_r, 'label': description})
            if tcp_r.get('throughput_mbps') is not None:
                print(f" {tcp_r['throughput_mbps']:.2f} Mbps  Retransmits={tcp_r['retransmits']}")
            else:
                print(f" ERROR: {tcp_r.get('error','')[:80]}")

            # 3. Throughput UDP
            print(f"    > iperf3 UDP {src_name} -> {dst_name} ...", end='', flush=True)
            udp_r = self.measurer.measure_throughput(src_name, dst_name, dst_ip, 'udp')
            self.all_results['throughput_udp'].append({**udp_r, 'label': description})
            if udp_r.get('throughput_mbps') is not None:
                print(f" {udp_r['throughput_mbps']:.2f} Mbps  "
                      f"Loss={udp_r.get('packet_loss_pct')}%  "
                      f"Jitter={udp_r.get('jitter_ms')}ms")
            else:
                print(f" ERROR: {udp_r.get('error','')[:80]}")

            # 4. Traceroute (chỉ inter-branch)
            if 'INTER' in label or 'Branch' in description and '->' in description:
                tr_r = self.measurer.measure_traceroute(src_name, dst_ip)
                self.all_results['traceroute'].append({**tr_r, 'label': description})
                print(f"    > Traceroute: {tr_r.get('hop_count', '?')} hops")

    def _run_stress_tests(self):
        print(f"\n{'─'*60}")
        print("  STRESS TESTS (High Load - 4 parallel streams)")
        print(f"{'─'*60}")

        stress_pairs = [
            ('pc01',  'web01', '10.3.10.11', 'B1->B3 Stress'),
            ('lab01', 'db01',  '10.3.30.11', 'B2->B3 Stress'),
            ('web01', 'pc01',  '10.1.0.11',  'B3->B1 Stress'),
        ]
        for src, dst, ip, label in stress_pairs:
            print(f"\n  [{label}]")
            print(f"    > Stress test {src} -> {dst} (4 streams x 15s)...", end='', flush=True)
            r = self.measurer.stress_test(src, dst, ip, parallel=4, duration=15)
            self.all_results['stress'].append({**r, 'label': label})
            if r.get('throughput_mbps') is not None:
                print(f" {r['throughput_mbps']:.2f} Mbps  Loss={r.get('packet_loss_pct')}%")
            else:
                print(f" ERROR")

    def _save_results(self):
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        json_path = os.path.join(RESULTS_DIR, f'results_{ts}.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(self.all_results, f, indent=2, ensure_ascii=False)
        print(f"\n\n  [✓] Raw results saved: {json_path}")
        self._save_csv(ts)

    def _save_csv(self, ts):
        import csv
        csv_path = os.path.join(RESULTS_DIR, f'summary_{ts}.csv')
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Label', 'Src', 'Dst',
                'Ping_Avg_ms', 'Ping_Min_ms', 'Ping_Max_ms',
                'Jitter_ms', 'Packet_Loss_pct',
                'TCP_Throughput_Mbps', 'TCP_Retransmits',
                'UDP_Throughput_Mbps', 'UDP_Loss_pct', 'UDP_Jitter_ms',
                'Hop_Count'
            ])

            # Merge results by label
            ping_map = {r['label']: r for r in self.all_results['ping']}
            tcp_map  = {r['label']: r for r in self.all_results['throughput_tcp']}
            udp_map  = {r['label']: r for r in self.all_results['throughput_udp']}
            tr_map   = {r['label']: r for r in self.all_results['traceroute']}

            all_labels = set(ping_map.keys()) | set(tcp_map.keys())
            for label in sorted(all_labels):
                p = ping_map.get(label, {})
                t = tcp_map.get(label,  {})
                u = udp_map.get(label,  {})
                tr= tr_map.get(label,   {})
                writer.writerow([
                    label,
                    p.get('src', ''), p.get('dst', ''),
                    p.get('avg_ms', ''), p.get('min_ms', ''), p.get('max_ms', ''),
                    p.get('jitter_ms', ''), p.get('packet_loss_pct', ''),
                    t.get('throughput_mbps', ''), t.get('retransmits', ''),
                    u.get('throughput_mbps', ''), u.get('packet_loss_pct', ''),
                    u.get('jitter_ms', ''),
                    tr.get('hop_count', ''),
                ])

        print(f"  [✓] CSV summary saved: {csv_path}")

    def _print_summary(self):
        print("\n" + "="*60)
        print("  KẾT QUẢ TỔNG HỢP")
        print("="*60)

        # Inter-branch summary table
        inter = [r for r in self.all_results['ping']
                 if any(r.get('label','').startswith(f'Branch{i}')
                        for i in [1,2,3]) and '->' in r.get('label','')]
        if inter:
            print("\n  Inter-Branch Ping Summary:")
            print(f"  {'Label':<35} {'RTT(ms)':>8} {'Loss%':>7} {'Jitter(ms)':>10}")
            print(f"  {'-'*35} {'-'*8} {'-'*7} {'-'*10}")
            for r in inter:
                rtt   = f"{r['avg_ms']:.1f}" if r.get('avg_ms') else 'N/A'
                loss  = f"{r['packet_loss_pct']:.0f}%" if r.get('packet_loss_pct') is not None else 'N/A'
                jit   = f"{r['jitter_ms']:.2f}" if r.get('jitter_ms') else 'N/A'
                label = r.get('label','')[:34]
                print(f"  {label:<35} {rtt:>8} {loss:>7} {jit:>10}")

        # TCP Throughput summary
        tcp = self.all_results['throughput_tcp']
        if tcp:
            valid = [r for r in tcp if r.get('throughput_mbps') is not None]
            if valid:
                avg_tp = sum(r['throughput_mbps'] for r in valid) / len(valid)
                max_tp = max(r['throughput_mbps'] for r in valid)
                min_tp = min(r['throughput_mbps'] for r in valid)
                print(f"\n  TCP Throughput: avg={avg_tp:.2f} Mbps  "
                      f"max={max_tp:.2f} Mbps  min={min_tp:.2f} Mbps")

        print("\n  [Done] Kiểm tra thư mục 'results/' để xem báo cáo chi tiết.")
        print("  [Tip] Chạy: python3 tools/generate_report.py để tạo biểu đồ\n")


# ============================================================
# Entry Point
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Đo lường hiệu năng Metro Ethernet MPLS')
    parser.add_argument('--mode', choices=['all', 'inter', 'intra', 'stress'],
                        default='all', help='Chế độ đo (default: all)')
    parser.add_argument('--duration', type=int, default=10,
                        help='Thời gian mỗi iperf3 test (giây, default: 10)')
    args = parser.parse_args()

    # Import topology và khởi động
    from topologies.full_topology import build_full_topology, configure_ip_addresses, configure_routing
    from mininet.log import setLogLevel
    setLogLevel('warning')

    print("[*] Khởi động Mininet topology...")
    net = build_full_topology()
    net.start()
    configure_ip_addresses(net)
    configure_routing(net)
    print("[*] Topology sẵn sàng. Chờ 3 giây...\n")
    time.sleep(3)

    try:
        runner = TestRunner(net, args)
        runner.run_all()
    finally:
        print("\n[*] Dừng Mininet...")
        net.stop()


if __name__ == '__main__':
    if os.geteuid() != 0:
        print("[ERROR] Cần chạy với quyền root: sudo python3 tools/measure_performance.py")
        sys.exit(1)
    main()
