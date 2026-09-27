import argparse
import ctypes
import json
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from backend_selector import BACKEND_CHOICES, runtime_dir, select_backend


DEFAULT_NODE_PORT = 50052
DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 1234
DEFAULT_CTX_SIZE = 2048
DEFAULT_REASONING = "auto"
LM_STUDIO_GENERIC_DEFAULTS = {
    "label": "LM Studio / llama.cpp umum",
    "temperature": 0.8,
    "top_k": 40,
    "top_p": 0.95,
    "min_p": 0.05,
    "repeat_penalty": 1.0,
    "reasoning_effort": "default",
}
LM_STUDIO_ENGINE_DEFAULTS = {
    "gpu_layers": "auto",
    "fit": "on",
    "load_mode": "auto",
    "flash_attention": "on",
    "batch_size": 512,
    "ubatch_size": 512,
    "parallel": 1,
    "threads": -1,
    "threads_batch": -1,
    "cache_type_k": "f16",
    "cache_type_v": "f16",
    "kv_offload": True,
    "continuous_batching": True,
    "cache_prompt": True,
    "cache_reuse": 0,
    "timeout": 3600,
    "max_output_tokens": -1,
    "seed": -1,
    "reasoning_budget": -1,
    "jinja": True,
    "reasoning_format": "auto",
    "structured_tool_calls": True,
    "typical_p": 1.0,
    "repeat_last_n": 64,
    "presence_penalty": 0.0,
    "frequency_penalty": 0.0,
    "dry_multiplier": 0.0,
    "dry_base": 1.75,
    "dry_allowed_length": 2,
    "dry_penalty_last_n": 64,
    "dynatemp_range": 0.0,
    "dynatemp_exp": 1.0,
    "xtc_probability": 0.0,
    "xtc_threshold": 0.1,
    "mirostat": 0,
}
DEFAULT_MODELS_DIR = Path(r"D:\AI\models")
NODE_CONFIG_NAME = "server-nodes.json"
SPLIT_GGUF_PATTERN = re.compile(
    r"^(?P<prefix>.+)-(?P<part>\d+)-of-(?P<total>\d+)\.gguf$",
    re.IGNORECASE,
)
class IoCounters(ctypes.Structure):
    _fields_ = [
        ("read_operations", ctypes.c_ulonglong),
        ("write_operations", ctypes.c_ulonglong),
        ("other_operations", ctypes.c_ulonglong),
        ("read_bytes", ctypes.c_ulonglong),
        ("write_bytes", ctypes.c_ulonglong),
        ("other_bytes", ctypes.c_ulonglong),
    ]


class ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("page_fault_count", ctypes.c_ulong),
        ("peak_working_set_size", ctypes.c_size_t),
        ("working_set_size", ctypes.c_size_t),
        ("quota_peak_paged_pool_usage", ctypes.c_size_t),
        ("quota_paged_pool_usage", ctypes.c_size_t),
        ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
        ("quota_non_paged_pool_usage", ctypes.c_size_t),
        ("pagefile_usage", ctypes.c_size_t),
        ("peak_pagefile_usage", ctypes.c_size_t),
        ("private_usage", ctypes.c_size_t),
    ]


def process_read_bytes(process_id):
    """Jumlah byte yang sudah dibaca proses Windows, atau None bila tidak tersedia."""
    if sys.platform != "win32":
        return None

    process_query_limited_information = 0x1000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(
        process_query_limited_information, False, process_id
    )
    if not handle:
        return None
    try:
        counters = IoCounters()
        if not kernel32.GetProcessIoCounters(handle, ctypes.byref(counters)):
            return None
        return counters.read_bytes
    finally:
        kernel32.CloseHandle(handle)


def process_memory_bytes(process_id):
    """Kembalikan working set dan private memory proses Windows."""
    if sys.platform != "win32":
        return None, None

    process_query_limited_information = 0x1000
    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    handle = kernel32.OpenProcess(
        process_query_limited_information, False, process_id
    )
    if not handle:
        return None, None
    try:
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        ):
            return None, None
        return counters.working_set_size, counters.private_usage
    finally:
        kernel32.CloseHandle(handle)


def calculate_load_percent(current_bytes, baseline_bytes, model_size):
    if current_bytes is None or baseline_bytes is None or model_size <= 0:
        return None, 0
    loaded_bytes = max(0, current_bytes - baseline_bytes)
    percent = min(99, int(loaded_bytes * 100 / model_size))
    return percent, loaded_bytes


def calculate_load_estimate(
    current_read,
    baseline_read,
    current_working_set,
    baseline_working_set,
    model_size,
    previous_bytes=0,
):
    """Gabungkan I/O biasa dan pertumbuhan RAM untuk load normal maupun mmap."""
    candidates = [max(0, previous_bytes)]
    source = "aktivitas"
    if current_read is not None and baseline_read is not None:
        read_bytes = max(0, current_read - baseline_read)
        candidates.append(read_bytes)
        if read_bytes >= max(candidates):
            source = "disk"
    if current_working_set is not None and baseline_working_set is not None:
        memory_bytes = max(0, current_working_set - baseline_working_set)
        candidates.append(memory_bytes)
        if memory_bytes >= max(candidates):
            source = "RAM/mmap"

    estimated_bytes = max(candidates)
    if model_size <= 0:
        return None, estimated_bytes, source
    percent = min(99, int(estimated_bytes * 100 / model_size))
    return percent, estimated_bytes, source


