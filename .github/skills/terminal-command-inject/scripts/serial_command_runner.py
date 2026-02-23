#!/usr/bin/env python3

import argparse
import glob
import os
from pathlib import Path
import re
import sys
import time
import stat
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple


SKILLS_DIR = Path(__file__).resolve().parents[2]
if str(SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(SKILLS_DIR))

from common.target_config import load_target_defaults

TARGET_DEFAULTS = load_target_defaults()


try:
    import serial  # type: ignore
except Exception as exc:  # pragma: no cover
    print("ERROR: pyserial is required. Install with: python3 -m pip install pyserial", file=sys.stderr)
    raise


DEFAULT_SCAN_GLOBS = ["/dev/ttyUSB*", "/dev/ttyACM*"]
DEFAULT_LOGIN_REGEX = r"(^|\r?\n)login:\s*$"
DEFAULT_PASSWORD_REGEX = r"(^|\r?\n)Password:\s*$"
DEFAULT_READY_MARKER = "__COPILOT_SERIAL_READY__"
DEFAULT_LINUX_CHECK_COMMAND = "uname -s"
DEFAULT_LINUX_CHECK_REGEX = r"\bLinux\b"
FALLBACK_SHELL_PROMPT_REGEX = r"(?:^|\r?\n)[^\r\n]*@[a-zA-Z0-9_.-]+:[^\r\n]*[$#](?:\s|$)"
DEFAULT_SERIAL_DEVICE = TARGET_DEFAULTS.serial_device
SERIAL_OPEN_RETRIES = 3
SERIAL_OPEN_RETRY_DELAY_S = 0.6
SERIAL_RETRY_ERROR_SNIPPETS = (
    "device reports readiness to read but returned no data",
    "multiple access on port",
    "could not open port",
)
SERIAL_NO_OUTPUT_PROBE_WINDOW_S = 0.8
SERIAL_MAX_CONSECUTIVE_SILENT_PROBES = 2
NO_SERIAL_CONNECTION_EXIT_CODE = 12
ALIVE_NO_LINUX_SHELL_EXIT_CODE = 13


@dataclass
class RunnerConfig:
    device: Optional[str]
    auto: bool
    scan_globs: List[str]
    baud: int
    prompt_regex: str
    username: Optional[str]
    password: Optional[str]
    overall_timeout: float
    command_timeout: float
    scan_timeout: float
    line_ending: str
    skip_linux_check: bool
    linux_check_command: str
    linux_check_regex: str


@dataclass
class PortProbeResult:
    device: str
    transcript: str
    state: str


def _now() -> float:
    return time.monotonic()


def _deadline_from_timeout(timeout_s: float) -> float:
    if timeout_s <= 0:
        return float("inf")
    return _now() + timeout_s


def _compile(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.MULTILINE)


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _candidate_devices(scan_globs: Iterable[str]) -> List[str]:
    candidates: List[str] = []
    for pattern in scan_globs:
        candidates.extend(glob.glob(pattern))
    # deterministic order: ttyUSB0, ttyUSB1, ..., ttyACM0, ... (lexicographic is fine)
    candidates = sorted(set(candidates))
    # Only keep existing char devices
    filtered: List[str] = []
    for path in candidates:
        try:
            st = os.stat(path)
        except FileNotFoundError:
            continue
        if os.path.exists(path) and stat.S_ISCHR(st.st_mode):
            filtered.append(path)
        else:
            # Fallback: keep it if it exists; OS may not expose as chr in some containers
            filtered.append(path)
    return filtered


def _write_line(ser: "serial.Serial", text: str, line_ending: str) -> None:
    payload = (text + line_ending).encode("utf-8", errors="replace")
    ser.write(payload)
    ser.flush()


