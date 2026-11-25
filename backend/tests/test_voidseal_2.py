"""失败测乙：水位对账不得把漏封当已推进绿。

题面红条件：水位对账把漏封当已推进绿则红。
空封指纹与水位对账同票；贯验改读空封集，缺封/破封必须拉红贯验与裁决。
"""
from __future__ import annotations

import sqlite3

import pytest

from app.db import 连接
from app.services import 结栏, 贯验, 空栏封印, 水位


def test_空封指纹与水位票同票():
    报 = 结栏.结当前栏()
    conn = 连接()
    try:
        w = conn.execute(
            "SELECT * FROM 栏水位账 WHERE 票号=?", (报["批次编号"],)
        ).fetchone()
        assert w is not None, "结栏水位编排管道必须落 栏水位账"
        assert w["栏号"] == "B-demo"
        assert w["前号"] == "B-demo"
        assert w["后号"] == "B-demo-0001"
        assert w["空栏"] == 1
        assert w["空封指纹"] == 报["空封指纹"]
        s = conn.execute(
            "SELECT * FROM 空栏封印 WHERE 栏号='B-demo'"
        ).fetchone()
        assert s["批次编号"] == w["票号"]
        assert s["指纹"] == w["空封指纹"]
    finally:
        conn.close()
    对 = 水位.对账()
    assert 对["对齐"] is True
    assert 对["漏封"] == [] and 对["断票"] == []


def test_删掉封印_水位仍推进_裁决与贯验必须红():
    结栏.结当前栏()
    conn = 连接()
    try:
        conn.execute("DELETE FROM 空栏封印 WHERE 栏号='B-demo'")
        conn.commit()
    finally:
        conn.close()

    对 = 水位.对账()
    assert 对["对齐"] is False
    assert "B-demo" in 对["漏封"]

    裁 = 空栏封印.裁决()
    assert 裁["裁决对齐"] is False
    项 = [x for x in 裁["明细"] if x["栏号"] == "B-demo"]
    assert 项 and 项[0]["裁决"] == "封印缺失"
    assert 项[0]["可回读"] is False

    验 = 贯验.跑一次()
    assert 验["是否对齐"] is False, "漏封不得被贯验判绿"
    assert "空封" in 验["说明"] or "漏封" in 验["说明"]
    # 贯验结果留痕且挂同票清单
    conn = 连接()
    try:
        row = conn.execute("SELECT * FROM 栏贯验 ORDER BY 编号 DESC LIMIT 1").fetchone()
        assert row["是否对齐"] == 0
        assert row["结栏票号"], "贯验结果必须挂结栏票"
    finally:
        conn.close()


def test_篡改指纹可辨且拉红():
    结栏.结当前栏()
    conn = 连接()
    try:
        conn.execute("UPDATE 空栏封印 SET 指纹=? WHERE 栏号='B-demo'", ("0" * 64,))
        conn.commit()
    finally:
        conn.close()
    裁 = 空栏封印.裁决()
    assert 裁["裁决对齐"] is False
    项 = [x for x in 裁["明细"] if x["栏号"] == "B-demo"][0]
    assert 项["裁决"] in ("指纹不符", "同票指纹异")
    assert 项["指纹一致"] is False


def test_封后旧栏混入判破封():
    结栏.结当前栏()
    conn = 连接()
    try:
        # 测试视角绕过写闸直插，模拟历史/旁路漏封成片
        conn.execute("DROP TRIGGER IF EXISTS 禁写已封栏")
        conn.execute(
            """INSERT INTO 入栏缓冲(报文编号,站点键,指标键,读数,观测时,栏号,命运,入栏时)
               VALUES (?,?,?,?,?,?,?,?)""",
            ("ghost-1", "站-河东", "PM25", 9.9, "2026-11-25T00:00:00Z",
             "B-demo", "在栏", "2026-11-25T00:00:01Z"),
        )
        conn.commit()
    finally:
        conn.close()
    裁 = 空栏封印.裁决()
    assert 裁["裁决对齐"] is False
    项 = [x for x in 裁["明细"] if x["栏号"] == "B-demo"][0]
    assert 项["裁决"] in ("封后混入", "证据根不符")
    验 = 贯验.跑一次()
    assert 验["是否对齐"] is False


def test_写闸触发器拒绝直写已封栏():
    结栏.结当前栏()
    conn = 连接()
    try:
        with pytest.raises(sqlite3.Error):
            conn.execute(
                """INSERT INTO 入栏缓冲(报文编号,站点键,指标键,读数,观测时,栏号,命运,入栏时)
                   VALUES (?,?,?,?,?,?,?,?)""",
                ("ghost-2", "站-河东", "PM25", 9.9, "2026-11-25T00:00:00Z",
                 "B-demo", "在栏", "2026-11-25T00:00:01Z"),
            )
            conn.commit()
    finally:
        conn.close()


def test_有缓冲成片对照_实结不需要空封且贯验绿():
    from app.services import 装载, 夹具

    装载.装一批(夹具.读取("入栏成汇总样例"))
    报 = 结栏.结当前栏()
    assert 报["空栏"] is False
    assert 报["汇总数"] == 2
    conn = 连接()
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM 空栏封印 WHERE 栏号='B-demo'"
        ).fetchone()["c"]
        assert n == 0, "有缓冲成片的实结不写空封"
        w = conn.execute(
            "SELECT 空栏,空封指纹 FROM 栏水位账 WHERE 栏号='B-demo'"
        ).fetchone()
        assert w["空栏"] == 0 and w["空封指纹"] == ""
    finally:
        conn.close()
    assert 贯验.跑一次()["是否对齐"] is True
    assert 空栏封印.裁决()["裁决对齐"] is True
