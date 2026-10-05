"""Typed Secret[T] wrapper (ADR-0003): never leaks via repr/str/format/JSON/pickle/copy; read via .value()."""

from .secret import Secret

__all__ = ["Secret"]