def _read_until_any(
    ser: "serial.Serial",
    patterns: List[re.Pattern],
    deadline: float,
    chunk_timeout: float = 0.2,
    max_buffer_chars: int = 200_000,
) -> Tuple[Optional[int], str]:
    """Read from serial until any regex matches. Returns (match_index, transcript)."""

    ser.timeout = chunk_timeout
    buf = ""
    while _now() < deadline:
        data = ser.read(4096)
        if data:
            buf += _decode(data)
            if len(buf) > max_buffer_chars:
                buf = buf[-max_buffer_chars:]
            for idx, pat in enumerate(patterns):
                if pat.search(buf):
                    return idx, buf
        else:
            # No data this tick
            pass
    return None, buf


def _probe_for_any_output(
    ser: "serial.Serial",
    deadline: float,
    window_s: float = SERIAL_NO_OUTPUT_PROBE_WINDOW_S,
) -> str:
    """Read briefly and return any visible output bytes as decoded text."""

    probe_deadline = min(deadline, _now() + window_s)
    if probe_deadline <= _now():
        return ""

    ser.timeout = min(0.2, max(0.05, probe_deadline - _now()))
    chunks: List[str] = []
    while _now() < probe_deadline:
        data = ser.read(4096)
        if data:
            chunks.append(_decode(data))
        else:
            # keep polling until probe window expires
            pass
    return "".join(chunks)


def _has_any_output(text: str) -> bool:
    return bool(text)


def _open_serial(device: str, baud: int) -> "serial.Serial":
    # Conservative defaults for typical Linux UART consoles
    try:
        return serial.Serial(
            port=device,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.2,
            write_timeout=2,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
            exclusive=True,
        )
    except TypeError:
        return serial.Serial(
            port=device,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.2,
            write_timeout=2,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )


def _is_retryable_serial_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(snippet in msg for snippet in SERIAL_RETRY_ERROR_SNIPPETS)


def _is_no_serial_connection_output(text: str) -> bool:
    return "connection appears inactive" in text.lower()


def _looks_like_shell_prompt(text: str, prompt_re: re.Pattern, fallback_prompt_re: re.Pattern) -> bool:
    if prompt_re.search(text) or fallback_prompt_re.search(text):
        return True

    ansi_re = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
    for raw_line in re.split(r"\r?\n", text):
        line = ansi_re.sub("", raw_line)
        if "@" in line and ":" in line and ("$" in line or "#" in line):
            return True
    return False


