---
name: terminal-command-inject
description: 'Run commands and tests on the device (target) terminal via SSH (using target defaults from .github/copilot-instructions.md), or a serial console'
---

# Terminal Command Inject (SSH-first, serial fallback)

This skill runs a user-provided set of Linux commands on the target device, preferring SSH to the target defined in `.github/copilot-instructions.md` (`target_ip`, `target_user`, `target_password`, `target_prompt_regex`, `target_serial_device`) and falling back to a Linux serial console when SSH is unavailable.

This skill should interpret requests like:

- "run <something> on the device"
- "run these commands on the target IP"
- "ssh and run <something>"
- "if ssh fails, use serial"
- "do <something> in serial terminal"

Interpret these as the same target:

- **device / target**: `target_user@target_ip` from `.github/copilot-instructions.md`

If the user explicitly asks for **serial** or **serial terminal**, treat that as an explicit request to use the serial console as the first choice.

If the user does NOT mention "terminal" / "shell" and the request could refer to a non-console UART (packet/data stream), ask a clarifying question before using the serial fallback.

as: "run the corresponding Linux commands on the target, and return the captured output".

When using this skill, print a short banner to the terminal so it’s clear the skill was used:

```powershell
Write-Host "================================" -ForegroundColor Cyan
Write-Host "   [skill] terminal command" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
```

## Inputs (ask if missing)

- **commands**: a list of Linux commands (provided inline in the user message)

SSH inputs:

- **host**: default `target_ip` from `.github/copilot-instructions.md`
- **username**: default `target_user` from `.github/copilot-instructions.md`
- **password**: default `target_password` from `.github/copilot-instructions.md` (do not print in logs/transcripts)
- **port (optional)**: default `22`

If `target_ip`, `target_user`, or `target_password` is missing and not passed via CLI args, ask the user to provide it before running commands.

Do NOT request these values via terminal stdin prompts. Ask in AI chat, then update `.github/copilot-instructions.md` so future runs do not ask again.

If SSH authentication fails, do NOT fall back to serial immediately. First ask for corrected `target_user`/`target_password` in AI chat, update `.github/copilot-instructions.md`, and retry with SSH.

Serial fallback inputs (only if needed):

- **serial device path**: default `target_serial_device` from `.github/copilot-instructions.md` (if missing, ask user to provide it)
If `target_serial_device` is missing for serial runs, ask in AI chat and update `.github/copilot-instructions.md` before retrying.

- **baud rate**: default `115200` (assume 8N1, no flow control)
- **prompt regex**: default `target_prompt_regex` from `.github/copilot-instructions.md` (supports `<username>` placeholder)

## Safety

- Only run the commands the user provides.
- Do not run destructive commands unless the user explicitly asks.
- Do not print the password in logs or transcripts.
- For unattended runs, auto-answer interactive prompts when possible, even when this is risky.
- Treat these as auto-answer prompts unless the user explicitly requests strict fail-fast behavior: `sudo` password prompts, SSH host-key confirmation prompts, package-manager confirmation prompts, and common yes/no confirmations.
- When a command may require privilege escalation, provide configured credentials automatically and continue execution.
- If auto-answer is not possible, return a clear error with the prompt text and stop that command.

## Procedure

### 1) Collect parameters

Defaults:

- `host=target_ip`, `username=target_user`, `port=22` (from `.github/copilot-instructions.md`)
- `commandTimeoutSeconds=300`, `overallTimeoutSeconds=1800`
- Serial fallback: `serialDevice=target_serial_device`, `baud=115200`, `promptRegex=target_prompt_regex` (from `.github/copilot-instructions.md`)

Missing-config flow (required):

1. Detect missing keys (`target_ip`, `target_user`, `target_password`, and for serial runs `target_serial_device`).
2. Ask the user in AI chat for missing values.
3. Update `.github/copilot-instructions.md` with the provided values.
4. Re-run the command using updated defaults.

SSH-auth flow (required):

1. If SSH auth fails, request updated username/password in AI chat.
2. Update `.github/copilot-instructions.md` with corrected values.
3. Retry with `--transport ssh` first.
4. Only use serial fallback after SSH config is complete and SSH still fails for non-auth reasons.

Timeout behavior:

- If `commandTimeoutSeconds=0`, treat it as **no per-command limit** (commands can run until `overallTimeoutSeconds`).
- If `overallTimeoutSeconds=0`, treat it as **no overall limit**.

PC-host equivalent behavior:

- Use `--command-timeout 0 --overall-timeout 0` to behave like running commands directly in a normal host shell (no time limits unless the user interrupts).

If the user provides a different prompt, adapt `promptRegex` accordingly.

### 2) Preflight checks (host)

- Confirm tools exist: `command -v python3`
- (Optional) Check reachability: `ping -c 1 <target_ip>` where `<target_ip>` comes from `.github/copilot-instructions.md`

