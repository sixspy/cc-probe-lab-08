"""栏贯验：已汇总缓冲报文数 == 汇总账报文数之和；并核空栏封印集与水位票。"""
from __future__ import annotations
import json

from app.db import 连接
from app.seed import 此刻
from app.services import 空栏封印


def 跑一次() -> dict:
    conn = 连接()
    try:
        在栏 = conn.execute(
            "SELECT COUNT(*) AS c FROM 入栏缓冲 WHERE 命运='在栏'"
        ).fetchone()["c"]
        已汇总缓冲 = conn.execute(
            "SELECT COUNT(*) AS c FROM 入栏缓冲 WHERE 命运='已汇总'"
        ).fetchone()["c"]
        汇总报文 = conn.execute(
            "SELECT COALESCE(SUM(报文数),0) AS c FROM 站点汇总账"
        ).fetchone()["c"]
        坏点 = conn.execute("SELECT COUNT(*) AS c FROM 坏点匣").fetchone()["c"]

        裁 = 空栏封印.裁决于(conn)
        数对齐 = int(已汇总缓冲) == int(汇总报文)
        对齐 = 1 if (数对齐 and 裁["裁决对齐"]) else 0

        票号 = [
            r["票号"]
            for r in conn.execute("SELECT 票号 FROM 栏水位账 ORDER BY 票号").fetchall()
        ]
        异常栏 = [f"{x['栏号']}:{x['裁决']}" for x in 裁["明细"] if x["裁决"] != "相符"]
        核 = {
            "空封数": 裁["空封数"],
            "相符数": 裁["相符数"],
            "异常数": 裁["异常数"],
            "异常": 异常栏,
            "水位对账对齐": 裁["水位对账"]["对齐"],
        }

        if 数对齐:
            说明 = "入栏已汇总与站点汇总报文数一致"
        else:
            说明 = f"撕裂：已汇总缓冲={已汇总缓冲} 汇总报文={汇总报文}"
        if 裁["裁决对齐"]:
            说明 += f"；空封 {裁['空封数']} 枚指纹相符、水位同票"
        else:
            说明 += "；空封核对异常：" + "、".join(异常栏 or ["水位对账不平"])

        时刻 = 此刻()
        conn.execute(
            """INSERT INTO 栏贯验
               (时刻,在栏笔数,汇总报文数,坏点笔数,是否对齐,说明,结栏票号,空封核对)
               VALUES (?,?,?,?,?,?,?,?)""",
            (时刻, 在栏, int(汇总报文), 坏点, 对齐, 说明,
             ",".join(票号), json.dumps(核, ensure_ascii=False)),
        )
        conn.commit()
        return {
            "时刻": 时刻,
            "在栏": 在栏,
            "已汇总缓冲": int(已汇总缓冲),
            "汇总报文": int(汇总报文),
            "坏点": 坏点,
            "是否对齐": bool(对齐),
            "说明": 说明,
            "结栏票号": 票号,
            "空封对齐": 裁["裁决对齐"],
            "空封数": 裁["空封数"],
            "空封异常": 异常栏,
            "空封核对": 核,
        }
    finally:
        conn.close()


def 只读快照() -> dict:
    """不落库的贯验快照，供页面预览。"""
    conn = 连接()
    try:
        在栏 = conn.execute(
            "SELECT COUNT(*) AS c FROM 入栏缓冲 WHERE 命运='在栏'"
        ).fetchone()["c"]
        已汇总缓冲 = conn.execute(
            "SELECT COUNT(*) AS c FROM 入栏缓冲 WHERE 命运='已汇总'"
        ).fetchone()["c"]
        汇总报文 = conn.execute(
            "SELECT COALESCE(SUM(报文数),0) AS c FROM 站点汇总账"
        ).fetchone()["c"]
        坏点 = conn.execute("SELECT COUNT(*) AS c FROM 坏点匣").fetchone()["c"]
        裁 = 空栏封印.裁决于(conn)
        数对齐 = int(已汇总缓冲) == int(汇总报文)
        return {
            "在栏": 在栏,
            "已汇总缓冲": int(已汇总缓冲),
            "汇总报文": int(汇总报文),
            "坏点": 坏点,
            "是否对齐": 数对齐 and 裁["裁决对齐"],
            "数对齐": 数对齐,
            "空封对齐": 裁["裁决对齐"],
            "空封数": 裁["空封数"],
            "空封异常": [x for x in 裁["明细"] if x["裁决"] != "相符"],
        }
    finally:
        conn.close()