def _wake_and_wait_for_console(
    ser: "serial.Serial",
    prompt_re: re.Pattern,
    login_re: re.Pattern,
    password_re: re.Pattern,
    deadline: float,
    line_ending: str,
    username: Optional[str],
    password: Optional[str],
) -> Tuple[bool, str]:
    """Try to reach a shell prompt (optionally logging in). Returns (ready, transcript)."""

    transcript_parts: List[str] = []
    silent_probes = 0
    fallback_prompt_re = _compile(FALLBACK_SHELL_PROMPT_REGEX)

    def _has_shell_now() -> bool:
        return _looks_like_shell_prompt("".join(transcript_parts), prompt_re=prompt_re, fallback_prompt_re=fallback_prompt_re)

    def _mark_probe_output(text: str) -> bool:
        nonlocal silent_probes
        if text:
            transcript_parts.append(text)
            silent_probes = 0
            return True
        silent_probes += 1
        return False

    def _fail_no_output_message() -> str:
        return (
            "".join(transcript_parts)
            + "\n[serial-runner] no output after active serial probes; connection appears inactive\n"
        )

    # Wake prompt: send newline a few times in case console is idle
    for _ in range(2):
        _write_line(ser, "", line_ending=line_ending)
        probe_out = _probe_for_any_output(ser, deadline=deadline)
        _mark_probe_output(probe_out)
        if _has_shell_now():
            return True, "".join(transcript_parts)
        if silent_probes >= SERIAL_MAX_CONSECUTIVE_SILENT_PROBES:
            return False, _fail_no_output_message()

    patterns = [prompt_re, fallback_prompt_re, login_re, password_re]
    login_attempts = 0
    max_login_attempts = 2

    while _now() < deadline:
        idx, out = _read_until_any(ser, patterns=patterns, deadline=min(deadline, _now() + 1.5))
        if out:
            transcript_parts.append(out)
            if _has_shell_now():
                return True, "".join(transcript_parts)

        if idx is None:
            # keep trying; periodically poke
            _write_line(ser, "", line_ending=line_ending)
            probe_out = _probe_for_any_output(ser, deadline=deadline)
            _mark_probe_output(probe_out)
            if _has_shell_now():
                return True, "".join(transcript_parts)
            if silent_probes >= SERIAL_MAX_CONSECUTIVE_SILENT_PROBES:
                return False, _fail_no_output_message()
            continue

        if idx in (0, 1):
            return True, "".join(transcript_parts)

        if idx == 2:
            if not username:
                return False, "".join(transcript_parts) + "\n[serial-runner] login prompt detected but no --username provided\n"
            if login_attempts >= max_login_attempts:
                return False, "".join(transcript_parts) + "\n[serial-runner] login prompt repeated after credential attempts\n"
            login_attempts += 1
            _write_line(ser, username, line_ending=line_ending)
            next_idx, next_out = _read_until_any(
                ser,
                patterns=[prompt_re, fallback_prompt_re, password_re, login_re],
                deadline=min(deadline, _now() + 3.0),
            )
            if next_out:
                transcript_parts.append(next_out)
            if next_idx in (0, 1):
                return True, "".join(transcript_parts)
            if next_idx == 2:
                if not password:
                    return False, "".join(transcript_parts) + "\n[serial-runner] password prompt detected but no --password provided\n"
                _write_line(ser, password, line_ending=line_ending)
                final_idx, final_out = _read_until_any(
                    ser,
                    patterns=[prompt_re, fallback_prompt_re, login_re, password_re],
                    deadline=min(deadline, _now() + 4.0),
                )
                if final_out:
                    transcript_parts.append(final_out)
                if final_idx in (0, 1):
                    return True, "".join(transcript_parts)
            elif next_idx is None:
                probe_out = _probe_for_any_output(ser, deadline=deadline)
                if not _mark_probe_output(probe_out):
                    return False, _fail_no_output_message()
            continue

        if idx == 3:
            if not password:
                return False, "".join(transcript_parts) + "\n[serial-runner] password prompt detected but no --password provided\n"
            _write_line(ser, password, line_ending=line_ending)
            probe_out = _probe_for_any_output(ser, deadline=deadline)
            if not _mark_probe_output(probe_out):
                return False, _fail_no_output_message()
            continue

    return False, "".join(transcript_parts)


def _sync_marker(
    ser: "serial.Serial",
    marker: str,
    prompt_re: re.Pattern,
    command_timeout: float,
    line_ending: str,
) -> Tuple[bool, str]:
    deadline = _deadline_from_timeout(command_timeout)
    marker_re = _compile(re.escape(marker))

    _write_line(ser, f"echo {marker}", line_ending=line_ending)

    idx, out = _read_until_any(ser, patterns=[marker_re, prompt_re], deadline=deadline)
    # We consider sync ok only if marker is observed
    ok = idx == 0
    return ok, out


def _run_one_command(
    ser: "serial.Serial",
    cmd: str,
    prompt_re: re.Pattern,
    command_timeout: float,
    line_ending: str,
) -> Tuple[bool, str]:
    # Unique end marker per command
    marker = f"__COPILOT_DONE_{int(time.time() * 1000)}__"
    marker_re = _compile(re.escape(marker))
    deadline = _deadline_from_timeout(command_timeout)

    _write_line(ser, cmd, line_ending=line_ending)
    _write_line(ser, f"echo {marker}", line_ending=line_ending)

    idx, out = _read_until_any(ser, patterns=[marker_re], deadline=deadline)
    ok = idx == 0
    return ok, out