def format_elapsed(seconds):
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def update_load_stage(progress_state, line):
    """Ambil fase pemuatan dari log llama.cpp yang tersedia."""
    lowered = line.casefold()
    if "load_model: loading model" in lowered:
        progress_state["stage"] = "membaca metadata model"
    elif "load_tensors" in lowered or "offloading" in lowered:
        progress_state["stage"] = "memindahkan tensor ke GPU/RPC"
    elif "graph_reserve" in lowered or "compute buffer" in lowered:
        progress_state["stage"] = "mengalokasikan compute buffer"
    elif "llama threadpool init" in lowered:
        progress_state["stage"] = "menyiapkan thread CPU"
    elif "initializing, n_slots" in lowered:
        progress_state["stage"] = "menyiapkan konteks dan slot"


def monitor_model_progress(
    process,
    model_size,
    model_loaded,
    stop_monitor,
    progress_state,
):
    """Tampilkan progres hidup untuk I/O biasa, mmap, dan transfer RPC."""
    baseline_read = process_read_bytes(process.pid)
    baseline_working_set, _ = process_memory_bytes(process.pid)
    start_time = time.monotonic()
    last_estimated_bytes = 0
    last_activity_time = start_time
    spinner = "|/-\\"
    spinner_index = 0

    print(
        "[PROGRES LOAD]   0% | 00:00 | memulai llama.cpp ...",
        flush=True,
    )

    while not stop_monitor.wait(5):
        if model_loaded.is_set():
            print("[PROGRES LOAD] 100% - model berhasil dimuat.", flush=True)
            return
        if process.poll() is not None:
            break

        current_read = process_read_bytes(process.pid)
        working_set, private_memory = process_memory_bytes(process.pid)
        percent, estimated_bytes, source = calculate_load_estimate(
            current_read,
            baseline_read,
            working_set,
            baseline_working_set,
            model_size,
            last_estimated_bytes,
        )
        now = time.monotonic()
        if estimated_bytes > last_estimated_bytes + (8 * 1024 * 1024):
            last_activity_time = now
        last_estimated_bytes = max(last_estimated_bytes, estimated_bytes)

        elapsed = format_elapsed(now - start_time)
        ram_gb = (working_set or 0) / (1024 ** 3)
        private_gb = (private_memory or 0) / (1024 ** 3)
        stage = progress_state.get("stage", "memuat model")
        if progress_state.get("rpc") and now - start_time >= 10:
            if "metadata" in stage or stage == "memuat model":
                stage = "penyesuaian GPU otomatis / transfer ke RPC node"
        elif now - start_time >= 10 and ("metadata" in stage or stage == "memuat model"):
            stage = "penyesuaian GPU otomatis / alokasi RAM dan VRAM"
        if now - last_activity_time >= 20:
            stage += " (menunggu proses internal)"

        marker = spinner[spinner_index % len(spinner)]
        spinner_index += 1
        if percent is None:
            percent_text = "  ?%"
            amount_text = ""
        else:
            percent_text = f"~{percent:2d}%"
            amount_text = (
                f" | {min(last_estimated_bytes, model_size) / (1024 ** 3):.2f}/"
                f"{model_size / (1024 ** 3):.2f} GB {source}"
            )
        print(
            f"[PROGRES LOAD] {marker} {percent_text} | {elapsed}{amount_text} "
            f"| RAM {ram_gb:.2f} GB (private {private_gb:.2f} GB) | {stage}",
            flush=True,
        )

    if model_loaded.is_set():
        print("[PROGRES LOAD] 100% - model berhasil dimuat.", flush=True)


