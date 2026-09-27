from pathlib import Path
import os


project = Path(r"D:\LLAMA RPC")
runtime_sources = {
    "cuda": project,
    "vulkan": project / "runtime" / "vulkan",
    "cpu": project / "runtime" / "cpu",
}

common_names = ["ggml.dll", "ggml-base.dll", "ggml-rpc.dll", "libomp.dll"]
cuda_names = ["ggml-cuda.dll", "cublas64_13.dll", "cublasLt64_13.dll", "cudart64_13.dll"]
vulkan_names = ["ggml-vulkan.dll"]

system32 = Path(os.environ["WINDIR"]) / "System32"
msvc_names = [
    "msvcp140.dll",
    "msvcp140_1.dll",
    "msvcp140_2.dll",
    "msvcp140_atomic_wait.dll",
    "msvcp140_codecvt_ids.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "vcruntime140_threads.dll",
]

binaries = []
for backend, source in runtime_sources.items():
    destination = f"backends/{backend}"
    names = common_names + sorted(path.name for path in source.glob("ggml-cpu-*.dll"))
    if backend == "cuda":
        names += cuda_names
    elif backend == "vulkan":
        names += vulkan_names
    names += ["ggml-rpc-server.exe"]
    binaries += [(str(source / name), destination) for name in names]
    binaries += [(str(system32 / name), destination) for name in msvc_names]

a = Analysis(
    [str(project / "node.py")],
    pathex=[str(project)],
    binaries=binaries,
    datas=[(str(project / "LICENSE-LLVM-OpenMP"), ".")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="LLAMA-RPC-NODE",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