def _probe_port(cfg: RunnerConfig, device: str) -> Optional[PortProbeResult]:
    for attempt in range(1, SERIAL_OPEN_RETRIES + 1):
        try:
            with _open_serial(device, cfg.baud) as ser:
                # best-effort flush to avoid stale data
                try:
                    ser.reset_input_buffer()
                except Exception:
                    pass

                prompt_re = _compile(cfg.prompt_regex)
                fallback_prompt_re = _compile(FALLBACK_SHELL_PROMPT_REGEX)
                login_re = _compile(DEFAULT_LOGIN_REGEX)
                password_re = _compile(DEFAULT_PASSWORD_REGEX)

                deadline = _now() + cfg.scan_timeout
                transcript_parts: List[str] = []

                def _probe_output(window_s: float = SERIAL_NO_OUTPUT_PROBE_WINDOW_S) -> str:
                    out = _probe_for_any_output(ser, deadline=deadline, window_s=window_s)
                    if out:
                        transcript_parts.append(out)
                    return out

                def _combined() -> str:
                    return "".join(transcript_parts)

                def _is_shell() -> bool:
                    return _looks_like_shell_prompt(_combined(), prompt_re=prompt_re, fallback_prompt_re=fallback_prompt_re)

                # Step A: assume shell already exists; send empty lines and check prompt first.
                _write_line(ser, "", line_ending=cfg.line_ending)
                _probe_output()
                if not _is_shell():
                    _write_line(ser, "", line_ending=cfg.line_ending)
                    _probe_output()

                # Step B fallback: assume login prompt and try username.
                if not _is_shell() and login_re.search(_combined()) and cfg.username:
                    _write_line(ser, cfg.username, line_ending=cfg.line_ending)
                    _probe_output()

                # Step C fallback: if waiting for password, provide password.
                if not _is_shell() and password_re.search(_combined()) and cfg.password:
                    _write_line(ser, cfg.password, line_ending=cfg.line_ending)
                    _probe_output()

                # Final login->password fallback sequence if login appears after first tries.
                if not _is_shell() and login_re.search(_combined()) and cfg.username:
                    _write_line(ser, cfg.username, line_ending=cfg.line_ending)
                    _probe_output()
                    if password_re.search(_combined()) and cfg.password:
                        _write_line(ser, cfg.password, line_ending=cfg.line_ending)
                        _probe_output()

                transcript = _combined()
                if not _is_shell():
                    state = "alive_no_shell" if _has_any_output(transcript) else "no_terminal"
                    return PortProbeResult(device=device, transcript=transcript, state=state)

                return PortProbeResult(device=device, transcript=transcript, state="shell")
        except serial.SerialException as exc:
            if attempt < SERIAL_OPEN_RETRIES and _is_retryable_serial_error(exc):
                time.sleep(SERIAL_OPEN_RETRY_DELAY_S)
                continue
            return PortProbeResult(device=device, transcript=f"serial error: {exc}", state="no_terminal")
        except PermissionError as exc:
            return PortProbeResult(device=device, transcript=f"permission denied: {exc}", state="no_terminal")

    return PortProbeResult(device=device, transcript="", state="no_terminal")


