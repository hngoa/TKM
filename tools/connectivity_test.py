#!/usr/bin/env python3
"""
tools/connectivity_test.py
==========================
Automated Connectivity Test Suite

Chạy kiểm tra kết nối tự động dựa trên test matrix trong ip_plan.yaml
và vpls_policy.yaml. Sinh báo cáo kết quả chi tiết.

Sử dụng:
    tester = ConnectivityTest(net)
    report = tester.test_intra_branch('branch1', config_loader)
    report = tester.test_inter_branch(vpls_config)
    tester.print_summary(report)
    tester.save_report(report, 'result/test.log')
"""

import os
import sys
import time
from datetime import datetime
from mininet.log import info, warn, error


class TestResult:
    """Kết quả của một ping test đơn lẻ."""

    PASS = 'PASS'
    FAIL = 'FAIL'
    SKIP = 'SKIP'

    def __init__(self, src, dst, status, rtt_ms=None, loss_pct=100, detail=''):
        self.src      = src
        self.dst      = dst
        self.status   = status
        self.rtt_ms   = rtt_ms
        self.loss_pct = loss_pct
        self.detail   = detail
        self.timestamp = datetime.now().strftime('%H:%M:%S')

    def __str__(self):
        rtt_str = f'{self.rtt_ms:.1f}ms' if self.rtt_ms else 'N/A'
        icon = '✓' if self.status == self.PASS else ('✗' if self.status == self.FAIL else '-')
        return (f"[{self.timestamp}] {icon} {self.src} -> {self.dst}: "
                f"{self.status} (RTT={rtt_str}, Loss={self.loss_pct}%)")


class TestReport:
    """Tập hợp kết quả của một bộ test."""

    def __init__(self, name, description=''):
        self.name        = name
        self.description = description
        self.results     = []
        self.start_time  = datetime.now()
        self.end_time    = None

    def add(self, result):
        self.results.append(result)

    def finish(self):
        self.end_time = datetime.now()

    @property
    def total(self):
        return len(self.results)

    @property
    def passed(self):
        return sum(1 for r in self.results if r.status == TestResult.PASS)

    @property
    def failed(self):
        return sum(1 for r in self.results if r.status == TestResult.FAIL)

    @property
    def skipped(self):
        return sum(1 for r in self.results if r.status == TestResult.SKIP)

    @property
    def pass_rate(self):
        eligible = self.total - self.skipped
        return (self.passed / eligible * 100) if eligible > 0 else 0

    @property
    def duration_secs(self):
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0


