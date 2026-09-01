# One-command setup + launch for the FBA Operations Manager bot, for Windows PowerShell.
# Same steps as start.sh (macOS/Linux): checks Ollama, pulls the model, starts the
# model server, sets up the Python backend, and launches the chat website.
#
# If PowerShell refuses to run this ("running scripts is disabled on this system"),
# run this once first: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $RepoRoot "backend"
$VenvDir = Join-Path $BackendDir "venv"
$Model = if ($env:AGENT_MODEL) { $env:AGENT_MODEL } else { "llama3.1" }
$Port = if ($env:PORT) { $env:PORT } else { "8000" }
$OllamaUrl = "http://localhost:11434/api/tags"

function Log($msg) { Write-Host "[start.ps1] $msg" }

function Test-Ollama {
    try {
        Invoke-WebRequest -Uri $OllamaUrl -UseBasicParsing -TimeoutSec 3 | Out-Null
        return $true
    } catch {
        return $false
    }
}

# 1. Ollama itself
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Log "Ollama isn't installed."
    Log "Download and run the installer from https://ollama.com/download/windows, then re-run this script (.\start.ps1)."
    exit 1
}
Log "Ollama found: $(ollama --version)"

# 2. Make sure the model server is reachable (it may already be running as a
#    background service after install, or from a previous run of this script).
if (-not (Test-Ollama)) {
    Log "Starting ollama serve in the background..."
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    $attempts = 0
    while (-not (Test-Ollama) -and $attempts -lt 30) {
        Start-Sleep -Seconds 1
        $attempts++
    }
}

if (Test-Ollama) {
    Log "Ollama server is up."
} else {
    Log "WARNING: couldn't confirm ollama serve is responding on :11434. Try running 'ollama serve' yourself in another PowerShell window, then re-run this script."
    exit 1
}

# 3. Model (ollama pull is itself idempotent - it no-ops quickly if already present)
Log "Making sure model '$Model' is pulled (first run downloads several GB, be patient)..."
ollama pull $Model

# 4. Python backend
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Log "Python isn't installed or isn't on PATH. Install it from https://python.org/downloads (check 'Add python.exe to PATH' during install), then re-run this script."
    exit 1
}

if (-not (Test-Path $VenvDir)) {
    Log "Creating Python virtual environment..."
    python -m venv $VenvDir
}

$activateScript = Join-Path $VenvDir "Scripts\Activate.ps1"
. $activateScript

Log "Installing backend dependencies..."
pip install -q -r (Join-Path $BackendDir "requirements.txt")

$envFile = Join-Path $BackendDir ".env"
$envExample = Join-Path $BackendDir ".env.example"
if (-not (Test-Path $envFile)) {
    Log "Creating backend\.env from .env.example (edit it later to add Keepa/SellerAmp keys for /analyze - not required for the chat bot)."
    Copy-Item $envExample $envFile
}

# 5. Launch
Log "Starting the FBA Operations Manager at http://localhost:$Port/"
Set-Location $BackendDir
$env:AGENT_MODEL = $Model
uvicorn main:app --host 0.0.0.0 --port $Port
