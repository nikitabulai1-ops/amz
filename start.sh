#!/usr/bin/env bash
# One-command setup + launch for the FBA Operations Manager bot.
# Installs Ollama if missing, pulls the model, starts the model server,
# sets up the Python backend, and launches the chat website.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
VENV_DIR="$BACKEND_DIR/venv"
MODEL="${AGENT_MODEL:-llama3.1}"
PORT="${PORT:-8000}"
OLLAMA_URL="http://localhost:11434/api/tags"

log() { echo "[start.sh] $*"; }

# 1. Ollama itself
if ! command -v ollama >/dev/null 2>&1; then
  log "Ollama not found."
  case "$(uname -s)" in
    Linux|Darwin)
      log "Installing via the official script (curl https://ollama.com/install.sh | sh)..."
      curl -fsSL https://ollama.com/install.sh | sh
      ;;
    *)
      log "Automatic install isn't supported on this OS. Download it from https://ollama.com/download, then re-run this script."
      exit 1
      ;;
  esac
else
  log "Ollama already installed ($(ollama --version 2>/dev/null | head -n1))."
fi

# 2. Make sure the model server is actually reachable (it may already be running
#    as a background service after install, or from a previous run of this script).
if ! curl -sf "$OLLAMA_URL" >/dev/null 2>&1; then
  log "Starting ollama serve in the background (log: $REPO_ROOT/.ollama.log)..."
  nohup ollama serve >"$REPO_ROOT/.ollama.log" 2>&1 &
  for _ in $(seq 1 30); do
    curl -sf "$OLLAMA_URL" >/dev/null 2>&1 && break
    sleep 1
  done
fi

if curl -sf "$OLLAMA_URL" >/dev/null 2>&1; then
  log "Ollama server is up."
else
  log "WARNING: couldn't confirm ollama serve is responding on :11434. Check $REPO_ROOT/.ollama.log and re-run."
  exit 1
fi

# 3. Model (ollama pull is itself idempotent - it no-ops quickly if already present)
log "Making sure model '$MODEL' is pulled (first run downloads several GB, be patient)..."
ollama pull "$MODEL"

# 4. Python backend
if [ ! -d "$VENV_DIR" ]; then
  log "Creating Python virtual environment..."
  python3 -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
log "Installing backend dependencies..."
pip install -q -r "$BACKEND_DIR/requirements.txt"

if [ ! -f "$BACKEND_DIR/.env" ]; then
  log "Creating backend/.env from .env.example (edit it later to add Keepa/SellerAmp keys for /analyze — not required for the chat bot)."
  cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
fi

# 5. Launch
log "Starting the FBA Operations Manager at http://localhost:$PORT/"
cd "$BACKEND_DIR"
export AGENT_MODEL="$MODEL"
exec uvicorn main:app --host 0.0.0.0 --port "$PORT"
