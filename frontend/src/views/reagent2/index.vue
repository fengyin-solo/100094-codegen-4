<template>
  <section class="page" data-module="reagent2">
    <header class="page-head">
      <div>
        <h2>试剂管理</h2>
        <p class="page-desc">维护试剂台账，支持勾选多条试剂整组领用、整组报废；瓶数余量随领用自动扣减，领用记录挂在试剂编号下。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记试剂</button>
        <button class="btn" type="button" :disabled="!selectedRows.length" @click="openCheckout">
          批量领用{{ selectedRows.length ? `（${selectedRows.length}）` : '' }}
        </button>
        <button class="btn" type="button" :disabled="!selectedRows.length" @click="openDispose">
          批量报废{{ selectedRows.length ? `（${selectedRows.length}）` : '' }}
        </button>
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

    <table class="data-table">
      <thead>
        <tr>
          <th class="check-col">
            <input type="checkbox" :checked="allChecked" aria-label="全选" @change="toggleAll" />
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
              :checked="selectedIds.includes(row.id)"
              :aria-label="`选择 ${row.试剂编号}`"
              @change="toggleRow(row.id)"
            />
          </td>
          <td v-for="column in columns" :key="column">
            <template v-if="column === '领用记录'">
              <button v-if="recordsOf(row).length" class="link" type="button" @click="openRecords(row)">
                {{ recordsOf(row).length }} 条
              </button>
              <span v-else>—</span>
            </template>
            <template v-else>{{ cellText(row, column) }}</template>
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
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="checkoutOpen" class="modal-mask">
      <div class="modal">
        <h3>批量领用（待提交 {{ checkoutLines.length }} 条）</h3>
        <label class="checkout-date">
          <span>领用日期（整组统一）</span>
          <input v-model="checkoutDate" type="date" />
        </label>
        <table class="data-table">
          <thead>
            <tr>
              <th>试剂编号</th>
              <th>试剂名称</th>
              <th>规格等级</th>
              <th>瓶数余量</th>
              <th>领用人</th>
              <th>领用数量</th>
              <th>逐条反馈</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="line in checkoutLines" :key="line.id">
              <td>{{ line.试剂编号 }}</td>
              <td>{{ line.试剂名称 }}</td>
              <td>{{ line.规格等级 }}</td>
              <td>{{ line.瓶数余量 }}</td>
              <td>
                <input v-model.trim="line.领用人" class="line-input" placeholder="逐条填写领用人" @input="line.error = ''" />
              </td>
              <td>
                <input
                  v-model.number="line.数量"
                  class="line-input qty-input"
                  type="number"
                  min="1"
                  :max="line.瓶数余量"
                  @input="line.error = ''"
                />
              </td>
              <td class="error-text">{{ line.error }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="checkoutSummary" class="modal-desc">{{ checkoutSummary }}</p>
        <footer class="modal-foot">
          <button class="btn primary" type="button" :disabled="submitting" @click="submitCheckout">
            {{ checkoutLines.some((line) => line.error) ? '仅重试失败条目' : '提交整组领用' }}
          </button>
          <button class="btn ghost" type="button" @click="closeCheckout">关闭</button>
        </footer>
      </div>
    </div>

    <div v-if="disposeOpen" class="modal-mask">
      <div class="modal">
        <h3>批量报废确认</h3>
        <template v-if="disposeTargets.length">
          <p class="modal-desc">以下 {{ disposeTargets.length }} 条将执行报废，瓶数余量归零并记入报废记录：</p>
          <ul class="result-list">
            <li v-for="row in disposeTargets" :key="row.id">
              {{ row.试剂编号 }} · {{ row.试剂名称 }}（{{ row.规格等级 }}，余 {{ row.瓶数余量 }} 瓶）
            </li>
          </ul>
        </template>
        <template v-if="disposeSkipped.length">
          <p class="modal-desc skip-desc">以下 {{ disposeSkipped.length }} 条已开封或已废弃，已单独挑出、本次不处理：</p>
          <ul class="result-list">
            <li v-for="row in disposeSkipped" :key="row.id">
              {{ row.试剂编号 }} · {{ row.试剂名称 }}（{{ row.status }}）
            </li>
          </ul>
        </template>
        <p v-if="!disposeTargets.length" class="modal-desc">所选试剂均已开封或已废弃，没有可报废的条目。</p>
        <p v-if="disposeSummary" class="modal-desc">{{ disposeSummary }}</p>
        <ul v-if="disposeFailures.length" class="result-list">
          <li v-for="item in disposeFailures" :key="String(item.id)" class="error-text">
            {{ item.试剂编号 ?? `#${item.id}` }}：{{ item.message }}
          </li>
        </ul>
        <footer class="modal-foot">
          <button
            v-if="!disposeSummary"
            class="btn primary"
            type="button"
            :disabled="!disposeTargets.length || submitting"
            @click="submitDispose"
          >
            确认报废
          </button>
          <button class="btn ghost" type="button" @click="closeDispose">{{ disposeSummary ? '关闭' : '取消' }}</button>
        </footer>
      </div>
    </div>

    <div v-if="recordsRow" class="modal-mask">
      <div class="modal">
        <h3>{{ recordsRow.试剂编号 }} · {{ recordsRow.试剂名称 }}（{{ recordsRow.规格等级 }}）领用记录</h3>
        <table class="data-table">
          <thead>
            <tr>
              <th>领用人</th>
              <th>领用日期</th>
              <th>领用数量</th>
              <th>剩余瓶数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(record, index) in recordsOf(recordsRow)" :key="index">
              <td>{{ record.领用人 }}</td>
              <td>{{ record.领用日期 }}</td>
              <td>{{ record.领用数量 }}</td>
              <td>{{ record.剩余瓶数 }}</td>
            </tr>
          </tbody>
        </table>
        <p class="modal-desc">当前瓶数余量 {{ recordsRow.瓶数余量 }} 瓶，与盘点页、试剂台账同源，不会出现对不上。</p>
        <footer class="modal-foot">
          <button class="btn ghost" type="button" @click="recordsRow = null">关闭</button>
        </footer>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type CheckoutRecord = {
  试剂编号?: string
  规格等级?: string
  领用人: string
  领用日期: string
  领用数量: number
  剩余瓶数: number
}

type Row = {
  id: number
  status: string
  试剂编号: string
  试剂名称: string
  规格等级: string
  瓶数余量: number
  领用记录?: CheckoutRecord[]
  [key: string]: unknown
}

type CheckoutLine = {
  id: number
  试剂编号: string
  试剂名称: string
  规格等级: string
  瓶数余量: number
  领用人: string
  数量: number
  error: string
}

type BatchItemResult = {
  id: number | null
  试剂编号: string | null
  ok: boolean
  message: string
}

type BatchResult = {
  ok: boolean
  message: string
  succeeded: number
  failed: number
  results: BatchItemResult[]
}

const ENDPOINT = '/api/reagent2'
const columns = ["试剂编号", "试剂名称", "规格等级", "存放方位", "有效期至", "瓶数余量", "领用记录", "试剂状态"]
const actions = ["开封登记", "标记到期", "废弃处置"]
const DISPOSE_SKIP_STATUSES = ['已开封', '已废弃']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const stats = computed(() => [
  { label: '试剂量充足', value: rows.value.filter((row) => row.status === '充足').length },
  { label: '将到期试剂', value: rows.value.filter((row) => row.status === '将到期').length },
  { label: '已废弃试剂', value: rows.value.filter((row) => row.status === '已废弃').length },
])

const selectedIds = ref<number[]>([])
const selectedRows = computed(() => rows.value.filter((row) => selectedIds.value.includes(row.id)))
const allChecked = computed(() => rows.value.length > 0 && rows.value.every((row) => selectedIds.value.includes(row.id)))

const submitting = ref(false)
const checkoutOpen = ref(false)
const checkoutDate = ref('')
const checkoutLines = ref<CheckoutLine[]>([])
const checkoutSummary = ref('')
const disposeOpen = ref(false)
const disposeSummary = ref('')
const disposeFailures = ref<BatchItemResult[]>([])
const recordsRow = ref<Row | null>(null)

const disposeTargets = computed(() => selectedRows.value.filter((row) => !DISPOSE_SKIP_STATUSES.includes(row.status)))
const disposeSkipped = computed(() => selectedRows.value.filter((row) => DISPOSE_SKIP_STATUSES.includes(row.status)))

function recordsOf(row: Row): CheckoutRecord[] {
  return Array.isArray(row.领用记录) ? row.领用记录 : []
}

function cellText(row: Row, column: string): string | number {
  if (column === '试剂状态') {
    return row.status
  }
  const value = row[column]
  if (value === null || value === undefined || value === '') {
    return '—'
  }
  return typeof value === 'object' ? '—' : (value as string | number)
}

function toggleRow(id: number) {
  selectedIds.value = selectedIds.value.includes(id)
    ? selectedIds.value.filter((item) => item !== id)
    : [...selectedIds.value, id]
}

function toggleAll() {
  selectedIds.value = allChecked.value ? [] : rows.value.map((row) => row.id)
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '试剂登记入口尚未接入审批流'
}

function openRecords(row: Row) {
  recordsRow.value = row
}

function openCheckout() {
  checkoutLines.value = selectedRows.value.map((row) => ({
    id: row.id,
    试剂编号: row.试剂编号,
    试剂名称: row.试剂名称,
    规格等级: row.规格等级,
    瓶数余量: row.瓶数余量,
    领用人: '',
    数量: 1,
    error: '',
  }))
  checkoutDate.value = new Date().toISOString().slice(0, 10)
  checkoutSummary.value = ''
  checkoutOpen.value = true
}

function closeCheckout() {
  checkoutOpen.value = false
  checkoutLines.value = []
  checkoutSummary.value = ''
}

async function submitCheckout() {
  if (submitting.value) {
    return
  }
  checkoutSummary.value = ''
  submitting.value = true
  try {
    const response = await request(`${ENDPOINT}/batch-checkout`, {
      method: 'POST',
      body: JSON.stringify({
        领用日期: checkoutDate.value,
        items: checkoutLines.value.map((line) => ({
          id: line.id,
          试剂编号: line.试剂编号,
          规格等级: line.规格等级,
          领用人: line.领用人,
          数量: line.数量,
        })),
      }),
    })
    const payload = (await response.json()) as BatchResult & { detail?: string }
    if (!response.ok) {
      throw new Error(payload.detail ?? '批量领用提交失败，请检查领用日期与勾选条目')
    }
    const failedById = new Map(payload.results.filter((item) => !item.ok).map((item) => [item.id, item.message]))
    const succeededIds = payload.results.filter((item) => item.ok).map((item) => item.id)
    checkoutLines.value = checkoutLines.value
      .filter((line) => failedById.has(line.id))
      .map((line) => ({ ...line, error: failedById.get(line.id) ?? '' }))
    selectedIds.value = selectedIds.value.filter((id) => !succeededIds.includes(id))
    checkoutSummary.value = payload.message
    await reload()
    if (!checkoutLines.value.length) {
      closeCheckout()
      noticeMessage.value = payload.message
    }
  } catch (error) {
    checkoutSummary.value = error instanceof Error ? error.message : '批量领用提交失败'
  } finally {
    submitting.value = false
  }
}

function openDispose() {
  disposeSummary.value = ''
  disposeFailures.value = []
  disposeOpen.value = true
}

function closeDispose() {
  disposeOpen.value = false
  disposeSummary.value = ''
  disposeFailures.value = []
}

async function submitDispose() {
  if (submitting.value) {
    return
  }
  submitting.value = true
  try {
    const response = await request(`${ENDPOINT}/batch-dispose`, {
      method: 'POST',
      body: JSON.stringify({ ids: selectedIds.value }),
    })
    const payload = (await response.json()) as BatchResult & { detail?: string }
    if (!response.ok) {
      throw new Error(payload.detail ?? '批量报废提交失败')
    }
    disposeSummary.value = payload.message
    disposeFailures.value = payload.results.filter((item) => !item.ok)
    const succeededIds = payload.results.filter((item) => item.ok).map((item) => item.id)
    selectedIds.value = selectedIds.value.filter((id) => !succeededIds.includes(id))
    await reload()
  } catch (error) {
    disposeSummary.value = error instanceof Error ? error.message : '批量报废提交失败'
  } finally {
    submitting.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('试剂管理动作未生效，请稍后重试')
    }
    await reload()
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
    selectedIds.value = selectedIds.value.filter((id) => rows.value.some((row) => row.id === id))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '试剂管理列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.check-col {
  width: 36px;
  text-align: center;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal {
  background: #fff;
  border-radius: 10px;
  padding: 16px 20px;
  width: min(880px, 92vw);
  max-height: 84vh;
  overflow: auto;
}
.modal h3 {
  margin: 0 0 12px;
  font-size: 15px;
}
.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
}
.modal-desc {
  font-size: 13px;
  color: var(--muted);
}
.skip-desc {
  color: #b42318;
}
.checkout-date {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  font-size: 13px;
}
.line-input {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 4px 6px;
}
.qty-input {
  width: 72px;
}
.result-list {
  margin: 8px 0;
  padding-left: 18px;
  font-size: 13px;
}
.notice-text {
  color: #067647;
}
</style>
