#!/usr/bin/env python3
"""probe-08 空栏封印 · 并发双请求 + 收工五页核脚本。

用法：
    python3 scripts/并发双请求.py [BASE_URL]
    BASE_URL 默认 http://127.0.0.1:8170

核对：
1) 空结 与 灌入 双请求并发：不漏封、不成片、裁决绿；
2) 同栏双结并发：同票，不双成功；
3) 混合并发脉冲后 空封裁决 + 栏贯验 双绿；
4) 收工五页（探栏台/站点汇总账/栏贯验/栏规/入栏缓冲）页面可见“空封”。
"""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8170").rstrip("/")
FAIL: list[str] = []


def _url(path: str) -> str:
    # 中文路径/查询需要百分号编码
    return BASE + urllib.parse.quote(path, safe="/?=&")


def call(method: str, path: str, body: dict | None = None, timeout: float = 30):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(_url(path), data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def check(cond: bool, msg: str) -> None:
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        FAIL.append(msg)


def 双请求_空结撞灌入() -> None:
    print("\n[1] 空结 × 灌入 并发双请求")
    bar = threading.Barrier(2)
    out: dict[str, object] = {}

    def close():
        bar.wait()
        out["close"] = call("POST", "/api/结栏/跑", {})

    def load():
        bar.wait()
        mid = "http-race-" + uuid.uuid4().hex[:10]
        body = {"报文": [{
            "报文编号": mid, "站点键": "站-河东", "指标键": "PM25",
            "读数": 18.5, "观测时": "2026-11-25T08:00:00Z",
        }]}
        out["load"] = call("POST", "/api/观测报文/装载", body)

    t1 = threading.Thread(target=close)
    t2 = threading.Thread(target=load)
    t1.start(); t2.start(); t1.join(40); t2.join(40)

    cs, cr = out.get("close", (None, None))
    ls, lr = out.get("load", (None, None))
    check(cs == 200 and isinstance(cr, dict), f"结栏 HTTP 200（实得 {cs}）")
    check(ls == 200 and isinstance(lr, dict) and lr.get("入栏") == 1,
          f"灌入入栏 1（实得 {ls} {lr if not isinstance(lr, dict) else lr.get('入栏')}）")
    if isinstance(cr, dict):
        check(bool(cr.get("批次编号")) and (cr.get("空栏") in (True, False)),
              "结栏报告含批次且声明空/实")

    s, 裁 = call("GET", "/api/空栏封印/裁决")
    check(s == 200 and isinstance(裁, dict), "裁决口 200")
    if isinstance(裁, dict):
        check(裁.get("裁决对齐") is True,
              f"空结撞灌入后裁决绿：{裁.get('说明')}")
        # 不变量：任何空封栏在缓冲/汇总里不得成片（裁决明细已含根核对，再直查口佐证）
        bad = [x for x in 裁.get("明细", []) if x.get("裁决") not in ("相符",)]
        check(not bad, f"无漏封/破封明细（异常 {[x.get('栏号') + ':' + str(x.get('裁决')) for x in bad]}）")


def 双结_同栏同票() -> None:
    print("\n[2] 同栏双结并发（互斥/同票）")
    bar = threading.Barrier(2)
    rs: list = []

    def go():
        bar.wait()
        rs.append(call("POST", "/api/结栏/跑", {"栏号": "B-demo"}))

    with ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(go); f2 = ex.submit(go)
        f1.result(40); f2.result(40)

    tickets = set()
    for st, r in rs:
        check(st == 200 and isinstance(r, dict), f"双结之一 HTTP 200（{st}）")
        if isinstance(r, dict):
            tickets.add(r.get("批次编号"))
    check(len(tickets) == 1, f"同栏双结同票不双成功（票={tickets}）")


def 混合脉冲() -> None:
    print("\n[3] 混合并发脉冲 4 灌 × 3 结")
    nload, nclose = 4, 3
    bar = threading.Barrier(nload + nclose)

    def load(i):
        bar.wait()
        mid = f"http-burst-{uuid.uuid4().hex[:8]}-{i}"
        return call("POST", "/api/观测报文/装载", {"报文": [{
            "报文编号": mid, "站点键": "站-湖西", "指标键": "浊度",
            "读数": 1.3 + i * 0.01, "观测时": "2026-11-25T09:00:00Z",
        }]})

    def close(_):
        bar.wait()
        return call("POST", "/api/结栏/跑", {})

    with ThreadPoolExecutor(max_workers=nload + nclose) as ex:
        lf = [ex.submit(load, i) for i in range(nload)]
        cf = [ex.submit(close, i) for i in range(nclose)]
        lrs = [f.result(60) for f in lf]
        crs = [f.result(60) for f in cf]
    check(all(s == 200 for s, _ in lrs), "4 个灌入请求全 200（无 database is locked 外溢）")
    check(all(s == 200 for s, _ in crs), "3 个结栏请求全 200")
    check(all(isinstance(r, dict) and r.get("入栏") == 1 for _, r in lrs),
          "每包 1 条全部入栏")

    s, 裁 = call("GET", "/api/空栏封印/裁决")
    check(isinstance(裁, dict) and 裁.get("裁决对齐") is True,
          f"脉冲后裁决绿：{裁.get('说明') if isinstance(裁, dict) else 裁}")


def 再贯验() -> None:
    print("\n[4] 再贯验")
    s, v = call("POST", "/api/栏贯验/跑", {})
    check(s == 200 and isinstance(v, dict), "贯验 HTTP 200")
    if isinstance(v, dict):
        check(v.get("是否对齐") is True, f"贯验对齐：{v.get('说明')}")
        check(bool(v.get("结栏票号")), "贯验结果挂结栏同票清单")


def 五页核() -> None:
    print("\n[5] 收工五页核（页面可见空封）")
    pages = [
        ("/", "探栏台"),
        ("/站点汇总账.html", "站点汇总账"),
        ("/栏贯验.html", "栏贯验"),
        ("/栏规.html", "栏规策略"),
        ("/入栏缓冲.html", "入栏缓冲"),
    ]
    for path, 名 in pages:
        try:
            with urllib.request.urlopen(_url(path), timeout=15) as r:
                html = r.read().decode("utf-8", "replace")
                ok = r.status == 200 and ("空封" in html or "空栏封印" in html)
                check(ok, f"{名} {path} 200 且含“空封/空栏封印”")
        except Exception as e:  # noqa: BLE001
            check(False, f"{名} {path} 抓取失败：{e}")


def main() -> int:
    print(f"probe-08 并发双请求核 @ {BASE}  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    # 等服务起来
    for i in range(30):
        try:
            with urllib.request.urlopen(_url("/api/概览"), timeout=3) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(1)
    else:
        print("服务不可达：", BASE)
        return 2

    双请求_空结撞灌入()
    双结_同栏同票()
    混合脉冲()
    再贯验()
    五页核()

    print("\n" + ("=" * 48))
    if FAIL:
        print(f"红：{len(FAIL)} 项不符")
        for m in FAIL:
            print(" -", m)
        return 1
    print("全绿：空封证据/水位同票/互斥写闸/五页可见 均通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
