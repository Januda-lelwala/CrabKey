from __future__ import annotations

import asyncio
import os
import shlex
import shutil
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SandboxConfig:
    allowed_paths: list[Path] = field(default_factory=list)
    allowed_env_vars: list[str] = field(default_factory=list)
    network_allowed: bool = False
    timeout_seconds: float = 30.0
    # Isolation backend: "none" (subprocess only), "seatbelt" (macOS sandbox-exec),
    # or "docker" (run inside a container with the working dir mounted).
    backend: str = "none"
    docker_image: str = "alpine:3.20"


class SandboxUnavailable(RuntimeError):
    """Raised when the configured sandbox backend is not available on this host."""


class Sandbox:
    """Constrains shell execution to approved paths and env vars.

    With backend="none" only a path check + timeout are applied. The "seatbelt"
    and "docker" backends add real OS-level isolation (filesystem write scoping
    and optional network denial).
    """

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

    # ── backend command building (pure, unit-testable) ──────────────────────

    def _seatbelt_profile(self, cwd: str | Path | None) -> str:
        """Build a Seatbelt profile: allow all, then deny writes outside the
        allowed paths (and /tmp), and deny network unless explicitly allowed."""
        write_paths = [Path(p).resolve() for p in self.config.allowed_paths]
        if cwd:
            write_paths.append(Path(cwd).resolve())
        subpaths = " ".join(f'(subpath "{p}")' for p in dict.fromkeys(write_paths))
        lines = [
            "(version 1)",
            "(allow default)",
            "(deny file-write*)",
            f'(allow file-write* (subpath "/tmp") (subpath "/private/tmp") {subpaths})',
        ]
        if not self.config.network_allowed:
            lines.append("(deny network*)")
        return "\n".join(lines)

    def _wrap_command(self, command: str, cwd: str | Path | None) -> str:
        """Return the shell string to execute for the configured backend."""
        backend = self.config.backend
        if backend == "none":
            return command

        if backend == "seatbelt":
            if not shutil.which("sandbox-exec"):
                raise SandboxUnavailable("sandbox-exec not found (Seatbelt is macOS-only).")
            profile = self._seatbelt_profile(cwd)
            return f"sandbox-exec -p {shlex.quote(profile)} /bin/sh -c {shlex.quote(command)}"

        if backend == "docker":
            docker = shutil.which("docker") or shutil.which("podman")
            if not docker:
                raise SandboxUnavailable("docker/podman not found.")
            mount = str(Path(cwd).resolve()) if cwd else os.getcwd()
            parts = [docker, "run", "--rm", "-v", f"{mount}:{mount}", "-w", mount]
            if not self.config.network_allowed:
                parts += ["--network", "none"]
            parts += [self.config.docker_image, "/bin/sh", "-c", command]
            return " ".join(shlex.quote(p) for p in parts)

        raise SandboxUnavailable(f"Unknown sandbox backend: {backend!r}")

    # ── execution ───────────────────────────────────────────────────────────

    async def run(
        self,
        command: str,
        cwd: str | Path | None = None,
    ) -> tuple[int, str, str]:
        """Run *command* inside the sandbox. Returns (returncode, stdout, stderr)."""
        if cwd:
            self._check_path(cwd)

        wrapped = self._wrap_command(command, cwd)

        proc = await asyncio.create_subprocess_shell(
            wrapped,
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
