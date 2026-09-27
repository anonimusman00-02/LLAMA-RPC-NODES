from pathlib import Path
import os


project = Path(r"D:\LLAMA RPC")
runtime = project / "runtime" / "cpu"
destination = "check_runtime"

runtime_names = [
    "llama-server.exe",
    "llama-server-impl.dll",
    "llama-common.dll",
    "llama.dll",
    "mtmd.dll",
    "ggml.dll",
    "ggml-base.dll",
    "ggml-rpc.dll",
    "libomp.dll",
]
runtime_names += sorted(path.name for path in runtime.glob("ggml-cpu-*.dll"))

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

binaries = [(str(runtime / name), destination) for name in runtime_names]
binaries += [(str(system32 / name), destination) for name in msvc_names]

a = Analysis(
    [str(project / "CHECK.py")],
    pathex=[str(project)],
    binaries=binaries,
    datas=[(str(runtime / "LICENSE-LLVM-OpenMP"), destination)],
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
    name="CHECK",
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
