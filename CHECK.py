import argparse
import csv
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


DEFAULT_RPC_PORT = 50052
DEFAULT_LATENCY_SAMPLES = 4
RPC_DEVICE_PATTERN = re.compile(
    r"^\s*RPC\d+:\s+(.+?)\s+\((\d+)\s+MiB,\s+(\d+)\s+MiB free\)\s*$",
    re.MULTILINE,
)


def application_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def runtime_dir():
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        return Path(bundled_root) / "check_runtime"
    return Path(__file__).resolve().parent


def load_nodes(config_path):
    if not config_path.is_file():
        return []
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"gagal membaca {config_path}: {exc}") from exc

    raw_nodes = data.get("nodes", []) if isinstance(data, dict) else []
    nodes = []
    seen = set()
    for raw in raw_nodes:
        if not isinstance(raw, dict):
            continue
        host = str(raw.get("host", "")).strip()
        try:
            port = int(raw.get("port", DEFAULT_RPC_PORT))
        except (TypeError, ValueError):
            continue
        key = (host.lower(), port)
        if host and 1 <= port <= 65535 and key not in seen:
            seen.add(key)
            nodes.append({"host": host, "port": port})
    return nodes


def parse_node_argument(value):
    value = value.strip()
    if not value:
        raise argparse.ArgumentTypeError("alamat node kosong")
    if value.count(":") == 0:
        return {"host": value, "port": DEFAULT_RPC_PORT}
    host, port_text = value.rsplit(":", 1)
    try:
        port = int(port_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"port tidak valid: {port_text}") from exc
    if not host or not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"alamat node tidak valid: {value}")
    return {"host": host, "port": port}


def measure_rpc_link(node, timeout, samples):
    """Ukur respons koneksi ke RPC yang memang sudah berjalan pada node."""
    timings = []
    errors = []
    for sample_index in range(samples):
        started = time.perf_counter()
        try:
            with socket.create_connection(
                (node["host"], node["port"]), timeout=min(timeout, 5.0)
            ):
                timings.append((time.perf_counter() - started) * 1000)
        except (OSError, TimeoutError) as exc:
            errors.append(str(exc))
        if sample_index + 1 < samples:
            time.sleep(0.05)

    if not timings:
        return {
            "link_available": False,
            "link_error": errors[-1] if errors else "tidak ada respons TCP",
        }

    average = sum(timings) / len(timings)
    jitter = max(timings) - min(timings) if len(timings) > 1 else 0.0
    if average <= 2 and jitter <= 2:
        quality = "SANGAT BAIK"
    elif average <= 5 and jitter <= 5:
        quality = "BAIK"
    elif average <= 15 and jitter <= 15:
        quality = "CUKUP"
    else:
        quality = "LAMBAT / TIDAK STABIL"

    return {
        "link_available": True,
        "link_samples_ok": len(timings),
        "link_samples_total": samples,
        "tcp_min_ms": min(timings),
        "tcp_avg_ms": average,
        "tcp_max_ms": max(timings),
        "tcp_jitter_ms": jitter,
        "link_quality": quality,
    }


