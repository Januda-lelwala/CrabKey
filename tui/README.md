# CrabKey TUI

A beautiful terminal UI for CrabKey, built with [Ink](https://github.com/vadimdemedes/ink)
(React for the terminal). It renders the chat, agent loop, tool calls, and token
usage as React components — styled to feel like Claude Code / opencode.

## How it works

```
┌─────────────────┐   NDJSON over stdio   ┌──────────────────────────┐
│  Ink UI (Node)  │ ───────────────────▶ │  python -m crabkey       │
│  source/*.tsx   │ ◀─────────────────── │  .cli.bridge (engine)    │
└─────────────────┘   events + prompts    └──────────────────────────┘
```

The Ink app (`source/`) is pure presentation. The Python `crabkey.cli.bridge`
module wraps the existing engine (`LoopEngine`, tools, providers) and speaks a
small newline-delimited JSON protocol. See the docstring in `bridge.py` for the
message shapes.

## Running

The normal entry point is the Python CLI, which boots Node for you:

```bash
crabkey tui                 # or: python -m crabkey.cli.app tui
```

First launch runs `npm install` automatically.

## Developing the UI standalone

```bash
cd tui
npm install
CRABKEY_PYTHON=python3 CRABKEY_REPO=.. CRABKEY_CWD=.. npm start
npm run typecheck           # type-check without emitting
```

## Layout

| File | Responsibility |
|---|---|
| `source/cli.tsx` | Entry point; mounts `<App>` |
| `source/App.tsx` | State, protocol event handling, layout |
| `source/backend.ts` | Spawns the Python bridge, parses NDJSON |
| `source/markdown.tsx` | Tiny terminal markdown renderer |
| `source/components/` | Banner, Message, Prompt, StatusBar |
| `source/theme.ts` | Color palette |
