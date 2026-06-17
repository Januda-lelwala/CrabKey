"""Launch the Ink (Node/React) terminal UI and wire it to the Python engine."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    # crabkey/cli/launcher.py → repo root is two parents up from the package.
    return Path(__file__).resolve().parents[2]


def launch_tui(cwd: Path, provider: str | None, model: str | None) -> int:
    repo_root = _repo_root()
    tui_dir = repo_root / "tui"

    if not tui_dir.exists():
        print(f"error: TUI directory not found at {tui_dir}", file=sys.stderr)
        return 1

    node = shutil.which("node")
    npm = shutil.which("npm")
    if not node or not npm:
        print(
            "error: Node.js is required for the CrabKey TUI.\n"
            "  Install Node.js >= 18 from https://nodejs.org and try again.",
            file=sys.stderr,
        )
        return 1

    # First run: install JS dependencies.
    if not (tui_dir / "node_modules").exists():
        print("Installing TUI dependencies (first run, this happens once)…", file=sys.stderr)
        result = subprocess.run([npm, "install"], cwd=tui_dir)
        if result.returncode != 0:
            print("error: `npm install` failed for the TUI.", file=sys.stderr)
            return result.returncode

    env = os.environ.copy()
    env["CRABKEY_PYTHON"] = sys.executable
    env["CRABKEY_REPO"] = str(repo_root)
    env["CRABKEY_CWD"] = str(Path(cwd).resolve())
    if provider:
        env["CRABKEY_PROVIDER"] = provider
    if model:
        env["CRABKEY_MODEL"] = model

    tsx = tui_dir / "node_modules" / ".bin" / "tsx"
    cmd = [str(tsx), "source/cli.tsx"] if tsx.exists() else [npm, "start", "--silent"]

    # Inherit the TTY so Ink can take over raw-mode keyboard input.
    return subprocess.run(cmd, cwd=tui_dir, env=env).returncode
