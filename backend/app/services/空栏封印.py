"""空栏封印裁决（形态甲：切流账册）。

择定工程形态：**甲 · 切流账册** —— 空结也在 空栏封印 表写下正式记录与空封指纹，
虽无汇总行，账册可回看指纹；贯验改读空封集，并与 栏水位账 同票对账。

裁决只读口同时认得形态乙（站点汇总账空占位 + 空栏封印归档只读双轨），
故“空缓冲结栏两种形态都能核对封印证据”。
"""
from __future__ import annotations

import hashlib
import uuid

from app.db import 连接
from app.services import 水位

形态 = "甲-切流账册"
证据版本 = "voidseal-evidence-v1"
指纹版本 = "VOIDSEAL-v1"


def 证据根(rows) -> str:
    """对结栏时刻该栏全量缓冲行做规范哈希；空集也有确定根。"""
    h = hashlib.sha256()
    h.update(f"{证据版本}\n".encode("utf-8"))
    for r in sorted(rows, key=lambda x: str(x["报文编号"])):
        h.update(
            "{}|{}|{}|{!r}\n".format(
                r["报文编号"], r["站点键"], r["指标键"], float(r["读数"])
            ).encode("utf-8")
        )
    return h.hexdigest()


def 指纹of(*, 栏号: str, 批次: str, 时刻: str, 根: str) -> str:
    文 = f"{指纹版本}|{栏号}|{批次}|{时刻}|{根}"
    return hashlib.sha256(文.encode("utf-8")).hexdigest()


def 新封印编号(栏号: str) -> str:
    return f"封-{栏号}-{uuid.uuid4().hex[:8]}"


