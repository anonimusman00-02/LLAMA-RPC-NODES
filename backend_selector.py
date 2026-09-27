import re
import subprocess
import sys
from pathlib import Path


BACKEND_CHOICES = ("auto", "cuda", "vulkan", "cpu")


def project_dir():
    return Path(__file__).resolve().parent


def runtime_dir(backend):
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        return Path(bundled_root) / "backends" / backend
    if backend == "cuda":
        return project_dir()
    return project_dir() / "runtime" / backend


def _probe_output(backend):
    directory = runtime_dir(backend)
    probe_exe = directory / "ggml-rpc-server.exe"
    if not probe_exe.is_file():
        return False, f"runtime {backend} tidak ditemukan: {probe_exe}"

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            [str(probe_exe), "--help"],
            cwd=directory,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
            creationflags=creation_flags,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    return True, result.stdout + "\n" + result.stderr


def probe_backend(backend):
    ok, output = _probe_output(backend)
    if not ok:
        return False, output

    if backend == "cuda":
        capabilities = [
            float(value)
            for value in re.findall(r"compute capability\s+(\d+(?:\.\d+)?)", output)
        ]
        compatible = [value for value in capabilities if value >= 7.5]
        if compatible:
            values = ", ".join(f"{value:.1f}" for value in compatible)
            return True, f"CUDA compute capability {values}"
        if capabilities:
            values = ", ".join(f"{value:.1f}" for value in capabilities)
            return False, f"GPU CUDA lama ({values}); gunakan Vulkan"
        return False, "GPU CUDA 13 yang kompatibel tidak terdeteksi"

    if backend == "vulkan":
        match = re.search(r"Found\s+(\d+)\s+Vulkan devices", output, re.IGNORECASE)
        if match and int(match.group(1)) > 0:
            return True, f"{match.group(1)} perangkat Vulkan"
        return False, "perangkat Vulkan tidak terdeteksi"

    if "loaded CPU backend" in output:
        return True, "backend CPU"
    return False, "backend CPU gagal dimuat"


def select_backend(requested="auto"):
    requested = requested.lower()
    if requested not in BACKEND_CHOICES:
        raise ValueError(f"Backend tidak dikenal: {requested}")

    candidates = ("cuda", "vulkan", "cpu") if requested == "auto" else (requested,)
    failures = []
    for backend in candidates:
        ok, detail = probe_backend(backend)
        if ok:
            return backend, detail
        failures.append(f"{backend}: {detail}")

    raise RuntimeError("; ".join(failures))