class ConnectivityTest:
    """
    Chạy connectivity tests tự động trên Mininet network.
    
    Sử dụng ping để kiểm tra kết nối giữa các hosts.
    Hỗ trợ cả intra-branch (nội bộ) và inter-branch (liên chi nhánh).
    """

    # Số gói ping cho mỗi test
    PING_COUNT  = 5
    # Timeout mỗi gói (giây)
    PING_TIMEOUT = 2
    # RTT threshold để coi là PASS (ms)
    RTT_THRESHOLD = 200

    def __init__(self, net):
        """
        Args:
            net: Mininet network object
        """
        self.net = net

    # ------------------------------------------------------------------
    # Intra-Branch Tests
    # ------------------------------------------------------------------

    def test_intra_branch(self, branch_id, config_loader=None):
        """
        Kiểm tra kết nối nội bộ trong một chi nhánh.
        
        Args:
            branch_id    : ví dụ 'branch1'
            config_loader: ConfigLoader object (nếu có, dùng test matrix từ YAML)
        
        Returns:
            TestReport
        """
        report = TestReport(
            name=f'Intra-Branch Test - {branch_id.upper()}',
            description=f'Kiểm tra connectivity trong nội bộ {branch_id}'
        )

        info(f'\n{"="*60}\n')
        info(f'  TEST: {report.name}\n')
        info(f'{"="*60}\n')

        if config_loader:
            # Dùng test matrix từ YAML
            self._run_from_matrix(report, config_loader.get_test_matrix())
        else:
            # Fallback: pingAll
            self._run_ping_all(report, branch_id)

        report.finish()
        return report

    def _run_from_matrix(self, report, test_matrix):
        """Chạy tests theo test matrix định nghĩa trong YAML."""

        # Intra-subnet tests
        for pair in test_matrix.get('intra_subnet', []):
            src_name, dst_name = pair[0], pair[1]
            result = self._ping_hosts(src_name, dst_name, 'intra-subnet')
            report.add(result)
            info(f'  {result}\n')

        # Intra-VLAN tests (Branch 2)
        for vlan_test in test_matrix.get('intra_vlan', []):
            vlan_id = vlan_test.get('vlan')
            for pair in vlan_test.get('pairs', []):
                result = self._ping_hosts(pair[0], pair[1], f'VLAN{vlan_id}')
                report.add(result)
                info(f'  {result}\n')

        # Inter-VLAN tests
        for pair in test_matrix.get('inter_vlan', []):
            result = self._ping_hosts(pair[0], pair[1], 'inter-VLAN')
            report.add(result)
            info(f'  {result}\n')

        # Intra-rack tests (Branch 3)
        for rack_test in test_matrix.get('intra_rack', []):
            rack_name = rack_test.get('rack')
            for pair in rack_test.get('pairs', []):
                result = self._ping_hosts(pair[0], pair[1], f'rack-{rack_name}')
                report.add(result)
                info(f'  {result}\n')

        # Inter-rack tests
        for pair in test_matrix.get('inter_rack', []):
            result = self._ping_hosts(pair[0], pair[1], 'inter-rack')
            report.add(result)
            info(f'  {result}\n')

        # Gateway reachability
        for gw_test in test_matrix.get('gateway_reachability', []):
            host   = gw_test['host']
            target = gw_test['target']
            result = self._ping_ip(host, target, 'gateway')
            report.add(result)
            info(f'  {result}\n')

    def _run_ping_all(self, report, branch_id):
        """Fallback: chạy pingAll và parse kết quả."""
        info(f'  Running pingAll for {branch_id}...\n')
        # Lọc chỉ hosts của branch này
        branch_prefix = {
            'branch1': ['pc'],
            'branch2': ['lab', 'admin', 'guest'],
            'branch3': ['web', 'dns', 'db'],
        }.get(branch_id, [])

        all_hosts = [h for h in self.net.hosts
                     if any(h.name.startswith(p) for p in branch_prefix)]

        for i, src in enumerate(all_hosts):
            for dst in all_hosts[i+1:]:
                result = self._ping_hosts(src.name, dst.name, 'auto')
                report.add(result)
                info(f'  {result}\n')

    # ------------------------------------------------------------------
    # Inter-Branch Tests
    # ------------------------------------------------------------------

    def test_inter_branch(self, vpls_config=None):
        """
        Kiểm tra kết nối liên chi nhánh qua MPLS VPLS.
        
        Args:
            vpls_config: dict từ vpls_policy.yaml
        
        Returns:
            TestReport
        """
        report = TestReport(
            name='Inter-Branch MPLS VPLS Test',
            description='Kiểm tra connectivity giữa các chi nhánh qua ISP MPLS backbone'
        )

        info(f'\n{"="*60}\n')
        info(f'  TEST: {report.name}\n')
        info(f'{"="*60}\n')

        if vpls_config and 'tests' in vpls_config:
            test_cfg = vpls_config['tests']
            # Inter-branch ping tests
            for pair_cfg in test_cfg.get('inter_branch_pairs', []):
                src  = pair_cfg['src']
                dst  = pair_cfg['dst']
                desc_str = f"Branch-to-Branch ({pair_cfg.get('src_ip','?')} -> {pair_cfg.get('dst_ip','?')})"
                result = self._ping_hosts(src, dst, desc_str)
                report.add(result)
                info(f'  {result}\n')
        else:
            # Fallback: test representative pairs
            DEFAULT_PAIRS = [
                ('pc01',   'lab01',   'B1->B2'),
                ('pc01',   'web01',   'B1->B3'),
                ('lab01',  'web01',   'B2->B3'),
                ('admin01','db01',    'B2(ADMIN)->B3(DB)'),
                ('guest01','dns01',   'B2(GUEST)->B3(DNS)'),
            ]
            for src, dst, label in DEFAULT_PAIRS:
                result = self._ping_hosts(src, dst, label)
                report.add(result)
                info(f'  {result}\n')

        report.finish()
        return report

    # ------------------------------------------------------------------
    # Backbone Tests
    # ------------------------------------------------------------------

    def test_backbone_connectivity(self):
        """
        Kiểm tra kết nối nội bộ MPLS backbone.
        Test: P-P links, PE-P links, PE loopback reachability.
        
        Returns:
            TestReport
        """
        report = TestReport(
            name='Backbone MPLS Connectivity Test',
            description='Kiểm tra P-P, PE-P links và loopback reachability trong backbone'
        )

        info(f'\n{"="*60}\n')
        info(f'  TEST: {report.name}\n')
        info(f'{"="*60}\n')

        # P-P link tests (trực tiếp)
        p_p_pairs = [
            ('p01', '10.0.10.2', 'P01->P02'),
            ('p02', '10.0.11.2', 'P02->P03'),
            ('p03', '10.0.12.2', 'P03->P04'),
            ('p01', '10.0.13.2', 'P01->P03 diagonal'),
            ('p02', '10.0.14.2', 'P02->P04 diagonal'),
        ]
        info('  [*] P-P Link tests:\n')
        for router, target_ip, label in p_p_pairs:
            result = self._ping_ip(router, target_ip, label)
            report.add(result)
            info(f'  {result}\n')

        # PE-P link tests
        pe_p_pairs = [
            ('pe01', '10.0.20.2', 'PE01->P01'),
            ('pe01', '10.0.21.2', 'PE01->P02'),
            ('pe02', '10.0.22.2', 'PE02->P02'),
            ('pe02', '10.0.23.2', 'PE02->P03'),
            ('pe03', '10.0.24.2', 'PE03->P03'),
            ('pe03', '10.0.25.2', 'PE03->P04'),
        ]
        info('  [*] PE-P Link tests:\n')
        for router, target_ip, label in pe_p_pairs:
            result = self._ping_ip(router, target_ip, label)
            report.add(result)
            info(f'  {result}\n')

        # PE loopback reachability (end-to-end backbone)
        loopback_pairs = [
            ('pe01', '10.0.0.12', 'PE01->PE02 loopback'),
            ('pe01', '10.0.0.13', 'PE01->PE03 loopback'),
            ('pe02', '10.0.0.13', 'PE02->PE03 loopback'),
        ]
        info('  [*] PE loopback reachability (end-to-end backbone):\n')
        for router, target_ip, label in loopback_pairs:
            result = self._ping_ip(router, target_ip, label)
            report.add(result)
            info(f'  {result}\n')

        # PE-CE WAN links
        pe_ce_pairs = [
            ('pe01', '10.100.1.2', 'PE01->CE01'),
            ('pe02', '10.100.2.2', 'PE02->CE02'),
            ('pe03', '10.100.3.2', 'PE03->CE03'),
        ]
        info('  [*] PE-CE WAN links:\n')
        for router, target_ip, label in pe_ce_pairs:
            result = self._ping_ip(router, target_ip, label)
            report.add(result)
            info(f'  {result}\n')

        report.finish()
        return report

    # ------------------------------------------------------------------
    # Core: Ping execution
    # ------------------------------------------------------------------

    def _ping_hosts(self, src_name, dst_name, test_type=''):
        """Ping từ host src đến host dst theo tên node."""
        src_node = self.net.get(src_name)
        dst_node = self.net.get(dst_name)

        if src_node is None or dst_node is None:
            missing = src_name if src_node is None else dst_name
            return TestResult(
                src_name, dst_name,
                status=TestResult.SKIP,
                detail=f'Node {missing} không tồn tại'
            )

        # Lấy IP của dst node
        dst_ip = dst_node.IP()
        if not dst_ip or dst_ip == '0.0.0.0':
            # Thử lấy IP từ defaultIntf
            intf = dst_node.defaultIntf()
            if intf:
                dst_ip = intf.ip
        if not dst_ip:
            return TestResult(
                src_name, dst_name,
                status=TestResult.SKIP,
                detail=f'{dst_name} không có IP'
            )

        return self._ping_ip(src_name, dst_ip, test_type, dst_display=dst_name)

    def _ping_ip(self, src_name, dst_ip, test_type='', dst_display=None):
        """Ping từ node src_name đến địa chỉ IP dst_ip."""
        src_node = self.net.get(src_name)
        if src_node is None:
            return TestResult(
                src_name, dst_display or dst_ip,
                status=TestResult.SKIP,
                detail=f'Source node {src_name} không tồn tại'
            )

        display_dst = dst_display or dst_ip
        cmd = (f'ping -c {self.PING_COUNT} -W {self.PING_TIMEOUT} '
               f'-q {dst_ip} 2>&1')
        output = src_node.cmd(cmd)

        # Parse kết quả ping
        loss_pct, rtt_avg = self._parse_ping_output(output)

        if loss_pct == 0 and rtt_avg is not None:
            status = TestResult.PASS
        elif loss_pct == 100:
            status = TestResult.FAIL
        else:
            # Partial loss
            status = TestResult.FAIL

        return TestResult(
            src=f'{src_name}',
            dst=display_dst,
            status=status,
            rtt_ms=rtt_avg,
            loss_pct=loss_pct,
            detail=f'[{test_type}] {output.strip().split(chr(10))[-1]}'
        )

    def _parse_ping_output(self, output):
        """
        Parse output của lệnh ping để lấy loss% và RTT trung bình.
        
        Returns:
            (loss_pct, rtt_avg_ms) hoặc (100, None) nếu lỗi
        """
        loss_pct = 100
        rtt_avg  = None

        for line in output.split('\n'):
            # Parse packet loss
            if '% packet loss' in line or '% loss' in line:
                try:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if '%' in part:
                            loss_str = part.replace('%', '').replace(',', '')
                            loss_pct = float(loss_str)
                            break
                except (ValueError, IndexError):
                    pass

            # Parse RTT: "rtt min/avg/max/mdev = 0.123/0.234/0.345/0.056 ms"
            if 'rtt min' in line or 'round-trip' in line:
                try:
                    # Lấy phần sau dấu =
                    rtt_part = line.split('=')[1].strip()
                    rtt_values = rtt_part.split('/') 
                    rtt_avg = float(rtt_values[1])  # avg là index 1
                except (IndexError, ValueError):
                    pass

        return loss_pct, rtt_avg

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def print_summary(self, report):
        """In summary của TestReport ra console."""
        separator = '=' * 60
        info(f'\n{separator}\n')
        info(f'  REPORT: {report.name}\n')
        info(f'  {report.description}\n')
        info(f'{separator}\n')

        # Chi tiết từng test
        for result in report.results:
            icon = '✓' if result.status == TestResult.PASS else \
                   ('-' if result.status == TestResult.SKIP else '✗')
            rtt  = f'{result.rtt_ms:.1f}ms' if result.rtt_ms else 'N/A'
            info(f'  [{icon}] {result.src:12} -> {result.dst:15} '
                 f'| {result.status:4} | RTT={rtt:8} | Loss={result.loss_pct:.0f}%\n')

        info(f'{separator}\n')
        info(f'  Total : {report.total}\n')
        info(f'  PASS  : {report.passed}\n')
        info(f'  FAIL  : {report.failed}\n')
        info(f'  SKIP  : {report.skipped}\n')
        info(f'  Rate  : {report.pass_rate:.1f}%\n')
        info(f'  Time  : {report.duration_secs:.1f}s\n')
        info(f'{separator}\n')

        if report.pass_rate == 100:
            info('  ✓ TẤT CẢ TESTS PASSED!\n')
        elif report.pass_rate >= 80:
            warn(f'  ~ Phần lớn tests passed ({report.pass_rate:.0f}%). Kiểm tra lại FAIL.\n')
        else:
            error(f'  ✗ NHIỀU TESTS FAILED ({report.failed}/{report.total}). Check routing!\n')

    def save_report(self, report, output_path):
        """Lưu báo cáo vào file text."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"{'='*60}\n")
            f.write(f"REPORT: {report.name}\n")
            f.write(f"Time: {report.start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Description: {report.description}\n")
            f.write(f"{'='*60}\n\n")

            for result in report.results:
                rtt = f'{result.rtt_ms:.1f}ms' if result.rtt_ms else 'N/A'
                f.write(f"[{result.status}] {result.src} -> {result.dst} "
                        f"| RTT={rtt} | Loss={result.loss_pct:.0f}%\n")
                if result.detail:
                    f.write(f"       {result.detail}\n")

            f.write(f"\n{'='*60}\n")
            f.write(f"SUMMARY:\n")
            f.write(f"  Total : {report.total}\n")
            f.write(f"  PASS  : {report.passed}\n")
            f.write(f"  FAIL  : {report.failed}\n")
            f.write(f"  Rate  : {report.pass_rate:.1f}%\n")
            f.write(f"  Duration: {report.duration_secs:.1f}s\n")

        info(f'*** Report saved: {output_path}\n')

    def save_all_reports(self, reports, output_dir='result'):
        """Lưu nhiều reports vào thư mục."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        for report in reports:
            filename = f"{report.name.replace(' ', '_').lower()}_{timestamp}.log"
            path = os.path.join(output_dir, filename)
            self.save_report(report, path)
