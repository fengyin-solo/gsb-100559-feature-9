<template>
  <section class="page" data-module="cleaning">
    <header class="page-head">
      <div>
        <h2>组件清洗管理</h2>
        <p class="page-desc">按清洗区域、清洗方式、计划日期组合检索台账；用水汇总与列表同口径，完成后自动计入巡视待办。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记清洗任务</button>
        <button class="btn" type="button" @click="exportRows">导出当前清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="applyFilters">
      <label class="filter-item">
        <span>任务编号</span>
        <input v-model.trim="draft.keyword" placeholder="按任务编号检索" />
      </label>
      <label class="filter-item">
        <span>清洗区域</span>
        <select v-model="draft.area">
          <option value="">全部区域</option>
          <option v-for="area in options.areas" :key="area" :value="area">{{ area }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>清洗方式</span>
        <select v-model="draft.method">
          <option value="">全部方式</option>
          <option v-for="method in options.methods" :key="method" :value="method">{{ method }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>计划日期起</span>
        <input v-model="draft.plan_date_from" type="date" />
      </label>
      <label class="filter-item">
        <span>计划日期止</span>
        <input v-model="draft.plan_date_to" type="date" />
      </label>
      <label class="filter-item">
        <span>清洗状态</span>
        <select v-model="draft.status">
          <option value="">全部状态</option>
          <option v-for="status in options.statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn primary" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div class="summary-block">
      <h3 class="summary-title">用水汇总（与列表同一筛选条件）</h3>
      <table class="data-table">
        <thead>
          <tr><th>清洗区域</th><th>任务数</th><th>用水吨数</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in summary.areas" :key="item.清洗区域">
            <td>{{ item.清洗区域 }}</td>
            <td>{{ item.任务数 }}</td>
            <td>{{ item.用水吨数 }}</td>
          </tr>
          <tr v-if="!summary.areas.length">
            <td colspan="3" class="empty-state">当前条件下暂无用水数据</td>
          </tr>
          <tr v-else class="summary-total">
            <td>合计</td>
            <td>{{ summary.task_count }}</td>
            <td>{{ summary.total_tons }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ formatCell(row, column) }}</td>
          <td class="row-actions">
            <button
              v-for="action in actionsFor(row)"
              :key="action.name"
              class="link"
              type="button"
              @click="runAction(action.name, row)"
            >
              {{ action.label }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">{{ emptyText }}</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条组件清洗记录</span>
      <span v-if="infoMessage" class="info-text">{{ infoMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="creating" class="modal-mask" @click.self="closeCreate">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记清洗任务</h3>
        <label v-for="field in createFields" :key="field.key" class="form-item">
          <span>{{ field.label }}<i v-if="field.required">*</i></span>
          <input
            v-model.trim="createForm[field.key]"
            :type="field.type || 'text'"
            :placeholder="`请输入${field.label}`"
          />
        </label>
        <p v-if="createError" class="error-text">{{ createError }}</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="closeCreate">取消</button>
          <button class="btn primary" type="submit">提交登记</button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type Filters = {
  keyword: string
  area: string
  method: string
  plan_date_from: string
  plan_date_to: string
  status: string
}
type Summary = { total_tons: number; task_count: number; areas: { 清洗区域: string; 任务数: number; 用水吨数: number }[] }

const ENDPOINT = '/api/cleaning'
const FILTER_STORAGE_KEY = 'cleaning-filters'
const columns = ["任务编号", "清洗区域", "清洗方式", "计划日期", "作业人员", "用水吨数", "清洗后PR值", "清洗状态"]

const emptyFilters = (): Filters => ({
  keyword: '', area: '', method: '', plan_date_from: '', plan_date_to: '', status: '',
})

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const infoMessage = ref('')

// 草稿只跟随输入；点查询后才提交到 applied，并写入 URL + localStorage，重新进入页面仍停在原条件。
const draft = reactive<Filters>(emptyFilters())
const applied = ref<Filters>(emptyFilters())
const options = reactive<{ areas: string[]; methods: string[]; statuses: string[] }>({
  areas: [], methods: [], statuses: [],
})
const summary = ref<Summary>({ total_tons: 0, task_count: 0, areas: [] })

const stats = computed(() => [
  { label: '当前条件任务数', value: total.value },
  { label: '用水合计（吨）', value: summary.value.total_tons },
  { label: '涉及清洗区域', value: summary.value.areas.length },
  { label: '已完成任务', value: rows.value.filter((row) => row.清洗状态 === '已完成').length },
])

const hasFilters = computed(() => Object.values(applied.value).some(Boolean))
const emptyText = computed(() =>
  hasFilters.value
    ? '当前筛选条件下没有匹配的清洗任务，请调整区域、清洗方式或计划日期后重试'
    : '暂无组件清洗数据，可先登记清洗任务',
)

const creating = ref(false)
const createError = ref('')
type CreateField = { key: string; label: string; type?: string; required?: boolean }
const createFields: CreateField[] = [
  { key: '任务编号', label: '任务编号', required: true },
  { key: '清洗区域', label: '清洗区域', required: true },
  { key: '清洗方式', label: '清洗方式', required: true },
  { key: '计划日期', label: '计划日期', type: 'date', required: true },
  { key: '作业人员', label: '作业人员' },
  { key: '用水吨数', label: '用水吨数', type: 'number' },
  { key: '清洗后PR值', label: '清洗后PR值', type: 'number' },
]
const createForm = ref<Record<string, string>>({})

function readPersistedFilters(): Filters {
  // 优先 URL（方便分享/刷新），其次 localStorage（站内重新进入页面）。
  const fromUrl = new URLSearchParams(window.location.search)
  const merged = emptyFilters()
  const saved = localStorage.getItem(FILTER_STORAGE_KEY)
  if (saved) {
    try {
      Object.assign(merged, JSON.parse(saved) as Partial<Filters>)
    } catch {
      /* 本地缓存损坏时忽略，退回空条件 */
    }
  }
  for (const key of Object.keys(merged) as (keyof Filters)[]) {
    const urlValue = fromUrl.get(key)
    if (urlValue !== null) merged[key] = urlValue
  }
  return merged
}

function persistFilters(filters: Filters) {
  localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify(filters))
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value) query.set(key, value)
  }
  const qs = query.toString()
  window.history.replaceState(null, '', qs ? `${window.location.pathname}?${qs}` : window.location.pathname)
}

function toQuery(filters: Filters): string {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value) query.set(key, value)
  }
  return query.toString()
}

