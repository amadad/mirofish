#!/usr/bin/env bash
# One-command bootstrap for MiroFish on macOS / Linux.
#
# Usage:
#   ./scripts/setup.sh                       # interactive-ish, sensible defaults
#   ./scripts/setup.sh --provider codex-cli  # pick LLM provider (default: claude-cli)
#   ./scripts/setup.sh --yes                 # non-interactive (auto-install uv)
#
# What it does:
#   1. Verifies (or installs) uv
#   2. Creates .env from .env.example and sets LLM_PROVIDER
#   3. Installs dependencies with `uv sync`
#   4. Verifies the provider CLI is available and hints at login if needed
#   5. Runs `mirofish doctor` for a final health check

set -euo pipefail

PROVIDER="claude-cli"
ASSUME_YES=0

while [ $# -gt 0 ]; do
  case "$1" in
    --provider) PROVIDER="${2:?--provider requires a value}"; shift 2 ;;
    --yes|-y)   ASSUME_YES=1; shift ;;
    -h|--help)  grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1 (see --help)"; exit 2 ;;
  esac
done

case "$PROVIDER" in
  claude-cli|codex-cli) ;;
  *) echo "Unsupported provider '$PROVIDER' (expected: claude-cli | codex-cli)"; exit 2 ;;
esac

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARN\033[0m %s\n' "$*"; }

# --- 1. uv ------------------------------------------------------------------
if command -v uv >/dev/null 2>&1; then
  say "uv found: $(uv --version)"
else
  if [ "$ASSUME_YES" -ne 1 ]; then
    printf 'uv is not installed. Install it now from https://astral.sh/uv? [y/N] '
    read -r ans
    case "$ans" in y|Y|yes|YES) ;; *) echo "Aborted: uv is required."; exit 1 ;; esac
  fi
  say "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # The installer drops uv into ~/.local/bin (or ~/.cargo/bin on older setups)
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  command -v uv >/dev/null 2>&1 || { echo "uv installed but not on PATH; open a new shell and re-run."; exit 1; }
fi

# --- 2. .env ----------------------------------------------------------------
if [ ! -f .env ]; then
  cp .env.example .env
  say "Created .env from .env.example"
fi
if grep -q '^LLM_PROVIDER=' .env; then
  # portable in-place edit (BSD sed on macOS needs the '' argument)
  sed -i.bak "s/^LLM_PROVIDER=.*/LLM_PROVIDER=${PROVIDER}/" .env && rm -f .env.bak
else
  printf '\nLLM_PROVIDER=%s\n' "$PROVIDER" >> .env
fi
say "LLM_PROVIDER=${PROVIDER}"

# --- 3. dependencies --------------------------------------------------------
say "Installing dependencies (uv sync)..."
uv sync

# --- 4. provider CLI --------------------------------------------------------
case "$PROVIDER" in
  claude-cli)
    if command -v claude >/dev/null 2>&1; then
      say "claude CLI found: $(claude --version 2>/dev/null || echo 'version unknown')"
      warn "If you have never logged in, run 'claude' once and use /login (headless '-p' calls fail otherwise)."
    else
      warn "claude CLI not found on PATH. Install Claude Code (https://claude.com/claude-code) and log in before running simulations."
    fi
    ;;
  codex-cli)
    if command -v codex >/dev/null 2>&1; then
      say "codex CLI found."
    else
      warn "codex CLI not found on PATH. Install and authenticate it before running simulations."
    fi
    ;;
esac

# --- 5. health check --------------------------------------------------------
say "Running mirofish doctor..."
uv run mirofish doctor || warn "doctor reported issues (see above) — fix them before your first run."

say "Done. Try:"
printf '  uv run mirofish run --files <your-docs> --requirement "Predict public reaction over 30 days" --platform parallel --max-rounds 15\n'