def _select_device(cfg: RunnerConfig) -> PortProbeResult:
    if cfg.device:
        return PortProbeResult(device=cfg.device, transcript="", state="unknown")

    candidates = _candidate_devices(cfg.scan_globs)
    if not candidates:
        return PortProbeResult(device="", transcript="No serial devices found", state="no_terminal")

    first_alive_no_shell: Optional[PortProbeResult] = None

    for dev in candidates:
        res = _probe_port(cfg, dev)
        if res.state == "shell":
            return res
        if res.state == "alive_no_shell" and first_alive_no_shell is None:
            first_alive_no_shell = res

    if first_alive_no_shell is not None:
        return first_alive_no_shell

    return PortProbeResult(
        device=", ".join(candidates),
        transcript="Could not auto-detect a responding serial console",
        state="no_terminal",
    )


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Inject commands over serial and capture output")

    mode = p.add_mutually_exclusive_group(required=False)
    mode.add_argument("--device", default=(DEFAULT_SERIAL_DEVICE or None), help="Serial device path (e.g. /dev/ttyUSB* or /dev/ttyACM*)")
    mode.add_argument("--auto", action="store_true", help="Auto-detect serial device by scanning")

    p.add_argument("--scan-glob", action="append", default=[], help="Additional glob(s) to scan in --auto mode")

    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--prompt-regex", required=True, help="Regex for the target shell prompt")

    p.add_argument("--username", default=None)
    p.add_argument("--password", default=None)
    p.add_argument(
        "--password-env",
        default=None,
        help="Name of env var containing the password (preferred over --password; value not printed)",
    )

    p.add_argument(
        "--overall-timeout",
        type=float,
        default=180,
        help="Overall timeout seconds for the whole run. Use 0 for no overall limit.",
    )
    p.add_argument(
        "--command-timeout",
        type=float,
        default=10,
        help="Per-command timeout seconds. Use 0 for no per-command limit (overall timeout still applies).",
    )
    p.add_argument("--scan-timeout", type=float, default=8.0, help="Seconds per port to decide if it is the console")

    p.add_argument(
        "--line-ending",
        choices=["CR", "LF", "CRLF"],
        default="CR",
        help="Line ending used when sending commands (default CR for serial consoles)",
    )

    p.add_argument(
        "--skip-linux-check",
        action="store_true",
        help="Skip Linux verification during auto-detect (not recommended).",
    )
    p.add_argument(
        "--linux-check-command",
        default=DEFAULT_LINUX_CHECK_COMMAND,
        help="Command used to verify the console is Linux (default: uname -s)",
    )
    p.add_argument(
        "--linux-check-regex",
        default=DEFAULT_LINUX_CHECK_REGEX,
        help="Regex that must match the check command output (default: \\bLinux\\b)",
    )

    p.add_argument("--command", action="append", default=[], help="Command to run (repeatable)")

    args = p.parse_args(argv)
    if not args.device and not args.auto:
        args.auto = True

    if args.password is None and args.password_env:
        args.password = os.environ.get(str(args.password_env))

    if not args.command:
        p.error("At least one --command is required")

    return args


