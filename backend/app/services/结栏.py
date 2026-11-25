"""结栏：入栏缓冲按站点+指标汇总物化。

probe-08 空栏封印：结栏落入“结栏水位编排管道”——
结栏批次、空栏封印（甲形态切流账册）、栏水位账与栏号推进在同一把编排锁、
同一个 BEGIN IMMEDIATE 事务里同成同败；同栏并发/重结按水位票同票回放。
"""
from __future__ import annotations

import json
import uuid
from collections import defaultdict

from app.db import 连接
from app.seed import 此刻
from app.services import 目录, 水位, 空栏封印


def _回放(conn, w) -> dict:
    """同栏已结：返回原票报告（同票），不再写第二批/第二封。"""
    b = conn.execute("SELECT 报告 FROM 结栏批次 WHERE 编号=?", (w["票号"],)).fetchone()
    if b and b["报告"]:
        try:
            报 = json.loads(b["报告"])
        except json.JSONDecodeError:
            报 = {}
    else:
        报 = {}
    报.update({
        "重复": True,
        "同票": True,
        "票号": w["票号"],
        "批次编号": w["票号"],
        "栏号": w["栏号"],
        "裁决": "该栏已封印，同票回读，不重复结栏",
    })
    return 报


def 结当前栏(栏号: str | None = None) -> dict:
    规 = 目录.栏规()
    目标 = 栏号 or 规.get("当前栏号", "B-demo")
    批 = f"结栏-{uuid.uuid4().hex[:8]}"

    with 水位.编排锁:
        with 水位.立即事务() as conn:
            # 互斥后先看水位票：同栏已封则同票回放，杜绝双成功
            w0 = conn.execute("SELECT * FROM 栏水位账 WHERE 栏号=?", (目标,)).fetchone()
            if w0 is not None:
                return _回放(conn, w0)

            cur = conn.execute("SELECT 值 FROM 栏规 WHERE 键='当前栏号'").fetchone()
            当前号 = cur["值"] if cur else 目标

            rows = conn.execute(
                "SELECT * FROM 入栏缓冲 WHERE 栏号=? AND 命运='在栏'", (目标,)
            ).fetchall()
            groups: dict[tuple[str, str], list] = defaultdict(list)
            for r in rows:
                groups[(r["站点键"], r["指标键"])].append(r)

            时刻 = 此刻()
            下一号 = 水位.下一栏号(目标)
            根 = 空栏封印.证据根(rows)
            空 = len(rows) == 0
            封编号 = 空栏封印.新封印编号(目标) if 空 else ""
            指纹 = (
                空栏封印.指纹of(栏号=目标, 批次=批, 时刻=时刻, 根=根) if 空 else ""
            )

            汇总 = 0
            明细 = []
            for (站点, 指标), evs in groups.items():
                均值 = sum(float(e["读数"]) for e in evs) / len(evs)
                编号 = f"汇-{目标}-{站点}-{指标}-{uuid.uuid4().hex[:6]}"
                conn.execute(
                    """INSERT INTO 站点汇总账(汇总编号,栏号,站点键,指标键,报文数,均值,物化时,命运)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (编号, 目标, 站点, 指标, len(evs), 均值, 时刻, "已汇总"),
                )
                for e in evs:
                    conn.execute(
                        "UPDATE 入栏缓冲 SET 命运=? WHERE 报文编号=?",
                        ("已汇总", e["报文编号"]),
                    )
                    conn.execute(
                        "UPDATE 观测报文 SET 命运=? WHERE 报文编号=?",
                        ("已汇总", e["报文编号"]),
                    )
                汇总 += 1
                明细.append({
                    "汇总编号": 编号,
                    "站点键": 站点,
                    "指标键": 指标,
                    "报文数": len(evs),
                    "均值": round(均值, 4),
                })

            报告 = {
                "批次编号": 批,
                "票号": 批,
                "栏号": 目标,
                "当前栏号": 当前号,
                "汇总数": 汇总,
                "缓冲消耗": len(rows),
                "明细": 明细,
                "空栏": 空,
                "封印": True,
                "空栏封印": 空,
                "封印编号": 封编号,
                "指纹": 指纹,
                "空封指纹": 指纹,
                "证据根": 根,
                "形态": 空栏封印.形态 if 空 else "",
                "水位前": 目标,
                "水位后": 下一号,
                "水位": {
                    "前号": 目标,
                    "后号": 下一号,
                    "推进": True,
                    "票号": 批,
                    "空封指纹": 指纹,
                },
                "可回读": 空,
                "重复": False,
                "裁决": "空栏已封印，指纹可回读" if 空 else "成片汇总物化，水位票同封",
            }

            # 批次先落：随后封印/水位/推进任一步失败，整事务回滚，批次不留半截
            conn.execute(
                """INSERT INTO 结栏批次(编号,栏号,时刻,汇总数,报告) VALUES (?,?,?,?,?)""",
                (批, 目标, 时刻, 汇总, json.dumps(报告, ensure_ascii=False)),
            )
            if 空:
                空栏封印.落封印(
                    conn,
                    封印编号=封编号,
                    指纹=指纹,
                    栏号=目标,
                    批次编号=批,
                    证据根值=根,
                    时刻=时刻,
                    水位前=目标,
                    水位后=下一号,
                )
            conn.execute(
                """INSERT INTO 栏水位账
                   (票号,栏号,前号,后号,空栏,空封指纹,汇总组数,缓冲消耗,时刻,状态)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (批, 目标, 目标, 下一号, 1 if 空 else 0, 指纹,
                 汇总, len(rows), 时刻,
                 "空封已落·已推进" if 空 else "已汇总·已推进"),
            )
            conn.execute(
                """INSERT INTO 栏规(键,值) VALUES ('当前栏号',?)
                   ON CONFLICT(键) DO UPDATE SET 值=excluded.值""",
                (下一号,),
            )
            return 报告


def 预览结栏() -> dict:
    """只读：当前栏在栏缓冲按站点指标分组，不写库。"""
    规 = 目录.栏规()
    栏号 = 规.get("当前栏号", "B-demo")
    conn = 连接()
    try:
        rows = conn.execute(
            "SELECT * FROM 入栏缓冲 WHERE 栏号=? AND 命运='在栏'", (栏号,)
        ).fetchall()
        groups: dict[tuple[str, str], list] = defaultdict(list)
        for r in rows:
            groups[(r["站点键"], r["指标键"])].append(dict(r))
        预览 = []
        for (站点, 指标), evs in sorted(groups.items()):
            预览.append({
                "站点键": 站点,
                "指标键": 指标,
                "报文数": len(evs),
                "均值": round(sum(float(e["读数"]) for e in evs) / len(evs), 4),
            })
        return {
            "栏号": 栏号,
            "在栏": len(rows),
            "将汇总组": 预览,
            "下一栏号": 水位.下一栏号(栏号),
            "空栏将封": len(rows) == 0,
        }
    finally:
        conn.close()
