<template>
  <section class="page" data-module="reagent2">
    <header class="page-head">
      <div>
        <h2>试剂管理</h2>
        <p class="page-desc">维护试剂台账，支持整组领用、整组报废；瓶数余量随领用自动扣减，盘点清单与台账同一份数据。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记试剂</button>
        <button class="btn" type="button" @click="openInventory">盘点清单</button>
        <button class="btn" type="button" @click="exportRows">导出试剂管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div v-if="selectedRows.length" class="batch-bar">
      <span>已勾选 {{ selectedRows.length }} 条</span>
      <button class="btn primary" type="button" @click="openRequisition">批量领用</button>
      <button class="btn" type="button" @click="openDisposal">批量报废</button>
      <button class="btn ghost" type="button" @click="clearSelection">清除勾选</button>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th class="check-col">
            <input
              type="checkbox"
              :checked="allChecked"
              aria-label="全选本页"
              @change="toggleAll"
            />
          </th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td class="check-col">
            <input
              type="checkbox"
              :checked="selectedIds.includes(Number(row.id))"
              :aria-label="`勾选${row['试剂编号']}`"
              @change="toggleOne(Number(row.id))"
            />
          </td>
          <td v-for="column in columns" :key="column">
            <template v-if="column === '领用记录'">
              <button class="link" type="button" @click="openRecords(row)">
                {{ recordList(row).length }} 条，查看
              </button>
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无试剂管理数据，可先登记试剂</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条试剂管理记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 批量领用：统一领用日期，逐条填领用人与瓶数，失败条目留在列表里修好后重试 -->
    <div v-if="reqDialog.open" class="modal-mask" @click.self="reqDialog.open = false">
      <div class="modal">
        <h3>批量领用（{{ editableReqLines.length }} 条待提交）</h3>
        <p v-if="reqDialog.summary" class="modal-summary">{{ reqDialog.summary }}</p>
        <label class="filter-item modal-date">
          <span>领用日期（整组统一）</span>
          <input v-model="reqDialog.date" type="date" />
        </label>
        <table class="data-table modal-table">
          <thead>
            <tr>
              <th>试剂编号</th>
              <th>试剂名称</th>
              <th>规格等级</th>
              <th>瓶数余量</th>
              <th>领用人</th>
              <th>领用数量</th>
              <th>结果</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="line in reqDialog.lines" :key="line.id" :class="{ 'line-ok': line.state === 'ok' }">
              <td>{{ line.试剂编号 }}</td>
              <td>{{ line.试剂名称 }}</td>
              <td>{{ line.规格等级 }}</td>
              <td>{{ line.瓶数余量 }}</td>
              <td>
                <input v-if="line.state !== 'ok'" v-model="line.领用人" placeholder="领用人" />
                <span v-else>{{ line.领用人 }}</span>
              </td>
              <td>
                <input
                  v-if="line.state !== 'ok'"
                  v-model.number="line.领用数量"
                  type="number"
                  min="1"
                  :max="line.瓶数余量"
                  class="qty-input"
                />
                <span v-else>{{ line.领用数量 }}</span>
              </td>
              <td :class="line.state === 'fail' ? 'error-text' : 'ok-text'">{{ line.message || '—' }}</td>
            </tr>
          </tbody>
        </table>
        <div class="modal-actions">
          <button
            class="btn primary"
            type="button"
            :disabled="reqDialog.submitting || !editableReqLines.length"
            @click="submitRequisition"
          >
            {{ reqDialog.lines.some((line) => line.state === 'fail') ? '只重试失败条目' : '整组提交领用' }}
          </button>
          <button class="btn ghost" type="button" @click="reqDialog.open = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- 批量报废：已开封/已废弃的自动挑出，只处理还能动的几条 -->
    <div v-if="disDialog.open" class="modal-mask" @click.self="disDialog.open = false">
      <div class="modal">
        <h3>批量报废</h3>
        <p v-if="disDialog.summary" class="modal-summary">{{ disDialog.summary }}</p>
        <div class="modal-form-row">
          <label class="filter-item">
            <span>报废日期（整组统一）</span>
            <input v-model="disDialog.date" type="date" />
          </label>
          <label class="filter-item">
            <span>处置说明</span>
            <input v-model="disDialog.note" placeholder="选填，如：季度清理" />
          </label>
        </div>
        <template v-if="!disDialog.results.length">
          <h4>将处理 {{ disposableRows.length }} 条</h4>
          <ul class="modal-list">
            <li v-for="row in disposableRows" :key="row.id">
              {{ row['试剂编号'] }} · {{ row['试剂名称'] }} · {{ row['规格等级'] }}（{{ row.status }}）
            </li>
          </ul>
          <h4 v-if="excludedRows.length">已挑出 {{ excludedRows.length }} 条，不参与本次报废</h4>
          <ul class="modal-list excluded">
            <li v-for="item in excludedRows" :key="item.row.id">
              {{ item.row['试剂编号'] }} · {{ item.row['试剂名称'] }}（{{ item.row.status }}）—— {{ item.reason }}
            </li>
          </ul>
        </template>
        <table v-else class="data-table modal-table">
          <thead>
            <tr><th>试剂编号</th><th>结果</th></tr>
          </thead>
          <tbody>
            <tr v-for="result in disDialog.results" :key="result.id">
              <td>{{ result['试剂编号'] }}</td>
              <td :class="result.ok ? 'ok-text' : 'error-text'">{{ result.message }}</td>
            </tr>
          </tbody>
        </table>
        <div class="modal-actions">
          <button
            v-if="!disDialog.results.length"
            class="btn primary"
            type="button"
            :disabled="disDialog.submitting || !disposableRows.length"
            @click="submitDisposal"
          >
            提交报废（{{ disposableRows.length }} 条）
          </button>
          <button class="btn ghost" type="button" @click="disDialog.open = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- 单条试剂的领用记录：挂在试剂编号下面，规格等级不同的各记各的 -->
    <div v-if="recordDialog.open" class="modal-mask" @click.self="recordDialog.open = false">
      <div class="modal">
        <h3>领用记录 · {{ recordDialog.code }}（{{ recordDialog.spec }}）</h3>
        <table v-if="recordDialog.records.length" class="data-table modal-table">
          <thead>
            <tr>
              <th>批次号</th>
              <th>领用人</th>
              <th>领用日期</th>
              <th>领用数量</th>
              <th>领用后余量</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(record, index) in recordDialog.records" :key="index">
              <td>{{ record['批次号'] }}</td>
              <td>{{ record['领用人'] }}</td>
              <td>{{ record['领用日期'] }}</td>
              <td>{{ record['领用数量'] }}</td>
              <td>{{ record['领用后余量'] }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="modal-summary">该试剂暂无领用记录</p>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="recordDialog.open = false">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>
type ReqLine = {
  id: number
  试剂编号: string
  试剂名称: string
  规格等级: string
  瓶数余量: number
  领用人: string
  领用数量: number
  state: 'edit' | 'ok' | 'fail'
  message: string
}
type BatchLineResult = { id: number; 试剂编号: string; ok: boolean; message: string }
type BatchResult = {
  ok: boolean
  message: string
  批次号: string
  succeeded: number
  failed: number
  results: BatchLineResult[]
}

const ENDPOINT = '/api/reagent2'
const columns = ["试剂编号", "试剂名称", "规格等级", "存放方位", "有效期至", "瓶数余量", "领用记录", "试剂状态"]
const actions = ["开封登记", "标记到期", "废弃处置"]
const DISPOSABLE_STATUSES = ['充足', '将到期']

const stats = ref([
  { label: '试剂量充足', value: 0 },
  { label: '将到期试剂', value: 0 },
  { label: '已废弃试剂', value: 0 },
])

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const selectedIds = ref<number[]>([])

const reqDialog = ref({
  open: false,
  date: today(),
  lines: [] as ReqLine[],
  summary: '',
  submitting: false,
})
const disDialog = ref({
  open: false,
  date: today(),
  note: '',
  results: [] as BatchLineResult[],
  summary: '',
  submitting: false,
})
const recordDialog = ref({
  open: false,
  code: '',
  spec: '',
  records: [] as Row[],
})

const selectedRows = computed<Row[]>(() =>
  rows.value.filter((row) => selectedIds.value.includes(Number(row.id))),
)
const allChecked = computed(
  () => rows.value.length > 0 && rows.value.every((row) => selectedIds.value.includes(Number(row.id))),
)
const editableReqLines = computed(() => reqDialog.value.lines.filter((line) => line.state !== 'ok'))
const disposableRows = computed(() =>
  selectedRows.value.filter((row) => DISPOSABLE_STATUSES.includes(String(row.status))),
)
const excludedRows = computed(() =>
  selectedRows.value
    .filter((row) => !DISPOSABLE_STATUSES.includes(String(row.status)))
    .map((row) => ({
      row,
      reason: row.status === '已开封' ? '已开封试剂不参与批量报废，请单独处置' : '已废弃，无需重复报废',
    })),
)

function today(): string {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

function recordList(row: Row): Row[] {
  return Array.isArray(row['领用记录']) ? (row['领用记录'] as Row[]) : []
}

function toggleOne(id: number) {
  selectedIds.value = selectedIds.value.includes(id)
    ? selectedIds.value.filter((item) => item !== id)
    : [...selectedIds.value, id]
}

function toggleAll() {
  selectedIds.value = allChecked.value ? [] : rows.value.map((row) => Number(row.id))
}

function clearSelection() {
  selectedIds.value = []
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openInventory() {
  window.open(`${ENDPOINT}/inventory`, '_blank')
}

function openCreate() {
  errorMessage.value = '试剂登记入口尚未接入审批流'
}

function openRecords(row: Row) {
  recordDialog.value = {
    open: true,
    code: String(row['试剂编号'] ?? ''),
    spec: String(row['规格等级'] ?? ''),
    records: recordList(row),
  }
}

function openRequisition() {
  reqDialog.value = {
    open: true,
    date: today(),
    lines: selectedRows.value.map((row) => ({
      id: Number(row.id),
      试剂编号: String(row['试剂编号'] ?? ''),
      试剂名称: String(row['试剂名称'] ?? ''),
      规格等级: String(row['规格等级'] ?? ''),
      瓶数余量: Number(row['瓶数余量'] ?? 0),
      领用人: '',
      领用数量: 1,
      state: 'edit',
      message: '',
    })),
    summary: '',
    submitting: false,
  }
}

function openDisposal() {
  disDialog.value = { open: true, date: today(), note: '', results: [], summary: '', submitting: false }
}

async function readDetail(response: Response): Promise<string> {
  try {
    const payload = await response.json()
    return String(payload.detail ?? `接口返回 ${response.status}`)
  } catch {
    return `接口返回 ${response.status}`
  }
}

async function submitRequisition() {
  const dialog = reqDialog.value
  const pendingLines = dialog.lines.filter((line) => line.state !== 'ok')
  if (!pendingLines.length) return
  dialog.submitting = true
  dialog.summary = ''
  try {
    const response = await request(`${ENDPOINT}/batch-requisition`, {
      method: 'POST',
      body: JSON.stringify({
        领用日期: dialog.date,
        items: pendingLines.map((line) => ({ id: line.id, 领用人: line.领用人, 领用数量: line.领用数量 })),
      }),
    })
    if (!response.ok) {
      throw new Error(await readDetail(response))
    }
    const result = (await response.json()) as BatchResult
    dialog.summary = `${result.message}（批次号 ${result['批次号']}）`
    for (const item of result.results) {
      const line = dialog.lines.find((entry) => entry.id === item.id)
      if (!line) continue
      line.state = item.ok ? 'ok' : 'fail'
      line.message = item.message
    }
    await Promise.all([reload(), loadStats()])
  } catch (error) {
    dialog.summary = error instanceof Error ? error.message : '批量领用提交失败'
  } finally {
    dialog.submitting = false
  }
}

async function submitDisposal() {
  const dialog = disDialog.value
  dialog.submitting = true
  dialog.summary = ''
  try {
    const response = await request(`${ENDPOINT}/batch-disposal`, {
      method: 'POST',
      body: JSON.stringify({
        报废日期: dialog.date,
        处置说明: dialog.note,
        ids: selectedRows.value.map((row) => Number(row.id)),
      }),
    })
    if (!response.ok) {
      throw new Error(await readDetail(response))
    }
    const result = (await response.json()) as BatchResult
    dialog.summary = `${result.message}（批次号 ${result['批次号']}）`
    dialog.results = result.results
    clearSelection()
    await Promise.all([reload(), loadStats()])
  } catch (error) {
    dialog.summary = error instanceof Error ? error.message : '批量报废提交失败'
  } finally {
    dialog.submitting = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('试剂管理动作未生效，请稍后重试')
    }
    await Promise.all([reload(), loadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '试剂管理操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('试剂列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    selectedIds.value = selectedIds.value.filter((id) =>
      rows.value.some((row) => Number(row.id) === id),
    )
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '试剂管理列表读取失败'
  }
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/inventory`)
    if (!response.ok) return
    const payload = await response.json()
    const items: Row[] = payload.items ?? []
    const countBy = (status: string) => items.filter((item) => item.status === status).length
    stats.value = [
      { label: '试剂量充足', value: countBy('充足') },
      { label: '将到期试剂', value: countBy('将到期') },
      { label: '已废弃试剂', value: countBy('已废弃') },
    ]
  } catch {
    // 统计卡片失败不打断页面
  }
}

onMounted(() => {
  void reload()
  void loadStats()
})
</script>

<style scoped>
.check-col { width: 36px; text-align: center; }
.batch-bar { display: flex; gap: 10px; align-items: center; margin-bottom: 10px; padding: 8px 12px; background: #eef4ff; border: 1px solid #c7dbff; border-radius: 8px; font-size: 13px; }
.modal-mask { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); display: flex; align-items: flex-start; justify-content: center; padding: 48px 16px; z-index: 20; }
.modal { background: #fff; border-radius: 10px; padding: 18px 20px; width: min(860px, 96vw); max-height: 84vh; overflow: auto; }
.modal h3 { margin: 0 0 10px; }
.modal h4 { margin: 12px 0 6px; font-size: 13px; }
.modal-summary { font-size: 13px; color: var(--muted); }
.modal-date { display: block; margin-bottom: 10px; }
.modal-form-row { display: flex; gap: 14px; margin-bottom: 6px; }
.modal-table { margin-top: 8px; }
.modal-table input { width: 100%; }
.modal-table .qty-input { width: 72px; }
.modal-list { margin: 0; padding-left: 18px; font-size: 13px; }
.modal-list.excluded { color: var(--muted); }
.modal-actions { display: flex; gap: 10px; margin-top: 14px; }
.line-ok { background: #f0fdf4; }
.ok-text { color: #15803d; }
</style>
