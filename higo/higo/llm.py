"""선택적 LLM(Claude) 연동.

`anthropic` 패키지가 설치되어 있고 자격 증명(ANTHROPIC_API_KEY 등)이 있으면
Graph RAG 합성과 원전 추출에 Claude 를 사용한다. 없으면 시스템은 규칙 기반
경로로 동작한다 — LLM 은 발견을 돕는 도구일 뿐, 그래프의 사실 판정자가 아니다.

환경 변수
  HIGO_LLM=off         LLM 사용을 끈다
  HIGO_MODEL           기본값 claude-opus-5
"""
from __future__ import annotations

import json
import os
import re

DEFAULT_MODEL = "claude-opus-5"


class LLMUnavailable(RuntimeError):
    pass


class LLMClient:
    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("HIGO_MODEL", DEFAULT_MODEL)
        self._client = None
        self._error: str | None = None
        if os.environ.get("HIGO_LLM", "").lower() in ("off", "0", "false"):
            self._error = "disabled by HIGO_LLM"
            return
        try:
            import anthropic
        except ImportError:
            self._error = "anthropic package not installed (pip install anthropic)"
            return
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
                or os.environ.get("ANTHROPIC_PROFILE")):
            self._error = "no Anthropic credentials in environment"
            return
        self._anthropic = anthropic
        self._client = anthropic.Anthropic()

    @property
    def available(self) -> bool:
        return self._client is not None

    def status(self) -> dict:
        return {"available": self.available, "model": self.model, "reason": self._error}

    def complete(self, system: str, user: str, max_tokens: int = 16000) -> str:
        if not self._client:
            raise LLMUnavailable(self._error or "LLM unavailable")
        anthropic = self._anthropic
        kwargs = dict(model=self.model, max_tokens=max_tokens, system=system,
                      messages=[{"role": "user", "content": user}],
                      thinking={"type": "adaptive"}, output_config={"effort": "medium"})
        try:
            # 안전 분류기가 요청을 거절(refusal)하면 서버 측에서 다른 모델로 자동 재시도한다.
            with self._client.beta.messages.stream(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs) as stream:
                resp = stream.get_final_message()
        except (anthropic.BadRequestError, TypeError):
            # fallback 베타를 쓸 수 없는 환경(구버전 SDK, 프록시 등)에서는 일반 호출
            with self._client.messages.stream(**kwargs) as stream:
                resp = stream.get_final_message()
        if resp.stop_reason == "refusal":
            raise LLMUnavailable("model declined the request")
        return "".join(b.text for b in resp.content if b.type == "text")

    def complete_json(self, system: str, user: str, max_tokens: int = 16000) -> dict:
        text = self.complete(system + "\n\nRespond with a single JSON object and nothing else.", user, max_tokens)
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ValueError("LLM did not return JSON")
        return json.loads(m.group(0))
