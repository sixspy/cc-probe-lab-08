"""结栏水位编排管道：进程内互斥、栏号推进、立即写事务、水位对账。

硬约束：
- 封印落库与栏号推进必须在同一个 BEGIN IMMEDIATE 事务里同成同败；
- 空结撞灌入由 编排锁 + 立即事务 + 栏水位账唯一栏号 + 写闸触发器共同封口；
- 缺互斥会双成功，故结栏/装载整条读改写都过同一把 编排锁。
"""
from __future__ import annotations

import re
import sqlite3
import threading
from contextlib import contextmanager

from app.db import 连接

# 结栏与装载共用的栏水位编排锁（RLock：同线程可重入）
编排锁 = threading.RLock()

_尾号 = re.compile(r"^(.*?)(\d+)$")


def 下一栏号(栏号: str) -> str:
    """B-demo -> B-demo-0001 -> B-demo-0002；B-01 -> B-02。"""
    s = str(栏号 or "").strip()
    m = _尾号.match(s)
    if not m:
        return f"{s}-0001"
    前缀, 序号 = m.group(1), m.group(2)
    位宽 = max(4, len(序号))
    return f"{前缀}{int(序号) + 1:0{位宽}d}"


@contextmanager
def 立即事务():
    """单连接 + autocommit 态显式 BEGIN IMMEDIATE，提交/回滚由上下文负责。"""
    conn = 连接()
    conn.isolation_level = None
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


def 账册列表(限制: int = 50) -> list[dict]:
    conn = 连接()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM 栏水位账 ORDER BY 时刻 DESC, 票号 DESC LIMIT ?",
                (限制,),
            ).fetchall()
        ]
    finally:
        conn.close()


def 对账于(conn) -> dict:
    """水位票 ↔ 空封证据同票核对（可在既有连接/事务内调用）。"""
    水票 = conn.execute("SELECT * FROM 栏水位账").fetchall()
    甲封 = {r["栏号"]: r for r in conn.execute("SELECT * FROM 空栏封印").fetchall()}
    try:
        乙封 = {r["栏号"]: r for r in conn.execute("SELECT * FROM 空栏封印归档").fetchall()}
    except sqlite3.OperationalError:
        乙封 = {}

    漏封: list[str] = []
    指纹异: list[str] = []
    for w in 水票:
        if not w["空栏"]:
            continue
        s = 甲封.get(w["栏号"]) or 乙封.get(w["栏号"])
        if s is None:
            漏封.append(w["栏号"])
            continue
        if s["批次编号"] != w["票号"] or s["指纹"] != w["空封指纹"]:
            指纹异.append(w["栏号"])

    断票: list[str] = []
    水按栏 = {w["栏号"]: w for w in 水票}
    for 栏, s in 甲封.items():
        w = 水按栏.get(栏)
        if w is None or w["票号"] != s["批次编号"]:
            断票.append(栏)

    return {
        "对齐": not (漏封 or 指纹异 or 断票),
        "票数": len(水票),
        "空票": sum(1 for w in 水票 if w["空栏"]),
        "漏封": 漏封,
        "指纹异": 指纹异,
        "断票": 断票,
    }


def 对账() -> dict:
    conn = 连接()
    try:
        return 对账于(conn)
    finally:
        conn.close()
