"""Thin client for Qwen Cloud's OpenAI-compatible Chat Completions API.

Model transport is intentionally isolated behind this one module: swapping
Qwen Cloud for a self-hosted Qwen 12B endpoint (or any other provider) means
changing QWEN_CLOUD_BASE_URL / the client construction here, nothing else in
the app. The Agent Firewall and memory store never import this module
directly with model-specific assumptions.

NOTE: confirm the exact Qwen Cloud base URL / model ID against the account
dashboard at qwencloud.com once provisioned — DashScope's OpenAI-compatible
endpoint (https://dashscope-intl.aliyuncs.com/compatible-mode/v1) is used
here as the default because Qwen Cloud exposes the same compatible-mode
surface; update QWEN_CLOUD_BASE_URL via env var if the account dashboard
gives a different regional endpoint.
"""

from __future__ import annotations

import os

from openai import OpenAI

QWEN_CLOUD_BASE_URL = os.environ.get(
    "QWEN_CLOUD_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)
QWEN_CLOUD_MODEL = os.environ.get("QWEN_CLOUD_MODEL", "qwen-plus")


def _client() -> OpenAI:
    api_key = os.environ.get("QWEN_CLOUD_API_KEY")
    if not api_key:
        raise RuntimeError("QWEN_CLOUD_API_KEY is not set")
    return OpenAI(api_key=api_key, base_url=QWEN_CLOUD_BASE_URL)


def chat(system_prompt: str, user_message: str) -> str:
    client = _client()
    response = client.chat.completions.create(
        model=QWEN_CLOUD_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    return response.choices[0].message.content or ""
