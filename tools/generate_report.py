#!/usr/bin/env python3
"""
generate_report.py - Tạo biểu đồ và báo cáo HTML từ kết quả đo lường
=====================================================================
Đọc file JSON/CSV từ thư mục results/ và tạo:
  - Biểu đồ so sánh throughput giữa các chi nhánh
  - Biểu đồ độ trễ (RTT) và jitter
  - Biểu đồ packet loss
  - Báo cáo HTML tổng hợp

Sử dụng:
  python3 tools/generate_report.py
  python3 tools/generate_report.py --input results/results_20240101_120000.json
"""

import argparse
import json
import os
import glob
import datetime
import sys

RESULTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'results')


def load_latest_results(input_path=None):
    """Load file kết quả mới nhất hoặc file được chỉ định."""
    if input_path:
        with open(input_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    json_files = sorted(glob.glob(os.path.join(RESULTS_DIR, 'results_*.json')))
    if not json_files:
        print("[ERROR] Không tìm thấy file kết quả trong results/")
        print("        Chạy measure_performance.py trước!")
        sys.exit(1)

    latest = json_files[-1]
    print(f"[*] Đọc kết quả: {latest}")
    with open(latest, 'r', encoding='utf-8') as f:
        return json.load(f)


def try_import_matplotlib():
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        return plt, mpatches
    except ImportError:
        return None, None


def generate_charts(data, output_dir):
    """Tạo biểu đồ bằng matplotlib nếu có."""
    plt, mpatches = try_import_matplotlib()
    charts = []

    if plt is None:
        print("[WARN] matplotlib không có sẵn. Bỏ qua charts.")
        print("       Cài đặt: pip install matplotlib")
        return charts

    colors = {
        'branch1': '#2196F3',
        'branch2': '#4CAF50',
        'branch3': '#FF9800',
        'stress':  '#F44336',
    }

    def get_color(label):
        label_lower = label.lower()
        if 'b1' in label_lower or 'branch1' in label_lower or 'pc0' in label_lower:
            return colors['branch1']
        elif 'b2' in label_lower or 'branch2' in label_lower or 'lab\|admin\|guest' in label_lower:
            return colors['branch2']
        elif 'b3' in label_lower or 'branch3' in label_lower or 'web\|dns\|db' in label_lower:
            return colors['branch3']
        return '#9C27B0'

    # ---- Chart 1: Inter-Branch RTT Comparison ----
    inter_ping = [r for r in data.get('ping', []) if r.get('avg_ms') is not None]
    if inter_ping:
        fig, ax = plt.subplots(figsize=(12, 6))
        labels = [r['label'][:40] for r in inter_ping]
        values = [r['avg_ms'] for r in inter_ping]
        errors = [r.get('jitter_ms', 0) or 0 for r in inter_ping]
        bar_colors = ['#2196F3' if 'B1' in l or 'Branch1' in l
                      else '#4CAF50' if 'B2' in l or 'Branch2' in l
                      else '#FF9800' for l in labels]

        bars = ax.barh(labels, values, color=bar_colors, alpha=0.85,
                       xerr=errors, capsize=3)
        ax.set_xlabel('Round-Trip Time (ms)', fontsize=12)
        ax.set_title('Độ Trễ (RTT) - So Sánh Giữa Các Kết Nối', fontsize=14, fontweight='bold')
        ax.grid(axis='x', alpha=0.3)
        # Add value labels
        for bar, val in zip(bars, values):
            ax.text(val + 0.1, bar.get_y() + bar.get_height()/2,
                    f'{val:.2f}ms', va='center', fontsize=9)
        plt.tight_layout()
        chart_path = os.path.join(output_dir, 'chart_rtt.png')
        plt.savefig(chart_path, dpi=150, bbox_inches='tight')
        plt.close()
        charts.append(('RTT Comparison', 'chart_rtt.png'))
        print(f"  [✓] chart_rtt.png")

    # ---- Chart 2: TCP Throughput ----
    tcp_data = [r for r in data.get('throughput_tcp', []) if r.get('throughput_mbps') is not None]
    if tcp_data:
        fig, ax = plt.subplots(figsize=(12, 6))
        labels = [r['label'][:40] for r in tcp_data]
        values = [r['throughput_mbps'] for r in tcp_data]
        ax.barh(labels, values, color='#2196F3', alpha=0.85)
        ax.set_xlabel('Throughput (Mbps)', fontsize=12)
        ax.set_title('TCP Throughput - So Sánh Giữa Các Kết Nối', fontsize=14, fontweight='bold')
        ax.grid(axis='x', alpha=0.3)
        for bar, val in zip(ax.patches, values):
            ax.text(val + 0.1, bar.get_y() + bar.get_height()/2,
                    f'{val:.1f}', va='center', fontsize=9)
        plt.tight_layout()
        chart_path = os.path.join(output_dir, 'chart_tcp_throughput.png')
        plt.savefig(chart_path, dpi=150, bbox_inches='tight')
        plt.close()
        charts.append(('TCP Throughput', 'chart_tcp_throughput.png'))
        print(f"  [✓] chart_tcp_throughput.png")

    # ---- Chart 3: UDP Packet Loss ----
    udp_data = [r for r in data.get('throughput_udp', []) if r.get('packet_loss_pct') is not None]
    if udp_data:
        fig, ax = plt.subplots(figsize=(12, 6))
        labels = [r['label'][:40] for r in udp_data]
        loss_values = [r['packet_loss_pct'] for r in udp_data]
        bar_colors = ['#F44336' if v > 5 else '#FF9800' if v > 1 else '#4CAF50'
                      for v in loss_values]
        ax.barh(labels, loss_values, color=bar_colors, alpha=0.85)
        ax.set_xlabel('Packet Loss (%)', fontsize=12)
        ax.set_title('UDP Packet Loss - So Sánh Giữa Các Kết Nối', fontsize=14, fontweight='bold')
        ax.axvline(x=1, color='orange', linestyle='--', alpha=0.7, label='1% threshold')
        ax.axvline(x=5, color='red',    linestyle='--', alpha=0.7, label='5% threshold')
        ax.legend(fontsize=9)
        ax.grid(axis='x', alpha=0.3)
        plt.tight_layout()
        chart_path = os.path.join(output_dir, 'chart_packet_loss.png')
        plt.savefig(chart_path, dpi=150, bbox_inches='tight')
        plt.close()
        charts.append(('Packet Loss', 'chart_packet_loss.png'))
        print(f"  [✓] chart_packet_loss.png")

    # ---- Chart 4: Jitter ----
    ping_jitter = [r for r in data.get('ping', []) if r.get('jitter_ms') is not None]
    if ping_jitter:
        fig, ax = plt.subplots(figsize=(12, 6))
        labels = [r['label'][:40] for r in ping_jitter]
        values = [r['jitter_ms'] for r in ping_jitter]
        ax.barh(labels, values, color='#9C27B0', alpha=0.85)
        ax.set_xlabel('Jitter (ms)', fontsize=12)
        ax.set_title('Jitter (mdev) - Đo Từ Ping', fontsize=14, fontweight='bold')
        ax.grid(axis='x', alpha=0.3)
        plt.tight_layout()
        chart_path = os.path.join(output_dir, 'chart_jitter.png')
        plt.savefig(chart_path, dpi=150, bbox_inches='tight')
        plt.close()
        charts.append(('Jitter', 'chart_jitter.png'))
        print(f"  [✓] chart_jitter.png")

    # ---- Chart 5: Architecture Comparison (grouped bar) ----
    arch_data = {
        'Flat (B1)': {'rtt': [], 'throughput': [], 'loss': []},
        '3-Tier (B2)': {'rtt': [], 'throughput': [], 'loss': []},
        'Spine-Leaf (B3)': {'rtt': [], 'throughput': [], 'loss': []},
    }
    for r in data.get('ping', []):
        label = r.get('label', '')
        rtt = r.get('avg_ms')
        if rtt is None: continue
        if 'B1' in label or 'Branch1' in label or 'pc0' in r.get('src',''):
            arch_data['Flat (B1)']['rtt'].append(rtt)
        elif 'B2' in label or 'Branch2' in label:
            arch_data['3-Tier (B2)']['rtt'].append(rtt)
        elif 'B3' in label or 'Branch3' in label:
            arch_data['Spine-Leaf (B3)']['rtt'].append(rtt)

    fig, axes = plt.subplots(1, 3, figsize=(14, 5))
    fig.suptitle('So Sánh Hiệu Năng Theo Kiến Trúc Mạng LAN', fontsize=14, fontweight='bold')

    arch_names = list(arch_data.keys())
    arch_colors = ['#2196F3', '#4CAF50', '#FF9800']

    # RTT subplot
    avg_rtts = []
    for arch in arch_names:
        rtts = arch_data[arch]['rtt']
        avg_rtts.append(sum(rtts)/len(rtts) if rtts else 0)
    axes[0].bar(arch_names, avg_rtts, color=arch_colors, alpha=0.85)
    axes[0].set_title('Avg RTT (ms)')
    axes[0].set_ylabel('RTT (ms)')

    # Throughput subplot (from TCP)
    arch_tp = {'Flat (B1)': [], '3-Tier (B2)': [], 'Spine-Leaf (B3)': []}
    for r in data.get('throughput_tcp', []):
        tp = r.get('throughput_mbps')
        label = r.get('label','')
        if tp is None: continue
        if 'B1' in label or 'Branch1' in label or 'pc0' in r.get('src',''):
            arch_tp['Flat (B1)'].append(tp)
        elif 'B2' in label or 'Branch2' in label:
            arch_tp['3-Tier (B2)'].append(tp)
        elif 'B3' in label or 'Branch3' in label:
            arch_tp['Spine-Leaf (B3)'].append(tp)
    avg_tps = [sum(v)/len(v) if v else 0 for v in arch_tp.values()]
    axes[1].bar(arch_names, avg_tps, color=arch_colors, alpha=0.85)
    axes[1].set_title('Avg TCP Throughput (Mbps)')
    axes[1].set_ylabel('Mbps')

    # Loss subplot
    arch_loss = {'Flat (B1)': [], '3-Tier (B2)': [], 'Spine-Leaf (B3)': []}
    for r in data.get('throughput_udp', []):
        loss = r.get('packet_loss_pct')
        label = r.get('label','')
        if loss is None: continue
        if 'B1' in label or 'Branch1' in label:
            arch_loss['Flat (B1)'].append(loss)
        elif 'B2' in label or 'Branch2' in label:
            arch_loss['3-Tier (B2)'].append(loss)
        elif 'B3' in label or 'Branch3' in label:
            arch_loss['Spine-Leaf (B3)'].append(loss)
    avg_loss = [sum(v)/len(v) if v else 0 for v in arch_loss.values()]
    axes[2].bar(arch_names, avg_loss, color=arch_colors, alpha=0.85)
    axes[2].set_title('Avg Packet Loss (%)')
    axes[2].set_ylabel('%')

    for ax in axes:
        ax.tick_params(axis='x', rotation=15)
        ax.grid(axis='y', alpha=0.3)

    plt.tight_layout()
    chart_path = os.path.join(output_dir, 'chart_arch_comparison.png')
    plt.savefig(chart_path, dpi=150, bbox_inches='tight')
    plt.close()
    charts.append(('Architecture Comparison', 'chart_arch_comparison.png'))
    print(f"  [✓] chart_arch_comparison.png")

    return charts


def generate_html_report(data, charts, output_dir):
    """Tạo báo cáo HTML đầy đủ."""
    ts = data.get('metadata', {}).get('timestamp', 'N/A')
    duration = data.get('metadata', {}).get('duration_per_test', 'N/A')

    # Build stats tables
    def build_ping_table():
        rows = ''
        for r in data.get('ping', []):
            status_color = '#4CAF50' if r.get('reachable') else '#F44336'
            status = '✓' if r.get('reachable') else '✗'
            rows += f'''
            <tr>
                <td>{r.get("label","")}</td>
                <td>{r.get("src","")}</td>
                <td>{r.get("dst","")}</td>
                <td style="color:{status_color};font-weight:bold">{status}</td>
                <td>{r.get("avg_ms","N/A")}</td>
                <td>{r.get("min_ms","N/A")}</td>
                <td>{r.get("max_ms","N/A")}</td>
                <td>{r.get("jitter_ms","N/A")}</td>
                <td>{r.get("packet_loss_pct","N/A")}%</td>
            </tr>'''
        return rows

    def build_throughput_table():
        rows = ''
        tcp_map = {r['label']: r for r in data.get('throughput_tcp', [])}
        udp_map = {r['label']: r for r in data.get('throughput_udp', [])}
        for label in sorted(set(tcp_map.keys()) | set(udp_map.keys())):
            t = tcp_map.get(label, {})
            u = udp_map.get(label, {})
            rows += f'''
            <tr>
                <td>{label}</td>
                <td>{t.get("throughput_mbps","N/A")}</td>
                <td>{t.get("retransmits","N/A")}</td>
                <td>{u.get("throughput_mbps","N/A")}</td>
                <td>{u.get("packet_loss_pct","N/A")}%</td>
                <td>{u.get("jitter_ms","N/A")}</td>
            </tr>'''
        return rows

    def build_traceroute_table():
        rows = ''
        for r in data.get('traceroute', []):
            hops_str = ' → '.join(h['ip'] for h in r.get('hops', []))
            rows += f'''
            <tr>
                <td>{r.get("label","")}</td>
                <td>{r.get("src","")}</td>
                <td>{r.get("dst","")}</td>
                <td>{r.get("hop_count","N/A")}</td>
                <td style="font-family:monospace;font-size:11px">{hops_str}</td>
            </tr>'''
        return rows

    # Charts HTML
    charts_html = ''
    for chart_title, chart_file in charts:
        charts_html += f'''
        <div class="chart-container">
            <h3>{chart_title}</h3>
            <img src="{chart_file}" alt="{chart_title}" style="max-width:100%">
        </div>'''

    html = f'''<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Metro Ethernet MPLS - Báo Cáo Hiệu Năng</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 0; padding: 20px;
          background: #f5f5f5; color: #333; }}
  .header {{ background: linear-gradient(135deg, #1565C0, #0288D1);
             color: white; padding: 30px; border-radius: 12px; margin-bottom: 24px; }}
  .header h1 {{ margin: 0 0 8px 0; font-size: 24px; }}
  .header p  {{ margin: 4px 0; opacity: 0.9; font-size: 14px; }}
  .section {{ background: white; border-radius: 10px; padding: 20px;
              margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
  .section h2 {{ color: #1565C0; border-bottom: 2px solid #E3F2FD;
                 padding-bottom: 10px; margin-top: 0; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ background: #1565C0; color: white; padding: 10px 8px;
        text-align: left; font-weight: 600; }}
  td {{ padding: 8px; border-bottom: 1px solid #f0f0f0; }}
  tr:hover td {{ background: #E3F2FD; }}
  .chart-container {{ margin: 16px 0; text-align: center; }}
  .chart-container h3 {{ color: #555; font-size: 15px; margin-bottom: 8px; }}
  .stat-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 16px; margin-bottom: 20px; }}
  .stat-card {{ background: #E3F2FD; border-radius: 8px; padding: 16px; text-align: center;
                border-left: 4px solid #1565C0; }}
  .stat-card .value {{ font-size: 28px; font-weight: bold; color: #1565C0; }}
  .stat-card .label {{ font-size: 12px; color: #666; margin-top: 4px; }}
  .badge {{ padding: 3px 8px; border-radius: 12px; font-size: 11px; font-weight: bold; }}
  .badge-ok {{ background: #C8E6C9; color: #2E7D32; }}
  .badge-warn {{ background: #FFF9C4; color: #F57F17; }}
  .badge-err {{ background: #FFCDD2; color: #C62828; }}
</style>
</head>
<body>

<div class="header">
  <h1>📡 Metro Ethernet MPLS — Báo Cáo Hiệu Năng Mạng</h1>
  <p>🕐 Thời gian đo: {ts}</p>
  <p>⏱ Thời gian mỗi test iperf3: {duration}s | Nền tảng: Mininet + FRRouting</p>
  <p>🏗 Kiến trúc: MPLS Backbone (P01-P04, PE01-PE03) + 3 Chi nhánh (Flat / 3-Tier / Spine-Leaf)</p>
</div>

<div class="section">
  <h2>📊 Thống Kê Tổng Quan</h2>
  <div class="stat-grid">
    <div class="stat-card">
      <div class="value">{len(data.get("ping",[]))}</div>
      <div class="label">Ping Tests</div>
    </div>
    <div class="stat-card">
      <div class="value">{len(data.get("throughput_tcp",[]))}</div>
      <div class="label">TCP Throughput Tests</div>
    </div>
    <div class="stat-card">
      <div class="value">{len(data.get("throughput_udp",[]))}</div>
      <div class="label">UDP Throughput Tests</div>
    </div>
    <div class="stat-card">
      <div class="value">{len(data.get("traceroute",[]))}</div>
      <div class="label">Traceroute Tests</div>
    </div>
  </div>
</div>

<div class="section">
  <h2>📈 Biểu Đồ So Sánh</h2>
  {charts_html if charts_html else '<p><em>Không có biểu đồ (cài matplotlib để tạo biểu đồ)</em></p>'}
</div>

<div class="section">
  <h2>🏓 Kết Quả Ping (RTT, Packet Loss, Jitter)</h2>
  <table>
    <tr>
      <th>Kết Nối</th><th>Nguồn</th><th>Đích</th><th>Status</th>
      <th>RTT Avg (ms)</th><th>RTT Min</th><th>RTT Max</th>
      <th>Jitter (ms)</th><th>Packet Loss</th>
    </tr>
    {build_ping_table()}
  </table>
</div>

<div class="section">
  <h2>⚡ Throughput (TCP & UDP)</h2>
  <table>
    <tr>
      <th>Kết Nối</th>
      <th>TCP (Mbps)</th><th>TCP Retransmits</th>
      <th>UDP (Mbps)</th><th>UDP Loss %</th><th>UDP Jitter</th>
    </tr>
    {build_throughput_table()}
  </table>
</div>

<div class="section">
  <h2>🗺 Traceroute (Số Hop & Đường Đi)</h2>
  <table>
    <tr>
      <th>Kết Nối</th><th>Nguồn</th><th>Đích</th><th>Hops</th><th>Đường Đi</th>
    </tr>
    {build_traceroute_table()}
  </table>
</div>

<div class="section" style="font-size:12px;color:#999;text-align:center">
  Báo cáo tự động tạo bởi generate_report.py — Metro Ethernet MPLS Simulation
</div>

</body>
</html>'''

    report_path = os.path.join(output_dir, 'report.html')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"  [✓] HTML report: {report_path}")
    return report_path


def main():
    parser = argparse.ArgumentParser(description='Tạo báo cáo hiệu năng từ kết quả đo')
    parser.add_argument('--input', type=str, default=None,
                        help='File JSON input (mặc định: file mới nhất trong results/)')
    args = parser.parse_args()

    print("=== Tạo Báo Cáo Hiệu Năng Metro Ethernet MPLS ===\n")

    data = load_latest_results(args.input)

    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    output_dir = os.path.join(RESULTS_DIR, f'report_{ts}')
    os.makedirs(output_dir, exist_ok=True)
    print(f"[*] Output dir: {output_dir}\n")

    print("[*] Tạo biểu đồ...")
    charts = generate_charts(data, output_dir)

    print("\n[*] Tạo báo cáo HTML...")
    report_path = generate_html_report(data, charts, output_dir)

    print(f"\n✅ Hoàn tất! Mở báo cáo:")
    print(f"   xdg-open {report_path}")
    print(f"   # hoặc: firefox {report_path}")


if __name__ == '__main__':
    main()