def application_dir():
    """Folder EXE saat dibundel, atau folder source saat dijalankan via Python."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def node_config_path():
    return application_dir() / NODE_CONFIG_NAME


def default_nodes():
    return []


def node_endpoint(node):
    host = node["host"]
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{host}:{node['port']}"


def parse_node(value, default_port=DEFAULT_NODE_PORT):
    """Ubah alamat host, host:port, atau [IPv6]:port menjadi data node."""
    value = value.strip()
    if not value:
        raise ValueError("alamat node tidak boleh kosong")

    host = value
    port = default_port
    if value.startswith("["):
        closing = value.find("]")
        if closing < 0:
            raise ValueError("format alamat IPv6 tidak valid")
        host = value[1:closing]
        remainder = value[closing + 1:]
        if remainder:
            if not remainder.startswith(":"):
                raise ValueError("format alamat node tidak valid")
            port = int(remainder[1:])
    elif value.count(":") == 1:
        possible_host, possible_port = value.rsplit(":", 1)
        if possible_port:
            host = possible_host
            port = int(possible_port)

    host = host.strip()
    if not host:
        raise ValueError("alamat node tidak boleh kosong")
    if not 1 <= port <= 65535:
        raise ValueError("port node harus antara 1 sampai 65535")
    return {"host": host, "port": port}


def unique_nodes(nodes):
    result = []
    seen = set()
    for node in nodes:
        key = (node["host"].casefold(), node["port"])
        if key not in seen:
            result.append(node)
            seen.add(key)
    return result


def load_nodes(path=None):
    path = path or node_config_path()
    if not path.is_file():
        return default_nodes()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        nodes = []
        for item in data.get("nodes", []):
            host = str(item["host"]).strip()
            port = int(item["port"])
            address = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
            nodes.append(parse_node(address))
        return unique_nodes(nodes)
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        json.JSONDecodeError,
    ) as exc:
        print(f"PERINGATAN: konfigurasi node tidak dapat dibaca: {exc}")
    return default_nodes()


def save_nodes(nodes, path=None):
    path = path or node_config_path()
    payload = {"nodes": unique_nodes(nodes)}
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def show_nodes(nodes):
    print("Node tersimpan:")
    if not nodes:
        print("  (belum ada node)")
        return
    for index, node in enumerate(nodes, start=1):
        print(f"  {index}. {node_endpoint(node)}")


def add_node_interactively(nodes, path=None):
    host = input("IP/hostname node baru (kosong untuk batal): ").strip()
    if not host:
        print("Tambah node dibatalkan.")
        return nodes

    port_value = input(f"Port node [{DEFAULT_NODE_PORT}]: ").strip()
    try:
        port = int(port_value) if port_value else DEFAULT_NODE_PORT
        node = parse_node(host, port)
    except ValueError as exc:
        print(f"Eror: {exc}.")
        return nodes

    updated = unique_nodes([*nodes, node])
    if len(updated) == len(nodes):
        print(f"Node {node_endpoint(node)} sudah ada.")
        return nodes

    try:
        save_nodes(updated, path)
    except OSError as exc:
        print(f"Eror menyimpan daftar node: {exc}")
        return nodes

    connected, error = wait_for_rpc(node["host"], node["port"], timeout=2)
    status = "ONLINE" if connected else f"tersimpan, tetapi sedang OFFLINE ({error})"
    print(f"Node {node_endpoint(node)} berhasil ditambahkan: {status}.")
    return updated


def remove_node_interactively(nodes, path=None):
    if not nodes:
        print("Tidak ada node yang dapat dihapus.")
        return nodes

    show_nodes(nodes)
    value = input("Nomor node yang akan dihapus (kosong untuk batal): ").strip()
    if not value:
        print("Hapus node dibatalkan.")
        return nodes

    try:
        index = int(value) - 1
    except ValueError:
        print("Eror: nomor node harus berupa angka.")
        return nodes
    if not 0 <= index < len(nodes):
        print("Eror: nomor node tidak ditemukan.")
        return nodes

    selected = nodes[index]
    endpoint = node_endpoint(selected)
    confirmation = input(f"Yakin hapus {endpoint}? [y/N]: ").strip().casefold()
    if confirmation not in ("y", "ya"):
        print("Hapus node dibatalkan.")
        return nodes

    updated = [node for position, node in enumerate(nodes) if position != index]
    try:
        save_nodes(updated, path)
    except OSError as exc:
        print(f"Eror menyimpan daftar node: {exc}")
        return nodes

    print(f"Node {endpoint} berhasil dihapus.")
    return updated


def interactive_menu(nodes, path=None):
    while True:
        print("\n" + "=" * 64)
        print("LLAMA-SERVER + BANYAK RPC NODE")
        print("=" * 64)
        show_nodes(nodes)
        print("\n1. Mulai")
        print("2. Tambah Node")
        print("3. Hapus Node")
        print("0. Keluar")
        choice = input("Pilih menu [1]: ").strip() or "1"
        if choice == "1":
            return nodes
        if choice == "2":
            nodes = add_node_interactively(nodes, path)
            continue
        if choice == "3":
            nodes = remove_node_interactively(nodes, path)
            continue
        if choice == "0":
            return None
        print("Eror: pilih 1, 2, 3, atau 0.")


def choose_nodes_for_session(nodes):
    """Pilih perangkat untuk sesi ini tanpa mengubah node yang tersimpan."""
    if not nodes:
        print("\nBelum ada NODE tersimpan; memakai GPU SERVER saja.")
        return []

    while True:
        print("\nPenggunaan perangkat:")
        print("  1. GPU SERVER saja - paling cepat bila model muat")
        print("  2. SERVER + semua NODE - kapasitas terbesar")
        print("  3. SERVER + pilih NODE - kurangi NODE lambat")
        choice = input("Pilih perangkat [2]: ").strip() or "2"
        if choice == "1":
            return []
        if choice == "2":
            return list(nodes)
        if choice == "3":
            show_nodes(nodes)
            value = input("Nomor NODE, pisahkan koma (contoh 1,2): ").strip()
            try:
                indexes = [int(item.strip()) - 1 for item in value.split(",")]
            except ValueError:
                indexes = []
            if indexes and all(0 <= index < len(nodes) for index in indexes):
                return unique_nodes([nodes[index] for index in indexes])
            print("Eror: masukkan nomor NODE yang valid.")
            continue
        print("Eror: pilih 1, 2, atau 3.")


def wait_for_rpc(host, port, timeout=5):
    """Pastikan endpoint RPC dapat dijangkau sebelum model dimuat."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, None
    except OSError as exc:
        return False, exc


def resolve_context_size(cli_value):
    """Ambil panjang konteks dari CLI atau tanyakan secara interaktif."""
    if cli_value is not None:
        if cli_value <= 0:
            raise ValueError("panjang konteks harus lebih besar dari 0")
        return cli_value

    while True:
        value = input(
            f"Panjang konteks AI dalam token [{DEFAULT_CTX_SIZE}] "
            "(contoh 2048, 4096, 8192, 16384): "
        ).strip()
        if not value:
            return DEFAULT_CTX_SIZE
        try:
            context_size = int(value)
            if context_size <= 0:
                raise ValueError
            return context_size
        except ValueError:
            print("Eror: panjang konteks harus berupa angka lebih besar dari 0.")


