"""账号体系（aimate/web/accounts）—— 纯 stdlib 持久化用户账户。

信创红线：零第三方依赖，仅用 hashlib/secrets/sqlite3。

功能：
- 注册 / 登录（pbkdf2 密码哈希，不存明文）
- 会话 token（secrets.token_urlsafe，服务端持有）
- 用户资料：姓名/岗位(post)/头像(avatar dataURL 或路径)/角色
- 导入 License（复用 license.manager，绑定到用户）
- 明暗主题偏好

存储：运行目录下 .aimate/accounts.sqlite3。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from typing import Optional


def _dir() -> str:
    """应用数据目录：CWD/.aimate（自动创建）。"""
    d = os.path.join(os.getcwd(), ".aimate")
    os.makedirs(d, exist_ok=True)
    return d


def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, bytes]:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return dk.hex(), salt


@dataclass
class Account:
    username: str
    name: str
    role: str = "member"          # admin/member/viewer/auditor
    post: str = ""                # 岗位
    avatar: str = ""              # dataURL 或相对路径
    theme: str = "light"          # light/dark
    license_raw: str = ""         # 导入的 license 原文
    license_features: list = field(default_factory=list)
    license_expires: int = 0
    created_at: float = field(default_factory=time.time)


class Session:
    """一个登录会话。"""
    def __init__(self, token: str, username: str, created: float) -> None:
        self.token = token
        self.username = username
        self.created = created


class AccountStore:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or os.path.join(_dir(), "accounts.sqlite3")
        self._sessions: dict[str, Session] = {}   # token -> Session（内存态，重启失效）
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def _init_db(self) -> None:
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS accounts (
                username TEXT PRIMARY KEY,
                pw_hash TEXT NOT NULL,
                pw_salt BLOB NOT NULL,
                name TEXT NOT NULL,
                role TEXT DEFAULT 'member',
                post TEXT DEFAULT '',
                avatar TEXT DEFAULT '',
                theme TEXT DEFAULT 'light',
                license_raw TEXT DEFAULT '',
                license_features TEXT DEFAULT '[]',
                license_expires INTEGER DEFAULT 0,
                created_at REAL
            )""")

    # ---- 注册/登录 ----
    def register(self, username: str, password: str, name: str = "",
                 role: str = "member", post: str = "") -> Account:
        username = (username or "").strip()
        if not username or not password:
            raise ValueError("用户名与密码必填")
        h, salt = _hash_password(password)
        name = name or username
        with self._conn() as c:
            cur = c.execute(
                "SELECT 1 FROM accounts WHERE username=?", (username,))
            if cur.fetchone():
                raise ValueError("用户名已存在")
            c.execute(
                "INSERT INTO accounts(username,pw_hash,pw_salt,name,role,post,"
                "created_at) VALUES(?,?,?,?,?,?,?)",
                (username, h, salt, name, role, post, time.time()))
        acc = self.get(username)
        assert acc is not None
        return acc

    def authenticate(self, username: str, password: str) -> Optional[Account]:
        acc = self.get(username)
        if not acc:
            return None
        with self._conn() as c:
            row = c.execute(
                "SELECT pw_hash,pw_salt FROM accounts WHERE username=?",
                (username,)).fetchone()
        if row is None:
            return None
        expected = row["pw_hash"]
        h, _ = _hash_password(password, bytes(row["pw_salt"]))
        if not hmac.compare_digest(expected, h):
            return None
        return acc

    def login(self, username: str, password: str) -> Optional[tuple[str, Account]]:
        """校验并签发会话。返回 (token, account)。"""
        acc = self.authenticate(username, password)
        if not acc:
            return None
        token = "sess_" + secrets.token_urlsafe(24)
        self._sessions[token] = Session(token, acc.username, time.time())
        return token, acc

    def whoami(self, token: str) -> Optional[Account]:
        s = self._sessions.get(token)
        return self.get(s.username) if s else None

    def logout(self, token: str) -> None:
        self._sessions.pop(token, None)

    # ---- 资料 ----
    def get(self, username: str) -> Optional[Account]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM accounts WHERE username=?",
                            (username,)).fetchone()
        if not row:
            return None
        return Account(
            username=row["username"], name=row["name"], role=row["role"],
            post=row["post"] or "", avatar=row["avatar"] or "",
            theme=row["theme"] or "light", license_raw=row["license_raw"] or "",
            license_features=json.loads(row["license_features"] or "[]"),
            license_expires=row["license_expires"] or 0,
            created_at=row["created_at"] or 0,
        )

    def update_profile(self, username: str, **kw) -> Account:
        fields = ["name", "post", "avatar", "theme"]
        sets, vals = [], []
        for f in fields:
            if f in kw:
                sets.append(f"{f}=?")
                vals.append(kw[f])
        if sets:
            vals.append(username)
            with self._conn() as c:
                c.execute(
                    f"UPDATE accounts SET {', '.join(sets)} WHERE username=?",
                    vals)
        acc = self.get(username)
        assert acc is not None
        return acc

    def change_password(self, username: str, old_pw: str, new_pw: str) -> bool:
        acc = self.authenticate(username, old_pw)
        if not acc:
            return False
        h, salt = _hash_password(new_pw)
        with self._conn() as c:
            c.execute("UPDATE accounts SET pw_hash=?,pw_salt=? WHERE username=?",
                      (h, salt, username))
        return True

    # ---- License 导入（复用 license.manager）----
    def import_license(self, username: str, raw: str) -> Account:
        from aimate.license.manager import LicenseManager
        lic = LicenseManager().load(raw, "tenant-demo")
        with self._conn() as c:
            c.execute(
                "UPDATE accounts SET license_raw=?,license_features=?,"
                "license_expires=? WHERE username=?",
                (raw, json.dumps(sorted(lic.features)), lic.expires_at, username))
        acc = self.get(username)
        assert acc is not None
        return acc

    # ---- 枚举（会话搜索/员工市场复用的成员视图）----
    def list_users(self) -> list[Account]:
        with self._conn() as c:
            rows = c.execute("SELECT username,name,role,post,avatar FROM accounts "
                             "ORDER BY created_at").fetchall()
        return [Account(username=r["username"], name=r["name"], role=r["role"],
                        post=r["post"] or "", avatar=r["avatar"] or "")
                for r in rows]
