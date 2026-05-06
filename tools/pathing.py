from __future__ import annotations

from pathlib import Path


def resolve_kernel_root(workspace_root: Path) -> Path:
    if (workspace_root / 'i386').exists() and (workspace_root / 'build-specs').exists():
        return workspace_root
    candidate = workspace_root / 'uts'
    if (candidate / 'i386').exists():
        return candidate
    return workspace_root