def resolve_reasoning(cli_value):
    """Ambil pilihan Think dari CLI atau tanyakan secara interaktif."""
    if cli_value is not None:
        return cli_value

    while True:
        print("\nMode Think/Reasoning:")
        print("  1. AUTO - ikuti kemampuan/template model (disarankan)")
        print("  2. ON   - AI berpikir lebih dahulu; jawaban bisa lebih lambat")
        print("  3. OFF  - langsung menjawab; lebih cepat")
        value = input("Pilih Think [1/AUTO]: ").strip().casefold()
        if not value or value in ("1", "auto", "otomatis"):
            return "auto"
        if value in ("2", "on", "hidup", "ya"):
            return "on"
        if value in ("3", "off", "mati", "tidak"):
            return "off"
        print("Eror: pilih 1/AUTO, 2/ON, atau 3/OFF.")


def prompt_advanced_number(label, current, number_type, validator, requirement):
    """Tanyakan angka lanjutan; Enter selalu mempertahankan nilai saat ini."""
    while True:
        value = input(f"{label} [{current}]: ").strip()
        if not value:
            return current
        try:
            normalized = value.replace(",", ".") if number_type is float else value
            result = number_type(normalized)
            if not validator(result):
                raise ValueError
            return result
        except ValueError:
            print(f"Eror: {label} harus {requirement}.")


def prompt_advanced_choice(label, current, choices):
    """Tanyakan pilihan teks lanjutan dengan validasi sederhana."""
    allowed = {choice.casefold(): choice for choice in choices}
    while True:
        value = input(
            f"{label} [{current}] ({'/'.join(choices)}): "
        ).strip().casefold()
        if not value:
            return current
        if value in allowed:
            return allowed[value]
        print(f"Eror: pilih salah satu: {', '.join(choices)}.")


def prompt_advanced_bool(label, current):
    value = prompt_advanced_choice(label, "on" if current else "off", ("on", "off"))
    return value == "on"


def configure_sampling_settings(sampling, engine):
    print("\n--- SAMPLING ---")
    sampling["temperature"] = prompt_advanced_number(
        "Temperature", sampling["temperature"], float, lambda value: value >= 0, "angka >= 0"
    )
    sampling["top_k"] = prompt_advanced_number(
        "Top-K", sampling["top_k"], int, lambda value: value >= 0, "bilangan bulat >= 0"
    )
    sampling["top_p"] = prompt_advanced_number(
        "Top-P", sampling["top_p"], float, lambda value: 0 <= value <= 1, "angka 0 sampai 1"
    )
    sampling["min_p"] = prompt_advanced_number(
        "Min-P", sampling["min_p"], float, lambda value: 0 <= value <= 1, "angka 0 sampai 1"
    )
    engine["typical_p"] = prompt_advanced_number(
        "Typical-P", engine["typical_p"], float, lambda value: 0 <= value <= 1, "angka 0 sampai 1"
    )
    sampling["repeat_penalty"] = prompt_advanced_number(
        "Repeat penalty", sampling["repeat_penalty"], float, lambda value: value > 0, "angka > 0"
    )
    engine["repeat_last_n"] = prompt_advanced_number(
        "Repeat last N", engine["repeat_last_n"], int, lambda value: value >= -1, "bilangan bulat >= -1"
    )
    engine["presence_penalty"] = prompt_advanced_number(
        "Presence penalty", engine["presence_penalty"], float, lambda value: -2 <= value <= 2, "angka -2 sampai 2"
    )
    engine["frequency_penalty"] = prompt_advanced_number(
        "Frequency penalty", engine["frequency_penalty"], float, lambda value: -2 <= value <= 2, "angka -2 sampai 2"
    )
    engine["dry_multiplier"] = prompt_advanced_number(
        "DRY multiplier", engine["dry_multiplier"], float, lambda value: value >= 0, "angka >= 0"
    )
    engine["dry_base"] = prompt_advanced_number(
        "DRY base", engine["dry_base"], float, lambda value: value > 0, "angka > 0"
    )
    engine["dry_allowed_length"] = prompt_advanced_number(
        "DRY allowed length", engine["dry_allowed_length"], int, lambda value: value >= 0, "bilangan bulat >= 0"
    )
    engine["dry_penalty_last_n"] = prompt_advanced_number(
        "DRY penalty last N", engine["dry_penalty_last_n"], int, lambda value: value >= -1, "bilangan bulat >= -1"
    )
    engine["dynatemp_range"] = prompt_advanced_number(
        "Dynamic temperature range", engine["dynatemp_range"], float, lambda value: value >= 0, "angka >= 0"
    )
    engine["dynatemp_exp"] = prompt_advanced_number(
        "Dynamic temperature exponent", engine["dynatemp_exp"], float, lambda value: value > 0, "angka > 0"
    )
    engine["xtc_probability"] = prompt_advanced_number(
        "XTC probability", engine["xtc_probability"], float, lambda value: 0 <= value <= 1, "angka 0 sampai 1"
    )
    engine["xtc_threshold"] = prompt_advanced_number(
        "XTC threshold", engine["xtc_threshold"], float, lambda value: 0 <= value <= 1, "angka 0 sampai 1"
    )
    engine["mirostat"] = prompt_advanced_number(
        "Mirostat mode", engine["mirostat"], int, lambda value: value in (0, 1, 2), "0, 1, atau 2"
    )


