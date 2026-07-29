# Scoped Store Notebook Sequence Diagram

This document illustrates the sequence of operations executed in the first notebook (`docs/notebooks/01_scoped_store.ipynb`), highlighting how the test harness (`adk_runtime.py`) orchestrates execution, interacts with the Google ADK runner, and manages session scopes using the `InMemorySessionService`.

---

## Sequence Diagram

The diagram below details the initialization, state-writing, state-persistence, and privacy-leak checks.

```mermaid
sequenceDiagram
    autonumber
    participant NB as "Jupyter Notebook"
    participant RT as "adk_runtime.py"
    participant RN as "Runner (ADK)"
    participant AG as "Agent (LlmAgent)"
    participant TL as "Scoped Tools"
    participant SS as "SessionService (InMemory)"
    participant LLM as "LLM (gpt-oss-20b)"

    Note over NB,SS: 1. Setup & Initialization Phase
    NB->>RT: make_model()
    RT-->>NB: returns LiteLlm model instance
    NB->>RT: make_agent(model, tools)
    RT-->>NB: returns LlmAgent instance
    NB->>RT: make_runner(agent, app_name)
    RT->>SS: Initialize InMemorySessionService
    RT-->>NB: returns (Runner, SessionService)

    Note over NB,SS: 2. Session 1: Writing Scoped State
    NB->>SS: create_session(user_id="alice", session_id="alice_s1")
    SS-->>NB: returns Session 1 instance
    NB->>RT: run_turn(runner, user_id="alice", session_id="alice_s1", message="Please remember: I always want a window seat. Also draft itinerary...")
    RT->>RN: run_async(user_id="alice", session_id="alice_s1", message)
    RN->>LLM: Generate response & check tool calls
    LLM-->>RN: Request tool call save_user_preference(value="window seat") & save_session_draft(...)
    RN->>TL: Execute save_user_preference(value="window seat", ToolContext)
    TL->>SS: Write "user:seat_preference" = "window seat" (durable user scope)
    TL-->>RN: Return result dict
    RN->>TL: Execute save_session_draft(value="Tokyo...", ToolContext)
    TL->>SS: Write "draft_itinerary" = "Tokyo..." (transient session scope)
    TL-->>RN: Return result dict
    RN->>LLM: Final prompt completion with tool results
    LLM-->>RN: Final text reply
    RN-->>RT: Stream reply chunks
    RT-->>NB: Return final agent reply text

    Note over NB,SS: 3. Verification & Session 2 (Persistence Check)
    NB->>SS: create_session(user_id="alice", session_id="alice_s2")
    SS->>SS: Look up existing user state for "user:alice"
    SS->>SS: Load "user:seat_preference" into new session
    Note right of SS: Session-only "draft_itinerary" is discarded (no prefix)
    SS-->>NB: returns Session 2 instance
    NB->>SS: get_session_state(user_id="alice", session_id="alice_s2")
    SS-->>NB: returns {'user:seat_preference': 'window seat'} (draft_itinerary is missing)

    Note over NB,SS: 4. Privacy Check: Bob Starts Session
    NB->>SS: create_session(user_id="bob", session_id="bob_s1")
    SS->>SS: Initialize clean state for user "bob"
    SS-->>NB: returns Session instance (empty state)
```

---

## Detailed Sequence Breakdown

1. **Initialization Phase**:
   - The Jupyter notebook loads environment parameters via `load_lab_env()`.
   - `make_model()` creates the ADK model instance.
   - `make_agent()` registers the scoped Python tools (`save_user_preference`, `save_session_draft`, etc.) with `LlmAgent`.
   - `make_runner()` creates a shared `InMemorySessionService` that manages the database in memory across different session executions.

2. **Session 1 - Alice's Preference Storage**:
   - The notebook calls `run_turn()` inside `adk_runtime.py` which triggers `runner.run_async()`.
   - The LLM identifies the tool definitions and triggers parallel calls:
     - `save_user_preference` sets a `user:seat_preference` key in `ToolContext.state`.
     - `save_session_draft` sets a bare `draft_itinerary` key in `ToolContext.state`.
   - The runtime records these state operations into the shared session service.

3. **Session 2 - User-Level Persistence**:
   - When `create_session()` is invoked for `alice` under a new session ID (`alice_s2`), `InMemorySessionService` recovers keys matching the prefix `user:` for `alice`.
   - State keys without a prefix (bare keys like `draft_itinerary`) are associated strictly with `alice_s1` and are discarded.
   - Assertions verify that `user:seat_preference` persists, whereas `draft_itinerary` is absent.

4. **Privacy Isolation (Bob)**:
   - When a session starts for user `bob`, the service ensures no other user's persistent keys are retrieved.
   - This validates that the `user:` prefix acts as a proper user boundary, preventing data leaks.
