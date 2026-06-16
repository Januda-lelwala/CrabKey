# CrabKey — Architecture Diagrams

> Model-agnostic agentic coding CLI. (Diagrams extracted from the SRS; project renamed to **CrabKey**.)

---

## System Architecture (layered)

CrabKey is organized into layers; lower layers know nothing about higher ones.

```
┌────────────────────────────────────────────────────────────┐
│  Presentation:  CLI / TUI  (streaming, diffs, thread switch) │
├────────────────────────────────────────────────────────────┤
│  Orchestration:  Loop Engine · Planner · Agent Router        │
│                  Thread Manager · Hook Dispatcher            │
├────────────────────────────────────────────────────────────┤
│  Cognition:  Context Assembler · Memory Manager · Reflector  │
├────────────────────────────────────────────────────────────┤
│  Capability:  Tool Registry  (files, shell, web, browser,    │
│               scrape, MCP client, custom)                    │
├────────────────────────────────────────────────────────────┤
│  Model Abstraction:  Provider Adapters  (Anthropic/OpenAI/   │
│        Gemini/OpenRouter/local) · unified tool-call dialect  │
├────────────────────────────────────────────────────────────┤
│  Persistence:  SQLite (threads/sessions/cost) · Vector store │
│        · Project files (CONTEXT.md, agent defs, config)      │
├────────────────────────────────────────────────────────────┤
│  Safety:  Permission Broker · Sandbox · Checkpoint/Git       │
└────────────────────────────────────────────────────────────┘
```

**Key architectural decisions baked in:**
- The **Model Abstraction Layer (MAL)** is the spine. Everything above it works in a single internal representation of messages and tool calls. Adapters translate to/from each provider's wire format and normalize tool-calling, streaming, token counting, and prompt caching.
- The **Loop Engine** and a **named Agent** are decoupled: an agent is data (config), the loop is the engine that runs it. Sub-agents are just agents invoked with an isolated context.
- **Memory Manager** and **Context Assembler** are separate: memory *stores*, context assembly *decides what enters the prompt this turn* under a token budget.

---

## On-disk Layout (per project)

```
<project>/
├── .crabkey/
│   ├── config.toml            # project config (overrides global)
│   ├── CONTEXT.md             # project memory (human-readable, versioned)
│   ├── agents/                # project-scoped agent definitions
│   │   └── reviewer.toml
│   ├── threads/               # thread state (or in SQLite)
│   ├── index/                 # repo map / symbol index cache
│   └── memory.db              # SQLite: episodic log, cost, sessions
├── .crabkey/vectors/          # local vector store (semantic/procedural memory)
└── ...your code...
```

Global config and built-in agents live in the user config dir (e.g., `~/.config/crabkey/`).

---

## Example Loop Trace

```
GOAL: "Make the failing auth tests pass."
PLAN:
  1. Run test suite, identify failures               [verify]
  2. Read failing tests + implicated source          [file.read]
  3. Form hypothesis                                  [think]
  4. Apply minimal fix                                [file.edit]  → checkpoint #1
  5. Re-run tests                                     [verify]
  6. If fail → reflect, goto 3 (max 5 cycles)
  7. Summarize change, update CONTEXT.md (as diff)

STEP 1  verify → 3 failed (auth/token expiry, timezone)
STEP 2  read   → token.ts uses local time; tests assume UTC
STEP 3  think  → hypothesis: replace Date.now-local with UTC
STEP 4  edit   → token.ts (diff shown, auto-applied) [ckpt #1]
STEP 5  verify → 0 failed ✅
STEP 7  memory → propose CONTEXT.md note: "auth uses UTC; never local time"
TERMINATE: success criteria met. Spend: 41k in / 6k out · $0.27 · 5 steps.
```