def configure_output_settings(sampling, engine):
    print("\n--- OUTPUT DAN REASONING ---")
    print("Pengaturan kompatibilitas Cline menjaga tools sebagai tool_calls terstruktur.")
    engine["max_output_tokens"] = prompt_advanced_number(
        "Max output tokens (-1=tak terbatas)", engine["max_output_tokens"], int,
        lambda value: value == -1 or value > 0, "-1 atau bilangan bulat > 0"
    )
    engine["seed"] = prompt_advanced_number(
        "Seed (-1=acak)", engine["seed"], int, lambda value: value >= -1, "bilangan bulat >= -1"
    )
    sampling["reasoning_effort"] = prompt_advanced_choice(
        "Reasoning effort", sampling["reasoning_effort"],
        ("default", "minimal", "low", "medium", "high", "xhigh", "max")
    )
    engine["reasoning_budget"] = prompt_advanced_number(
        "Think budget (-1=tak terbatas, 0=langsung selesai)", engine["reasoning_budget"], int,
        lambda value: value >= -1, "bilangan bulat >= -1"
    )
    engine["jinja"] = prompt_advanced_bool(
        "Jinja chat template / tool calling", engine["jinja"]
    )
    engine["reasoning_format"] = prompt_advanced_choice(
        "Reasoning output format", engine["reasoning_format"],
        ("auto", "none", "deepseek", "deepseek-legacy")
    )
    engine["structured_tool_calls"] = prompt_advanced_bool(
        "Structured tool_calls untuk Cline", engine["structured_tool_calls"]
    )


def configure_performance_settings(engine):
    print("\n--- PERFORMA DAN MEMORY ---")
    while True:
        value = input(
            f"GPU layers [{engine['gpu_layers']}] (auto/all/angka >= 0): "
        ).strip().casefold()
        if not value:
            break
        if value in ("auto", "all") or (value.isdigit() and int(value) >= 0):
            engine["gpu_layers"] = value
            break
        print("Eror: isi auto, all, atau bilangan bulat >= 0.")
    engine["fit"] = prompt_advanced_choice("Fit ke memori perangkat", engine["fit"], ("on", "off"))
    engine["load_mode"] = prompt_advanced_choice(
        "Load mode", engine["load_mode"], ("auto", "none", "mmap", "mlock", "mmap+mlock")
    )
    engine["flash_attention"] = prompt_advanced_choice(
        "Flash Attention", engine["flash_attention"], ("on", "off", "auto")
    )
    kv_types = ("f32", "f16", "bf16", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1")
    engine["cache_type_k"] = prompt_advanced_choice("KV cache K", engine["cache_type_k"], kv_types)
    engine["cache_type_v"] = prompt_advanced_choice("KV cache V", engine["cache_type_v"], kv_types)
    engine["kv_offload"] = prompt_advanced_bool("KV cache offload ke GPU", engine["kv_offload"])
    engine["batch_size"] = prompt_advanced_number(
        "Batch size", engine["batch_size"], int, lambda value: value > 0, "bilangan bulat > 0"
    )
    engine["ubatch_size"] = prompt_advanced_number(
        "Micro-batch size", engine["ubatch_size"], int, lambda value: value > 0, "bilangan bulat > 0"
    )
    engine["parallel"] = prompt_advanced_number(
        "Parallel slot (-1=auto)", engine["parallel"], int,
        lambda value: value == -1 or value > 0, "-1 atau bilangan bulat > 0"
    )
    engine["threads"] = prompt_advanced_number(
        "CPU threads (-1=auto)", engine["threads"], int,
        lambda value: value == -1 or value > 0, "-1 atau bilangan bulat > 0"
    )
    engine["threads_batch"] = prompt_advanced_number(
        "CPU threads batch (-1=auto)", engine["threads_batch"], int,
        lambda value: value == -1 or value > 0, "-1 atau bilangan bulat > 0"
    )
    engine["continuous_batching"] = prompt_advanced_bool(
        "Continuous batching", engine["continuous_batching"]
    )
    engine["cache_prompt"] = prompt_advanced_bool("Prompt cache", engine["cache_prompt"])
    engine["cache_reuse"] = prompt_advanced_number(
        "Cache reuse", engine["cache_reuse"], int, lambda value: value >= 0, "bilangan bulat >= 0"
    )
    engine["timeout"] = prompt_advanced_number(
        "Timeout detik", engine["timeout"], int, lambda value: value >= 0, "bilangan bulat >= 0"
    )


def resolve_advanced_settings(model_path, offer_prompt, force=False):
    """Kembalikan default utuh, atau izinkan pengguna mengubah kategori tertentu."""
    sampling = lm_studio_defaults_for_model(model_path)
    engine = dict(LM_STUDIO_ENGINE_DEFAULTS)
    if not offer_prompt:
        return sampling, engine

    if not force:
        answer = input("\nUbah pengaturan lanjutan? [y/N]: ").strip().casefold()
        if answer not in ("y", "yes", "ya"):
            print("Pengaturan lanjutan: memakai semua nilai default.")
            return sampling, engine

    while True:
        print("\nPENGATURAN LANJUTAN (Enter pada nilai = pertahankan nilai saat ini)")
        print("  1. Sampling")
        print("  2. Output dan Reasoning")
        print("  3. Performa dan Memory")
        print("  4. Ubah semua kategori")
        print("  0. Selesai")
        choice = input("Pilih kategori [0]: ").strip() or "0"
        if choice == "0":
            return sampling, engine
        if choice in ("1", "4"):
            configure_sampling_settings(sampling, engine)
        if choice in ("2", "4"):
            configure_output_settings(sampling, engine)
        if choice in ("3", "4"):
            configure_performance_settings(engine)
        if choice not in ("1", "2", "3", "4"):
            print("Eror: pilih 0 sampai 4.")
        elif choice == "4":
            return sampling, engine


def is_selectable_gguf(path):
    """Pilih file model utama; abaikan mmproj dan shard kedua dan seterusnya."""
    if path.suffix.casefold() != ".gguf":
        return False
    if "mmproj" in path.name.casefold():
        return False
    split_match = SPLIT_GGUF_PATTERN.match(path.name)
    if split_match and int(split_match.group("part")) != 1:
        return False
    return True


def scan_models(models_dir):
    """Cari model GGUF secara rekursif dan urutkan berdasarkan nama."""
    try:
        models = [
            path
            for path in models_dir.rglob("*")
            if path.is_file() and is_selectable_gguf(path)
        ]
    except OSError as exc:
        raise ValueError(f"folder model gagal dipindai: {exc}") from exc
    return sorted(models, key=lambda path: (path.stem.casefold(), str(path).casefold()))


def model_total_size(model_path):
    """Hitung ukuran model, termasuk seluruh file bila GGUF terbagi menjadi shard."""
    split_match = SPLIT_GGUF_PATTERN.match(model_path.name)
    if not split_match:
        return model_path.stat().st_size

    prefix = split_match.group("prefix")
    total_parts = int(split_match.group("total"))
    digit_width = len(split_match.group("part"))
    total_width = len(split_match.group("total"))
    total_size = 0
    for part in range(1, total_parts + 1):
        shard = model_path.with_name(
            f"{prefix}-{part:0{digit_width}d}-of-"
            f"{total_parts:0{total_width}d}.gguf"
        )
        if shard.is_file():
            total_size += shard.stat().st_size
    return total_size or model_path.stat().st_size


def friendly_model_id(model_path):
    """Buat Model ID API pendek dari nama GGUF, tanpa path Windows."""
    name = model_path.name
    split_match = SPLIT_GGUF_PATTERN.match(name)
    if split_match:
        name = split_match.group("prefix")
    else:
        name = model_path.stem
    name = re.sub(r"\s+", "-", name.strip())
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name)
    name = re.sub(r"-{2,}", "-", name).strip("-._")
    return name or "local-model"


