"""Test data vault: the one place for test accounts, OTP settings, data sets and secrets.

Everything is kept encrypted in the project's .agentqa/vault.json. The encryption key is not in the
project folder, so copying or committing a project never exposes passwords:

  Windows   the key is protected with DPAPI under your Windows account (%APPDATA%\\AgentQA\\vault.key)
  others    ~/.agentqa/vault.key, readable only by you
  CI        set AGENTQA_VAULT_KEY (a Fernet key) as a pipeline secret instead

Contents (decrypted):
  accounts     role -> {login_option, method, username, mobile, email, password, otp_source, otp_fixed,
                        totp_secret, aliases, notes}; '<role>__peer' is the role's second account
  login_steps  role -> the login steps recorded when AgentQA (or you) found the way in
  login_screens role -> what each login screen offered (buttons, boxes), for functional test design
  datasets     name -> list of values (valid mobiles, PIN codes, file names...)
  secrets      name -> value (GOOGLE_API_KEY, tracker tokens)
"""
from __future__ import annotations

import base64
import json
import os
import sys
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

METHODS = {
    "password": "Username and password",
    "password_otp": "Username, password and OTP",
    "mobile_otp": "Mobile number and OTP",
    "email_otp": "Email and OTP",
    "mfa": "Username, password and authenticator code (MFA)",
    "sso": "Single sign-on (SSO) page",
    "custom": "Other (AgentQA reads the screen and asks you)",
}
OTP_SOURCES = {
    "ask": "Ask me on screen (live portals)",
    "inbox": "AgentQA mock inbox (test environments)",
    "fixed": "A fixed test OTP",
    "totp": "Authenticator app secret (TOTP)",
    "api": "A test API of the portal",
}
SECRET_FIELDS = ("password", "otp_fixed", "totp_secret")
_LOCK = threading.Lock()


def _key_path() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home())) / "AgentQA" / "vault.key"
    return Path.home() / ".agentqa" / "vault.key"


def _dpapi(data: bytes, protect: bool) -> bytes:  # pragma: no cover - Windows only
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    src = Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)))
    out = Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("Windows could not protect the vault key (DPAPI)")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def _key() -> bytes:
    env = os.environ.get("AGENTQA_VAULT_KEY")
    if env:
        return env.encode()
    path = _key_path()
    if path.exists():
        raw = path.read_bytes()
        return _dpapi(base64.b64decode(raw), protect=False) if os.name == "nt" else raw.strip()
    key = Fernet.generate_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        path.write_bytes(base64.b64encode(_dpapi(key, protect=True)))
    else:
        path.write_bytes(key)
        os.chmod(path, 0o600)
    return key


