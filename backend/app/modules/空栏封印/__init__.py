"""空栏封印（probe-08 已实装，择定形态甲：切流账册）

契约：
- 入栏为空时结栏仍写空栏封印记录（app.services.空栏封印 / 表 空栏封印）
- 封印落库与栏号推进同事务；编排锁互斥；已封栏写闸禁写
- 裁决只读口 GET /api/空栏封印/裁决，形态中立核对甲/乙两种证据
- 不得改坏基线默认门槛 happy path（装载→入栏/坏点→结栏汇总→贯验）。
- 页面须能读到：当前策略名、命运变化、可点的下一步。
"""
NAME = "空栏封印"
CONTRACT = "入栏为空时结栏仍写空栏封印记录"
HOOKS = ("before_load", "after_load", "decide_gate", "before_close", "after_close", "extra_verify_checks")
实装形态 = "甲-切流账册"


def describe() -> dict:
    return {
        "空桩": NAME,
        "契约": CONTRACT,
        "钩子": list(HOOKS),
        "默认启用": True,
        "实装": True,
        "实装形态": 实装形态,
        "裁决口": "/api/空栏封印/裁决",
    }


def before_load(batch: dict) -> dict:
    return batch


def after_load(report: dict) -> dict:
    return report


def decide_gate(event: dict, rules: dict) -> str:
    return "入栏"


def before_close(pen_id: str) -> None:
    return None


def after_close(report: dict) -> dict:
    return report


def extra_verify_checks(snapshot: dict) -> list[str]:
    return []