def lm_studio_defaults_for_model(model_path):
    """Gunakan satu fallback LM Studio/llama.cpp yang sama untuk semua model."""
    del model_path
    return dict(LM_STUDIO_GENERIC_DEFAULTS)


def format_model_size(size_bytes):
    return f"{size_bytes / (1024 ** 3):.2f} GB"


def choose_model_from_directory(models_dir):
    print(f"\nMemindai model GGUF di: {models_dir}")
    models = scan_models(models_dir)
    if not models:
        raise ValueError(f"tidak ada model .gguf di dalam {models_dir}")

    print(f"Ditemukan {len(models)} model AI:\n")
    for index, model in enumerate(models, 1):
        relative_parent = model.parent.relative_to(models_dir)
        location = str(relative_parent) if str(relative_parent) != "." else "(folder utama)"
        try:
            size_text = format_model_size(model_total_size(model))
        except OSError:
            size_text = "ukuran tidak tersedia"
        print(f"  {index:>3}. {friendly_model_id(model)}")
        print(f"       {size_text} | {location}")

    while True:
        value = input("\nPilih nomor model [1]: ").strip() or "1"
        try:
            selected_index = int(value) - 1
        except ValueError:
            selected_index = -1
        if 0 <= selected_index < len(models):
            return models[selected_index]
        print(f"Eror: pilih nomor 1 sampai {len(models)}.")


def resolve_model_path(model_value):
    """Terima folder models untuk dipindai, dengan kompatibilitas path GGUF lama."""
    if model_value:
        source = Path(model_value.strip().strip('"').strip("'")).expanduser()
    else:
        entered = input(f"Folder models [{DEFAULT_MODELS_DIR}]: ").strip()
        source = Path(entered.strip('"').strip("'")).expanduser() if entered else DEFAULT_MODELS_DIR

    if source.is_dir():
        return choose_model_from_directory(source)
    if source.is_file() and is_selectable_gguf(source):
        return source
    if source.suffix.casefold() == ".gguf":
        raise ValueError(f"file model tidak ditemukan: {source}")
    raise ValueError(f"folder models tidak ditemukan: {source}")