Recommended (to avoid repeated dependency installs / PATH issues): use the provided wrapper which creates a workspace-local venv using `/usr/bin/python3` and installs dependencies once:

- `.github/skills/terminal-command-inject/scripts/run_terminal_command.sh`

### 3) Run SSH command runner (preferred)

This skill uses the SSH-first helper script:

- `.github/skills/terminal-command-inject/scripts/terminal_command_runner.py`

Dependencies:

- `/usr/bin/python3` (preferred) or `python3`
- Dependencies are installed into a workspace-local venv on first run via the wrapper:
  - `.github/skills/terminal-command-inject/scripts/run_terminal_command.sh`

Example:

- `.github/skills/terminal-command-inject/scripts/run_terminal_command.sh \
  --transport auto \
  --host <target_ip> \
  --port 22 \
  --username <target_user> \
  --password <target_password> \
  --overall-timeout 1800 \
  --command-timeout 300 \
  --transcript-file /tmp/terminal-runner.log \
  --command '<cmd1>' \
  --command '<cmd2>' \
  --command '<cmdN>'`

For long-running operations (for example, installs), you can disable the per-command timeout:

- `.github/skills/terminal-command-inject/scripts/run_terminal_command.sh --command-timeout 0 --overall-timeout 1800 --command '<cmd>'`

If the user asked for **serial terminal**, run serial-first (with optional SSH fallback if serial fails):

- `.github/skills/terminal-command-inject/scripts/run_terminal_command.sh --transport serial --command '<cmd>'`

Serial-first behavior now classifies connection state immediately as one of:

- `there is a terminal connection - now we can run the shell commands in serial`
- `there is a terminal connection - but it is not linux shell` (reported as `serial is alive, but no linux shell`)
- `there is no terminal connection` (reported as `no terminal`)

Serial probe order in `--transport serial` is:

1. Try username first (assume `login:` state).
2. If `Password:` is seen, send password and check for Linux prompt.
3. If no Linux shell but any output characters are observed, classify as alive/no-linux-shell.
4. If no output is observed, classify as no terminal.

If SSH fails (auth, network, host key prompt, connection refused), proceed to the serial fallback.

Interactive prompt behavior during command execution:

- If output indicates an interactive prompt (password/confirmation prompt), attempt to auto-answer and continue command execution.
- For yes/no prompts, prefer affirmative answers by default unless the user asked otherwise.
- If a TUI/editor takes over (for example `vim`, `less`, `top`), send a safe exit sequence and continue with remaining commands.
- If the prompt cannot be answered automatically, stop that command and return a short remediation hint.

Additional output options:

- `--transcript-file <path>`: writes the full transcript to a local file.
- The runner prints a final summary (`transport`, command count, return code, duration) on completion.

### 4) Serial fallback runner (only if SSH unavailable)

This skill uses the existing helper script:

- `.github/skills/terminal-command-inject/scripts/serial_command_runner.py`

Dependencies:

- `python3`
- If you use `.github/skills/terminal-command-inject/scripts/run_terminal_command.sh`, it installs `pyserial` into the same venv automatically (needed for serial fallback).

Examples:

- Auto-detect device:

  `python3 .github/skills/terminal-command-inject/scripts/serial_command_runner.py \
    --auto \
    --baud 115200 \
    --prompt-regex '<target_prompt_regex>' \
    --overall-timeout 1800 \
    --command-timeout 300 \
    --command '<cmd1>' \
    --command '<cmd2>'`

- Explicit device:

  `python3 .github/skills/terminal-command-inject/scripts/serial_command_runner.py \
    --device <serialDevice> \
    --baud 115200 \
    --prompt-regex '<target_prompt_regex>' \
    --overall-timeout 1800 \
    --command-timeout 300 \
    --command '<cmd1>'`

If a login prompt appears, include:

- `--username <username> --password <password>` (avoid printing passwords in transcripts)

Liveness behavior:

- The serial runner actively probes the console (sends input such as newline/login text) and expects visible output back.
- If consecutive probes produce no characters, it fails fast with a "no serial connection" result instead of waiting for the full timeout.
- When this condition is detected, the runner does not retry serial and does not fall back to SSH for serial-only requests.

### 5) Output

Return the captured transcript to the user, grouped per command, and clearly indicate whether SSH or serial was used.

When `--transcript-file` is provided, include the transcript file path in your handoff so users can inspect the complete log.

## Notes / common issues

- If SSH is flaky, confirm the link (USB gadget ethernet vs. direct Ethernet) and that the device is booted.
- Boot logs over serial can be noisy; prompt detection may take time until Linux finishes booting.
- If serial is disconnected/unresponsive, the runner now exits quickly after active probe attempts with no returned output.
- If your prompt differs from `target_prompt_regex`, pass a different `--prompt-regex`.
