from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    model: str
    openai_api_key: str
    openai_base_url: str
    bitgn_api_key: str | None
    benchmark_host: str
    benchmark_id: str
    run_name: str
    max_turns: int
    concurrency: int
    request_timeout: float

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            model=os.getenv("MODEL_ID", "gpt-oss-120b"),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_base_url=os.getenv("OPENAI_BASE_URL", ""),
            bitgn_api_key=os.getenv("BITGN_API_KEY"),
            benchmark_host=os.getenv("BENCHMARK_HOST", "https://api.bitgn.com"),
            benchmark_id=os.getenv("BENCHMARK_ID", "bitgn/pac1-dev"),
            run_name=os.getenv("BITGN_RUN_NAME", "neuraldeep gpt oss120b x2 4090(48gb)"),
            max_turns=int(os.getenv("AGENT_MAX_TURNS", "50")),
            concurrency=int(os.getenv("AGENT_CONCURRENCY", "10")),
            request_timeout=float(os.getenv("AGENT_REQUEST_TIMEOUT", "120")),
        )
