#!/usr/bin/env bash
# Source on OCI before normalize/ingest/generate:
#   source /mmoneyhome/mobiquity/fsd-model/scripts/env.sh

export FSD_HOME=/mmoneyhome/mobiquity/fsd-model
export FSD_DATA=/mmoneyhome/mobiquity/fsd-data

cd "$FSD_HOME" || {
  echo "ERROR: project not found at $FSD_HOME — git clone code there first."
  return 1 2>/dev/null || exit 1
}

export OLLAMA_MODELS="${OLLAMA_MODELS:-/mmoneyhome/mobiquity/.ollama/models}"
mkdir -p "$OLLAMA_MODELS"
mkdir -p "$FSD_DATA"/{fsds/FSD,normalized,index,output}

if [ -f "$FSD_HOME/.venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$FSD_HOME/.venv/bin/activate"
  echo "[env] venv activated: $FSD_HOME/.venv"
else
  echo "[env] WARNING: no .venv yet. Create with: python3 -m venv .venv"
fi

echo "[env] FSD_HOME=$FSD_HOME   (git code)"
echo "[env] FSD_DATA=$FSD_DATA   (docx / normalized / index / output / app.db)"
echo "[env] OLLAMA_MODELS=$OLLAMA_MODELS"
pwd
