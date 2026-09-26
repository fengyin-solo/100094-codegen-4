"""试剂管理业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "reagent2"
REQUIRED_FIELDS = ["试剂编号", "试剂名称", "规格等级"]
OPTIONAL_FIELDS = ["存放方位", "有效期至"]
STATUS_ORDER = ["充足", "将到期", "已开封", "已废弃"]
ACTION_RULES = {"开封登记": "已开封", "标记到期": "将到期", "废弃处置": "已废弃"}
NEGATIVE_ACTIONS = []
CHECKOUT_BLOCKED_STATUS = "已废弃"
DISPOSE_SKIP_STATUSES = {"已开封", "已废弃"}


def _to_int(value: Any) -> int | None:
    """把瓶数、数量这类字段收敛成非负整数；转不动时返回 None 交给校验层说明。"""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _balance(entry: dict[str, Any]) -> int:
    return _to_int(entry.get("瓶数余量")) or 0


def _set_status(entry: dict[str, Any], status: str) -> None:
    """状态与台账展示列一起换，保证盘点页和试剂台账看到的是同一份数据。"""
    entry["status"] = status
    entry["试剂状态"] = status
    entry["pending"] = status != STATUS_ORDER[-1]


def _fail(entry_id: Any, code: str, message: str) -> dict[str, Any]:
    return {"id": entry_id, "试剂编号": code or None, "ok": False, "message": message}


class Reagent2Service:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("试剂编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS + OPTIONAL_FIELDS})
        entry["瓶数余量"] = _to_int(values.get("瓶数余量")) or 0
        entry["领用记录"] = []
        entry["报废记录"] = []
        entry["abnormal"] = False
        _set_status(entry, STATUS_ORDER[0])
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"试剂 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于试剂管理可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        if target == "已废弃":
            disposed = self._dispose(entry, date.today().isoformat())
            return entry, f"试剂已{action}，报废 {disposed} 瓶，瓶数余量归零"
        _set_status(entry, target)
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"试剂已{action}"

    def batch_checkout(self, checkout_date: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        """整组领用：逐条独立扣减，成功的立即落库不回滚，失败的带原因返回供单独重试。"""
        results = [self._checkout_one(checkout_date, item) for item in items]
        return self._summarize(results)

    def batch_dispose(self, ids: list[int], dispose_date: str) -> dict[str, Any]:
        """批量报废：已开封、已废弃的逐条挑出说明原因，只处理还能动的那几条。"""
        results = [self._dispose_one(entry_id, dispose_date) for entry_id in ids]
        return self._summarize(results)

    def _summarize(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        succeeded = sum(1 for result in results if result["ok"])
        return {
            "ok": succeeded == len(results),
            "succeeded": succeeded,
            "failed": len(results) - succeeded,
            "results": results,
        }

    def _checkout_one(self, checkout_date: str, item: dict[str, Any]) -> dict[str, Any]:
        entry_id = item.get("id")
        code = str(item.get("试剂编号") or "").strip()
        grade = str(item.get("规格等级") or "").strip()
        receiver = str(item.get("领用人") or "").strip()
        label = code or f"#{entry_id}"

        entry = store.find(MODULE, entry_id) if isinstance(entry_id, int) else None
        if entry is None:
            return _fail(entry_id, code, f"试剂 {label} 不存在或已归档")
        real_code = str(entry.get("试剂编号", ""))
        if code and code != real_code:
            return _fail(entry_id, code, f"提交编号 {code} 与台账 {real_code} 不一致，请刷新列表后重试")
        if grade and grade != str(entry.get("规格等级", "")):
            return _fail(entry_id, code, f"规格等级与台账「{entry.get('规格等级')}」不一致，不同规格等级不能合并领用")
        if not receiver:
            return _fail(entry_id, real_code, f"{real_code} 领用人未填写")
        amount = _to_int(item.get("数量"))
        if amount is None or amount < 1:
            return _fail(entry_id, real_code, f"{real_code} 领用数量需为不小于 1 的整数")
        if entry.get("status") == CHECKOUT_BLOCKED_STATUS:
            return _fail(entry_id, real_code, f"{real_code} 已废弃，不能领用")
        balance = _balance(entry)
        if amount > balance:
            return _fail(entry_id, real_code, f"{real_code} 瓶数余量不足：余 {balance} 瓶，本次申领 {amount} 瓶")

        entry["瓶数余量"] = balance - amount
        entry.setdefault("领用记录", []).append({
            "试剂编号": real_code,
            "规格等级": entry.get("规格等级"),
            "领用人": receiver,
            "领用日期": checkout_date,
            "领用数量": amount,
            "剩余瓶数": entry["瓶数余量"],
        })
        return {
            "id": entry["id"],
            "试剂编号": real_code,
            "ok": True,
            "message": f"{real_code} 已领用 {amount} 瓶，瓶数余量 {balance} → {entry['瓶数余量']}",
        }

    def _dispose_one(self, entry_id: int, dispose_date: str) -> dict[str, Any]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return _fail(entry_id, "", f"试剂 #{entry_id} 不存在或已归档")
        code = str(entry.get("试剂编号", ""))
        status = entry.get("status")
        if status == "已开封":
            return _fail(entry_id, code, f"{code} 已开封，需单独走开封处置流程，未纳入本次报废")
        if status == "已废弃":
            return _fail(entry_id, code, f"{code} 此前已报废，无需重复处理")
        disposed = self._dispose(entry, dispose_date)
        return {
            "id": entry["id"],
            "试剂编号": code,
            "ok": True,
            "message": f"{code} 已报废 {disposed} 瓶，瓶数余量归零",
        }

    def _dispose(self, entry: dict[str, Any], dispose_date: str) -> int:
        disposed = _balance(entry)
        entry["瓶数余量"] = 0
        entry.setdefault("报废记录", []).append({
            "试剂编号": entry.get("试剂编号"),
            "报废日期": dispose_date,
            "报废数量": disposed,
        })
        _set_status(entry, "已废弃")
        entry["abnormal"] = False
        return disposed
