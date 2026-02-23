#!/usr/bin/env python3

import argparse
import glob
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

SKILLS_DIR = Path(__file__).resolve().parents[2]
if str(SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(SKILLS_DIR))

from common.target_config import load_target_defaults

TARGET_DEFAULTS = load_target_defaults()

DEFAULT_HOST = TARGET_DEFAULTS.ip
DEFAULT_USERNAME = TARGET_DEFAULTS.user
DEFAULT_PASSWORD = TARGET_DEFAULTS.password
DEFAULT_SERIAL_DEVICE = TARGET_DEFAULTS.serial_device
DEFAULT_PORT = 22
NO_SERIAL_CONNECTION_EXIT_CODE = 12
ALIVE_NO_LINUX_SHELL_EXIT_CODE = 13

DEFAULT_SSH_CONNECT_TIMEOUT_S = 5.0

# Default shell prompt matcher is resolved from target defaults in copilot instructions.
DEFAULT_PROMPT_REGEX = TARGET_DEFAULTS.prompt_regex


@dataclass
class RunnerConfig:
    transport: str
    host: str
    port: int
    username: str
    password: str
    overall_timeout: float
    command_timeout: float
    prompt_regex: str

    # SSH
    ssh_connect_timeout: float

    # Serial fallback
    serial_device: Optional[str]
    serial_auto: bool
    serial_baud: int
    serial_line_ending: str
    serial_username: Optional[str]


def _write_transcript(path: Optional[str], content: str) -> None:
    if not path:
        return
    try:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    except Exception as exc:
        print(f"[terminal-runner] WARNING: failed to write transcript file {path}: {exc}", file=sys.stderr)


def _print_summary(transport: str, rc: int, started_at: float, transcript: str) -> None:
    duration = _now() - started_at
    command_count = transcript.count("===== COMMAND")
    print("[terminal-runner] summary:")
    print(f"[terminal-runner]   transport={transport}")
    print(f"[terminal-runner]   commands={command_count}")
    print(f"[terminal-runner]   rc={int(rc)}")
    print(f"[terminal-runner]   duration_s={duration:.2f}")


def _now() -> float:
    return time.monotonic()


def _run(
    argv: List[str],
    *,
    timeout: Optional[float] = None,
) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, str) else ""
        err = exc.stderr if isinstance(exc.stderr, str) else ""
        timeout_msg = (
            f"[terminal-runner] ERROR: subprocess timed out after {float(exc.timeout):.1f}s"
            if exc.timeout is not None
            else "[terminal-runner] ERROR: subprocess timed out"
        )
        if err:
            err = f"{err.rstrip()}\n{timeout_msg}\n"
        else:
            err = timeout_msg + "\n"
        return 124, out, err


def _deadline_from_timeout(timeout_s: float) -> float:
    if timeout_s <= 0:
        return float("inf")
    return _now() + timeout_s


def _try_import_paramiko():
    try:
        import paramiko  # type: ignore

        return paramiko, None
    except Exception as exc:
        return None, exc


