"""Runtime context (SCHEMA_v1 ``run_context``): machine, OS, execution mode, memory, devices.

Every probe is best-effort and cheap; a fact we could not read is ``None`` with a reason.
Devices are ``observed`` only when the value came from the loaded backend at runtime;
otherwise the configured value is reported as ``configured`` — never inferred from a name.
"""

from __future__ import annotations

import hashlib
import os
import platform
import re
import socket
import subprocess
import sys
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any
from uuid import UUID

from .redact import redact
from .schema import Device, ExecutionMode, Reason, RunContext

_CGROUP_MARKERS = ("docker", "containerd", "kubepods", "podman", "libpod")


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _sysctl(name: str) -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.run(  # noqa: S603 — fixed argv, no shell
            ["/usr/sbin/sysctl", "-n", name], capture_output=True, text=True, timeout=2, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


@cache
def execution_mode() -> ExecutionMode:
    """``container`` when this process runs in a container, else ``native``. ``remote`` is for
    a stage whose work runs behind an HTTP backend; it is set on that stage's device, not here."""
    if Path("/.dockerenv").exists() or Path("/run/.containerenv").exists():
        return "container"
    cgroup = _read("/proc/1/cgroup") or ""
    if any(marker in cgroup for marker in _CGROUP_MARKERS):
        return "container"
    return "native"


@cache
def host_label() -> str:
    """A host label without a person's name: container hostnames (ids) as they are; a native
    host (often "<Name>s-MacBook-Air") as a short stable hash."""
    name = socket.gethostname() or "unknown"
    if execution_mode() == "container":
        return name[:64]
    return "native-" + hashlib.sha256(name.encode()).hexdigest()[:10]


@cache
def _chip_model() -> str | None:
    if sys.platform == "darwin":
        return _sysctl("machdep.cpu.brand_string")
    info = _read("/proc/cpuinfo") or ""
    match = re.search(r"^model name\s*:\s*(.+)$", info, re.MULTILINE)
    return match.group(1).strip() if match else None


@cache
def _memory_total() -> int | None:
    if sys.platform == "darwin":
        raw = _sysctl("hw.memsize")
        return int(raw) if raw and raw.isdigit() else None
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None


@cache
def _container_mem_limit() -> int | None:
    for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        raw = (_read(path) or "").strip()
        if raw.isdigit() and int(raw) < 1 << 60:  # "max" / huge = unlimited
            return int(raw)
    return None


def process_rss() -> int | None:
    statm = _read("/proc/self/statm")
    if statm:
        try:
            return int(statm.split()[1]) * os.sysconf("SC_PAGE_SIZE")
        except (IndexError, ValueError, OSError):
            return None
    if sys.platform == "darwin":
        try:
            out = subprocess.run(  # noqa: S603
                ["/bin/ps", "-o", "rss=", "-p", str(os.getpid())],
                capture_output=True, text=True, timeout=2, check=False,
            )  # fmt: skip
            return int(out.stdout.strip()) * 1024 if out.stdout.strip().isdigit() else None
        except (OSError, subprocess.SubprocessError):
            return None
    return None


def swap_used() -> int | None:
    meminfo = _read("/proc/meminfo")
    if meminfo:
        total = re.search(r"^SwapTotal:\s+(\d+)", meminfo, re.MULTILINE)
        free = re.search(r"^SwapFree:\s+(\d+)", meminfo, re.MULTILINE)
        if total and free:
            return (int(total.group(1)) - int(free.group(1))) * 1024
    raw = _sysctl("vm.swapusage")  # "total = 2048.00M  used = 1035.25M  free = …"
    if raw:
        match = re.search(r"used = ([\d.]+)([KMG])", raw)
        if match:
            scale = {"K": 1 << 10, "M": 1 << 20, "G": 1 << 30}[match.group(2)]
            return int(float(match.group(1)) * scale)
    return None


def memory_pressure() -> str | None:
    """``normal|warn|critical`` on macOS; ``some avg10=…`` on Linux (PSI); else None."""
    raw = _sysctl("kern.memorystatus_vm_pressure_level")
    if raw:
        return {"1": "normal", "2": "warn", "4": "critical"}.get(raw, raw)
    psi = _read("/proc/pressure/memory")
    if psi:
        first = psi.splitlines()[0]
        match = re.search(r"avg10=([\d.]+)", first)
        return f"some_avg10={match.group(1)}" if match else None
    return None


def observe_device(backend: Any, configured: str | None) -> Device | None:
    """The device a loaded backend actually runs on, read from the backend at runtime
    (faster-whisper/CTranslate2 ``model.model.device``, a torch module's parameters, MLX's
    default device); otherwise the configured value marked ``configured``."""
    # Only library objects whose ``device`` is read from the runtime, never a wrapper that
    # stores the configured string: faster-whisper WhisperModel → ctranslate2 model, torch module.
    probes: tuple[Callable[[Any], Any], ...] = (
        lambda b: getattr(getattr(b, "model", None), "device", None),
        lambda b: next(b.parameters()).device,
    )
    for probe in probes:
        try:
            value = probe(backend)
        except Exception:  # noqa: BLE001 — a probe that does not apply
            continue
        if value is not None and not callable(value):
            return Device(value=str(value), observation="observed")
    if "mlx.core" in sys.modules:
        try:
            return Device(
                value=str(sys.modules["mlx.core"].default_device()), observation="observed"
            )
        except Exception:  # noqa: BLE001
            pass
    return Device(value=configured, observation="configured") if configured else None


def collect_run_context(
    processing_run_id: UUID,
    tenant_id: UUID,
    *,
    app_commit: str | None,
    app_build: str | None,
    effective_config: dict[str, Any],
    device_asr: Device | None = None,
    device_diarization: Device | None = None,
    device_llm: Device | None = None,
) -> RunContext:
    """The context at run start; ``finish_context`` adds the ``_end`` snapshots."""
    reasons: dict[str, Reason] = {}

    def fact(name: str, value: Any, reason: Reason = "unavailable") -> Any:
        if value is None:
            reasons[name] = reason
        return value

    return RunContext(
        processing_run_id=processing_run_id,
        tenant_id=tenant_id,
        app_commit=fact("app_commit", app_commit or None),
        app_build=fact("app_build", app_build or None),
        os_name=fact("os_name", platform.system() or None),
        os_version=fact("os_version", platform.release() or None),
        arch=fact("arch", platform.machine() or None),
        chip_model=fact("chip_model", _chip_model(), "not_supported"),
        memory_total_bytes=fact("memory_total_bytes", _memory_total()),
        execution_mode=execution_mode(),
        effective_config=redact(effective_config),
        device_asr=fact("device_asr", device_asr, "not_measured"),
        device_diarization=fact("device_diarization", device_diarization, "not_measured"),
        device_llm=fact("device_llm", device_llm, "not_applicable"),
        memory_pressure_start=fact("memory_pressure_start", memory_pressure(), "not_supported"),
        memory_pressure_end=fact("memory_pressure_end", None, "not_measured"),
        process_rss_start=fact("process_rss_start", process_rss(), "not_supported"),
        process_rss_end=fact("process_rss_end", None, "not_measured"),
        swap_used_start=fact("swap_used_start", swap_used(), "not_supported"),
        swap_used_end=fact("swap_used_end", None, "not_measured"),
        container_mem_limit=fact(
            "container_mem_limit",
            _container_mem_limit(),
            "not_applicable" if execution_mode() == "native" else "unavailable",
        ),
        null_reasons=reasons,
    )


def end_snapshot() -> dict[str, tuple[Any, Reason]]:
    """``{field: (value, reason-if-None)}`` for the run's end."""
    return {
        "memory_pressure_end": (memory_pressure(), "not_supported"),
        "process_rss_end": (process_rss(), "not_supported"),
        "swap_used_end": (swap_used(), "not_supported"),
    }
