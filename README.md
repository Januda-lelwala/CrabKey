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

**Prerequisites:**

- **Python ≥ 3.11** (the engine's language — must be present)
- **Node.js ≥ 18** — used by the Ink/React TUI. **You don't need to install it
  yourself:** if no suitable Node is found, the installer downloads a private
  copy into `~/.local/share/crabkey/node` and uses it only for CrabKey. Your
  system is untouched. (Override the version with `CRABKEY_NODE_VERSION`.)

The installer creates a private virtualenv, installs the engine, provisions
Node, runs `npm install` for the TUI, and links the `crabkey` command.

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
| `install.sh` (recommended) | ✅ | Self-contained. Auto-downloads Node if missing — user only needs Python. |
| PyPI (`pip install`) | ⚠️ needs packaging work | Would require bundling `tui/` into the wheel; Node would not be auto-provisioned. |
