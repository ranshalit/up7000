---
name: scp-file-copy
description: 'copy (deploy) files/directories/scripts/tools/utility between the host and a device (target) via SCP using target defaults from .github/copilot-instructions.md. Also supports deploy-then-run workflows when the user asks to run/test/check a local binary/script on the device.'
---

# SCP File Copy + Deploy/Run

This skill performs file transfer between the host and the device using target defaults from `.github/copilot-instructions.md` (`target_ip`, `target_user`, `target_password`). It supports:

- **push** (host → device) and **pull** (device → host) via SCP (including recursive directory copy)
- **deploy-then-run**: when the user asks to **run/test/check** a local binary/script on the device, this skill should **SCP push** it first and then **run it on the device via SSH**.

Interpret requests like:

- "copy/push this file to the device"
- "pull logs from the target"
- "scp this folder over ethernet"
- "copy X to/from the device"

as: "use SCP to transfer the specified paths to/from `target_user@target_ip`, capture output per transfer, and stop on failure".

Also interpret requests like:

- "run/test/check this script on the device"
- "deploy and run ./my_tool on the device"
- "run ./foo.sh on target"

as: "SCP push the local artifact to the device, ensure it can be executed, then execute it on the device and capture output".

```powershell
Write-Host "================================" -ForegroundColor Cyan
Write-Host "   [skill] copy/deploy files" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
```

## Terminology mapping

Treat these as the same remote target:

- **network / over network / ethernet**: use SCP over the Ethernet link
- **device / target**: `target_user@target_ip` from `.github/copilot-instructions.md`

Copy directions:

- **push**: host → device (local path to remote path)
- **pull**: device → host (remote path to local path)

## Hard requirements

- Always use `target_ip` from `.github/copilot-instructions.md`.
- Default credentials:
  - SSH username: `target_user` from `.github/copilot-instructions.md`
  - SSH password: `target_password` from `.github/copilot-instructions.md`

Credentials are sourced from `.github/copilot-instructions.md` by default (or explicit CLI overrides), not from hardcoded script values.

If `target_ip`, `target_user`, or `target_password` is missing and not passed via CLI args, ask the user to provide it before running SCP/SSH actions.

Do NOT request these values via terminal stdin prompts. Ask in AI chat, then update `.github/copilot-instructions.md` so future runs do not ask again.

If the user explicitly asks to **run/test/check** something on the device, running remote commands **is allowed** only as needed to execute the deployed artifact and capture its output.

- Do not run unrelated remote commands.
- Prefer running only the deployed binary/script (plus minimal setup like `chmod +x`).

## Inputs (ask if missing)

- One or more SCP actions:
  - **push**: local path → remote path
  - **pull**: remote path → local path
- Whether each action is **recursive** (required for directories).
- Whether overwriting an existing destination is acceptable (if not specified, ask).

If the user did not provide any SCP action, ask whether they want **push** (host → device) or **pull** (device → host), and which paths.

For deploy-then-run requests, ask only if truly necessary. Otherwise use safe defaults:

- Remote deploy path default: `/tmp/<basename>`
- If overwriting is not specified: ask before overwriting an existing remote path
- If the user does not specify how to execute: default to `chmod +x` and run it as `./<basename>` (or `bash <file>` if it ends with `.sh`)

## Safety

- Only perform the exact copy actions the user provides.
- Do not delete or modify remote files beyond copying.
- Never print passwords in logs or transcripts.

If the copy target looks ambiguous or risky (for example, copying into `/` or overwriting a system file), stop and confirm with the user.

For deploy-then-run, also stop and confirm if:

- The requested command looks destructive (e.g. mentions `rm -rf`, `mkfs`, raw block devices, `dd`, partitioning)
- The user requests running under `sudo` without a clear reason

## Procedure

### 1) Preflight checks (host)

- Confirm tools exist: `command -v scp ssh python3`
- (Optional) Check device reachable: `ping -c 1 <target_ip>` where `<target_ip>` comes from `.github/copilot-instructions.md`

Missing-config flow (required):