def 落封印(conn, *, 封印编号: str, 指纹: str, 栏号: str, 批次编号: str,
           证据根值: str, 时刻: str, 水位前: str, 水位后: str) -> dict:
    """在结栏事务内写空封记录；与栏号推进同成同败。"""
    conn.execute(
        """INSERT INTO 空栏封印
           (封印编号,栏号,批次编号,指纹,证据根,时刻,水位前,水位后,形态)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (封印编号, 栏号, 批次编号, 指纹, 证据根值, 时刻, 水位前, 水位后, 形态),
    )
    return {
        "封印编号": 封印编号,
        "栏号": 栏号,
        "批次编号": 批次编号,
        "指纹": 指纹,
        "空封指纹": 指纹,
        "证据根": 证据根值,
        "时刻": 时刻,
        "水位前": 水位前,
        "水位后": 水位后,
        "形态": 形态,
    }


def 空封集(栏号: str | None = None) -> list[dict]:
    conn = 连接()
    try:
        if 栏号:
            rows = conn.execute(
                "SELECT * FROM 空栏封印 WHERE 栏号=? ORDER BY 时刻 DESC", (栏号,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM 空栏封印 ORDER BY 时刻 DESC, 封印编号 DESC"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# 只读列表别名
列表 = 空封集


def _活根(conn, 栏号: str) -> tuple[str, int]:
    """该栏当前缓冲全量行的证据根与行数（封后混入即可识破）。"""
    rows = conn.execute(
        "SELECT 报文编号,站点键,指标键,读数 FROM 入栏缓冲 WHERE 栏号=?", (栏号,)
    ).fetchall()
    return 证据根(rows), len(rows)


def _核甲(conn, s, 水按栏: dict) -> dict:
    栏 = s["栏号"]
    活根, 行数 = _活根(conn, 栏)
    根一致 = 活根 == s["证据根"]
    算指纹 = 指纹of(栏号=栏, 批次=s["批次编号"], 时刻=s["时刻"], 根=s["证据根"])
    指纹一致 = 算指纹 == s["指纹"]
    w = 水按栏.get(栏)
    水位同票 = bool(
        w is not None and w["票号"] == s["批次编号"] and w["空封指纹"] == s["指纹"]
    )
    if not 根一致:
        状态 = "封后混入" if 行数 else "证据根不符"
        可回读 = False
    elif not 指纹一致:
        状态 = "指纹不符"
        可回读 = False
    elif w is None:
        状态 = "水位断票"
        可回读 = False
    elif not 水位同票:
        状态 = "同票指纹异"
        可回读 = False
    else:
        状态 = "相符"
        可回读 = True
    return {
        "栏号": 栏,
        "形态": s["形态"] or 形态,
        "封印编号": s["封印编号"],
        "批次编号": s["批次编号"],
        "票号": s["批次编号"],
        "指纹": s["指纹"],
        "空封指纹": s["指纹"],
        "证据根": s["证据根"],
        "时刻": s["时刻"],
        "水位前": s["水位前"],
        "水位后": s["水位后"],
        "水位同票": 水位同票,
        "指纹一致": 指纹一致,
        "根一致": 根一致,
        "缓冲行数": 行数,
        "可回读": 可回读,
        "裁决": 状态,
        "状态": 状态,
    }


def _核乙(conn, a, 水按栏: dict) -> dict:
    栏 = a["栏号"]
    活根, 行数 = _活根(conn, 栏)
    根一致 = 活根 == (a["证据根"] or 证据根([]))
    算指纹 = 指纹of(栏号=栏, 批次=a["批次编号"], 时刻=a["时刻"], 根=a["证据根"] or 证据根([]))
    指纹一致 = 算指纹 == a["指纹"]
    占位 = None
    if a["占位编号"]:
        占位 = conn.execute(
            "SELECT * FROM 站点汇总账 WHERE 汇总编号=?", (a["占位编号"],)
        ).fetchone()
    if 占位 is None:
        占位 = conn.execute(
            "SELECT * FROM 站点汇总账 WHERE 栏号=? AND 命运 IN ('空栏占位','空栏封印') "
            "ORDER BY 报文数 ASC LIMIT 1",
            (栏,),
        ).fetchone()
    占位在 = 占位 is not None and int(占位["报文数"]) == 0
    w = 水按栏.get(栏)
    水位同票 = bool(
        w is not None and w["票号"] == a["批次编号"] and w["空封指纹"] == a["指纹"]
    )
    if not 占位在:
        状态 = "占位缺失"
    elif not 根一致:
        状态 = "封后混入" if 行数 else "证据根不符"
    elif not 指纹一致:
        状态 = "指纹不符"
    elif w is not None and not 水位同票:
        状态 = "同票指纹异"
    else:
        状态 = "相符"
    return {
        "栏号": 栏,
        "形态": a["形态"] or "乙-双写两轨",
        "封印编号": a["归档编号"],
        "批次编号": a["批次编号"],
        "票号": a["批次编号"],
        "指纹": a["指纹"],
        "空封指纹": a["指纹"],
        "证据根": a["证据根"],
        "占位编号": a["占位编号"],
        "时刻": a["时刻"],
        "水位同票": 水位同票,
        "指纹一致": 指纹一致,
        "根一致": 根一致,
        "占位在": 占位在,
        "缓冲行数": 行数,
        "可回读": 状态 == "相符",
        "裁决": 状态,
        "状态": 状态,
    }


def 裁决于(conn, 栏号: str | None = None) -> dict:
    """只读裁决核心：可在既有连接内调用，不写任何库。"""
    甲rows = conn.execute("SELECT * FROM 空栏封印").fetchall()
    try:
        乙rows = conn.execute("SELECT * FROM 空栏封印归档").fetchall()
    except Exception:
        乙rows = []
    水rows = conn.execute("SELECT * FROM 栏水位账").fetchall()
    水按栏 = {w["栏号"]: w for w in 水rows}

    明细: list[dict] = []
    见栏: set[str] = set()
    for s in 甲rows:
        if 栏号 and s["栏号"] != 栏号:
            continue
        明细.append(_核甲(conn, s, 水按栏))
        见栏.add(s["栏号"])
    for a in 乙rows:
        if 栏号 and a["栏号"] != 栏号:
            continue
        明细.append(_核乙(conn, a, 水按栏))
        见栏.add(a["栏号"])

    # 水位票声称空结却找不到任何封印证据 -> 封印缺失（失败测乙的红条件）
    for w in 水rows:
        if not w["空栏"]:
            continue
        if 栏号 and w["栏号"] != 栏号:
            continue
        if w["栏号"] in {s["栏号"] for s in 甲rows} or w["栏号"] in {
            a["栏号"] for a in 乙rows
        }:
            continue
        明细.append({
            "栏号": w["栏号"],
            "形态": "",
            "封印编号": "",
            "批次编号": w["票号"],
            "票号": w["票号"],
            "指纹": "",
            "空封指纹": "",
            "时刻": w["时刻"],
            "水位同票": False,
            "可回读": False,
            "裁决": "封印缺失",
            "状态": "封印缺失",
        })

    if 栏号:
        明细 = [x for x in 明细 if x["栏号"] == 栏号]

    异常 = [x for x in 明细 if x["裁决"] != "相符"]
    对账 = 水位.对账于(conn)
    对齐 = not 异常 and 对账["对齐"]
    甲集 = [dict(s) for s in 甲rows if not 栏号 or s["栏号"] == 栏号]
    return {
        "接口": "空栏封印裁决",
        "形态": 形态,
        "裁决对齐": 对齐,
        "对齐": 对齐,
        "是否对齐": 对齐,
        "绿": 对齐,
        "空封数": len(甲集),
        "归档数": len(乙rows),
        "相符数": len([x for x in 明细 if x["裁决"] == "相符"]),
        "异常数": len(异常),
        "明细": 明细,
        "空封集": 甲集,
        "水位对账": 对账,
        "说明": (
            f"空封 {len(甲集)} 枚，相符 {len(明细) - len(异常)}，异常 {len(异常)}；"
            + ("指纹可回读、水位同票" if 对齐 else "存在漏封/断票/指纹不符，不得判绿")
        ),
    }


def 裁决(栏号: str | None = None) -> dict:
    """新增的空栏封印裁决只读接口（服务口）。"""
    conn = 连接()
    try:
        return 裁决于(conn, 栏号)
    finally:
        conn.close()


def 回读(栏号: str) -> dict | None:
    裁 = 裁决(栏号)
    for x in 裁["明细"]:
        if x["栏号"] == 栏号:
            return x
    return None
