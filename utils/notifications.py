"""Notificação nativa do macOS via osascript.

Extraído de scripts/health_check.py pra ser reaproveitado por outros
processos locais (ex.: o agendador da newsletter) sem duplicar a lógica
de escaping do AppleScript.
"""

from __future__ import annotations

import subprocess


def _as_applescript_string(value: str) -> str:
    # AppleScript exige aspas duplas pra literais de string (aspas simples
    # não são válidas ali) — escapa barras invertidas e aspas duplas.
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def notify(title: str, message: str, sound: str = "Glass") -> None:
    script = (
        f"display notification {_as_applescript_string(message)} "
        f"with title {_as_applescript_string(title)} "
        f"sound name {_as_applescript_string(sound)}"
    )
    subprocess.run(["osascript", "-e", script], check=False)