def main(argv: List[str]) -> int:
    args = parse_args(argv)

    line_ending = {"CR": "\r", "LF": "\n", "CRLF": "\r\n"}[args.line_ending]

    scan_globs = DEFAULT_SCAN_GLOBS[:]
    if args.scan_glob:
        scan_globs.extend(args.scan_glob)

    cfg = RunnerConfig(
        device=args.device,
        auto=bool(args.auto),
        scan_globs=scan_globs,
        baud=args.baud,
        prompt_regex=args.prompt_regex,
        username=args.username,
        password=args.password,
        overall_timeout=float(args.overall_timeout),
        command_timeout=float(args.command_timeout),
        scan_timeout=float(args.scan_timeout),
        line_ending=line_ending,
        skip_linux_check=bool(args.skip_linux_check),
        linux_check_command=str(args.linux_check_command),
        linux_check_regex=str(args.linux_check_regex),
    )

    overall_deadline = _deadline_from_timeout(cfg.overall_timeout)

    selection = _select_device(cfg)
    selected_device = selection.device
    probe_transcript = selection.transcript

    if selection.state == "no_terminal":
        print("ERROR: no terminal", file=sys.stderr)
        if probe_transcript:
            print(f"[serial-runner] details: {probe_transcript}", file=sys.stderr)
        return NO_SERIAL_CONNECTION_EXIT_CODE

    if selection.state == "alive_no_shell":
        if selected_device:
            print(f"[serial-runner] selected device (alive): {selected_device}")
        print("ERROR: serial is alive, but no linux shell", file=sys.stderr)
        if probe_transcript:
            print("\n[serial-runner] probe transcript (partial):\n" + probe_transcript)
        return ALIVE_NO_LINUX_SHELL_EXIT_CODE

    if selection.state == "unknown":
        print(f"[serial-runner] selected device: {selected_device}")
    else:
        print(f"[serial-runner] selected device (terminal/shell console): {selected_device}")

    prompt_re = _compile(cfg.prompt_regex)

    for attempt in range(1, SERIAL_OPEN_RETRIES + 1):
        try:
            with _open_serial(selected_device, cfg.baud) as ser:
                try:
                    ser.reset_input_buffer()
                except Exception:
                    pass

                # Ensure prompt is reachable (again), with longer timeout now
                ready, ready_out = _wake_and_wait_for_console(
                    ser,
                    prompt_re=prompt_re,
                    login_re=_compile(DEFAULT_LOGIN_REGEX),
                    password_re=_compile(DEFAULT_PASSWORD_REGEX),
                    deadline=(overall_deadline if cfg.command_timeout <= 0 else min(overall_deadline, _now() + max(5.0, cfg.command_timeout))),
                    line_ending=cfg.line_ending,
                    username=cfg.username,
                    password=cfg.password,
                )
                if not ready:
                    if _is_no_serial_connection_output(ready_out):
                        print("ERROR: no terminal", file=sys.stderr)
                        if ready_out:
                            print("\n[serial-runner] session transcript (partial):\n" + ready_out)
                        return NO_SERIAL_CONNECTION_EXIT_CODE

                    if _has_any_output(ready_out):
                        print("ERROR: serial is alive, but no linux shell", file=sys.stderr)
                        if ready_out:
                            print("\n[serial-runner] session transcript (partial):\n" + ready_out)
                        return ALIVE_NO_LINUX_SHELL_EXIT_CODE

                    print("ERROR: could not reach a shell prompt on the selected device", file=sys.stderr)
                    if probe_transcript:
                        print("\n[serial-runner] probe transcript (partial):\n" + probe_transcript)
                    if ready_out:
                        print("\n[serial-runner] session transcript (partial):\n" + ready_out)
                    return 3

                sync_ok, sync_out = _sync_marker(
                    ser,
                    marker=DEFAULT_READY_MARKER,
                    prompt_re=prompt_re,
                    command_timeout=(5.0 if cfg.command_timeout <= 0 else max(5.0, cfg.command_timeout)),
                    line_ending=cfg.line_ending,
                )
                if not sync_ok:
                    print("ERROR: failed to synchronize marker with prompt", file=sys.stderr)
                    print(sync_out)
                    return 4

                if probe_transcript:
                    print("\n[serial-runner] auto-detect transcript (partial):\n" + probe_transcript)

                print("\n[serial-runner] synchronized. running commands...\n")

                for i, cmd in enumerate(args.command, start=1):
                    if _now() >= overall_deadline:
                        print("ERROR: overall timeout exceeded", file=sys.stderr)
                        return 5

                    print(f"===== COMMAND {i}/{len(args.command)} =====")
                    print(f"$ {cmd}")

                    ok, out = _run_one_command(
                        ser,
                        cmd=cmd,
                        prompt_re=prompt_re,
                        command_timeout=(max(1.0, overall_deadline - _now()) if cfg.command_timeout <= 0 else min(cfg.command_timeout, max(1.0, overall_deadline - _now()))),
                        line_ending=cfg.line_ending,
                    )
                    print(out)

                    if not ok:
                        if cfg.command_timeout <= 0:
                            print(f"ERROR: command did not complete before overall timeout: {cmd}", file=sys.stderr)
                        else:
                            print(f"ERROR: command timed out after {cfg.command_timeout}s: {cmd}", file=sys.stderr)
                        return 6

                print("\n[serial-runner] done")
                return 0

        except serial.SerialException as exc:
            if attempt < SERIAL_OPEN_RETRIES and _is_retryable_serial_error(exc):
                time.sleep(SERIAL_OPEN_RETRY_DELAY_S)
                continue
            print(f"ERROR: serial error: {exc}", file=sys.stderr)
            return 10


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
