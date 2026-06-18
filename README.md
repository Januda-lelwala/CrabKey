# 🦀 CrabKey

A model-agnostic agentic coding CLI with a beautiful terminal UI.

The engine is **Python** (agent loop, tools, 12 model providers); the UI is an
**Ink (React) TUI** that renders the chat, agent loop, tool calls, and token
usage. The two halves talk over a local stdio pipe — there is no server.

## Install

CrabKey installs into a self-contained directory (`~/.local/share/crabkey`) and
puts a `crabkey` command on your PATH.

```bash
# From a published repo:
curl -fsSL https://raw.githubusercontent.com/Janudax/CrabKey/main/install.sh | bash

# Or from a local checkout:
./install.sh
```

**Prerequisites** (the installer checks for these):

- **Python ≥ 3.11**
- **Node.js ≥ 18** — required because the TUI is built with Ink/React

The installer creates a private virtualenv, installs the engine, runs
`npm install` for the TUI, and links the `crabkey` command.

## Usage

```bash
crabkey configure     # pick a provider, set your API key, choose a model
crabkey tui           # launch the Ink terminal UI
```

Other commands: `crabkey run "<goal>"`, `crabkey chat`, `crabkey providers`,
`crabkey models <provider>`.

## Uninstall

```bash
./install.sh --uninstall      # removes ~/.local/share/crabkey (config is kept)
```

## How the TUI works

See [`tui/README.md`](tui/README.md) for the architecture of the Ink frontend
and its JSON bridge to the Python engine.

## Distribution options

| Method | Ships the TUI? | Notes |
|---|---|---|
| `install.sh` (recommended) | ✅ | Owns Python + Node setup in one dir. Needs Node on the machine. |
| PyPI (`pip install`) | ⚠️ needs packaging work | Would require bundling `tui/` into the wheel and Node on the machine. |
