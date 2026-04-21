#!/usr/bin/env python3
"""
frr_deploy.py
Triển khai cấu hình FRR vào các node đang chạy trong Mininet.
Yêu cầu: FRR đã được cài đặt (apt install frr).
Chạy sau khi Mininet topology đã khởi động.
"""

import os
import subprocess
import sys

CONFIGS_DIR = os.path.join(os.path.dirname(__file__), '..', 'configs')
DAEMONS = ['ospfd', 'ldpd', 'bgpd']

ROUTERS = ['p01', 'p02', 'p03', 'p04', 'pe01', 'pe02', 'pe03', 'ce01', 'ce02', 'ce03']


def get_node_pid(node_name):
    """Lấy PID của Mininet node thông qua namespace."""
    result = subprocess.run(
        ['pgrep', '-f', f'mininet:{node_name}'],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        return result.stdout.strip().split('\n')[0]
    return None


def run_in_ns(node_name, cmd):
    """Chạy lệnh trong network namespace của node."""
    # Mininet tạo namespace dựa trên PID
    full_cmd = f'ip netns exec {node_name} {cmd}'
    result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True)
    return result


def deploy_frr_to_node(node_name):
    """Deploy FRR config vào một node cụ thể."""
    conf_file = os.path.join(CONFIGS_DIR, f'{node_name}.conf')
    if not os.path.exists(conf_file):
        print(f"  [SKIP] Không tìm thấy config: {conf_file}")
        return False

    # Tạo thư mục FRR trong namespace
    run_in_ns(node_name, 'mkdir -p /etc/frr')

    # Tạo daemons file
    daemons_content = "zebra=yes\nospfd=yes\nldpd=yes\nbgpd=yes\nvtysh_enable=yes\n"
    daemons_path = f'/tmp/frr_daemons_{node_name}'
    with open(daemons_path, 'w') as f:
        f.write(daemons_content)

    run_in_ns(node_name, f'cp {daemons_path} /etc/frr/daemons')
    run_in_ns(node_name, f'cp {conf_file} /etc/frr/frr.conf')
    run_in_ns(node_name, 'chown -R frr:frr /etc/frr/')
    run_in_ns(node_name, 'chmod 640 /etc/frr/frr.conf')

    # Khởi động FRR
    result = run_in_ns(node_name, '/usr/lib/frr/frrinit.sh start')
    if result.returncode == 0:
        print(f"  [OK] FRR started on {node_name}")
        return True
    else:
        print(f"  [WARN] FRR start trả về code {result.returncode} cho {node_name}")
        print(f"         stderr: {result.stderr[:200]}")
        return False


def deploy_frr_via_mnexec(node_name, net_object):
    """
    Deploy FRR sử dụng Mininet node object trực tiếp.
    Dùng phương pháp này khi có access vào net object.
    """
    conf_file = os.path.join(CONFIGS_DIR, f'{node_name}.conf')
    if not os.path.exists(conf_file):
        print(f"  [SKIP] {node_name}: Không có config file")
        return

    node = net_object.get(node_name)
    if node is None:
        print(f"  [SKIP] {node_name}: Không tìm thấy trong topology")
        return

    # Setup FRR directories
    node.cmd('mkdir -p /etc/frr /var/run/frr /var/log/frr')
    node.cmd('chmod 755 /etc/frr /var/run/frr /var/log/frr')

    # Daemons file
    node.cmd('echo "zebra=yes\nospfd=yes\nldpd=yes\nbgpd=yes\nvtysh_enable=yes" > /etc/frr/daemons')

    # Copy config
    with open(conf_file, 'r') as f:
        config_content = f.read()

    # Write config via node
    node.cmd(f'cat > /etc/frr/frr.conf << \'EOFCONF\'\n{config_content}\nEOFCONF')

    # Set permissions
    node.cmd('chown -R frr:frr /etc/frr/ 2>/dev/null || true')
    node.cmd('chmod 640 /etc/frr/frr.conf')

    # Start FRR daemons
    node.cmd('/usr/lib/frr/zebra -d -f /etc/frr/frr.conf -i /var/run/frr/zebra.pid 2>/dev/null')
    node.cmd('/usr/lib/frr/ospfd -d -f /etc/frr/frr.conf -i /var/run/frr/ospfd.pid 2>/dev/null')
    node.cmd('/usr/lib/frr/ldpd -d -f /etc/frr/frr.conf -i /var/run/frr/ldpd.pid 2>/dev/null')

    # BGP chỉ cho PE
    if node_name.startswith('pe'):
        node.cmd('/usr/lib/frr/bgpd -d -f /etc/frr/frr.conf -i /var/run/frr/bgpd.pid 2>/dev/null')

    print(f"  [OK] FRR deployed to {node_name}")


def deploy_all(net_object=None):
    """Deploy FRR vào tất cả routers."""
    print("=== Triển khai FRR vào tất cả routers ===\n")

    # Kiểm tra FRR installed
    result = subprocess.run(['which', 'zebra'], capture_output=True)
    if result.returncode != 0:
        # Try alternate path
        result2 = subprocess.run(['ls', '/usr/lib/frr/zebra'], capture_output=True)
        if result2.returncode != 0:
            print("[ERROR] FRR chưa được cài đặt!")
            print("        Chạy: sudo apt install -y frr")
            sys.exit(1)

    for router in ROUTERS:
        print(f"\n  Deploying {router}...")
        if net_object:
            deploy_frr_via_mnexec(router, net_object)
        else:
            deploy_frr_to_node(router)

    print("\n=== Deployment hoàn tất! ===")
    print("    Chờ 10-15 giây để OSPF và LDP hội tụ...")


if __name__ == '__main__':
    print("FRR Deploy Tool")
    print("Sử dụng từ full_topology.py hoặc gọi deploy_all(net) với net object")