1. Detect missing keys (`target_ip`, `target_user`, `target_password`).
2. Ask the user in AI chat for missing values.
3. Update `.github/copilot-instructions.md` with the provided values.
4. Re-run SCP/SSH actions using updated defaults.

### 2) Run the SCP runner

This skill uses the helper script:

- `.github/skills/scp-file-copy/scripts/ssh_scp_runner.py`

Dependencies:

- `python3`
- `sshpass` (recommended for password-based automation): `sudo apt-get install sshpass`

The runner supports both authentication styles:

- **SSH keys** (preferred when configured): fully non-interactive.
- **Password** via `sshpass`: uses the provided `--password` (default `target_password` from `.github/copilot-instructions.md`).

By default (`--auth auto`), it will **try SSH keys first** and **fall back to sshpass**.

Reliability options:

- `--overall-timeout <seconds>`: caps total runtime for the full action list (`0` means no overall limit).
- `--scp-timeout <seconds>`: per-transfer timeout (`0` means no per-transfer limit).
- `--scp-retries <count>`: retry failed SCP/rsync transfers this many times.
- `--retry-delay <seconds>`: delay between retries.
- `--scp-resume`: use `rsync --partial --append-verify` for resumable transfers (requires `rsync` on host and target).

Examples:

- SCP push (host → device):

  `python3 .github/skills/scp-file-copy/scripts/ssh_scp_runner.py \
    --scp-push ./local_file.txt /tmp/local_file.txt`

- SCP push directory recursively:

  `python3 .github/skills/scp-file-copy/scripts/ssh_scp_runner.py \
    --scp-push ./local_folder /tmp/local_folder \
    --scp-recursive`

- SCP pull (device → host):

  `python3 .github/skills/scp-file-copy/scripts/ssh_scp_runner.py \
    --scp-pull /var/log/syslog ./syslog.from_target`

- Resumable transfer with retries (recommended for large files):

  `python3 .github/skills/scp-file-copy/scripts/ssh_scp_runner.py \
    --scp-push ./big_image.raw /tmp/big_image.raw \
    --scp-resume \
    --scp-retries 3 \
    --retry-delay 2 \
    --scp-timeout 0 \
    --overall-timeout 3600`

- Multiple transfers in one run:

  `python3 .github/skills/scp-file-copy/scripts/ssh_scp_runner.py \
    --scp-push ./a.txt /tmp/a.txt \
    --scp-pull /etc/os-release ./os-release.from_target`

- Deploy-then-run (push + execute):

  `python3 .github/skills/scp-file-copy/scripts/ssh_scp_runner.py \
    --scp-push ./my_tool /tmp/my_tool \
    --command "chmod +x /tmp/my_tool" \
    --command "/tmp/my_tool --help"`

- Force password mode (sshpass) even if keys exist:

  `python3 .github/skills/scp-file-copy/scripts/ssh_scp_runner.py \
    --auth sshpass \
    --scp-push ./local_file.txt /tmp/local_file.txt`

- Force key-only mode (fail fast if keys aren’t set up):

  `python3 .github/skills/scp-file-copy/scripts/ssh_scp_runner.py \
    --auth key \
    --scp-push ./local_file.txt /tmp/local_file.txt`

- Deploy-then-run a shell script:

  `python3 .github/skills/scp-file-copy/scripts/ssh_scp_runner.py \
    --scp-push ./test.sh /tmp/test.sh \
    --command "bash /tmp/test.sh"`

### 3) Expected behavior

The runner will:

1. Transfer each requested path using SCP to/from `target_user@target_ip` (from `.github/copilot-instructions.md`).
2. If `--command` is provided (deploy-then-run), open an SSH session and run the commands after SCP.
3. Capture output and exit status for each transfer and each command.
4. Stop immediately on failure and report what failed (unless `--continue-on-error` is used).
5. Return a transcript grouped per transfer and per command.
6. Print a final action summary with per-item status, attempt count, and elapsed duration.

## Notes / common issues

- First connection host-key prompts can hang automation; the runner disables strict host key checking for this reason.
- If the device reboots or the link drops, rerun after connectivity returns.