def _decode_bytes(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


_SUDO_PROMPT_RE = re.compile(r"(\[sudo\]\s+password\s+for\s+[^:]+:|password\s+for\s+[^:]+:|\r?\nPassword:\s*$)", re.IGNORECASE | re.MULTILINE)


def _run_remote_command_interactive(
    client,
    command: str,
    *,
    password: str,
    timeout_s: float,
) -> Tuple[int, str, str]:
    """Run a remote command via an interactive PTY channel.

    This is used to support commands that may prompt (notably `sudo`).
    The password is only sent when a password prompt is detected.
    """

    transport = client.get_transport()
    if transport is None:
        return 255, "", "[terminal-runner] ERROR: SSH transport not available\n"

    chan = transport.open_session()
    chan.get_pty()
    chan.exec_command(command)

    started = _now()
    stdout_chunks: List[str] = []
    stderr_chunks: List[str] = []
    sent_password = False

    def _combined_tail(max_chars: int = 4000) -> str:
        combined = "".join(stdout_chunks) + "".join(stderr_chunks)
        return combined[-max_chars:]

    while True:
        if chan.recv_ready():
            stdout_chunks.append(_decode_bytes(chan.recv(4096)))

        if chan.recv_stderr_ready():
            stderr_chunks.append(_decode_bytes(chan.recv_stderr(4096)))

        if (not sent_password) and password and _SUDO_PROMPT_RE.search(_combined_tail()):
            try:
                chan.send(password + "\n")
                sent_password = True
            except Exception:
                # If we cannot send the password, continue and let the command fail.
                sent_password = True

        if chan.exit_status_ready():
            break

        if timeout_s > 0 and (_now() - started) > timeout_s:
            try:
                chan.close()
            except Exception:
                pass
            return 124, "".join(stdout_chunks), "".join(stderr_chunks) + f"\n[terminal-runner] ERROR: command timed out after {timeout_s:.1f}s\n"

        time.sleep(0.05)

    rc = int(chan.recv_exit_status())
    return rc, "".join(stdout_chunks), "".join(stderr_chunks)


def _try_run_commands_over_ssh(cfg: RunnerConfig, commands: List[str]) -> Tuple[bool, int, str]:
    paramiko, import_exc = _try_import_paramiko()
    if paramiko is None:
        return (
            False,
            255,
            "[terminal-runner] paramiko not available.\n"
            f"[terminal-runner] python: {sys.executable}\n"
            "[terminal-runner] recommended: run via the workspace wrapper to bootstrap a per-skill venv:\n"
            "[terminal-runner]   .github/skills/terminal-command-inject/scripts/run_terminal_command.sh ...\n"
            "[terminal-runner] alternative: install into THIS interpreter with:\n"
            f"[terminal-runner]   {sys.executable} -m pip install paramiko\n"
            + f"[terminal-runner] import error: {type(import_exc).__name__}: {import_exc}",
        )

    overall_deadline = _deadline_from_timeout(cfg.overall_timeout)

    transcript: List[str] = []
    transcript.append("[terminal-runner] transport: ssh")
    transcript.append(f"[terminal-runner] target: {cfg.username}@{cfg.host}:{cfg.port}")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(
            hostname=cfg.host,
            port=cfg.port,
            username=cfg.username,
            password=cfg.password,
            timeout=cfg.ssh_connect_timeout,
            banner_timeout=cfg.ssh_connect_timeout,
            auth_timeout=cfg.ssh_connect_timeout,
            look_for_keys=False,
            allow_agent=False,
        )
    except Exception as exc:
        msg = str(exc).strip()
        if msg:
            transcript.append(f"[terminal-runner] SSH connect failed: {type(exc).__name__}: {msg}")
        else:
            transcript.append(f"[terminal-runner] SSH connect failed: {type(exc).__name__}")
        return False, 255, "\n".join(transcript) + "\n"

    try:
        exit_code = 0
        for i, cmd in enumerate(commands, start=1):
            remaining = max(0.1, overall_deadline - _now())
            per_cmd_timeout = remaining if cfg.command_timeout <= 0 else min(cfg.command_timeout, remaining)

            if remaining <= 0:
                transcript.append("[terminal-runner] ERROR: overall timeout exceeded")
                return True, 5, "\n".join(transcript) + "\n"

            transcript.append(f"===== COMMAND {i}/{len(commands)} =====")
            transcript.append(f"$ {cmd}")

            try:
                status, out, err = _run_remote_command_interactive(
                    client,
                    cmd,
                    password=cfg.password,
                    timeout_s=float(per_cmd_timeout),
                )
            except Exception as exc:
                transcript.append(
                    f"[terminal-runner] ERROR: command execution failed: {type(exc).__name__}: {str(exc).strip()}"
                )
                # SSH is up, but the command failed to execute/read within the requested bounds.
                # Do not fall back to serial in this case.
                return True, 124, "\n".join(transcript) + "\n"

            if out:
                transcript.append(out.rstrip("\n"))
            if err:
                transcript.append(err.rstrip("\n"))

            if int(status) != 0:
                transcript.append(f"[terminal-runner] NOTE: remote exit status {int(status)}")
                if exit_code == 0:
                    exit_code = int(status)

        transcript.append("[terminal-runner] done")
        return True, int(exit_code), "\n".join(transcript) + "\n"
    finally:
        try:
            client.close()
        except Exception:
            pass


def _serial_runner_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "serial_command_runner.py")


