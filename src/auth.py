"""
Local administrator accounts and role-based permissions for the admin page (localhost demonstration).

Accounts live in instance/admin_users.json (git-ignored), with salted PBKDF2-SHA256 password hashes; no password is
ever stored or logged in plain text. Every admin action checks permission on the server side through require();
hiding a button is never the only protection. The knowledge-base service additionally checks its own roles.

Roles (each includes the permissions listed):
- viewer     view analytics and knowledge-base status
- reviewer   + review rules and documents, record review notes
- uploader   + upload, validate and stage documents (staging is not public)
- publisher  + approve, publish, withdraw and roll back knowledge-base versions
- admin      + manage accounts

    python -m src.auth create USER --role admin        (asks for the password; or MSU_ADMIN_PASSWORD for scripts)
    python -m src.auth list
"""
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, Optional

ROOT = Path(__file__).resolve().parents[1]
USERS_FILE = ROOT / "instance" / "admin_users.json"
ROLES = ("viewer", "reviewer", "uploader", "publisher", "admin")
PERMISSIONS = {
    "view": {"viewer", "reviewer", "uploader", "publisher", "admin"},
    "review": {"reviewer", "uploader", "publisher", "admin"},
    "upload": {"uploader", "publisher", "admin"},
    "publish": {"publisher", "admin"},
    "manage_users": {"admin"},
}
KB_ROLES = {"uploader": {"kb_uploader"}, "publisher": {"kb_uploader", "kb_approver"},
            "admin": {"kb_uploader", "kb_approver", "kb_admin"}}
ITERATIONS = 200_000
MIN_PASSWORD = 10
MAX_FAILURES, LOCK_SECONDS = 5, 300


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class User:
    name: str
    role: str

    def can(self, permission: str) -> bool:
        return self.role in PERMISSIONS.get(permission, set())

    @property
    def kb_roles(self) -> FrozenSet[str]:
        return frozenset(KB_ROLES.get(self.role, set()))


def _hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS).hex()


class UserStore:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path or os.environ.get("MSU_ADMIN_USERS") or USERS_FILE)
        self._failures: Dict[str, list] = {}

    def _load(self) -> Dict[str, dict]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8")).get("users", {})

    def _save(self, users: Dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"users": users}, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def has_users(self) -> bool:
        return bool(self._load())

    def users(self) -> Dict[str, str]:
        return {n: u["role"] for n, u in self._load().items()}

    def create(self, name: str, password: str, role: str, by: Optional[User] = None) -> User:
        users = self._load()
        if users and (by is None or not by.can("manage_users")):
            raise AuthError("only an administrator can create accounts")
        if not users and role != "admin":
            raise AuthError("the first account must be an administrator")
        name = (name or "").strip()
        if not name or len(name) > 40 or not name.replace("_", "").replace(".", "").replace("-", "").isalnum():
            raise AuthError("user names may contain letters, digits, '.', '_' and '-' (up to 40)")
        if role not in ROLES:
            raise AuthError(f"unknown role {role!r}")
        if len(password or "") < MIN_PASSWORD:
            raise AuthError(f"passwords need at least {MIN_PASSWORD} characters")
        if name in users:
            raise AuthError("that user already exists")
        salt = secrets.token_bytes(16)
        users[name] = {"role": role, "salt": salt.hex(), "hash": _hash(password, salt), "iterations": ITERATIONS,
                       "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "created_by": by.name if by else "first-run setup"}
        self._save(users)
        return User(name, role)

    def remove(self, name: str, by: User) -> None:
        if not by.can("manage_users"):
            raise AuthError("only an administrator can remove accounts")
        users = self._load()
        if name == by.name:
            raise AuthError("you cannot remove your own account")
        users.pop(name, None)
        self._save(users)

    def authenticate(self, name: str, password: str) -> User:
        """Constant-time comparison; a few failures lock the account for LOCK_SECONDS (per process)."""
        now = time.time()
        recent = [t for t in self._failures.get(name, []) if now - t < LOCK_SECONDS]
        if len(recent) >= MAX_FAILURES:
            raise AuthError("too many failed attempts; try again in a few minutes")
        u = self._load().get(name)
        ok = bool(u) and hmac.compare_digest(_hash(password or "", bytes.fromhex(u["salt"])), u["hash"])
        if not ok:
            self._failures[name] = recent + [now]
            raise AuthError("unknown user or wrong password")
        self._failures.pop(name, None)
        return User(name, u["role"])


def require(user: Optional[User], permission: str) -> User:
    """Server-side permission check used by every admin action."""
    if user is None:
        raise AuthError("please sign in")
    if not user.can(permission):
        raise AuthError(f"your role ({user.role}) does not allow this action")
    return user


def main(argv=None) -> int:
    import argparse
    import getpass
    ap = argparse.ArgumentParser(prog="python -m src.auth")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("name")
    c.add_argument("--role", default="admin", choices=ROLES)
    sub.add_parser("list")
    a = ap.parse_args(argv)
    store = UserStore()
    if a.cmd == "list":
        for n, r in store.users().items():
            print(n, r)
        return 0
    password = os.environ.get("MSU_ADMIN_PASSWORD") or getpass.getpass("Password: ")
    admin = None
    if store.has_users():
        admin_name = input("Existing administrator: ")
        admin = store.authenticate(admin_name, getpass.getpass("Administrator password: "))
    store.create(a.name, password, a.role, by=admin)
    print(f"created {a.name} ({a.role})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
