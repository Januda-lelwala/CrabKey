from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SandboxConfig:
    allowed_paths: list[Path] = field(default_factory=list)
    allowed_env_vars: list[str] = field(default_factory=list)
    network_allowed: bool = False
    timeout_seconds: float = 30.0


class Sandbox:
    """Constrains shell execution to approved paths and env vars."""

    def __init__(self, config: SandboxConfig | None = None) -> None:
        self.config = config or SandboxConfig()

    def _check_path(self, path: str | Path) -> None:
        p = Path(path).resolve()
        if not self.config.allowed_paths:
            return
        for allowed in self.config.allowed_paths:
            try:
                p.relative_to(allowed.resolve())
                return
            except ValueError:
                continue
        raise PermissionError(f"Path '{p}' is outside sandbox allowed paths.")

    def _build_env(self) -> dict[str, str]:
        if not self.config.allowed_env_vars:
            return dict(os.environ)
        return {k: os.environ[k] for k in self.config.allowed_env_vars if k in os.environ}

    async def run(
        self,
        command: str,
        cwd: str | Path | None = None,
    ) -> tuple[int, str, str]:
        """Run *command* inside the sandbox. Returns (returncode, stdout, stderr)."""
        if cwd:
            self._check_path(cwd)

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._build_env(),
            cwd=str(cwd) if cwd else None,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.config.timeout_seconds
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise TimeoutError(
                f"Command timed out after {self.config.timeout_seconds}s: {command!r}"
            )
        return proc.returncode or 0, stdout.decode(), stderr.decode()
