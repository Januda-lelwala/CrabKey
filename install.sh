#!/usr/bin/env bash
#
# CrabKey installer.
#
# Installs the Python engine and the Ink (Node) terminal UI into a single
# self-contained directory, then puts a `crabkey` command on your PATH.
#
# Usage:
#   ./install.sh                      # install from this checked-out repo
#   curl -fsSL <raw-url>/install.sh | bash    # install from the published repo
#   ./install.sh --uninstall          # remove CrabKey
#
# Honors these environment variables:
#   CRABKEY_HOME      install location   (default: ~/.local/share/crabkey)
#   CRABKEY_BIN_DIR   where the shim goes (default: ~/.local/bin)
#   CRABKEY_REPO_URL  git URL to clone when not run from a local checkout
#
set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
CRABKEY_REPO_URL="${CRABKEY_REPO_URL:-https://github.com/Janudax/CrabKey.git}"
CRABKEY_HOME="${CRABKEY_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/crabkey}"
BIN_DIR="${CRABKEY_BIN_DIR:-$HOME/.local/bin}"
MIN_PY_MINOR=11      # require Python 3.11+
MIN_NODE_MAJOR=18    # require Node 18+
NODE_VERSION="${CRABKEY_NODE_VERSION:-v22.11.0}"   # vendored if no system Node

# ── Pretty output ────────────────────────────────────────────────────────────
if [ -t 1 ]; then
	C_RESET="$(printf '\033[0m')"; C_DIM="$(printf '\033[2m')"
	C_RED="$(printf '\033[31m')"; C_GREEN="$(printf '\033[32m')"
	C_YELLOW="$(printf '\033[33m')"; C_ORANGE="$(printf '\033[38;5;209m')"
else
	C_RESET=""; C_DIM=""; C_RED=""; C_GREEN=""; C_YELLOW=""; C_ORANGE=""
fi
info()  { printf '%s▸%s %s\n' "$C_ORANGE" "$C_RESET" "$1"; }
ok()    { printf '%s✓%s %s\n' "$C_GREEN" "$C_RESET" "$1"; }
warn()  { printf '%s⚠%s %s\n' "$C_YELLOW" "$C_RESET" "$1" >&2; }
die()   { printf '%s✗%s %s\n' "$C_RED" "$C_RESET" "$1" >&2; exit 1; }

# Stream a URL to stdout using whatever's available.
fetch() {
	if command -v curl >/dev/null 2>&1; then curl -fsSL "$1"
	elif command -v wget >/dev/null 2>&1; then wget -qO- "$1"
	else die "Need 'curl' or 'wget' to download files."; fi
}

# Ensure a usable Node ≥ MIN_NODE_MAJOR; vendor a private copy if missing.
# Sets the globals NODE_BIN (dir containing node/npm) and NPM (path to npm).
ensure_node() {
	if command -v node >/dev/null 2>&1 \
		&& [ "$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)" -ge "$MIN_NODE_MAJOR" ] \
		&& command -v npm >/dev/null 2>&1; then
		NODE_BIN="$(dirname "$(command -v node)")"
		ok "Node: $(node --version) (system)"
		NPM="$(command -v npm)"
		return
	fi

	# No suitable system Node — download the official prebuilt into the app dir.
	local os arch plat dest
	case "$(uname -s)" in
		Darwin) os=darwin ;;
		Linux)  os=linux  ;;
		*) die "Auto Node install isn't supported on $(uname -s). Install Node $MIN_NODE_MAJOR+ from https://nodejs.org and re-run." ;;
	esac
	case "$(uname -m)" in
		arm64|aarch64) arch=arm64 ;;
		x86_64|amd64)  arch=x64   ;;
		*) die "Auto Node install isn't supported on $(uname -m). Install Node $MIN_NODE_MAJOR+ from https://nodejs.org and re-run." ;;
	esac
	plat="node-${NODE_VERSION}-${os}-${arch}"
	dest="$CRABKEY_HOME/node"

	info "No system Node.js found — downloading a private copy ($plat)…"
	mkdir -p "$dest"
	fetch "https://nodejs.org/dist/${NODE_VERSION}/${plat}.tar.gz" \
		| tar -xz -C "$dest" --strip-components=1 \
		|| die "Failed to download Node.js. Check your connection, or install Node $MIN_NODE_MAJOR+ manually."

	NODE_BIN="$dest/bin"
	NPM="$NODE_BIN/npm"
	[ -x "$NODE_BIN/node" ] || die "Node download looks incomplete (no $NODE_BIN/node)."
	ok "Node: $("$NODE_BIN/node" --version) (private copy in $dest)"
}