def build_server_command(
    server_exe,
    model_path,
    rpc_servers,
    api_host,
    api_port,
    context_size,
    reasoning,
    model_id,
    sampling_settings=None,
    engine_settings=None,
):
    sampling = (
        lm_studio_defaults_for_model(model_path)
        if sampling_settings is None
        else dict(sampling_settings)
    )
    engine = (
        dict(LM_STUDIO_ENGINE_DEFAULTS)
        if engine_settings is None
        else dict(engine_settings)
    )
    command = [
        str(server_exe),
        "-m", str(model_path),
        "--host", api_host,
        "--port", str(api_port),
        "--load-mode", engine["load_mode"],
        "--n-gpu-layers", engine["gpu_layers"],
        "--fit", engine["fit"],
        "--ctx-size", str(context_size),
        "--alias", model_id,
        "--jinja" if engine["jinja"] else "--no-jinja",
        "--reasoning-format", engine["reasoning_format"],
        "--no-skip-chat-parsing" if engine["structured_tool_calls"] else "--skip-chat-parsing",
        "--reasoning", reasoning,
        "--reasoning-effort", sampling["reasoning_effort"],
        "--reasoning-budget", str(engine["reasoning_budget"]),
        "--n-predict", str(engine["max_output_tokens"]),
        "--temperature", f"{sampling['temperature']:g}",
        "--top-k", str(sampling["top_k"]),
        "--top-p", f"{sampling['top_p']:g}",
        "--min-p", f"{sampling['min_p']:g}",
        "--typical-p", f"{engine['typical_p']:g}",
        "--repeat-last-n", str(engine["repeat_last_n"]),
        "--repeat-penalty", f"{sampling['repeat_penalty']:g}",
        "--presence-penalty", f"{engine['presence_penalty']:g}",
        "--frequency-penalty", f"{engine['frequency_penalty']:g}",
        "--dry-multiplier", f"{engine['dry_multiplier']:g}",
        "--dry-base", f"{engine['dry_base']:g}",
        "--dry-allowed-length", str(engine["dry_allowed_length"]),
        "--dry-penalty-last-n", str(engine["dry_penalty_last_n"]),
        "--dynatemp-range", f"{engine['dynatemp_range']:g}",
        "--dynatemp-exp", f"{engine['dynatemp_exp']:g}",
        "--xtc-probability", f"{engine['xtc_probability']:g}",
        "--xtc-threshold", f"{engine['xtc_threshold']:g}",
        "--mirostat", str(engine["mirostat"]),
        "--seed", str(engine["seed"]),
        "--parallel", str(engine["parallel"]),
        "--threads", str(engine["threads"]),
        "--threads-batch", str(engine["threads_batch"]),
        "--cont-batching" if engine["continuous_batching"] else "--no-cont-batching",
        "--flash-attn", engine["flash_attention"],
        "--cache-type-k", engine["cache_type_k"],
        "--cache-type-v", engine["cache_type_v"],
        "--kv-offload" if engine["kv_offload"] else "--no-kv-offload",
        "--batch-size", str(engine["batch_size"]),
        "--ubatch-size", str(engine["ubatch_size"]),
        "--cache-prompt" if engine["cache_prompt"] else "--no-cache-prompt",
        "--cache-reuse", str(engine["cache_reuse"]),
        "--timeout", str(engine["timeout"]),
    ]
    if rpc_servers:
        command[3:3] = ["--rpc", rpc_servers]
    if reasoning == "off":
        command.append("--no-reasoning-preserve")
    return command