function applyFilters() {
  if (draft.plan_date_from && draft.plan_date_to && draft.plan_date_from > draft.plan_date_to) {
    errorMessage.value = '计划日期起始不能晚于截止'
    return
  }
  applied.value = { ...draft }
  persistFilters(applied.value)
  void reload()
}

function resetFilters() {
  Object.assign(draft, emptyFilters())
  applied.value = emptyFilters()
  persistFilters(applied.value)
  void reload()
}

function exportRows() {
  const qs = toQuery(applied.value)
  window.open(`${ENDPOINT}/export${qs ? `?${qs}` : ''}`, '_blank')
}

function formatCell(row: Row, column: string): string {
  const value = row[column]
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
}

// 状态沿 计划 → 执行中 → 已完成 推进；已完成再点执行（退回执行）退回执行中。
function actionsFor(row: Row) {
  switch (row.清洗状态) {
    case '计划':
      return [{ name: '开始作业', label: '开始作业' }]
    case '执行中':
      return [{ name: '验收完成', label: '验收完成' }]
    case '已完成':
      return [{ name: '退回执行', label: '退回执行' }]
    default:
      return []
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  infoMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.detail || payload?.message || '组件清洗动作未生效，请稍后重试')
    }
    infoMessage.value = payload.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '组件清洗操作失败'
  }
}

async function loadOptions() {
  try {
    const response = await request(`${ENDPOINT}/options`)
    if (!response.ok) return
    const payload = await response.json()
    options.areas = payload.areas ?? []
    options.methods = payload.methods ?? []
    options.statuses = payload.statuses ?? []
  } catch {
    /* 候选项加载失败不阻塞列表，输入框仍可使用 */
  }
}

// 列表与用水汇总共用同一查询串，杜绝两边口径不一致。
async function reload() {
  errorMessage.value = ''
  // 先清空旧结果：查不到时展示空态，绝不能拿上一次的结果顶替。
  rows.value = []
  total.value = 0
  summary.value = { total_tons: 0, task_count: 0, areas: [] }
  const qs = toQuery(applied.value)
  try {
    const [listResp, summaryResp] = await Promise.all([
      request(`${ENDPOINT}?${qs}`),
      request(`${ENDPOINT}/water-summary?${qs}`),
    ])
    if (!listResp.ok) throw new Error('清洗任务列表读取失败')
    if (!summaryResp.ok) throw new Error('用水汇总读取失败')
    const listPayload = await listResp.json()
    const summaryPayload = await summaryResp.json()
    rows.value = listPayload.items ?? []
    total.value = listPayload.total ?? rows.value.length
    summary.value = {
      total_tons: summaryPayload.total_tons ?? 0,
      task_count: summaryPayload.task_count ?? 0,
      areas: summaryPayload.areas ?? [],
    }
    // 汇总口径自检：任务数对不上时给出提示，而不是悄悄展示错数。
    if (summary.value.task_count !== total.value) {
      errorMessage.value = '用水汇总与列表任务数不一致，请刷新后重试'
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '组件清洗列表读取失败'
  }
}

function openCreate() {
  createForm.value = { 任务编号: '', 清洗区域: '', 清洗方式: '', 计划日期: '', 作业人员: '', 用水吨数: '', 清洗后PR值: '' }
  createError.value = ''
  creating.value = true
}

function closeCreate() {
  creating.value = false
}

async function submitCreate() {
  createError.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createForm.value }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      createError.value = payload?.detail || payload?.message || '清洗任务登记失败'
      return
    }
    infoMessage.value = payload.message
    creating.value = false
    await loadOptions()
    await reload()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '清洗任务登记失败'
  }
}

onMounted(async () => {
  const restored = readPersistedFilters()
  Object.assign(draft, restored)
  applied.value = { ...restored }
  persistFilters(applied.value)
  await loadOptions()
  await reload()
})
</script>
