#!/usr/bin/env bash
set -euo pipefail

# Workspace-local bootstrap wrapper for terminal_command_runner.py.
# Creates a per-skill virtualenv using system Python and installs deps once.

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${SKILL_DIR}/.venv"
REQ_FILE="${SKILL_DIR}/requirements.txt"
RUNNER="${SKILL_DIR}/scripts/terminal_command_runner.py"

SYSTEM_PY="/usr/bin/python3"
if [[ -x "${SYSTEM_PY}" ]]; then
  BOOTSTRAP_PY="${SYSTEM_PY}"
else
  BOOTSTRAP_PY="$(command -v python3)"
fi

ensure_venv() {
  if [[ -x "${VENV_DIR}/bin/python" ]]; then
    return 0
  fi
  "${BOOTSTRAP_PY}" -m venv "${VENV_DIR}"
}

ensure_deps() {
  local vpy="${VENV_DIR}/bin/python"
  local vpip="${VENV_DIR}/bin/pip"

  # Avoid hitting the network on every run.
  if "${vpy}" -c 'import paramiko, serial' >/dev/null 2>&1; then
    return 0
  fi

  "${vpip}" install --upgrade pip >/dev/null
  "${vpip}" install -r "${REQ_FILE}"
}

ensure_venv
ensure_deps

exec "${VENV_DIR}/bin/python" "${RUNNER}" "$@"
