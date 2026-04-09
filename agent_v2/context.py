from __future__ import annotations

import time
from dataclasses import dataclass, field


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
    telemetry: Telemetry = field(default_factory=Telemetry)
    completion_submitted: bool = False
    files_read: list[str] = field(default_factory=list)
    files_written: list[str] = field(default_factory=list)
    file_contents: dict[str, str] = field(default_factory=dict)
    _runtime: object | None = field(default=None, repr=False)

    @property
    def runtime(self):
        if self._runtime is None:
            from .runtime import AsyncPcmRuntime

            self._runtime = AsyncPcmRuntime(self.runtime_url)
        return self._runtime
