#!/usr/bin/env bash
# Usage: source activate_uv_script_venv.sh script.py
# Activates the uv ephemeral venv for the given script

if [ -z "$1" ]; then
  echo "Usage: source $0 <script.py>" >&2
  return 1 2>/dev/null || exit 1
fi

SCRIPT_PATH="$1"
# Add .py if not present
if [[ "$SCRIPT_PATH" != *.py ]]; then
  SCRIPT_PATH="${SCRIPT_PATH}.py"
fi

PYTHON_PATH=$(uv python find --script "$SCRIPT_PATH")
mkdir -p .vscode
if [ -f .vscode/settings.json ]; then
  jq --arg path "$PYTHON_PATH" '.["python.defaultInterpreterPath"] = $path' .vscode/settings.json > .vscode/settings.json.tmp && mv .vscode/settings.json.tmp .vscode/settings.json
else
  echo "{ \"python.defaultInterpreterPath\": \"$PYTHON_PATH\" }" > .vscode/settings.json
fi

if [ -z "$PYTHON_PATH" ]; then
  echo "Could not find a uv venv for $SCRIPT_PATH" >&2
  return 1 2>/dev/null || exit 1
fi

VENV_DIR="$(dirname "$(dirname "$PYTHON_PATH")")"
ACTIVATE_SCRIPT="$VENV_DIR/bin/activate"

if [ ! -f "$ACTIVATE_SCRIPT" ]; then
  echo "Activate script not found: $ACTIVATE_SCRIPT" >&2
  return 1 2>/dev/null || exit 1
fi

# shellcheck source=/dev/null
source "$ACTIVATE_SCRIPT"