def _run_commands_over_serial_fallback(cfg: RunnerConfig, commands: List[str]) -> Tuple[int, str, str]:
    runner = _serial_runner_path()

    argv = [sys.executable, runner]

    if cfg.serial_device:
        argv += ["--device", cfg.serial_device]
    else:
        devices = _collect_serial_devices(cfg)
        if len(devices) == 1:
            argv += ["--device", devices[0]]
        else:
            argv += ["--auto"]

    argv += [
        "--baud",
        str(cfg.serial_baud),
        "--prompt-regex",
        cfg.prompt_regex,
        "--overall-timeout",
        str(cfg.overall_timeout),
        "--command-timeout",
        str(cfg.command_timeout),
        "--line-ending",
        cfg.serial_line_ending,
    ]

    if cfg.serial_username:
        argv += ["--username", cfg.serial_username]
    else:
        argv += ["--username", cfg.username]

    argv += ["--password", cfg.password]

    for cmd in commands:
        argv += ["--command", cmd]

    subprocess_timeout = None if cfg.overall_timeout <= 0 else (cfg.overall_timeout + 5.0)
    rc, out, err = _run(argv, timeout=subprocess_timeout)
    return rc, out, err


def _is_no_serial_connection_result(rc: int, out: str, err: str) -> bool:
    if int(rc) == NO_SERIAL_CONNECTION_EXIT_CODE:
        return True
    combined = f"{out}\n{err}".lower()
    return (
        "no serial connection" in combined
        or "connection appears inactive" in combined
        or "no terminal" in combined
    )


def _is_serial_alive_no_linux_shell_result(rc: int, out: str, err: str) -> bool:
    if int(rc) == ALIVE_NO_LINUX_SHELL_EXIT_CODE:
        return True
    combined = f"{out}\n{err}".lower()
    return "serial is alive, but no linux shell" in combined


def _is_serial_unavailable_result(out: str, err: str) -> bool:
    combined = f"{out}\n{err}".lower()
    signals = (
        "no serial devices found",
        "could not auto-detect a responding serial console",
        "could not open port",
        "permission denied",
        "serial error",
    )
    return any(token in combined for token in signals)


def _is_ssh_auth_failure(transcript: str) -> bool:
    combined = (transcript or "").lower()
    signals = (
        "authenticationexception",
        "authentication failed",
        "auth failed",
        "bad authentication",
        "permission denied",
    )
    return any(token in combined for token in signals)


