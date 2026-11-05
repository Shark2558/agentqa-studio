"""The throwaway server of check_app.py / check_gates.py must not see the owner's real AI keys: its environment is the
machine's minus every *_API_KEY, with its own AgentQA home and its own vault key (so %APPDATA%\\AgentQA is never read,
and `--shots` cannot write a masked real key into a tracked docs/design picture).

    python -I frontend/design-system/test_check_app_env.py
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_app as app  # noqa: E402

REAL = {
    "PATH": "C:/tools", "APPDATA": "C:/Users/someone/AppData/Roaming", "ANTHROPIC_API_KEY": "sk-ant-real-0000", "gemini_api_key": "AIza-real-0000",
    "OPENAI_API_KEY": "sk-real-0000", "AGENTQA_HOME": "C:/real/home", "AGENTQA_VAULT_KEY": "real-vault-key", "AGENTQA_OWNER_EMAIL": "me@real.example",
    "AGENTQA_SECRET_KEY": "real-session-key",
}


def problems_with(env: dict[str, str], home: Path) -> list[str]:
    found = []
    left = [k for k in env if k.upper().endswith("_API_KEY")]
    if left:
        found.append(f"AI keys are still in the environment: {left}")
    if env.get("AGENTQA_HOME") != str(home):
        found.append(f"AGENTQA_HOME is {env.get('AGENTQA_HOME')!r}, not the throwaway folder {str(home)!r}")
    vault = env.get("AGENTQA_VAULT_KEY", "")
    try:
        sized = len(base64.urlsafe_b64decode(vault.encode()))
    except ValueError:
        sized = -1
    if vault == REAL["AGENTQA_VAULT_KEY"] or sized != 32:
        found.append(f"AGENTQA_VAULT_KEY is not a fresh 32-byte key: {vault!r}")
    if env.get("AGENTQA_OWNER_EMAIL") != app.EMAIL or env.get("AGENTQA_SECRET_KEY") != app.SECRET:
        found.append("the throwaway owner and session key are not the ones the check signs in with")
    if env.get("PATH") != REAL["PATH"] or env.get("APPDATA") != REAL["APPDATA"]:
        found.append("the rest of the machine's environment was not kept")
    return found


def main() -> int:
    home = Path("X:/throwaway/agentqa-home")
    found = problems_with(app.server_env(home, REAL), home)
    again = app.server_env(home, REAL)["AGENTQA_VAULT_KEY"]
    if again == app.server_env(home, REAL)["AGENTQA_VAULT_KEY"]:
        found.append("every call gave the same vault key: it must be new for every server")
    if not found:
        print("ok: the throwaway server's environment holds no AI key, its own home and its own vault key")
        return 0
    print("\n".join(f"  PROBLEM  {p}" for p in found))
    return 1


if __name__ == "__main__":
    sys.exit(main())
