"""Offline stand-in for anthropic.Anthropic used ONLY by code tests.

It returns keyword-heuristic labels in the enrichment line format so the
orchestration (batching, validation, retry, cache, resume) can be tested without
API spend. Nothing produced by this mock is used as evidence of model execution.
"""
import re
import uuid
from types import SimpleNamespace


def _label(text):
    t = text.lower()
    if re.search(r"login|log in|password", t):
        return "access|login_failure|complaint|-0.6|4"
    if re.search(r"\bads?\b", t):
        return "usability|ads|complaint|-0.5|2"
    if re.search(r"crash|stop|not working", t):
        return "playback|crashes_or_wont_open|complaint|-0.6|3"
    if re.search(r"premium|price|pay", t):
        return "billing|price|complaint|-0.4|2"
    if re.search(r"uninstall|cancel", t):
        return "other|general_criticism|cancellation|-0.8|2"
    if re.search(r"good|great|love|nice|best|excellent|awesome", t):
        return "other|general_praise|praise|0.8|1"
    return "other|unrelated_or_unclear|unclear|0.0|1"


class _Messages:
    def __init__(self, parent):
        self.parent = parent

    def create(self, extra_body=None, **params):
        self.parent.calls += 1
        user = params["messages"][0]["content"]
        lines = []
        for i, text in re.findall(r'<r i="(\d+)">(.*?)</r>', user, flags=re.S):
            if self.parent.drop_idx_once and i == "1" and not self.parent.dropped:
                self.parent.dropped = True
                continue  # simulate a missing line -> triggers invalid-output retry
            lines.append(f"{i}|{_label(text)}|0|*")
        out = "\n".join(lines)
        usage = SimpleNamespace(input_tokens=len(user) // 4, cache_creation_input_tokens=0,
                                cache_read_input_tokens=4500, output_tokens=len(out) // 3)
        return SimpleNamespace(id=f"mock-{uuid.uuid4().hex[:12]}", model=params["model"] + "-mock", usage=usage, stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text=out)])


class MockClient:
    def __init__(self, drop_idx_once=False):
        self.calls = 0
        self.drop_idx_once = drop_idx_once
        self.dropped = False
        self.messages = _Messages(self)