def launch_llama_server(argv=None):
    parser = argparse.ArgumentParser(description="Llama server dengan node RPC")
    parser.add_argument(
        "model",
        nargs="?",
        help="Folder models untuk dipindai, atau path file GGUF",
    )
    parser.add_argument(
        "--node",
        action="append",
        help="Node host[:port]; dapat diulang atau dipisahkan koma",
    )
    parser.add_argument("--rpc-port", type=int, default=DEFAULT_NODE_PORT)
    parser.add_argument("--api-host", default=DEFAULT_API_HOST)
    parser.add_argument("--api-port", type=int, default=DEFAULT_API_PORT)
    parser.add_argument(
        "--ctx-size",
        type=int,
        help=f"Panjang konteks AI dalam token (default interaktif: {DEFAULT_CTX_SIZE})",
    )
    parser.add_argument(
        "--think",
        "--reasoning",
        dest="reasoning",
        choices=("auto", "on", "off"),
        help=f"Mode Think/Reasoning auto, on, atau off (default: {DEFAULT_REASONING})",
    )
    parser.add_argument(
        "--model-id",
        help="Nama model yang ditampilkan oleh API; default memakai nama file GGUF",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Gunakan GPU SERVER saja tanpa NODE RPC",
    )
    parser.add_argument(
        "--backend",
        choices=BACKEND_CHOICES,
        default="auto",
        help="Pilih backend; default mendeteksi CUDA, Vulkan, lalu CPU",
    )
    parser.add_argument(
        "--advanced",
        action="store_true",
        help="Buka menu interaktif untuk mengubah pengaturan lanjutan",
    )
    raw_args = sys.argv[1:] if argv is None else argv
    args = parser.parse_args(raw_args)

    if args.local_only and args.node:
        print("Eror: --local-only tidak dapat digabungkan dengan --node.")
        return 1

    if args.node:
        try:
            nodes = unique_nodes([
                parse_node(value, args.rpc_port)
                for group in args.node
                for value in group.split(",")
            ])
        except ValueError as exc:
            print(f"Eror: alamat node tidak valid: {exc}.")
            return 1
    else:
        nodes = load_nodes()

    if not raw_args:
        nodes = interactive_menu(nodes)
        if nodes is None:
            print("Program ditutup.")
            return 0
        nodes = choose_nodes_for_session(nodes)
    elif args.local_only:
        nodes = []
    else:
        print("=" * 64)
        print("LLAMA-SERVER + BANYAK RPC NODE")
        print("=" * 64)

    try:
        model_path = resolve_model_path(args.model)
    except (OSError, ValueError) as exc:
        print(f"Eror: {exc}.")
        return 1
    model_id = args.model_id.strip() if args.model_id else friendly_model_id(model_path)
    if not model_id:
        print("Eror: Model ID tidak boleh kosong.")
        return 1

    try:
        context_size = resolve_context_size(args.ctx_size)
        reasoning = resolve_reasoning(args.reasoning)
        sampling, engine = resolve_advanced_settings(
            model_path,
            offer_prompt=not raw_args or args.advanced,
            force=args.advanced,
        )
    except ValueError as exc:
        print(f"Eror pengaturan: {exc}.")
        return 1

    try:
        selected_backend, backend_detail = select_backend(args.backend)
    except (RuntimeError, ValueError) as exc:
        print(f"Eror memilih backend: {exc}")
        return 1

    base_dir = runtime_dir(selected_backend)
    server_exe = base_dir / "llama-server.exe"
    if not server_exe.is_file():
        print(f"Eror: {server_exe} tidak ditemukan.")
        return 1

    online_nodes = []
    print("Memeriksa semua node RPC ..." if nodes else "Mode lokal: GPU SERVER saja.")
    for node in nodes:
        endpoint = node_endpoint(node)
        connected, error = wait_for_rpc(node["host"], node["port"])
        if connected:
            online_nodes.append(node)
            print(f"  [ONLINE]  {endpoint}")
        else:
            print(f"  [OFFLINE] {endpoint} - dilewati ({error})")

    if nodes and not online_nodes:
        print("Eror: tidak ada node RPC yang dapat dijangkau.")
        print("Jalankan NODE.exe dan pastikan firewall TCP pada port node terbuka.")
        return 1

    rpc_servers = ",".join(node_endpoint(node) for node in online_nodes)
    command = build_server_command(
        server_exe,
        model_path,
        rpc_servers,
        args.api_host,
        args.api_port,
        context_size,
        reasoning,
        model_id,
        sampling,
        engine,
    )

    if nodes:
        print(f"Node RPC tersambung: {len(online_nodes)} dari {len(nodes)}.")
    else:
        print("Node RPC tersambung: 0 (GPU SERVER saja).")
    print(f"Backend lokal: {selected_backend.upper()} ({backend_detail})")
    print(f"Model : {model_path.name}")
    print(f"Model ID: {model_id}")
    print(f"Konteks: {context_size:,} token")
    print(f"Think : {reasoning.upper()}")
    threads_text = "AUTO" if engine["threads"] == -1 else str(engine["threads"])
    threads_batch_text = (
        "AUTO" if engine["threads_batch"] == -1 else str(engine["threads_batch"])
    )
    print(
        f"Pemuatan: GPU={str(engine['gpu_layers']).upper()}, "
        f"Fit={engine['fit'].upper()}, Load={engine['load_mode'].upper()}, "
        f"CPU Threads={threads_text}/{threads_batch_text}"
    )
    print(
        f"Sampling: {sampling['label']} | temp={sampling['temperature']:g}, "
        f"top-k={sampling['top_k']}, top-p={sampling['top_p']:g}, "
        f"min-p={sampling['min_p']:g}, repeat={sampling['repeat_penalty']:g}"
    )
    print(
        f"Performa: Flash={engine['flash_attention'].upper()}, "
        f"KV={engine['cache_type_k'].upper()}/{engine['cache_type_v'].upper()} "
        f"({'GPU' if engine['kv_offload'] else 'CPU'}), "
        f"batch={engine['batch_size']}, ubatch={engine['ubatch_size']}, "
        f"parallel={engine['parallel']}, continuous-batching="
        f"{'ON' if engine['continuous_batching'] else 'OFF'}"
    )
    print(
        f"Cache: prompt={'ON' if engine['cache_prompt'] else 'OFF'}, "
        f"reuse={engine['cache_reuse']} | Output="
        f"{'tak terbatas' if engine['max_output_tokens'] == -1 else engine['max_output_tokens']} | "
        f"Seed={'acak' if engine['seed'] == -1 else engine['seed']} | "
        f"Timeout={engine['timeout']} detik"
    )
    print(
        f"Sampler lanjutan: typical={engine['typical_p']:g}, "
        f"XTC={engine['xtc_probability']:g}/{engine['xtc_threshold']:g}, "
        f"Dynamic Temp={engine['dynatemp_range']:g}/{engine['dynatemp_exp']:g}, "
        f"Mirostat={engine['mirostat']}, DRY={engine['dry_multiplier']:g}, "
        f"presence/frequency={engine['presence_penalty']:g}/"
        f"{engine['frequency_penalty']:g}"
    )
    print(
        f"Reasoning Effort: {sampling['reasoning_effort'].upper()} | "
        f"Think Budget: {engine['reasoning_budget']}"
    )
    print(
        f"Mode Agent/Cline: Jinja={'ON' if engine['jinja'] else 'OFF'}, "
        f"tool_calls={'TERSTRUKTUR' if engine['structured_tool_calls'] else 'TEKS BIASA'}, "
        f"reasoning-format={engine['reasoning_format'].upper()}"
    )
    print("Tools/Skills: dikirim dan dijalankan oleh Cline (tools internal SERVER tetap OFF).")
    print("Parameter dari aplikasi klien tetap dapat menimpa default sampling.")
    print(f"Node  : {rpc_servers or '(tanpa NODE)'}")
    print(f"API   : http://{args.api_host}:{args.api_port}")
    print(f"Cline : http://{args.api_host}:{args.api_port}/v1 | Model ID: {model_id}")
    print("Tekan Ctrl+C untuk menghentikan server.\n")

    model_loaded = threading.Event()
    stop_monitor = threading.Event()
    progress_state = {
        "stage": "memuat model",
        "rpc": bool(rpc_servers),
    }
    process = None
    progress_thread = None
    try:
        process = subprocess.Popen(
            command,
            cwd=base_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        progress_thread = threading.Thread(
            target=monitor_model_progress,
            args=(
                process,
                model_total_size(model_path),
                model_loaded,
                stop_monitor,
                progress_state,
            ),
            daemon=True,
        )
        progress_thread.start()

        for line in process.stdout:
            print(line, end="", flush=True)
            update_load_stage(progress_state, line)
            if "model loaded" in line.lower():
                model_loaded.set()
        return process.wait()
    except KeyboardInterrupt:
        if process and process.poll() is None:
            process.terminate()
        print("\nServer dihentikan.")
        return 0
    except OSError as exc:
        print(f"Eror menjalankan llama-server: {exc}")
        return 1
    finally:
        stop_monitor.set()
        if progress_thread:
            progress_thread.join(timeout=2)


if __name__ == "__main__":
    sys.exit(launch_llama_server())
