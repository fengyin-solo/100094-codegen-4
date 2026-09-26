"""试剂管理接口：维护试剂，覆盖开封登记、标记到期、废弃处置与批量领用/报废。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import (
    ActionResult,
    BatchDisposalPayload,
    BatchResult,
    BatchRequisitionPayload,
    EntryPayload,
    PageResult,
)
from app.services.reagent2 import Reagent2Service

router = APIRouter(prefix="/api/reagent2", tags=["试剂管理"])

service = Reagent2Service()

LIST_FIELDS = ["试剂编号", "试剂名称", "规格等级", "存放方位", "有效期至", "瓶数余量", "领用记录", "试剂状态"]
STATUSES = ["充足", "将到期", "已开封", "已废弃"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按试剂编号检索"),
    status: str | None = Query(default=None, description="充足、将到期、已开封、已废弃"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按试剂编号与状态过滤试剂管理列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/inventory")
def inventory_entries() -> dict[str, Any]:
    """盘点清单：与台账同一份数据，瓶数余量不会对不上。"""
    items = service.inventory()
    return {"module": "reagent2", "total": len(items), "items": items}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出试剂管理清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "reagent2", "total": total, "items": items}


@router.post("/batch-requisition", response_model=BatchResult)
def batch_requisition(payload: BatchRequisitionPayload) -> BatchResult:
    """整组领用：逐条扣减瓶数余量，失败的条目写清试剂编号与原因，成功的不回滚。"""
    if not payload.领用日期.strip():
        raise HTTPException(status_code=400, detail="请填写统一的领用日期")
    if not payload.items:
        raise HTTPException(status_code=400, detail="请至少勾选一条试剂再提交领用")
    items = [line.model_dump() for line in payload.items]
    return BatchResult(**service.batch_requisition(payload.领用日期.strip(), items))


@router.post("/batch-disposal", response_model=BatchResult)
def batch_disposal(payload: BatchDisposalPayload) -> BatchResult:
    """整组报废：已开封、已废弃的逐条挑出来，只处理还能动的几条。"""
    if not payload.报废日期.strip():
        raise HTTPException(status_code=400, detail="请填写统一的报废日期")
    if not payload.ids:
        raise HTTPException(status_code=400, detail="请至少勾选一条试剂再提交报废")
    return BatchResult(**service.batch_disposal(payload.报废日期.strip(), payload.处置说明, payload.ids))


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条试剂明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"试剂 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条试剂，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="试剂已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条试剂执行开封登记、标记到期、废弃处置；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
