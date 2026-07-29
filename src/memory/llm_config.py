"""
LLM configuration for the labs.

Students run against an OpenAI-compatible endpoint (vLLM-style router).
The default model is ``openai/gpt-oss-20b`` (override with ``LLM_MODEL_NAME`` in ``.env``).

LiteLLM needs a provider prefix. We use ``hosted_vllm/<router-id>`` so the
router receives the full id unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from google.adk.models.lite_llm import LiteLlm


def _find_project_root() -> Path:
    """Walk upward from CWD until we find pyproject.toml (or give up)."""
    here = Path.cwd().resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return here


def load_lab_env() -> Path:
    """
    Load ``.env`` from the project root and ensure OPENAI_API_KEY is set.

    The lab endpoint typically does not require a real key, but the OpenAI
    client (used under LiteLLM) expects the variable to exist.
    """
    root = _find_project_root()
    load_dotenv(root / ".env", override=False)
    os.environ.setdefault("OPENAI_API_KEY", "not-needed")
    os.environ.setdefault("LLM_API_BASE", "http://10.0.10.51:8000/v1")
    os.environ.setdefault("LLM_MODEL_NAME", "openai/gpt-oss-20b")
    return root


def litellm_model_id(router_model_name: str) -> str:
    """Map a router model id to a LiteLLM model string."""
    name = router_model_name.strip()
    if name.startswith(("hosted_vllm/", "openai/openai/")):
        return name
    # Preserve ids like "openai/gpt-oss-20b" for the router.
    return f"hosted_vllm/{name}"


def make_model(
    *,
    model_name: str | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.2,
) -> LiteLlm:
    """
    Build an ADK ``LiteLlm`` pointing at the lab endpoint.

    Parameters
    ----------
    model_name:
        Router model id. Defaults to ``LLM_MODEL_NAME`` from the environment
        (``openai/gpt-oss-20b``).
    api_base:
        OpenAI-compatible base URL. Defaults to ``LLM_API_BASE``.
    """
    load_lab_env()
    router_id = model_name or os.environ["LLM_MODEL_NAME"]
    base = api_base or os.environ["LLM_API_BASE"]
    key = api_key or os.environ.get("OPENAI_API_KEY", "not-needed")

    return LiteLlm(
        model=litellm_model_id(router_id),
        api_base=base,
        api_key=key,
        # gpt-oss models spend tokens on internal reasoning before content;
        # keep the ceiling generous so tool calls and answers are not truncated.
        max_tokens=max_tokens,
        temperature=temperature,
    )


def model_summary() -> str:
    """Human-readable one-liner for notebook headers."""
    load_lab_env()
    return (
        f"endpoint={os.environ['LLM_API_BASE']}  "
        f"model={os.environ['LLM_MODEL_NAME']}"
    )


def complete(
    prompt: str,
    *,
    max_tokens: int = 512,
    temperature: float = 0.0,
) -> str:
    """
    Synchronous chat completion against the lab endpoint.

    Prefer this inside ADK *tools* (which are sync callables) so you do not
    nest ``asyncio`` event loops. Notebook cells that are already async may
    still use ``litellm.acompletion`` directly if they prefer.
    """
    import litellm

    load_lab_env()
    resp = litellm.completion(
        model=litellm_model_id(os.environ["LLM_MODEL_NAME"]),
        api_base=os.environ["LLM_API_BASE"],
        api_key=os.environ.get("OPENAI_API_KEY", "not-needed"),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return (resp.choices[0].message.content or "").strip()