def query_rpc_device(node, timeout):
    executable = runtime_dir() / "llama-server.exe"
    endpoint = f"{node['host']}:{node['port']}"
    if not executable.is_file():
        return {
            **node,
            "online": False,
            "error": f"runtime pemeriksa tidak ditemukan: {executable}",
        }

    started = time.perf_counter()
    try:
        result = subprocess.run(
            [str(executable), "--rpc", endpoint, "--list-devices"],
            cwd=runtime_dir(),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {**node, "online": False, "error": f"timeout setelah {timeout:g} detik"}
    except OSError as exc:
        return {**node, "online": False, "error": str(exc)}

    output = result.stdout + "\n" + result.stderr
    response_ms = (time.perf_counter() - started) * 1000
    matches = RPC_DEVICE_PATTERN.findall(output)
    for remote_name, total_text, free_text in matches:
        if remote_name.strip().lower() == endpoint.lower():
            total_mib = int(total_text)
            free_mib = int(free_text)
            return {
                **node,
                "online": True,
                "rpc_name": remote_name.strip(),
                "vram_total_mib": total_mib,
                "vram_free_mib": free_mib,
                "vram_used_mib": max(0, total_mib - free_mib),
                "rpc_response_ms": response_ms,
            }

    short_error = ""
    for line in reversed(output.splitlines()):
        line = line.strip()
        if line and not line.startswith("Available devices"):
            short_error = line
            break
    return {
        **node,
        "online": False,
        "error": short_error or "node tidak muncul pada daftar perangkat RPC",
    }


def inspect_node(node, timeout, network_test_enabled, latency_samples):
    result = query_rpc_device(node, timeout)
    if result["online"] and network_test_enabled:
        result.update(measure_rpc_link(node, timeout, latency_samples))
    return result


def find_nvidia_smi():
    executable = shutil.which("nvidia-smi")
    if executable:
        return Path(executable)

    candidates = [
        Path(os.environ.get("WINDIR", r"C:\Windows"))
        / "System32"
        / "nvidia-smi.exe",
        Path(os.environ.get("ProgramW6432", r"C:\Program Files"))
        / "NVIDIA Corporation"
        / "NVSMI"
        / "nvidia-smi.exe",
    ]
    return next((path for path in candidates if path.is_file()), None)


def query_server_gpus(timeout):
    executable = find_nvidia_smi()
    if not executable:
        return [], "nvidia-smi tidak ditemukan; GPU NVIDIA SERVER tidak terdeteksi"

    fields = (
        "index,name,compute_cap,memory.total,memory.used,memory.free,"
        "utilization.gpu"
    )
    try:
        result = subprocess.run(
            [
                str(executable),
                f"--query-gpu={fields}",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return [], f"nvidia-smi timeout setelah {timeout:g} detik"
    except OSError as exc:
        return [], str(exc)

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return [], detail or f"nvidia-smi keluar dengan kode {result.returncode}"

    gpus = []
    for row in csv.reader(result.stdout.splitlines(), skipinitialspace=True):
        if len(row) < 7:
            continue
        try:
            total_mib = int(row[3].strip())
            used_mib = int(row[4].strip())
            free_mib = int(row[5].strip())
            utilization = int(row[6].strip())
        except ValueError:
            continue
        gpus.append(
            {
                "index": row[0].strip(),
                "name": row[1].strip(),
                "compute_capability": row[2].strip(),
                "vram_total_mib": total_mib,
                "vram_used_mib": used_mib,
                "vram_free_mib": free_mib,
                "utilization_percent": utilization,
            }
        )
    if not gpus:
        return [], "nvidia-smi tidak mengembalikan data GPU"
    return gpus, None


def gib(mib):
    return f"{mib / 1024:.2f} GiB"


def unique_nodes(nodes):
    result = []
    seen = set()
    for node in nodes:
        key = (node["host"].lower(), node["port"])
        if key not in seen:
            seen.add(key)
            result.append(node)
    return result


def run_check(
    nodes,
    config_path,
    timeout,
    network_test_enabled=True,
    latency_samples=DEFAULT_LATENCY_SAMPLES,
):
    print("=" * 68)
    print("CHECK KONEKSI, KEMAMPUAN, DAN KINERJA NODE LLAMA RPC")
    print("=" * 68)
    print(f"Konfigurasi     : {config_path}")
    print(f"Node terdaftar  : {len(nodes)}")
    if network_test_enabled:
        print(f"Tes koneksi     : {latency_samples} sampel langsung ke port RPC node")
        print("Program NODE    : cukup LLAMA-RPC mode NODE; CHECK tidak diperlukan")
    else:
        print("Tes koneksi     : DINONAKTIFKAN")

    results_by_key = {}
    if nodes:
        print("Memeriksa perangkat RPC langsung dari setiap node ...")
        worker_count = min(len(nodes), 8)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {
                executor.submit(
                    inspect_node,
                    node,
                    timeout,
                    network_test_enabled,
                    latency_samples,
                ): node
                for node in nodes
            }
            for future in as_completed(future_map):
                result = future.result()
                results_by_key[(result["host"].lower(), result["port"])] = result
    else:
        print("Belum ada node. Pemeriksaan tetap dilanjutkan untuk PC SERVER.")

    results = [
        results_by_key[(node["host"].lower(), node["port"])] for node in nodes
    ]
    online = [result for result in results if result["online"]]
    server_gpus, server_error = query_server_gpus(timeout)

    for index, result in enumerate(results, 1):
        endpoint = f"{result['host']}:{result['port']}"
        print(f"\n[{index}] {endpoint}")
        if result["online"]:
            print("    Status       : ONLINE dan terhubung melalui RPC")
            print(f"    Kapasitas    : {gib(result['vram_total_mib'])} VRAM")
            print(f"    Sedang dipakai: {gib(result['vram_used_mib'])}")
            print(f"    Masih kosong : {gib(result['vram_free_mib'])}")
            print(f"    Respons RPC  : {result['rpc_response_ms']:.1f} ms")
            if network_test_enabled and result.get("link_available"):
                print(
                    "    Latensi TCP  : "
                    f"min {result['tcp_min_ms']:.1f} / "
                    f"rata-rata {result['tcp_avg_ms']:.1f} / "
                    f"maks {result['tcp_max_ms']:.1f} ms"
                )
                print(f"    Jitter TCP   : {result['tcp_jitter_ms']:.1f} ms")
                print(
                    f"    Sampel sukses: {result['link_samples_ok']} dari "
                    f"{result['link_samples_total']}"
                )
                print(f"    Kualitas RPC : {result['link_quality']}")
            elif network_test_enabled:
                print("    Kualitas RPC : GAGAL DIUKUR")
                print(f"    Detail       : {result.get('link_error', 'tidak diketahui')}")
        else:
            print("    Status       : OFFLINE / tidak dapat terhubung")
            print(f"    Detail       : {result['error']}")

    node_total_mib = sum(item["vram_total_mib"] for item in online)
    node_used_mib = sum(item["vram_used_mib"] for item in online)
    node_free_mib = sum(item["vram_free_mib"] for item in online)

    print("\n" + "=" * 68)
    print("TOTAL KEMAMPUAN PC PEMBANTU")
    print("=" * 68)
    print(f"Koneksi pembantu aktif : {len(online)} dari {len(nodes)}")
    print(f"Total perangkat RPC    : {len(online)}")
    print(f"Total kapasitas VRAM   : {gib(node_total_mib)} ({node_total_mib:,} MiB)")
    print(f"Total VRAM terpakai    : {gib(node_used_mib)} ({node_used_mib:,} MiB)")
    print(f"Total VRAM masih kosong: {gib(node_free_mib)} ({node_free_mib:,} MiB)")

    link_results = [item for item in online if item.get("link_available")]
    if network_test_enabled:
        print("\n" + "=" * 68)
        print("RINGKASAN KINERJA KONEKSI RPC")
        print("=" * 68)
        print(f"Node berhasil diuji     : {len(link_results)} dari {len(online)} node online")
        if link_results:
            average_latency = sum(item["tcp_avg_ms"] for item in link_results) / len(
                link_results
            )
            average_jitter = sum(item["tcp_jitter_ms"] for item in link_results) / len(
                link_results
            )
            fastest = min(link_results, key=lambda item: item["tcp_avg_ms"])
            slowest = max(link_results, key=lambda item: item["tcp_avg_ms"])
            print(f"Rata-rata latensi       : {average_latency:.1f} ms")
            print(f"Rata-rata jitter        : {average_jitter:.1f} ms")
            print(
                f"Respons tercepat        : {fastest['host']} "
                f"({fastest['tcp_avg_ms']:.1f} ms)"
            )
            print(
                f"Respons terlambat       : {slowest['host']} "
                f"({slowest['tcp_avg_ms']:.1f} ms)"
            )
        print("Catatan: ini mengukur respons RPC, bukan angka bandwidth MB/s buatan.")

    print("\n" + "=" * 68)
    print("KEMAMPUAN GPU PC SERVER")
    print("=" * 68)
    if server_gpus:
        for index, gpu in enumerate(server_gpus, 1):
            print(f"[{index}] {gpu['name']}")
            print(f"    Compute capability : {gpu['compute_capability']}")
            print(f"    Kapasitas          : {gib(gpu['vram_total_mib'])} VRAM")
            print(f"    Sedang dipakai     : {gib(gpu['vram_used_mib'])}")
            print(f"    Masih kosong       : {gib(gpu['vram_free_mib'])}")
            print(f"    Penggunaan GPU     : {gpu['utilization_percent']}%")
    else:
        print(f"GPU SERVER tidak dapat dibaca: {server_error}")

    server_total_mib = sum(gpu["vram_total_mib"] for gpu in server_gpus)
    server_used_mib = sum(gpu["vram_used_mib"] for gpu in server_gpus)
    server_free_mib = sum(gpu["vram_free_mib"] for gpu in server_gpus)
    overall_total_mib = node_total_mib + server_total_mib
    overall_used_mib = node_used_mib + server_used_mib
    overall_free_mib = node_free_mib + server_free_mib

    print("\n" + "=" * 68)
    print("TOTAL KESELURUHAN SERVER + SEMUA NODE")
    print("=" * 68)
    print(f"GPU SERVER             : {len(server_gpus)}")
    print(f"Perangkat RPC NODE     : {len(online)}")
    print(f"Total perangkat hitung : {len(server_gpus) + len(online)}")
    print(f"TOTAL kapasitas VRAM   : {gib(overall_total_mib)} ({overall_total_mib:,} MiB)")
    print(f"TOTAL VRAM terpakai    : {gib(overall_used_mib)} ({overall_used_mib:,} MiB)")
    print(f"TOTAL VRAM masih kosong: {gib(overall_free_mib)} ({overall_free_mib:,} MiB)")
    return 0 if len(online) == len(nodes) else 2


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Cek node LLAMA RPC, total VRAM, serta kualitas koneksi dari satu PC"
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=application_dir() / "server-nodes.json",
        help="lokasi server-nodes.json",
    )
    parser.add_argument(
        "--node",
        action="append",
        type=parse_node_argument,
        default=[],
        help="node tambahan, contoh 192.168.88.250:50052",
    )
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument(
        "--latency-samples",
        type=int,
        default=DEFAULT_LATENCY_SAMPLES,
        help=f"jumlah sampel koneksi per node (default: {DEFAULT_LATENCY_SAMPLES})",
    )
    parser.add_argument(
        "--no-network-test",
        "--no-speed-test",
        dest="no_network_test",
        action="store_true",
        help="lewati tes kualitas koneksi dan hanya cek RPC/VRAM",
    )
    parser.add_argument("--no-pause", action="store_true")
    args = parser.parse_args(argv)

    if not 1 <= args.latency_samples <= 20:
        parser.error("--latency-samples harus antara 1 dan 20")

    config_path = args.config.resolve()
    try:
        nodes = load_nodes(config_path)
    except ValueError as exc:
        print(f"EROR: {exc}")
        return 1
    nodes = unique_nodes(nodes + args.node)
    exit_code = run_check(
        nodes,
        config_path,
        max(1.0, args.timeout),
        network_test_enabled=not args.no_network_test,
        latency_samples=args.latency_samples,
    )

    if not args.no_pause and sys.stdin.isatty():
        try:
            input("\nTekan Enter untuk menutup...")
        except (EOFError, KeyboardInterrupt):
            pass
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
