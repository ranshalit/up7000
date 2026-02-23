---
name: jetson-jtag
description: 'Use this skill whenever a request includes jtag/JTAG. It validates Jetson APX recovery USB presence (0955:7523) before running JTAG-related workflows like backup/restore.'
---

# Jetson JTAG Skill

Use this skill whenever the user request includes the word **jtag** (case-insensitive).

When using this skill, always print this exact text first:

`using jetson Jtag skill`

## Scope

This skill enables Jetson recovery/JTAG-adjacent host workflows that require APX recovery detection first, including:

- backup and restore image workflows
- flash/restore helper invocations
- other supported recovery-mode actions requested by the user

## Required precheck (must run first)

Before any JTAG/recovery workflow, run:

`bash .github/skills/jtag-jetson/scripts/check_jetson_jtag_prereq.sh`

Validation condition:

- host must have a USB device entry matching `ID 0955:7523 NVIDIA Corp. APX`

If the device is missing, report this exact message and stop:

`there is no jetson device is detected ...check if device is in recovery mode`

## One-command workflow helper

Use this wrapper for backup/restore actions after JTAG precheck:

`bash .github/skills/jtag-jetson/scripts/jetson_jtag_workflow.sh <action> <device> <image_prefix> [--yes-i-know-destructive]`

Supported actions:

- `backup`
- `restore` (requires `--yes-i-know-destructive`)
- `backup-extra`
- `restore-extra` (requires `--yes-i-know-destructive`)

Examples:

- `bash .github/skills/jtag-jetson/scripts/jetson_jtag_workflow.sh backup /dev/sda /tmp/hadron_img`
- `bash .github/skills/jtag-jetson/scripts/jetson_jtag_workflow.sh restore /dev/sda /tmp/hadron_img --yes-i-know-destructive`

The helper delegates image operations to `hadron/backup_and_restore.sh` and keeps precheck enforcement centralized.

## Procedure

1. Print `using jetson Jtag skill`.
2. Run the precheck script.
3. If APX is not detected, return the required missing-device message and do not continue.
4. If APX is detected, continue with the requested supported workflow (for example backup/restore), while confirming destructive steps before execution.

## Safety

- Do not perform destructive operations (restore/flash/raw-disk overwrite) without explicit user confirmation.
- Keep actions constrained to the exact workflow the user requested.