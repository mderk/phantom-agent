from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol


class RuntimeClient(Protocol):
    async def get_context(self) -> str: ...
    async def tree(self, root: str = "/", level: int = 2) -> str: ...
    async def list_dir(self, path: str = "/") -> str: ...
    async def read_file(
        self,
        path: str,
        start_line: int = 0,
        end_line: int = 0,
        number: bool = False,
    ) -> str: ...
    async def find_files(
        self,
        name: str,
        root: str = "/",
        kind: str = "all",
        limit: int = 10,
    ) -> str: ...
    async def search(self, pattern: str, root: str = "/", limit: int = 10) -> str: ...
    async def write_file(
        self,
        path: str,
        content: str,
        start_line: int = 0,
        end_line: int = 0,
    ) -> str: ...
    async def delete(self, path: str) -> str: ...
    async def mkdir(self, path: str) -> str: ...
    async def move(self, from_path: str, to_path: str) -> str: ...
    async def answer(self, message: str, outcome: str, refs: list[str]) -> str: ...


@dataclass
class Telemetry:
    started: float = field(default_factory=time.time)
    tool_calls: int = 0
    wall_time_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def finish(self) -> None:
        self.wall_time_ms = int((time.time() - self.started) * 1000)


@dataclass
class TaskContext:
    """Passed as context to every tool via RunContextWrapper."""

    runtime_url: str
    task_text: str
    skill_id: str = ""
    model: str | None = None
    telemetry: Telemetry = field(default_factory=Telemetry)
    completion_submitted: bool = False
    files_read: list[str] = field(default_factory=list)
    files_written: list[str] = field(default_factory=list)
    file_contents: dict[str, str] = field(default_factory=dict)
    agents_dirs_read: set[str] = field(default_factory=set)
    _runtime: RuntimeClient | None = field(default=None, repr=False)

    @property
    def runtime(self) -> RuntimeClient:
        if self._runtime is None:
            from .runtime import AsyncPcmRuntime

            self._runtime = AsyncPcmRuntime(self.runtime_url)
        return self._runtime
