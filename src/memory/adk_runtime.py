"""
Thin ADK helpers so notebooks stay focused on memory ideas, not boilerplate.

Notebooks share one pattern:
  1. build a model with ``make_model()``
  2. build an ``LlmAgent`` (optionally with tools)
  3. create a ``Runner`` over an ``InMemorySessionService``
  4. call ``run_turn(...)`` and inspect session state
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from typing import Any

import nest_asyncio
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService, Session
from google.genai import types

# Jupyter already has a running event loop; nest_asyncio lets us asyncio.run().
nest_asyncio.apply()


def make_agent(
    *,
    name: str,
    model: LiteLlm,
    instruction: str,
    tools: Sequence[Callable[..., Any]] | None = None,
    description: str = "",
) -> LlmAgent:
    """Create a plain ``LlmAgent``. Pass Python callables as tools; ADK wraps them."""
    return LlmAgent(
        name=name,
        model=model,
        instruction=instruction,
        description=description or name,
        tools=list(tools or []),
    )


def make_runner(
    agent: LlmAgent,
    *,
    app_name: str,
    session_service: InMemorySessionService | None = None,
) -> tuple[Runner, InMemorySessionService]:
    """Wire agent + session service into a Runner. Reuse the service across sessions."""
    service = session_service or InMemorySessionService()
    runner = Runner(agent=agent, app_name=app_name, session_service=service)
    return runner, service


async def create_session(
    session_service: InMemorySessionService,
    *,
    app_name: str,
    user_id: str,
    session_id: str | None = None,
    state: dict[str, Any] | None = None,
) -> Session:
    return await session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
        state=state,
    )


async def get_session_state(
    session_service: InMemorySessionService,
    *,
    app_name: str,
    user_id: str,
    session_id: str,
) -> dict[str, Any]:
    session = await session_service.get_session(
        app_name=app_name, user_id=user_id, session_id=session_id
    )
    if session is None:
        raise KeyError(f"No session {session_id!r} for user {user_id!r}")
    return dict(session.state)


def ground_message_to_user(user_id: str, message: str) -> str:
    """
    Make the speaker identity visible to the LLM.

    ADK's ``user_id`` only scopes sessions; it is not part of the model prompt.
    Memory extractors often rewrite "I" → ``{user_id}``, so the probe must know
    that first-person pronouns and memories naming ``user_id`` refer to the
    same person — otherwise the model may treat those memories as about someone else.
    """
    return (
        f"[Current user: {user_id}. First-person pronouns and memories about "
        f"{user_id} refer to this user.]\n{message}"
    )


async def _collect_turn(
    runner: Runner,
    *,
    user_id: str,
    session_id: str,
    message: str,
) -> str:
    content = types.Content(role="user", parts=[types.Part(text=message)])
    chunks: list[str] = []
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=content,
    ):
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            text = getattr(part, "text", None)
            if text:
                chunks.append(text)
    return "".join(chunks).strip()


def run_turn(
    runner: Runner,
    *,
    user_id: str,
    session_id: str,
    message: str,
    ground_user: bool = True,
) -> str:
    """
    Send one user message and return the agent's final text.

    When ``ground_user`` is True (default), prepends a short identity line so the
    model resolves first-person "I"/"my" to ``user_id`` and treats recalled facts
    about that name as about the current speaker.

    Safe to call from notebook cells (uses nest_asyncio under the hood).
    """
    if ground_user:
        message = ground_message_to_user(user_id, message)
    return asyncio.run(
        _collect_turn(
            runner, user_id=user_id, session_id=session_id, message=message
        )
    )
