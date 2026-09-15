"""薄持久化适配层 — M1-12。

统一连接工厂：默认 SQLite（纯 stdlib，信创资质内零依赖可跑全绿）；
达梦 / 人大金仓 / OceanBase 通过各自驱动插拔（检测到即用，否则回退 SQLite）。

信创 DB 方言差异（sqlite FTS5 虚拟表、`?` 占位符 vs PG/MySQL 风格）是切库时
的**已知边界**：`ponytail:` 三处存储（session_store / accounts / scheduler）
的 DDL 与 SQL 均按 SQLite 方言编写，切到达梦/金仓/OB 需做方言迁移
（见 docs/roadmap M1-12）。本层只负责「连到哪个库」，不翻译 SQL。
"""
from __future__ import annotations

import os

SQLITE = "sqlite"
# 方言 → 候选驱动模块名（按优先级）
_DIALECTS = {
    "dm": ("dmPython",),          # 达梦
    "kingbase": ("psycopg", "psycopg2"),   # 人大金仓（PG 协议）
    "oceanbase": ("pymysql", "mysql.connector"),  # OceanBase（MySQL 协议）
}


def available_dialects() -> list[str]:
    """返回当前环境实际可用的方言（含 sqlite）。"""
    out = [SQLITE]
    for name, mods in _DIALECTS.items():
        for m in mods:
            try:
                __import__(m)
                out.append(name)
                break
            except ImportError:
                continue
    return out


def connect(dsn: str = "", dialect: str = SQLITE, **kw):
    """返回一个连接对象。

    - dialect=sqlite（默认）：dsn 为 .sqlite3 文件路径 → sqlite3.Connection。
    - dialect=dm/kingbase/oceanbase：加载对应驱动；未安装抛 ConnectionError。
    """
    if dialect == SQLITE:
        import sqlite3
        return sqlite3.connect(dsn, **kw)

    driver = _load_driver(dialect)
    params = dict(kv.split("=", 1) for kv in dsn.split(";") if kv)
    return _dialect_connect(dialect, driver, params, **kw)


def _load_driver(dialect: str):
    mods = _DIALECTS.get(dialect)
    if not mods:
        raise ValueError(f"未知方言: {dialect}（可用 {list(_DIALECTS)}）")
    for m in mods:
        try:
            return __import__(m)
        except ImportError:
            continue
    raise ConnectionError(
        f"方言 {dialect} 需要驱动 {'/'.join(mods)}，请先安装（信创部署时）"
    )


def _dialect_connect(dialect: str, driver, params: dict, **kw):
    """按方言调用驱动建连。参数细节以厂商文档为准（本机无这些库，
    ponytail: 部署时核对端口/参数名）。"""
    if dialect == "dm":
        return driver.connect(
            user=params.get("user"), password=params.get("password"),
            server=params.get("server"), port=int(params.get("port", "5236")),
            database=params.get("database"),
        )
    if dialect == "kingbase":
        return driver.connect(
            host=params.get("host", "127.0.0.1"),
            port=int(params.get("port", "54321")),
            dbname=params.get("database"), user=params.get("user"),
            password=params.get("password"),
        )
    # oceanbase（mysql 协议）
    return driver.connect(
        host=params.get("host", "127.0.0.1"),
        port=int(params.get("port", "3306")),
        database=params.get("database"), user=params.get("user"),
        password=params.get("password"),
    )


def storage_path() -> str:
    """默认存储目录：运行目录下 .aimate/。"""
    return os.path.join(os.getcwd(), ".aimate")


def ensure_dir() -> str:
    d = storage_path()
    os.makedirs(d, exist_ok=True)
    return d
