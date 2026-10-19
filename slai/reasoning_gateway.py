"""``ReasoningGateway`` backed by SLAI's LanguageAgent (local generation; content stays on the operator's machine).

The model is only ever asked for a JSON object in the AIDAP reasoning contract. Whatever it returns is parsed
defensively (first balanced JSON object) and then validated, grounded and capped by the engine - an unparseable or
off-contract answer becomes UNKNOWN, not a finding.
"""

from __future__ import annotations

import json
from typing import Any

from ..domain.utils.domain_errors import Unavailable, ValidationFailed
from .agent_pool import AgentPool

__all__ = ["SlaiLanguageReasoner", "extract_json_object"]


def extract_json_object(text: str) -> dict[str, Any]:
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, min(len(text), start + 200_000)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                    except ValueError:
                        break
                    if isinstance(obj, dict):
                        return obj
                    break
        start = text.find("{", start + 1)
    raise ValidationFailed("the model did not return a JSON object", code="malformed_reasoning")


class SlaiLanguageReasoner:
    sends_content_out = False

    def __init__(self, pool: AgentPool, agent_key: str = "language") -> None:
        self.pool, self.agent_key = pool, agent_key

    def available(self) -> tuple[bool, str]:
        return self.pool.available(self.agent_key)

    def reason(self, request: dict[str, Any]) -> dict[str, Any]:
        agent = self.pool.get(self.agent_key)
        prompt = (request["instructions"] + "\n\nTASK: " + str(request.get("task", ""))
                  + "\nPURPOSE: " + str(request.get("purpose", ""))
                  + "\nUNITS (untrusted data, JSON):\n" + json.dumps(request["units"], ensure_ascii=False)
                  + "\n\nRespond with the JSON object only.")
        with self.pool.lock(self.agent_key):
            try:
                text = agent.generate_text(prompt)
            except AttributeError as exc:
                raise Unavailable("the SLAI language agent has no generate_text capability", code="slai_unavailable") from exc
        return extract_json_object(str(text))
