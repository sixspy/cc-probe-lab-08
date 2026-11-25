"""失败测甲：空结后正式库里必须有封印痕迹，空封指纹可回读、可裁决。

题面红条件：空结后正式无任何封印痕迹却报成功则红。
工程形态择定：甲（切流账册写 空栏封印 记录，贯验改读空封集）；
裁决只读口对甲（账册指纹）、乙（汇总占位+只读归档）两种证据形态都须能核对。
"""
from __future__ import annotations

import asyncio
import sqlite3

import pytest

from app.db import 连接
from app.services import 结栏, 空栏封印, 水位


def _空结B栏():
    报 = 结栏.结当前栏()
    assert 报["栏号"] == "B-demo"
    assert 报["空栏"] is True
    assert 报["汇总数"] == 0
    return 报


def test_空结报告即带封印票与指纹():
    报 = _空结B栏()
    assert 报.get("封印") is True
    指纹 = 报.get("空封指纹") or 报.get("指纹")
    assert isinstance(指纹, str) and len(指纹) >= 16
    assert 报.get("封印编号")
    # 批次票号一贯
    assert 报.get("票号") == 报["批次编号"]


def test_正式库表留空栏封印证据():
    报 = _空结B栏()
    conn = 连接()
    try:
        row = conn.execute(
            "SELECT * FROM 空栏封印 WHERE 栏号=?", ("B-demo",)
        ).fetchone()
        assert row is not None, "空结必须在 空栏封印 表留痕"
        assert row["批次编号"] == 报["批次编号"]
        assert row["指纹"] == 报["空封指纹"]
        assert row["形态"].startswith("甲")
        # 结栏批次记录同票存在
        b = conn.execute(
            "SELECT * FROM 结栏批次 WHERE 编号=?", (报["批次编号"],)
        ).fetchone()
        assert b is not None and b["栏号"] == "B-demo"
    finally:
        conn.close()


def test_空封指纹可回读且裁决相符():
    报 = _空结B栏()
    回 = 空栏封印.回读("B-demo")
    assert 回 is not None
    assert 回["可回读"] is True
    assert 回["裁决"] == "相符"
    assert (回.get("空封指纹") or 回.get("指纹")) == 报["空封指纹"]

    裁 = 空栏封印.裁决()
    assert 裁["裁决对齐"] is True
    assert 裁.get("是否对齐") is True
    assert 裁.get("绿") is True
    项 = [x for x in 裁["明细"] if x["栏号"] == "B-demo"]
    assert len(项) == 1 and 项[0]["裁决"] == "相符"
    assert 项[0]["水位同票"] is True


def test_裁决只读http接口可区分回读():
    _空结B栏()
    from app.main import app

    async def 打():
        async with app.test_client() as c:
            r = await c.get("/api/空栏封印/裁决")
            assert r.status_code == 200
            d = await r.get_json()
            assert d["裁决对齐"] is True
            r2 = await c.get("/api/空栏封印")
            assert r2.status_code == 200
            rows = await r2.get_json()
            assert any(x["栏号"] == "B-demo" for x in rows)
            # 别名路径同样可用
            r3 = await c.get("/api/空栏封印裁决")
            assert r3.status_code == 200

    asyncio.run(打())


def test_同栏重结同票不双封():
    报1 = _空结B栏()
    报2 = 结栏.结当前栏(栏号="B-demo")
    assert 报2.get("重复") is True
    assert 报2["批次编号"] == 报1["批次编号"]
    conn = 连接()
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM 空栏封印 WHERE 栏号='B-demo'"
        ).fetchone()["c"]
        assert n == 1
    finally:
        conn.close()


def test_封印落库与栏号推进同成同败(monkeypatch):
    报 = _空结B栏()
    assert 报["水位前"] == "B-demo"
    assert 报["水位后"] == "B-demo-0001"
    conn = 连接()
    try:
        cur = conn.execute("SELECT 值 FROM 栏规 WHERE 键='当前栏号'").fetchone()["值"]
        assert cur == "B-demo-0001"
    finally:
        conn.close()

    # 强令第二票的封印落库失败：整票回滚，栏号不得推进，批次不得半截留下
    def 炸(*a, **k):
        raise RuntimeError("封印落库失败")

    monkeypatch.setattr(空栏封印, "落封印", 炸)
    with pytest.raises(RuntimeError):
        结栏.结当前栏()  # 当前为 B-demo-0001
    conn = 连接()
    try:
        cur = conn.execute("SELECT 值 FROM 栏规 WHERE 键='当前栏号'").fetchone()["值"]
        assert cur == "B-demo-0001", "封印失败时栏号推进必须一起回滚"
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM 空栏封印 WHERE 栏号='B-demo-0001'"
        ).fetchone()["c"]
        assert n == 0
        b = conn.execute(
            "SELECT COUNT(*) AS c FROM 结栏批次 WHERE 栏号='B-demo-0001'"
        ).fetchone()["c"]
        assert b == 0
    finally:
        conn.close()


def test_形态乙占位加归档也能被裁决核对():
    """乙：现行汇总账落空占位，详细指纹进只读归档；裁决口须同样认得。"""
    结栏.结当前栏()  # 先有一枚甲形态
    时刻 = "2026-11-25T01:02:03Z"
    指纹 = 空栏封印.指纹of(
        栏号="B-yi", 批次="结栏-yi1", 时刻=时刻, 根=空栏封印.证据根([])
    )
    conn = 连接()
    try:
        conn.execute(
            """INSERT INTO 站点汇总账(汇总编号,栏号,站点键,指标键,报文数,均值,物化时,命运)
               VALUES (?,?,?,?,?,?,?,?)""",
            ("空占-B-yi", "B-yi", "", "空栏封印", 0, 0.0, 时刻, "空栏占位"),
        )
        conn.execute(
            """INSERT INTO 空栏封印归档(归档编号,栏号,批次编号,指纹,证据根,占位编号,时刻,形态)
               VALUES (?,?,?,?,?,?,?,?)""",
            ("档-B-yi", "B-yi", "结栏-yi1", 指纹, 空栏封印.证据根([]),
             "空占-B-yi", 时刻, "乙-双写两轨"),
        )
        conn.execute(
            """INSERT INTO 栏水位账(票号,栏号,前号,后号,空栏,空封指纹,汇总组数,缓冲消耗,时刻,状态)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            ("结栏-yi1", "B-yi", "B-prev", "B-yi-next", 1, 指纹, 0, 0, 时刻, "已推进"),
        )
        conn.commit()
    finally:
        conn.close()

    裁 = 空栏封印.裁决()
    项 = [x for x in 裁["明细"] if x["栏号"] == "B-yi"]
    assert len(项) == 1
    assert 项[0]["形态"].startswith("乙")
    assert 项[0]["可回读"] is True
    assert 项[0]["裁决"] == "相符"
    assert 裁["裁决对齐"] is True
