# One-command bootstrap for MiroFish on Windows (PowerShell 5.1+).
#
# Usage:
#   .\scripts\setup.ps1                        # sensible defaults
#   .\scripts\setup.ps1 -Provider codex-cli    # pick LLM provider (default: claude-cli)
#   .\scripts\setup.ps1 -Yes                   # non-interactive (auto-install uv)
#
# What it does:
#   1. Verifies (or installs) uv
#   2. Creates .env from .env.example and sets LLM_PROVIDER
#   3. Installs dependencies with `uv sync`
#   4. Verifies the provider CLI is available and hints at login if needed
#   5. Runs `mirofish doctor` for a final health check
#
# Note: full Windows runtime support for the claude-cli provider also needs
# the fixes in PR #26 (POSIX cwd, argv length limit, cp1252 decoding).

param(
    [ValidateSet("claude-cli", "codex-cli")]
    [string]$Provider = "claude-cli",
    [switch]$Yes
)

$ErrorActionPreference = "Stop"
$RepoDir = Split-Path -Parent $PSScriptRoot
Set-Location $RepoDir

function Say($msg)  { Write-Host "==> $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "WARN $msg" -ForegroundColor Yellow }

# --- 1. uv ------------------------------------------------------------------
if (Get-Command uv -ErrorAction SilentlyContinue) {
    Say "uv found: $(uv --version)"
} else {
    if (-not $Yes) {
        $ans = Read-Host "uv is not installed. Install it now from https://astral.sh/uv? [y/N]"
        if ($ans -notmatch '^(y|yes)$') { Write-Host "Aborted: uv is required."; exit 1 }
    }
    Say "Installing uv..."
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Host "uv installed but not on PATH; open a new terminal and re-run."
        exit 1
    }
}

# --- 2. .env ----------------------------------------------------------------
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Say "Created .env from .env.example"
}
$envText = Get-Content ".env" -Raw
if ($envText -match "(?m)^LLM_PROVIDER=") {
    $envText = $envText -replace "(?m)^LLM_PROVIDER=.*$", "LLM_PROVIDER=$Provider"
} else {
    $envText = $envText.TrimEnd() + "`nLLM_PROVIDER=$Provider`n"
}
[IO.File]::WriteAllText((Join-Path $RepoDir ".env"), $envText, (New-Object System.Text.UTF8Encoding($false)))
Say "LLM_PROVIDER=$Provider"

# --- 3. UTF-8 (Windows defaults to a legacy code page like cp1252) ----------
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
Say "PYTHONUTF8=1 set for this session (add it to your user environment variables for permanence)"

# --- 4. dependencies --------------------------------------------------------
Say "Installing dependencies (uv sync)..."
uv sync
if ($LASTEXITCODE -ne 0) { Write-Host "uv sync failed."; exit 1 }

# --- 5. provider CLI --------------------------------------------------------
if ($Provider -eq "claude-cli") {
    if (Get-Command claude -ErrorAction SilentlyContinue) {
        Say "claude CLI found."
        Warn "If you have never logged in, run 'claude' once and use /login (headless '-p' calls fail otherwise)."
    } else {
        Warn "claude CLI not found on PATH. Install Claude Code (https://claude.com/claude-code) and log in before running simulations."
    }
} else {
    if (Get-Command codex -ErrorAction SilentlyContinue) {
        Say "codex CLI found."
    } else {
        Warn "codex CLI not found on PATH. Install and authenticate it before running simulations."
    }
}

# --- 6. health check --------------------------------------------------------
Say "Running mirofish doctor..."
uv run mirofish doctor
if ($LASTEXITCODE -ne 0) { Warn "doctor reported issues (see above) - fix them before your first run." }

Say "Done. Try:"
Write-Host '  uv run mirofish run --files <your-docs> --requirement "Predict public reaction over 30 days" --platform parallel --max-rounds 15'
