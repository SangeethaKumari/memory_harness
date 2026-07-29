# Agent Memory System Architecture

This document details the software architecture, core components, and data flows of the **Agent Memory Labs** built with the Google Agent Development Kit (ADK). The architecture is designed to address complex memory challenges: scope management, write-time reconciliation, multi-factor retrieval scoring, context compaction gates, and memory-time governance.

---

## 1. System Component Overview

The diagram below shows the high-level components of the application. The system decouples **transient context (ADK session state)** from **durable memories (FactStore)**.

```mermaid
graph TD
    User(["User"]) --- Runner["ADK Runner"]
    
    subgraph ADK_Runtime ["adk_runtime.py"]
        Runner --- SessionService["InMemorySessionService"]
        Runner --> Agent["LlmAgent"]
    end

    subgraph LLM_Configuration ["llm_config.py"]
        Agent --- LiteLLM["LiteLLM Client"]
        LiteLLM --- RemoteLLM["vLLM Router Endpoint"]
    end

    subgraph Durable_Memory ["fact_store.py"]
        Agent --- FactStore["FactStore"]
        FactStore --> Encoder["SentenceTransformer (all-MiniLM-L6-v2)"]
        FactStore --> FactMap["In-Memory Fact Map with Audit Logs"]
    end
```

---

## 2. Memory Scoping & Storage Architecture

When the agent writes to the store, it tags variables and facts with specific scopes using state prefixes. The scopes determine the longevity and visibility of the data:

```mermaid
flowchart LR
    subgraph Scopes ["State Scopes"]
        Temp["temp: Prefix"] --> Invocation["Single Run Turn Workspace"]
        Session["No Prefix"] --> ActiveSession["Active Session Only"]
        UserScope["user: Prefix"] --> MultiSession["Persists across Sessions for a Specific User"]
        AppScope["app: Prefix"] --> GlobalScope["Shared across All Users and Sessions"]
    end
```

- **`temp:`**: Workspace for intermediate reasoning (e.g. scratchpad). Cleared as soon as `run_turn` finishes.
- **Session (no prefix)**: Stored in the active session. Dies when the session ends.
- **`user:`**: Persistent user preferences. Survives session termination and is re-loaded when the same `user_id` starts a new session via `InMemorySessionService`.
- **`app:`**: Global application-wide states or configurations shared by all users.

---

## 3. Write-Policy & Reconciliation Pipeline (Lab 02)

Every memory write is a **reconciliation process**, rather than a blind insert. This pipeline prevents redundant facts, cleans up outdated state, and maintains audit trails.

```mermaid
flowchart TD
    Start(["Candidate Fact Extracted"]) --> Embed["Compute Embedding using MiniLM-L6"]
    Embed --> SearchNeighbors["Query FactStore for Semantic Neighbors"]
    SearchNeighbors --> Evaluate{"Evaluate Conflict or Redundancy"}
    
    Evaluate -->|"No Similar Fact"| Add["ADD: Store new Fact"]
    Evaluate -->|"Same Semantic Fact, New Details"| Update["UPDATE: Tombstone old Fact + Add successor"]
    Evaluate -->|"Contradictory Fact or Deletion"| Delete["DELETE: Invalidate old Fact via Tombstone"]
    Evaluate -->|"Identical Content"| NoOp["NOOP: Do nothing / Skip"]

    subgraph Fact_Schema ["Fact Schema"]
        FactRecord["Fact Record (id, text, importance, timestamps, provenance, superseded, superseded_by, superseded_at)"]
    end
    
    Add --> FactRecord
    Update --> FactRecord
    Delete --> FactRecord
```

- **Tombstones**: Instead of hard deleting, invalidated facts set `superseded = True` and link to their replacement via `superseded_by` for full audit trail tracing.

---

## 4. Memory Stream Retrieval Pipeline (Lab 02b)

Retrieval computes a multi-factor score instead of a raw cosine-similarity nearest-neighbor search. This prevents recent small chatter (e.g., "likes tea today") from overriding critical cold facts (e.g., "severe peanut allergy").

```mermaid
flowchart TD
    Query(["Query / Prompt"]) --> Embed["Generate Embedding"]
    Embed --> GetCandidates["Fetch non-superseded Facts"]
    
    subgraph Scorers ["Multi-Factor Scoring"]
        Recency["Recency Score"] -->|"e^-λt decay"| NormRecency["Min-Max Normalize"]
        Importance["Importance Score"] -->|"Set at Write-Time"| NormImportance["Min-Max Normalize"]
        Relevance["Relevance Score"] -->|"Cosine Similarity"| NormRelevance["Min-Max Normalize"]
    end
    
    GetCandidates --> Scorers
    
    NormRecency --> Sum["Weighted Sum: w1*Recency + w2*Importance + w3*Relevance"]
    NormImportance --> Sum
    NormRelevance --> Sum
    
    Sum --> Rank["Sort by Score"]
    Rank --> Limit["Select Top-K Facts"]
    Limit --> Prompt(["Render to LLM Prompt Context"])
```

---

## 5. Compaction & Preservation Gate (Lab 03)

As the context window fills, memory must be compressed. Compaction summarizes historical turns but introduces the risk of **amnesia**. The preservation gate acts as a safety unit test.

```mermaid
flowchart TD
    Start(["Start Agent Turn"]) --> MonitorContext["Monitor Context Size"]
    MonitorContext --> CheckThreshold{"Context Size >= 70% Limit?"}
    
    CheckThreshold -->|"No"| ActiveTurn["Proceed with Active Turn"]
    CheckThreshold -->|"Yes"| CompactionTriggered["Trigger Compaction Process"]
    
    subgraph Compaction ["Compaction Subsystem"]
        CompactionTriggered --> PinCore["Pin System Prompt & Core Rules"]
        PinCore --> Externalize["Flush critical facts (allergies, etc.) to FactStore"]
        Externalize --> Summarize["Summarize transient conversation logs"]
        Summarize --> Reassemble["Reassemble condensed context"]
    end
    
    Reassemble --> RunProbes["Preservation Gate: Run verification probes"]
    
    subgraph Gate ["Preservation Gate Subsystem"]
        RunProbes --> AskProbes["Query agent with must-answer questions"]
        AskProbes --> GradeAnswers{"Passed verification probes?"}
    end
    
    GradeAnswers -->|"Yes"| UpdateContext["Update Context & Proceed"]
    GradeAnswers -->|"No"| Rollback["Amnesia detected! Rollback & Escalate"]
    
    UpdateContext --> MonitorContext
```

---

## 6. Write-Time Memory Governance (Lab 05)

When agents write memories based on external tools, user input, or web documents, they are exposed to **indirect prompt injection** (poisoned memories). The governor serves as a gatekeeper.

```mermaid
flowchart TD
    Input["Candidate Fact from Agent Turn"] --> Governor{"Write-Time Governor"}
    
    Governor -->|"Suspicious (Injection/Bias/Suppression)"| Quarantine["Quarantine Area"]
    Governor -->|"Safe & Clean"| FactStore[("FactStore Database")]
    
    Quarantine --> AuditLog["Append-Log / Forensic Audit Trail"]
    Quarantine --> Alert["Trigger Security Quarantine Alert"]
    
    FactStore --> Read["Read-time Context Retrieval"]
    
    subgraph Mitigation ["Mitigation Subsystem"]
        Tombstone["Targeted Tombstone Invalidation"] -->|"Remediation"| FactStore
    end
```

- **Quarantine**: Instead of silently dropping toxic instructions (which makes debugging hard), facts are quarantined with metadata details, allowing developers to trace the source of the prompt injection.
