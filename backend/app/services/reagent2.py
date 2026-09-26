"""试剂管理业务规则：状态流转、批量领用/报废与盘点口径都收在这里。

瓶数余量只存在试剂台账行上，领用扣减、报废处置、盘点清单都读写同一份数据，
盘点页与台账看到的余量天然一致，不存在两处对账。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "reagent2"
REQUIRED_FIELDS = ["试剂编号", "试剂名称", "规格等级"]
STATUS_ORDER = ["充足", "将到期", "已开封", "已废弃"]
ACTION_RULES = {"开封登记": "已开封", "标记到期": "将到期", "废弃处置": "已废弃"}
NEGATIVE_ACTIONS = []
# 批量报废只处理还能动的状态；已开封、已废弃会被逐条挑出来并说明原因
DISPOSABLE_STATUSES = ["充足", "将到期"]
# 已废弃试剂不能再领用，其余状态都还有可领用的瓶数
NON_REQUISITION_STATUSES = ["已废弃"]


def _to_int(value: Any) -> int:
    """瓶数余量、领用数量统一按整数口径读取，读不出来按 0 处理。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


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
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["存放方位"] = values.get("存放方位") or ""
        entry["有效期至"] = values.get("有效期至") or ""
        entry["瓶数余量"] = _to_int(values.get("瓶数余量"))
        entry["领用记录"] = []
        entry["status"] = STATUS_ORDER[0]
        entry["试剂状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
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
        entry["status"] = target
        entry["试剂状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"试剂已{action}"

    def inventory(self) -> list[dict[str, Any]]:
        """盘点清单：直接读台账行，瓶数余量与台账、领用扣减看到的是同一个数。"""
        return [
            {
                "id": row.get("id"),
                "试剂编号": row.get("试剂编号"),
                "试剂名称": row.get("试剂名称"),
                "规格等级": row.get("规格等级"),
                "存放方位": row.get("存放方位"),
                "瓶数余量": _to_int(row.get("瓶数余量")),
                "status": row.get("status"),
                "领用次数": len(row.get("领用记录") or []),
            }
            for row in store.rows(MODULE)
        ]

    def batch_requisition(self, 领用日期: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        """整组领用：逐条校验逐条扣减，成功的条目不回滚，失败的写清试剂编号与原因。

        每条领用记录都挂在对应试剂编号下面，并带上规格等级快照——规格等级不同的
        试剂在台账里是不同的行，记录天然不会合并成一条。
        """
        batch_no = self._next_batch_no("LY", 领用日期, "领用记录")
        results: list[dict[str, Any]] = []
        seen: set[int] = set()
        for item in items:
            entry_id = _to_int(item.get("id"))
            entry = store.find(MODULE, entry_id)
            code = str(entry.get("试剂编号")) if entry else f"id={entry_id}"
            fail = self._validate_requisition(entry, item, entry_id, seen)
            if fail:
                results.append({"id": entry_id, "试剂编号": code, "ok": False, "message": fail})
                continue
            seen.add(entry_id)
            quantity = _to_int(item.get("领用数量"))
            remain = _to_int(entry.get("瓶数余量")) - quantity
            entry["瓶数余量"] = remain
            records = entry.setdefault("领用记录", [])
            records.append({
                "批次号": batch_no,
                "试剂编号": entry.get("试剂编号"),
                "规格等级": entry.get("规格等级"),
                "领用人": str(item.get("领用人")).strip(),
                "领用日期": 领用日期,
                "领用数量": quantity,
                "领用后余量": remain,
            })
            results.append({
                "id": entry_id,
                "试剂编号": code,
                "ok": True,
                "message": f"已领用 {quantity} 瓶，余量 {remain} 瓶",
            })
        return self._summarize(batch_no, results, "领用")

    def batch_disposal(self, 报废日期: str, 处置说明: str | None, ids: list[int]) -> dict[str, Any]:
        """整组报废：已开封、已废弃的逐条挑出来不处理，只报废还能动的几条。"""
        batch_no = self._next_batch_no("BF", 报废日期, "处置记录")
        results: list[dict[str, Any]] = []
        seen: set[int] = set()
        for raw_id in ids:
            entry_id = _to_int(raw_id)
            entry = store.find(MODULE, entry_id)
            code = str(entry.get("试剂编号")) if entry else f"id={entry_id}"
            if entry is None:
                results.append({"id": entry_id, "试剂编号": code, "ok": False, "message": "试剂不存在或已归档"})
                continue
            if entry_id in seen:
                results.append({"id": entry_id, "试剂编号": code, "ok": False, "message": "同一批次重复提交，已跳过"})
                continue
            seen.add(entry_id)
            status = str(entry.get("status") or "")
            if status not in DISPOSABLE_STATUSES:
                reason = "已开封试剂不参与批量报废，请单独处置" if status == "已开封" else "已废弃，无需重复报废"
                results.append({"id": entry_id, "试剂编号": code, "ok": False, "message": reason})
                continue
            entry["status"] = "已废弃"
            entry["试剂状态"] = "已废弃"
            entry["pending"] = False
            entry.setdefault("处置记录", []).append({
                "批次号": batch_no,
                "试剂编号": entry.get("试剂编号"),
                "规格等级": entry.get("规格等级"),
                "报废日期": 报废日期,
                "处置说明": 处置说明 or "",
                "处置前状态": status,
            })
            results.append({"id": entry_id, "试剂编号": code, "ok": True, "message": f"已报废，原状态「{status}」"})
        return self._summarize(batch_no, results, "报废")

    def _validate_requisition(
        self,
        entry: dict[str, Any] | None,
        item: dict[str, Any],
        entry_id: int,
        seen: set[int],
    ) -> str | None:
        """单条领用校验：返回 None 表示可以扣减，否则返回卡住的原因。"""
        if entry is None:
            return "试剂不存在或已归档"
        if entry_id in seen:
            return "同一批次重复提交，请合并数量后一次提交"
        if str(entry.get("status") or "") in NON_REQUISITION_STATUSES:
            return "已废弃试剂不能领用"
        if not str(item.get("领用人") or "").strip():
            return "领用人未填写"
        quantity = _to_int(item.get("领用数量"))
        if quantity < 1:
            return "领用数量需为正整数"
        stock = _to_int(entry.get("瓶数余量"))
        if quantity > stock:
            return f"瓶数余量 {stock} 瓶，不够领用 {quantity} 瓶"
        return None

    def _next_batch_no(self, prefix: str, biz_date: str, record_field: str) -> str:
        """批次号：业务日期 + 全台账同类记录数递增，同组提交共用一个批次号。"""
        digits = "".join(ch for ch in str(biz_date) if ch.isdigit())
        day = digits[:8] if len(digits) >= 8 else date.today().strftime("%Y%m%d")
        seq = sum(len(row.get(record_field) or []) for row in store.rows(MODULE)) + 1
        return f"{prefix}-{day}-{seq:04d}"

    def _summarize(self, batch_no: str, results: list[dict[str, Any]], verb: str) -> dict[str, Any]:
        succeeded = sum(1 for item in results if item["ok"])
        failed = len(results) - succeeded
        if not results:
            message = f"没有需要{verb}的试剂行"
        elif failed == 0:
            message = f"{verb}完成：{succeeded} 条全部成功"
        else:
            message = f"{verb}部分完成：成功 {succeeded} 条，{failed} 条被卡住，成功的已保留不回滚"
        return {
            "ok": bool(results) and failed == 0,
            "message": message,
            "批次号": batch_no,
            "succeeded": succeeded,
            "failed": failed,
            "results": results,
        }
