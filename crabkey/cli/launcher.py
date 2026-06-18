"""Launch the Ink (Node/React) terminal UI and wire it to the Python engine."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _find_tui_dir() -> Path | None:
    """Locate the Ink TUI source, across editable repos and installed app dirs."""
    candidates: list[Path] = []
    env = os.environ.get("CRABKEY_TUI_DIR")
    if env:
        candidates.append(Path(env))
    # Editable / repo layout: crabkey/cli/launcher.py → <root>/tui
    candidates.append(Path(__file__).resolve().parents[2] / "tui")
    # install.sh layout: ~/.local/share/crabkey/tui
    xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    candidates.append(Path(xdg) / "crabkey" / "tui")
    for c in candidates:
        if (c / "package.json").exists():
            return c
    return None


def _find_node_bin(tui_dir: Path) -> Path | None:
    """Find a Node bin dir: a copy vendored beside the install, else system Node."""
    # install.sh may vendor Node at <install_root>/node/bin (next to tui/).
    vendored = tui_dir.parent / "node" / "bin"
    if (vendored / "node").exists():
        return vendored
    node = shutil.which("node")
    if node:
        return Path(node).resolve().parent
    return None


def launch_tui(cwd: Path, provider: str | None, model: str | None) -> int:
    tui_dir = _find_tui_dir()
    if tui_dir is None:
        print(
            "error: could not locate the CrabKey TUI source.\n"
            "  Set CRABKEY_TUI_DIR to the directory containing tui/package.json.",
            file=sys.stderr,
        )
        return 1

    node_bin = _find_node_bin(tui_dir)
    if node_bin is None:
        print(
            "error: Node.js is required for the CrabKey TUI.\n"
            "  Re-run the installer (it can fetch a private copy), or install\n"
            "  Node.js >= 18 from https://nodejs.org and try again.",
            file=sys.stderr,
        )
        return 1

    npm = node_bin / "npm"

    env = os.environ.copy()
    # Put our Node first so npm and tsx's `#!/usr/bin/env node` shebang resolve.
    env["PATH"] = f"{node_bin}{os.pathsep}{env.get('PATH', '')}"
    env["CRABKEY_PYTHON"] = sys.executable
    # cwd for the spawned engine: the parent of tui/ holds the crabkey package
    # in source layouts; harmless when crabkey is importable globally (editable).
    env["CRABKEY_REPO"] = str(tui_dir.parent)
    env["CRABKEY_CWD"] = str(Path(cwd).resolve())
    if provider:
        env["CRABKEY_PROVIDER"] = provider
    if model:
        env["CRABKEY_MODEL"] = model

    # First run (e.g. a dev checkout): install JS dependencies if missing.
    if not (tui_dir / "node_modules").exists():
        print("Installing TUI dependencies (first run, this happens once)…", file=sys.stderr)
        result = subprocess.run([str(npm), "install"], cwd=tui_dir, env=env)
        if result.returncode != 0:
            print("error: `npm install` failed for the TUI.", file=sys.stderr)
            return result.returncode

    tsx = tui_dir / "node_modules" / ".bin" / "tsx"
    cmd = [str(tsx), "source/cli.tsx"] if tsx.exists() else [npm, "start", "--silent"]

    # Inherit the TTY so Ink can take over raw-mode keyboard input.
    return subprocess.run(cmd, cwd=tui_dir, env=env).returncode
