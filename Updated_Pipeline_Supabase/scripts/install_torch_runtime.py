"""
Select and install the local PyTorch runtime for this workstation.

The cloud/Docker path stays CPU-only. Local Windows/demo startup also enforces
CPU Torch; Ollama owns GPU acceleration for local report generation.
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS_PATH = ROOT / "requirements.txt"
DEFAULT_CPU_INDEX_URL = "https://download.pytorch.org/whl/cpu"


def _run(cmd: List[str], *, timeout: int = 12) -> Tuple[int, str]:
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return completed.returncode, (completed.stdout or "") + (completed.stderr or "")
    except Exception as exc:
        return 1, str(exc)


def _read_pinned_packages() -> List[str]:
    pins: Dict[str, str] = {}
    try:
        lines = REQUIREMENTS_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        lines = []

    for line in lines:
        clean = line.strip()
        if not clean or clean.startswith("#"):
            continue
        match = re.match(r"^(torch|torchvision|torchaudio)==([^\s#]+)", clean, flags=re.IGNORECASE)
        if match:
            pins[match.group(1).lower()] = f"{match.group(1).lower()}=={match.group(2)}"

    packages = []
    for name in ("torch", "torchvision", "torchaudio"):
        if name in pins:
            packages.append(pins[name])

    return packages or ["torch", "torchvision"]


def _torch_state() -> Dict[str, object]:
    state: Dict[str, object] = {
        "installed": False,
        "torch_version": None,
        "torch_cuda_version": None,
        "cuda_available": False,
        "cuda_device_count": 0,
        "cuda_device_name": None,
        "error": None,
    }
    try:
        import torch

        state["installed"] = True
        state["torch_version"] = getattr(torch, "__version__", None)
        state["torch_cuda_version"] = getattr(getattr(torch, "version", None), "cuda", None)
        cuda_available = bool(torch.cuda.is_available())
        state["cuda_available"] = cuda_available
        if cuda_available:
            count = int(torch.cuda.device_count())
            state["cuda_device_count"] = count
            if count > 0:
                state["cuda_device_name"] = torch.cuda.get_device_name(0)
    except Exception as exc:
        state["error"] = str(exc)
    return state


def _target_runtime(mode: str) -> Tuple[str, bool, str]:
    normalized = str(mode or "auto").strip().lower()
    if normalized in ("skip", "none", "off"):
        return "skip", False, "Torch runtime install disabled"
    if normalized in ("cpu", "cpu-only"):
        return "cpu", False, "CPU runtime requested"
    if normalized in ("auto", "cuda", "gpu", "nvidia"):
        return "cpu", False, "CUDA Torch install is disabled; using CPU runtime"

    return "cpu", False, f"Unsupported Torch mode {normalized!r}; using CPU runtime"


def _needs_install(target: str, state: Dict[str, object]) -> Tuple[bool, str]:
    if not state.get("installed"):
        return True, "torch is not installed"

    has_cuda_build = bool(state.get("torch_cuda_version"))
    cuda_available = bool(state.get("cuda_available"))

    if target == "cpu":
        if has_cuda_build:
            return True, "CPU runtime requested but CUDA Torch is installed"
        return False, "CPU runtime is acceptable"

    return False, "No runtime change needed"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Install the selected Torch runtime when needed")
    args = parser.parse_args()

    mode = os.getenv("CASM_TORCH_INSTALL_MODE", os.getenv("PYTORCH_INSTALL_MODE", "cpu"))
    target, _has_gpu, hardware_label = _target_runtime(mode)
    state = _torch_state()

    print("Torch runtime selector")
    print(f"  mode            : {mode}")
    print(f"  target          : {target}")
    print("  cuda_install    : disabled")
    if hardware_label:
        print(f"  hardware        : {hardware_label}")
    print(f"  installed_torch : {state.get('torch_version') or 'missing'}")
    print(f"  torch_cuda      : {state.get('torch_cuda_version') or 'none'}")
    print(f"  cuda_available  : {state.get('cuda_available')}")

    if target == "skip":
        return 0

    needed, reason = _needs_install(target, state)
    print(f"  action_needed   : {needed} ({reason})")
    if not needed:
        return 0

    if not args.apply:
        return 0

    packages = _read_pinned_packages()
    index_url = os.getenv("PYTORCH_CPU_INDEX_URL", DEFAULT_CPU_INDEX_URL)

    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--upgrade",
        "--force-reinstall",
        *packages,
        "--index-url",
        index_url,
    ]
    print(f"Installing {target} Torch runtime from {index_url}")
    result = subprocess.run(cmd, cwd=str(ROOT), check=False)
    if result.returncode != 0:
        print("WARN: Torch runtime install failed; existing runtime will be used.")
        return result.returncode

    after = _torch_state()
    print(f"  post_torch      : {after.get('torch_version') or 'missing'}")
    print(f"  post_torch_cuda : {after.get('torch_cuda_version') or 'none'}")
    print(f"  post_cuda_ok    : {after.get('cuda_available')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
