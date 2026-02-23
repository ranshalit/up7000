# Copilot coding agent instructions (UP-7000 workspace)

## What this repo is
- This workspace is primarily **device automation helpers** for an Intel UP 7000 target board.
- The main entrypoints live under `.github/skills/` (SSH/serial command runner + SCP deploy/copy).

## Device connections (host ↔ target)
- **Ethernet**: used for SSH/SCP to `target_user@target_ip` (for example, a USB gadget Ethernet link or direct LAN).
- **Serial**: used for Linux console access on `target_serial_device` (used as a fallback when SSH is unavailable, or when explicitly requested).

## Target defaults (used by automation)
These keys are parsed by `.github/skills/common/target_config.py` and used as defaults by the runners.

- `target_ip`: `192.168.55.1`
- `target_user`: `ubuntu`
- `target_password`: `ubuntu`
- `target_serial_device`: `/dev/ttyACM0`
- `target_prompt_regex`: `(?:<username>@<username>:.*[$#]|[$#]) ?$`

Notes:
- You can also override defaults via env vars: `JETSON_TARGET_IP`, `JETSON_TARGET_USER`, `JETSON_TARGET_PASSWORD`, `JETSON_TARGET_SERIAL_DEVICE`, `JETSON_TARGET_PROMPT_REGEX`.
- `<username>` / `<target_user>` placeholders in `target_prompt_regex` are replaced with the configured username.

## Common workflows
### Run commands on the device (SSH-first, serial fallback)
- Preferred wrapper (bootstraps a workspace-local venv at `.github/skills/terminal-command-inject/.venv`):
  - `bash .github/skills/terminal-command-inject/scripts/run_terminal_command.sh --transport auto --command 'uname -a'`
- Runner script:
  - `.github/skills/terminal-command-inject/scripts/terminal_command_runner.py`

### Copy/deploy files to the device (SCP + optional run)
- Runner script:
  - `.github/skills/scp-file-copy/scripts/ssh_scp_runner.py`
- Examples:
  - Push: `python3 .github/skills/scp-file-copy/scripts/ssh_scp_runner.py --scp-push ./local.txt /tmp/local.txt`
  - Pull: `python3 .github/skills/scp-file-copy/scripts/ssh_scp_runner.py --scp-pull /var/log/syslog ./syslog.from_target`
  - Deploy then run: `python3 .github/skills/scp-file-copy/scripts/ssh_scp_runner.py --scp-push ./my_tool /tmp/my_tool --command 'chmod +x /tmp/my_tool' --command '/tmp/my_tool --help'`

## Repo-specific conventions
- Don’t prompt for target credentials via terminal stdin; update the values in this file so runners pick them up automatically.
- For SCP password auth, the runner may require `sshpass` on the host (`sudo apt-get install sshpass`).
