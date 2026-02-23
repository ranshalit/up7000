#!/usr/bin/env python3

from __future__ import annotations

import re
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

DEFAULT_TARGET_IP = os.environ.get("JETSON_TARGET_IP", "")
DEFAULT_TARGET_USER = os.environ.get("JETSON_TARGET_USER", "")
DEFAULT_TARGET_PASSWORD = os.environ.get("JETSON_TARGET_PASSWORD", "")
DEFAULT_TARGET_PROMPT_REGEX = os.environ.get("JETSON_TARGET_PROMPT_REGEX", "")
DEFAULT_TARGET_SERIAL_DEVICE = os.environ.get("JETSON_TARGET_SERIAL_DEVICE", "")

KEY_MAP = {
    "target_ip": "ip",
    "target_user": "user",
    "target_password": "password",
    "target_prompt_regex": "prompt_regex",
    "target_serial_device": "serial_device",
}

ENTRY_PATTERN = re.compile(
    r"`(?P<key>target_ip|target_user|target_password|target_prompt_regex|target_serial_device)`\s*:\s*`(?P<value>[^`]+)`",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class TargetDefaults:
    ip: str
    user: str
    password: str
    prompt_regex: str
    serial_device: str
    source_file: str


def _build_prompt_regex(user: str, configured_prompt_regex: str) -> str:
    username = (user or "").strip()
    configured = (configured_prompt_regex or "").strip()

    if configured:
        safe_user = re.escape(username)
        return configured.replace("<target_user>", safe_user).replace("<username>", safe_user)

    if username:
        safe_user = re.escape(username)
        return rf"(?:{safe_user}@{safe_user}:.*[$#]|[$#]) ?$"

    return r"[$#] ?$"


def _find_copilot_instructions() -> Path | None:
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / ".github" / "copilot-instructions.md"
        if candidate.is_file():
            return candidate
    return None


def _parse_target_entries(markdown_text: str) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    for match in ENTRY_PATTERN.finditer(markdown_text):
        key = (match.group("key") or "").strip().lower()
        value = (match.group("value") or "").strip()
        mapped = KEY_MAP.get(key)
        if mapped and value:
            parsed[mapped] = value
    return parsed


def load_target_defaults() -> TargetDefaults:
    source_path = _find_copilot_instructions()
    data: Dict[str, str] = {}

    if source_path is not None:
        try:
            data = _parse_target_entries(source_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    return TargetDefaults(
        ip=data.get("ip", DEFAULT_TARGET_IP),
        user=data.get("user", DEFAULT_TARGET_USER),
        password=data.get("password", DEFAULT_TARGET_PASSWORD),
        prompt_regex=_build_prompt_regex(
            user=data.get("user", DEFAULT_TARGET_USER),
            configured_prompt_regex=data.get("prompt_regex", DEFAULT_TARGET_PROMPT_REGEX),
        ),
        serial_device=data.get("serial_device", DEFAULT_TARGET_SERIAL_DEVICE),
        source_file=str(source_path) if source_path else "<built-in defaults>",
    )