class Vault:
    def __init__(self, state_dir: Path):
        self.path = Path(state_dir) / "vault.json"
        self._data: dict | None = None

    # ---- storage ----------------------------------------------------------------------
    def load(self) -> dict:
        if self._data is None:
            data = {}
            if self.path.exists():
                token = json.loads(self.path.read_text(encoding="utf-8")).get("data", "")
                try:
                    data = json.loads(Fernet(_key()).decrypt(token.encode()))
                except InvalidToken as exc:
                    raise RuntimeError(f"The test data vault {self.path} was encrypted with another key. "
                                       "Set AGENTQA_VAULT_KEY or re-enter the accounts.") from exc
            for k in ("accounts", "login_steps", "login_screens", "login_hints", "nav_hints", "datasets", "secrets"):
                data.setdefault(k, {})
            self._data = data
        return self._data

    def save(self) -> None:
        with _LOCK:
            token = Fernet(_key()).encrypt(json.dumps(self.load(), ensure_ascii=False).encode()).decode()
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"version": 1, "data": token}), encoding="utf-8")
            os.replace(tmp, self.path)

    # ---- accounts ------------------------------------------------------------------------
    def accounts(self) -> dict[str, dict]:
        return self.load()["accounts"]

    def account(self, role: str) -> dict:
        return dict(self.accounts().get(role) or {})

    def set_account(self, role: str, values: dict, keep_secrets: bool = True) -> None:
        acc = self.accounts().setdefault(role, {})
        for k, v in values.items():
            if k in SECRET_FIELDS and keep_secrets and not v:
                continue        # an empty password box means "keep the stored one"
            acc[k] = v
        self.save()

    def remove_account(self, role: str) -> None:
        self.accounts().pop(role, None)
        self.load()["login_steps"].pop(role, None)
        self.load()["login_screens"].pop(role, None)
        self.load()["login_hints"].pop(role, None)
        self.load()["nav_hints"].pop(role, None)
        self.save()

    # ---- recorded login steps ------------------------------------------------------------------
    def login_steps(self, role: str) -> list[dict]:
        return list(self.load()["login_steps"].get(role) or [])

    def set_login_steps(self, role: str, steps: list[dict] | None) -> None:
        if steps:
            self.load()["login_steps"][role] = steps
        else:
            self.load()["login_steps"].pop(role, None)
        self.save()

    def login_hints(self, role: str) -> dict[str, list[dict]]:
        """What a person showed on each login screen (by page), kept even when that login did not finish."""
        return dict(self.load()["login_hints"].get(role) or {})

    def add_login_hint(self, role: str, path: str, steps: list[dict]) -> None:
        if steps:
            self.load()["login_hints"].setdefault(role, {})[path] = steps
            self.save()

    def nav_hints(self, role: str) -> list[dict]:
        """Navigation a person showed the Explorer (how to reach a page the crawler could not): a list of
        {"to": path, "steps": [...]} kept per role and replayed on later runs."""
        return list(self.load()["nav_hints"].get(role) or [])

    def add_nav_hint(self, role: str, to_path: str, steps: list[dict]) -> None:
        if not steps:
            return
        hints = self.load()["nav_hints"].setdefault(role, [])
        hints[:] = [h for h in hints if h.get("to") != to_path] + [{"to": to_path, "steps": steps}]
        self.save()

    def set_nav_hints(self, role: str, hints: list[dict] | None) -> None:
        if hints:
            self.load()["nav_hints"][role] = hints
        else:
            self.load()["nav_hints"].pop(role, None)
        self.save()

    def login_screens(self, role: str) -> dict:
        """What the login screens offered (buttons, boxes) when AgentQA last went through them."""
        return dict(self.load()["login_screens"].get(role) or {})

    def set_login_screens(self, role: str, screens: dict | None) -> None:
        if screens:
            self.load()["login_screens"][role] = screens
        else:
            self.load()["login_screens"].pop(role, None)
        self.save()

    # ---- data sets and secrets ---------------------------------------------------------------
    def datasets(self) -> dict[str, list]:
        return self.load()["datasets"]

    def set_dataset(self, name: str, values: list[str] | None) -> None:
        if values:
            self.datasets()[name] = values
        else:
            self.datasets().pop(name, None)
        self.save()

    def secret(self, name: str) -> str | None:
        return os.environ.get(name) or self.load()["secrets"].get(name)

    def set_secret(self, name: str, value: str | None) -> None:
        if value:
            self.load()["secrets"][name] = value
        else:
            self.load()["secrets"].pop(name, None)
        self.save()

    def summary(self) -> dict:
        """What the dashboard may show: never a password, OTP secret or token."""
        out = {}
        for role, a in self.accounts().items():
            out[role] = {k: v for k, v in a.items() if k not in SECRET_FIELDS}
            out[role]["has_password"] = bool(a.get("password"))
            out[role]["has_fixed_otp"] = bool(a.get("otp_fixed"))
            out[role]["has_totp"] = bool(a.get("totp_secret"))
            out[role]["steps"] = len(self.login_steps(role))
        return out


def mask(value: str | None) -> str:
    v = str(value or "")
    if len(v) <= 4:
        return "*" * len(v)
    return v[:2] + "*" * (len(v) - 4) + v[-2:]


if __name__ == "__main__":  # pragma: no cover
    print(json.dumps(Vault(Path(sys.argv[1])).summary(), indent=2))
