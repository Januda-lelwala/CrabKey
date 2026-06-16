from __future__ import annotations

import asyncio
import datetime
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CheckpointInfo:
    sha: str
    label: str
    created_at: datetime.datetime


class Checkpoint:
    """Creates git checkpoints before destructive tool calls so they can be rolled back."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    async def _git(self, *args: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=str(self.repo_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {stderr.decode().strip()}")
        return stdout.decode().strip()

    async def create(self, label: str) -> CheckpointInfo:
        await self._git("add", "-A")
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        msg = f"crabkey-checkpoint: {label} [{timestamp}]"
        try:
            await self._git("commit", "-m", msg, "--allow-empty")
        except RuntimeError:
            pass  # nothing to commit — checkpoint is a no-op
        sha = await self._git("rev-parse", "HEAD")
        return CheckpointInfo(sha=sha, label=label, created_at=datetime.datetime.now(datetime.timezone.utc))

    async def restore(self, info: CheckpointInfo) -> None:
        await self._git("reset", "--hard", info.sha)

    async def list(self) -> list[CheckpointInfo]:
        log = await self._git(
            "log", "--oneline", "--grep=crabkey-checkpoint:", "--format=%H %s"
        )
        results: list[CheckpointInfo] = []
        for line in log.splitlines():
            sha, _, rest = line.partition(" ")
            label = rest.replace("crabkey-checkpoint: ", "").split(" [")[0]
            results.append(CheckpointInfo(sha=sha, label=label, created_at=datetime.datetime.min))
        return results
