import select
import sys
from typing import Iterable


class HeadlessCommandReader:
    def __init__(self, supported_commands: Iterable[str]):
        self._supported_commands = set(supported_commands)
        self._stdin = sys.stdin
        self._eof = False

    def poll(self) -> str | None:
        if self._eof:
            return None

        try:
            ready, _, _ = select.select([self._stdin], [], [], 0.0)
        except Exception:
            self._eof = True
            return None

        if not ready:
            return None

        try:
            line = self._stdin.readline()
        except Exception:
            self._eof = True
            return None

        if line == "":
            self._eof = True
            return None

        token = line.strip()
        if not token:
            return None

        token_l = token.lower()
        if "esc" in self._supported_commands and token_l in {"esc", "exit", "quit"}:
            return "esc"
        return token


def command_from_keypress(key_code: int, key_map: dict[int, str]) -> str | None:
    if key_code < 0:
        return None
    return key_map.get(key_code & 0xFF)