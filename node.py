import argparse
import os
import socket
import subprocess
import sys
from pathlib import Path

from backend_selector import BACKEND_CHOICES, runtime_dir, select_backend


DEFAULT_PORT = 50052
FIREWALL_RULE_PREFIX = "LLAMA RPC Portable Node TCP"


def get_ip_address():
    """Cari alamat IPv4 LAN tanpa memerlukan akses internet."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.168.88.1", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def ensure_windows_firewall(port):
    """Tambahkan rule LocalSubnet bila proses memiliki hak Administrator."""
    if os.name != "nt":
        return

    rule_name = f"{FIREWALL_RULE_PREFIX} {port}"

    check_command = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        f"Get-NetFirewallRule -DisplayName '{rule_name}' -ErrorAction Stop | Out-Null",
    ]
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    check = subprocess.run(
        check_command,
        capture_output=True,
        text=True,
        creationflags=creation_flags,
        check=False,
    )
    if check.returncode == 0:
        print(f"Firewall siap: {rule_name}")
        return

    add_script = (
        f"New-NetFirewallRule -DisplayName '{rule_name}' "
        "-Direction Inbound -Action Allow -Protocol TCP "
        f"-LocalPort {port} -RemoteAddress LocalSubnet -Profile Any | Out-Null"
    )
    add = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            add_script,
        ],
        capture_output=True,
        text=True,
        creationflags=creation_flags,
        check=False,
    )
    if add.returncode == 0:
        print(f"Firewall dibuat: {rule_name}")
    else:
        print("PERINGATAN: rule firewall belum dapat dibuat.")
        print("Jalankan NODE.exe sekali dengan klik kanan -> Run as administrator.")


def start_rpc_server():
    parser = argparse.ArgumentParser(description="Node RPC llama.cpp")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--threads", type=int, help="Jumlah thread CPU node")
    parser.add_argument("--device", help="Batasi device, contoh: CUDA0")
    parser.add_argument(
        "--backend",
        choices=BACKEND_CHOICES,
        default="auto",
        help="Pilih backend; default mendeteksi CUDA, Vulkan, lalu CPU",
    )
    args = parser.parse_args()

    try:
        selected_backend, backend_detail = select_backend(args.backend)
    except (RuntimeError, ValueError) as exc:
        print(f"Eror memilih backend: {exc}")
        return 1

    base_dir = runtime_dir(selected_backend)
    rpc_exe = base_dir / "ggml-rpc-server.exe"
    if not rpc_exe.is_file():
        print(f"Eror: {rpc_exe} tidak ditemukan.")
        return 1

    ip_pembantu = get_ip_address()
    command = [str(rpc_exe), "--host", args.host, "--port", str(args.port)]
    if args.threads:
        command += ["--threads", str(args.threads)]
    if args.device:
        command += ["--device", args.device]

    ensure_windows_firewall(args.port)

    print("=" * 60)
    print(f"NODE RPC PC PEMBANTU: {ip_pembantu}:{args.port}")
    print(f"Backend otomatis: {selected_backend.upper()} ({backend_detail})")
    print("Gunakan alamat di atas pada server.py di PC utama.")
    print("Tekan Ctrl+C untuk menghentikan node.")
    print("=" * 60)

    try:
        return subprocess.run(command, cwd=base_dir, check=False).returncode
    except KeyboardInterrupt:
        print("\nNode RPC dihentikan.")
        return 0
    except OSError as exc:
        print(f"Eror menjalankan node RPC: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(start_rpc_server())