# ── Uninstall ────────────────────────────────────────────────────────────────
if [ "${1:-}" = "--uninstall" ]; then
	info "Removing $CRABKEY_HOME"
	rm -rf "$CRABKEY_HOME"
	[ -L "$BIN_DIR/crabkey" ] && rm -f "$BIN_DIR/crabkey"
	ok "CrabKey uninstalled. (Config in ~/.config/crabkey was left untouched.)"
	exit 0
fi

printf '\n%s🦀  CrabKey installer%s\n\n' "$C_ORANGE" "$C_RESET"

# ── Prerequisite: Python ≥ 3.11 ──────────────────────────────────────────────
find_python() {
	for cand in python3.12 python3.11 python3.13 python3.14 python3; do
		if command -v "$cand" >/dev/null 2>&1; then
			if "$cand" -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, $MIN_PY_MINOR) else 1)" 2>/dev/null; then
				command -v "$cand"; return 0
			fi
		fi
	done
	return 1
}
PYTHON="$(find_python)" || die "Python 3.$MIN_PY_MINOR+ not found. Install it from https://python.org (or: brew install python@3.12)."
ok "Python: $("$PYTHON" --version 2>&1) ($PYTHON)"

# Node is provisioned *after* the source is in place (it may be vendored into
# the install dir). See ensure_node below.

# ── Obtain the source ────────────────────────────────────────────────────────
SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
	SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

info "Installing into $CRABKEY_HOME"
rm -rf "$CRABKEY_HOME"
mkdir -p "$CRABKEY_HOME"

if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/pyproject.toml" ] && [ -d "$SCRIPT_DIR/crabkey" ]; then
	info "Copying source from local checkout…"
	if command -v rsync >/dev/null 2>&1; then
		rsync -a --exclude '.git' --exclude '.venv' --exclude 'node_modules' \
			--exclude '__pycache__' --exclude '*.egg-info' \
			"$SCRIPT_DIR"/ "$CRABKEY_HOME"/
	else
		# rsync-free fallback
		(cd "$SCRIPT_DIR" && tar --exclude='.git' --exclude='.venv' \
			--exclude='node_modules' --exclude='__pycache__' --exclude='*.egg-info' \
			-cf - .) | (cd "$CRABKEY_HOME" && tar -xf -)
	fi
else
	info "Cloning $CRABKEY_REPO_URL…"
	command -v git >/dev/null 2>&1 || die "git is required to download CrabKey. Install git and retry."
	git clone --depth 1 "$CRABKEY_REPO_URL" "$CRABKEY_HOME"
fi

# ── Node (system or vendored) ────────────────────────────────────────────────
ensure_node
export PATH="$NODE_BIN:$PATH"   # so npm + tsx's `#!/usr/bin/env node` resolve

# ── Python venv + engine ─────────────────────────────────────────────────────
info "Creating Python virtual environment…"
"$PYTHON" -m venv "$CRABKEY_HOME/venv"
VENV_PY="$CRABKEY_HOME/venv/bin/python"
"$VENV_PY" -m pip install --quiet --upgrade pip
info "Installing the CrabKey engine (this can take a minute)…"
# Editable install keeps the package adjacent to tui/ so the launcher finds it.
"$VENV_PY" -m pip install --quiet -e "$CRABKEY_HOME"
ok "Engine installed."

# ── Ink TUI dependencies ─────────────────────────────────────────────────────
info "Installing TUI dependencies (npm)…"
( cd "$CRABKEY_HOME/tui" && "$NPM" install --omit=dev --no-audit --no-fund --silent )
ok "TUI installed."

# ── Shim on PATH ─────────────────────────────────────────────────────────────
mkdir -p "$BIN_DIR"
ln -sf "$CRABKEY_HOME/venv/bin/crabkey" "$BIN_DIR/crabkey"
ok "Linked $BIN_DIR/crabkey"

# ── Done ─────────────────────────────────────────────────────────────────────
printf '\n%s🦀  CrabKey is installed!%s\n\n' "$C_GREEN" "$C_RESET"
case ":$PATH:" in
	*":$BIN_DIR:"*) ;;
	*)
		warn "$BIN_DIR is not on your PATH. Add this to your shell profile:"
		printf '    %sexport PATH="%s:$PATH"%s\n\n' "$C_DIM" "$BIN_DIR" "$C_RESET"
		;;
esac
printf '  Get started:\n'
printf '    %scrabkey configure%s   set your provider, API key, and model\n' "$C_ORANGE" "$C_RESET"
printf '    %scrabkey tui%s         launch the terminal UI\n\n' "$C_ORANGE" "$C_RESET"
printf '  %sUninstall:%s  %s./install.sh --uninstall%s\n\n' "$C_DIM" "$C_RESET" "$C_DIM" "$C_RESET"
