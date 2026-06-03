"""
Select and install the local PyTorch runtime for this workstation.

The cloud/Docker path stays CPU-only. Local Windows/demo startup also enforces
CPU Torch; Ollama owns GPU acceleration for local report generation.
"""
# Readability: Utility script: keep operational maintenance steps visible and repeatable.

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# Prepare root for the next step.
ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS_PATH = ROOT / "requirements.txt"
DEFAULT_CPU_INDEX_URL = "https://download.pytorch.org/whl/cpu"


# Section: run the run workflow with clear inputs and outputs.
def _run(cmd: List[str], *, timeout: int = 12) -> Tuple[int, str]:
    # Protect this step so expected failures can fall back cleanly.
    try:
        # Prepare completed for the next step.
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return completed.returncode, (completed.stdout or "") + (completed.stderr or "")
    except Exception as exc:
        # Return the prepared result to the caller.
        return 1, str(exc)


# Section: run the read pinned packages workflow with clear inputs and outputs.
def _read_pinned_packages() -> List[str]:
    pins: Dict[str, str] = {}
    # Protect this step so expected failures can fall back cleanly.
    try:
        lines = REQUIREMENTS_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        lines = []

    for line in lines:
        # Prepare clean for the next step.
        clean = line.strip()
        if not clean or clean.startswith("#"):
            continue
        match = re.match(r"^(torch|torchvision|torchaudio)==([^\s#]+)", clean, flags=re.IGNORECASE)
        if match:
            # Prepare values needed by the next step.
            pins[match.group(1).lower()] = f"{match.group(1).lower()}=={match.group(2)}"

    # Prepare packages for the next step.
    packages = []
    for name in ("torch", "torchvision", "torchaudio"):
        # Choose the correct branch before the workflow continues.
        if name in pins:
            packages.append(pins[name])

    return packages or ["torch", "torchvision"]


# Section: run the torch state workflow with clear inputs and outputs.
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
    # Protect this step so expected failures can fall back cleanly.
    try:
        import torch

        # Prepare values needed by the next step.
        state["installed"] = True
        state["torch_version"] = getattr(torch, "__version__", None)
        state["torch_cuda_version"] = getattr(getattr(torch, "version", None), "cuda", None)
        cuda_available = bool(torch.cuda.is_available())
        state["cuda_available"] = cuda_available
        if cuda_available:
            # Prepare count for the next step.
            count = int(torch.cuda.device_count())
            state["cuda_device_count"] = count
            if count > 0:
                # Prepare values needed by the next step.
                state["cuda_device_name"] = torch.cuda.get_device_name(0)
    except Exception as exc:
        # Prepare values needed by the next step.
        state["error"] = str(exc)
    # Return the prepared result to the caller.
    return state


# Section: run the target runtime workflow with clear inputs and outputs.
def _target_runtime(mode: str) -> Tuple[str, bool, str]:
    normalized = str(mode or "auto").strip().lower()
    if normalized in ("skip", "none", "off"):
        return "skip", False, "Torch runtime install disabled"
    if normalized in ("cpu", "cpu-only"):
        # Return the prepared result to the caller.
        return "cpu", False, "CPU runtime requested"
    # Choose the correct branch before the workflow continues.
    if normalized in ("auto", "cuda", "gpu", "nvidia"):
        return "cpu", False, "CUDA Torch install is disabled; using CPU runtime"

    return "cpu", False, f"Unsupported Torch mode {normalized!r}; using CPU runtime"


# Section: run the needs install workflow with clear inputs and outputs.
def _needs_install(target: str, state: Dict[str, object]) -> Tuple[bool, str]:
    if not state.get("installed"):
        # Return the prepared result to the caller.
        return True, "torch is not installed"

    # Prepare has cuda build for the next step.
    has_cuda_build = bool(state.get("torch_cuda_version"))
    cuda_available = bool(state.get("cuda_available"))

    if target == "cpu":
        if has_cuda_build:
            # Return the prepared result to the caller.
            return True, "CPU runtime requested but CUDA Torch is installed"
        return False, "CPU runtime is acceptable"

    return False, "No runtime change needed"


# Section: run the main workflow with clear inputs and outputs.
def main() -> int:
    # Prepare parser for the next step.
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Install the selected Torch runtime when needed")
    args = parser.parse_args()

    mode = os.getenv("CASM_TORCH_INSTALL_MODE", os.getenv("PYTORCH_INSTALL_MODE", "cpu"))
    target, _has_gpu, hardware_label = _target_runtime(mode)
    state = _torch_state()

    print("Torch runtime selector")
    # Trigger the side effect required for this stage.
    print(f"  mode            : {mode}")
    print(f"  target          : {target}")
    print("  cuda_install    : disabled")
    if hardware_label:
        # Trigger the side effect required for this stage.
        print(f"  hardware        : {hardware_label}")
    print(f"  installed_torch : {state.get('torch_version') or 'missing'}")
    print(f"  torch_cuda      : {state.get('torch_cuda_version') or 'none'}")
    print(f"  cuda_available  : {state.get('cuda_available')}")

    # Choose the correct branch before the workflow continues.
    if target == "skip":
        return 0

    needed, reason = _needs_install(target, state)
    print(f"  action_needed   : {needed} ({reason})")
    if not needed:
        # Return the prepared result to the caller.
        return 0

    if not args.apply:
        return 0

    # Prepare packages for the next step.
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
    # Trigger the side effect required for this stage.
    print(f"Installing {target} Torch runtime from {index_url}")
    result = subprocess.run(cmd, cwd=str(ROOT), check=False)
    if result.returncode != 0:
        # Trigger the side effect required for this stage.
        print("WARN: Torch runtime install failed; existing runtime will be used.")
        return result.returncode

    after = _torch_state()
    print(f"  post_torch      : {after.get('torch_version') or 'missing'}")
    print(f"  post_torch_cuda : {after.get('torch_cuda_version') or 'none'}")
    # Trigger the side effect required for this stage.
    print(f"  post_cuda_ok    : {after.get('cuda_available')}")
    return 0


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    raise SystemExit(main())