def _collect_serial_devices(cfg: RunnerConfig) -> List[str]:
    if cfg.serial_device:
        return [cfg.serial_device]

    candidates = sorted(set(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")))
    return [path for path in candidates if os.path.exists(path)]


def _pids_using_device(device: str) -> List[int]:
    pids: List[int] = []

    if shutil.which("lsof"):
        rc, out, _ = _run(["lsof", "-t", device])
        if rc == 0 and out.strip():
            for token in out.split():
                if token.isdigit():
                    pids.append(int(token))
            return sorted(set(pids))

    if shutil.which("fuser"):
        rc, out, err = _run(["fuser", device])
        combined = f"{out}\n{err}"
        if rc == 0 and combined.strip():
            for token in re.findall(r"\d+", combined):
                pids.append(int(token))

    return sorted(set(pids))


def _terminate_serial_holders(cfg: RunnerConfig) -> str:
    devices = _collect_serial_devices(cfg)
    if not devices:
        return "[terminal-runner] serial cleanup: no /dev/ttyUSB* or /dev/ttyACM* devices found"

    lines: List[str] = []
    for device in devices:
        pids = _pids_using_device(device)
        if not pids:
            lines.append(f"[terminal-runner] serial cleanup: no holder process on {device}")
            continue

        lines.append(f"[terminal-runner] serial cleanup: {device} held by pids {pids}; terminating")
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                continue
            except PermissionError:
                lines.append(f"[terminal-runner] serial cleanup: no permission to terminate pid {pid}")

        time.sleep(0.5)

        remaining: List[int] = []
        for pid in pids:
            try:
                os.kill(pid, 0)
                remaining.append(pid)
            except ProcessLookupError:
                continue
            except PermissionError:
                remaining.append(pid)

        if remaining:
            lines.append(f"[terminal-runner] serial cleanup: escalating to SIGKILL for pids {remaining}")
            for pid in remaining:
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass

    return "\n".join(lines)


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Run Linux commands on the target device via SSH and/or serial console. "
            "Default transport is SSH-first with serial fallback. Passwords are never printed."
        )
    )

    # Common
    p.add_argument("--command", action="append", default=[], help="Command to run (repeatable)")
    p.add_argument(
        "--transport",
        choices=["auto", "ssh", "serial"],
        default="auto",
        help=(
            "Transport selection: auto=SSH-first then serial fallback; "
            "ssh=SSH only; serial=serial first then SSH fallback."
        ),
    )
    p.add_argument(
        "--overall-timeout",
        type=float,
        default=1800,
        help="Overall timeout seconds for the whole run. Use 0 for no overall limit.",
    )
    p.add_argument(
        "--command-timeout",
        type=float,
        default=300,
        help="Per-command timeout seconds. Use 0 for no per-command limit (overall timeout still applies).",
    )
    p.add_argument(
        "--transcript-file",
        default=None,
        help="Optional path to write full runner transcript output.",
    )

    # Prompt regex (primarily for serial fallback; kept for backwards compatibility)
    p.add_argument("--prompt-regex", default=DEFAULT_PROMPT_REGEX)

    # SSH
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--username", default=DEFAULT_USERNAME)
    p.add_argument("--password", default=DEFAULT_PASSWORD, help="SSH password from target defaults")
    p.add_argument("--ssh-connect-timeout", type=float, default=DEFAULT_SSH_CONNECT_TIMEOUT_S)

    # Serial fallback
    serial = p.add_argument_group("serial fallback")
    serial.add_argument("--serial-device", default=(DEFAULT_SERIAL_DEVICE or None), help="Serial device path (e.g. /dev/ttyUSB* or /dev/ttyACM*)")
    serial.add_argument("--serial-auto", action="store_true", help="Auto-detect /dev/ttyUSB* or /dev/ttyACM*")
    serial.add_argument("--serial-baud", type=int, default=115200)
    serial.add_argument(
        "--serial-line-ending",
        choices=["CR", "LF", "CRLF"],
        default="CR",
        help="Line ending used for serial writes (default CR)",
    )
    serial.add_argument("--serial-username", default=None)

    args = p.parse_args(argv)
    if not str(args.host or "").strip():
        p.error("Missing target config: `target_ip`. Ask in Copilot chat and update .github/copilot-instructions.md, or pass --host.")
    if not str(args.username or "").strip():
        p.error("Missing target config: `target_user`. Ask in Copilot chat and update .github/copilot-instructions.md, or pass --username.")
    if not str(args.password or "").strip():
        p.error("Missing target config: `target_password`. Ask in Copilot chat and update .github/copilot-instructions.md, or pass --password.")
    if str(args.transport) == "serial" and not str(args.serial_device or "").strip():
        p.error("Missing target config: `target_serial_device`. Ask in Copilot chat and update .github/copilot-instructions.md, or pass --serial-device.")
    if not args.command:
        p.error("At least one --command is required")

    if not args.serial_device and not args.serial_auto:
        args.serial_auto = True

    return args


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    started_at = _now()

    cfg = RunnerConfig(
        transport=str(args.transport),
        host=str(args.host),
        port=int(args.port),
        username=str(args.username),
        password=str(args.password),
        overall_timeout=float(args.overall_timeout),
        command_timeout=float(args.command_timeout),
        prompt_regex=str(args.prompt_regex),
        ssh_connect_timeout=float(args.ssh_connect_timeout),
        serial_device=args.serial_device,
        serial_auto=bool(args.serial_auto),
        serial_baud=int(args.serial_baud),
        serial_line_ending=str(args.serial_line_ending),
        serial_username=args.serial_username,
    )

    commands = list(args.command)

    if cfg.transport == "ssh":
        ssh_ok, exit_code, transcript = _try_run_commands_over_ssh(cfg, commands)
        print(transcript, file=sys.stderr if not ssh_ok else sys.stdout)
        final_rc = int(exit_code if ssh_ok else 255)
        _write_transcript(args.transcript_file, transcript)
        _print_summary("ssh", final_rc, started_at, transcript)
        return final_rc

    if cfg.transport == "serial":
        serial_transcript_parts: List[str] = []
        print("[terminal-runner] serial mode selected; cleaning up serial holders", file=sys.stderr)
        cleanup_text = _terminate_serial_holders(cfg)
        print(cleanup_text, file=sys.stderr)
        serial_transcript_parts.append(cleanup_text)

        rc, out, err = _run_commands_over_serial_fallback(cfg, commands)
        if out:
            print(out, end="" if out.endswith("\n") else "\n")
            serial_transcript_parts.append(out)
        if err:
            print(err, file=sys.stderr, end="" if err.endswith("\n") else "\n")
            serial_transcript_parts.append(err)

        serial_transcript = "\n".join(serial_transcript_parts)

        if rc == 0:
            _write_transcript(args.transcript_file, serial_transcript)
            _print_summary("serial", 0, started_at, serial_transcript)
            return 0

        if _is_serial_alive_no_linux_shell_result(rc, out, err):
            print("[terminal-runner] serial is alive, but no linux shell", file=sys.stderr)
            final_rc = int(ALIVE_NO_LINUX_SHELL_EXIT_CODE)
            _write_transcript(args.transcript_file, serial_transcript)
            _print_summary("serial", final_rc, started_at, serial_transcript)
            return final_rc

        if _is_no_serial_connection_result(rc, out, err) or _is_serial_unavailable_result(out, err):
            print("[terminal-runner] no terminal", file=sys.stderr)
            final_rc = int(NO_SERIAL_CONNECTION_EXIT_CODE)
            _write_transcript(args.transcript_file, serial_transcript)
            _print_summary("serial", final_rc, started_at, serial_transcript)
            return final_rc

        print("[terminal-runner] serial failed", file=sys.stderr)
        final_rc = int(rc)
        _write_transcript(args.transcript_file, serial_transcript)
        _print_summary("serial", final_rc, started_at, serial_transcript)
        return final_rc

    # auto (default): SSH-first then serial fallback
    ssh_ok, exit_code, transcript = _try_run_commands_over_ssh(cfg, commands)
    if ssh_ok:
        print(transcript)
        final_rc = int(exit_code)
        _write_transcript(args.transcript_file, transcript)
        _print_summary("auto(ssh)", final_rc, started_at, transcript)
        return final_rc

    print(transcript, file=sys.stderr)

    if _is_ssh_auth_failure(transcript):
        print(
            "[terminal-runner] ssh authentication failed; update `target_user`/`target_password` in .github/copilot-instructions.md via AI chat and retry with --transport ssh.",
            file=sys.stderr,
        )
        return 255

    print("[terminal-runner] ssh failed; attempting serial fallback...", file=sys.stderr)

    ssh_timeout = ("TimeoutError" in transcript) or ("timed out" in transcript.lower())
    if ssh_timeout:
        print("[terminal-runner] ssh timeout detected; cleaning up serial holders before fallback", file=sys.stderr)
        print(_terminate_serial_holders(cfg), file=sys.stderr)

    rc, out, err = _run_commands_over_serial_fallback(cfg, commands)
    if _is_serial_alive_no_linux_shell_result(rc, out, err):
        print("[terminal-runner] serial is alive, but no linux shell", file=sys.stderr)
    elif _is_no_serial_connection_result(rc, out, err):
        print("[terminal-runner] no terminal", file=sys.stderr)
    elif rc != 0 and ssh_timeout:
        print("[terminal-runner] first serial fallback failed after ssh timeout; retrying once", file=sys.stderr)
        print(_terminate_serial_holders(cfg), file=sys.stderr)
        rc, out, err = _run_commands_over_serial_fallback(cfg, commands)

    if out:
        print(out, end="" if out.endswith("\n") else "\n")
    if err:
        print(err, file=sys.stderr, end="" if err.endswith("\n") else "\n")
    combined = "\n".join([transcript, out or "", err or ""]).strip()
    final_rc = int(rc)
    _write_transcript(args.transcript_file, combined)
    _print_summary("auto(serial-fallback)", final_rc, started_at, combined)
    return final_rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
