"""争用失败测：空结与灌入并发，不得漏封又成片；缺互斥会双成功。

题面红条件：空结与灌入并发双请求漏封又成片则红。
硬不变量（与调度次序无关）：
- 同一栏至多一枚封印/水位票（互斥 + 唯一约束），同栏重结同票；
- 空封栏在 入栏缓冲 / 站点汇总账 都不得再有该片行（不漏封、不成片）；
- 报文命运守恒，栏贯验与空封裁决终局皆绿。
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from app.db import 连接
from app.services import 结栏, 装载, 贯验, 空栏封印, 水位


def _报文(编号: str) -> dict:
    return {
        "报文编号": 编号,
        "站点键": "站-河东",
        "指标键": "PM25",
        "读数": 20.0,
        "观测时": "2026-11-25T08:00:00Z",
    }


def test_空结先成_补装必落新栏():
    报 = 结栏.结当前栏()
    assert 报["空栏"] is True
    lr = 装载.装一批({"报文": [_报文("late-seal-1")]})
    assert lr["入栏"] == 1
    conn = 连接()
    try:
        r = conn.execute(
            "SELECT 栏号,命运 FROM 入栏缓冲 WHERE 报文编号='late-seal-1'"
        ).fetchone()
        assert r["栏号"] == "B-demo-0001", "封印后补装必须随栏号推进落入新栏"
        assert r["栏号"] != "B-demo"
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM 入栏缓冲 WHERE 栏号='B-demo'"
        ).fetchone()["c"]
        assert n == 0, "空封旧栏不得再成片"
    finally:
        conn.close()
    assert 空栏封印.裁决()["裁决对齐"] is True
    assert 贯验.跑一次()["是否对齐"] is True


def test_灌入先成_空结转实结成片对照():
    assert 装载.装一批({"报文": [_报文("race-seq-1")]})["入栏"] == 1
    报 = 结栏.结当前栏()
    assert 报["空栏"] is False and 报["汇总数"] == 1
    conn = 连接()
    try:
        assert conn.execute(
            "SELECT COUNT(*) AS c FROM 空栏封印 WHERE 栏号='B-demo'"
        ).fetchone()["c"] == 0
        assert conn.execute(
            "SELECT COUNT(*) AS c FROM 站点汇总账 WHERE 栏号='B-demo'"
        ).fetchone()["c"] == 1
    finally:
        conn.close()
    assert 贯验.跑一次()["是否对齐"] is True


def test_并发同栏双空结_互斥只封一票():
    闸 = threading.Barrier(2)

    def 双请():
        闸.wait()
        return 结栏.结当前栏(栏号="B-demo")

    with ThreadPoolExecutor(max_workers=2) as ex:
        rs = list(ex.map(lambda _: 双请(), range(2)))

    票 = {r["批次编号"] for r in rs}
    assert len(票) == 1, f"同栏并发双请必须同票，实际 {rs}"
    assert sum(1 for r in rs if not r.get("重复")) == 1
    conn = 连接()
    try:
        for 表 in ("空栏封印", "栏水位账", "结栏批次"):
            n = conn.execute(
                f"SELECT COUNT(*) AS c FROM {表} WHERE 栏号='B-demo'"
            ).fetchone()["c"]
            assert n == 1, f"{表} B-demo 必须恰好 1 行，实际 {n}"
    finally:
        conn.close()
    assert 空栏封印.裁决()["裁决对齐"] is True


def test_空结撞灌入_并发混合不变量():
    N装, N结 = 6, 4
    闸 = threading.Barrier(N装 + N结)

    def 装(i: int):
        闸.wait()
        return 装载.装一批({"报文": [_报文(f"race-{i}-{j}") for j in range(3)]})

    def 结(i: int):
        闸.wait()
        return 结栏.结当前栏()

    with ThreadPoolExecutor(max_workers=N装 + N结) as ex:
        装fut = [ex.submit(装, i) for i in range(N装)]
        结fut = [ex.submit(结, i) for i in range(N结)]
        装报 = [f.result() for f in 装fut]   # 异常会在此抛出
        结报 = [f.result() for f in 结fut]

    assert sum(r["入栏"] for r in 装报) == N装 * 3

    conn = 连接()
    try:
        # 1) 封印/水位票栏号唯一（无漏封式重复，也无双封）
        for 表 in ("空栏封印", "栏水位账"):
            dup = conn.execute(
                f"SELECT 栏号, COUNT(*) c FROM {表} GROUP BY 栏号 HAVING c>1"
            ).fetchall()
            assert not dup, f"{表} 出现同栏多票: {[tuple(r) for r in dup]}"

        当前 = conn.execute("SELECT 值 FROM 栏规 WHERE 键='当前栏号'").fetchone()["值"]

        # 2) 空封栏不得有缓冲行/汇总行（漏封又成片之禁）
        空封栏 = [r["栏号"] for r in conn.execute("SELECT 栏号 FROM 空栏封印")]
        for 栏 in 空封栏:
            b = conn.execute(
                "SELECT COUNT(*) c FROM 入栏缓冲 WHERE 栏号=?", (栏,)
            ).fetchone()["c"]
            s = conn.execute(
                "SELECT COUNT(*) c FROM 站点汇总账 WHERE 栏号=?", (栏,)
            ).fetchone()["c"]
            assert b == 0 and s == 0, f"空封栏 {栏} 漏封成片 缓冲{b} 汇总{s}"

        # 3) 每一片缓冲行只能落在当前开栏或已持水位票的栏
        票栏 = {r["栏号"] for r in conn.execute("SELECT 栏号 FROM 栏水位账")}
        票栏.add(当前)
        野 = conn.execute(
            "SELECT DISTINCT 栏号 FROM 入栏缓冲"
        ).fetchall()
        for r in 野:
            assert r["栏号"] in 票栏, f"缓冲落入无票野栏 {r['栏号']}"
    finally:
        conn.close()

    # 4) 终局贯验 + 裁决双绿
    assert 空栏封印.裁决()["裁决对齐"] is True
    v = 贯验.跑一次()
    assert v["是否对齐"] is True, v["说明"]
    # 每次结栏都有报告返回
    assert len(结报) == N结
