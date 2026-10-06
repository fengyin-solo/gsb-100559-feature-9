<template>
  <section class="page" data-module="cleaning">
    <header class="page-head">
      <div>
        <h2>组件清洗管理</h2>
        <p class="page-desc">维护清洗任务，围绕任务编号、清洗区域、清洗方式、计划日期做登记、组合检索、用水汇总与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记清洗任务</button>
        <button class="btn" type="button" @click="exportRows">导出组件清洗清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>清洗区域</span>
        <select v-model="filters.area">
          <option value="">全部区域</option>
          <option v-for="area in options.areas" :key="area" :value="area">{{ area }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>清洗方式</span>
        <select v-model="filters.method">
          <option value="">全部方式</option>
          <option v-for="method in options.methods" :key="method" :value="method">{{ method }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>计划日期 起</span>
        <input v-model="filters.dateFrom" type="date" />
      </label>
      <label class="filter-item">
        <span>计划日期 止</span>
        <input v-model="filters.dateTo" type="date" />
      </label>
      <button class="btn primary" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <!-- 用水汇总：与列表同一筛选口径，按清洗区域合并 -->
    <section class="water-panel">
      <h3 class="water-title">用水汇总（与当前检索结果同口径）</h3>
      <div class="water-body">
        <p class="water-total">
          命中任务 <strong>{{ summary.total_tasks }}</strong> 条，合计用水
          <strong>{{ summary.total_water }}</strong> 吨
          <span class="water-hint">（计划 {{ summary.status_counts['计划'] }} / 执行中 {{ summary.status_counts['执行中'] }} / 已完成 {{ summary.status_counts['已完成'] }}）</span>
        </p>
        <table class="data-table">
          <thead>
            <tr><th>清洗区域</th><th>任务数</th><th>用水吨数</th></tr>
          </thead>
          <tbody>
            <tr v-for="area in summary.areas" :key="area['清洗区域']">
              <td>{{ area['清洗区域'] }}</td>
              <td>{{ area['任务数'] }}</td>
              <td>{{ area['用水吨数'] }}</td>
            </tr>
            <tr v-if="!summary.areas.length">
              <td colspan="3" class="empty-state">当前条件下没有用水记录</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-if="actionOf(row.status)"
              class="link"
              type="button"
              @click="runAction(actionOf(row.status)!, row)"
            >
              {{ actionLabelOf(row.status) }}
            </button>
            <span v-else class="action-done">已完成</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">{{ emptyHint }}</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条组件清洗记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 登记清洗任务 -->
    <div v-if="createOpen" class="modal-mask" @click.self="closeCreate">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记清洗任务</h3>
        <label class="modal-item"><span>任务编号 *</span><input v-model="form.taskNo" placeholder="如 CLEA-0010" /></label>
        <label class="modal-item"><span>清洗区域 *</span><input v-model="form.area" list="cleaning-areas" placeholder="如 北区阵列" /></label>
        <label class="modal-item"><span>清洗方式 *</span>
          <select v-model="form.method">
            <option value="">请选择</option>
            <option v-for="method in options.methods" :key="method" :value="method">{{ method }}</option>
          </select>
        </label>
        <label class="modal-item"><span>计划日期</span><input v-model="form.planDate" type="date" /></label>
        <label class="modal-item"><span>作业人员</span><input v-model="form.workers" /></label>
        <label class="modal-item"><span>用水吨数</span><input v-model.number="form.waterTons" type="number" min="0" step="0.1" /></label>
        <datalist id="cleaning-areas">
          <option v-for="area in options.areas" :key="area" :value="area" />
        </datalist>
        <p v-if="createMessage" class="error-text">{{ createMessage }}</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="closeCreate">取消</button>
          <button class="btn primary" type="submit">提交</button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { storeToRefs } from 'pinia'

import { request } from '@/api/client'
import { useCleaningFilterStore } from '@/stores/cleaningFilter'

type Row = Record<string, string | number | null>
type Summary = {
  total_tasks: number
  total_water: number
  areas: { 清洗区域: string; 用水吨数: number; 任务数: number }[]
  status_counts: Record<string, number>
}

const ENDPOINT = '/api/cleaning'
const columns = ["任务编号", "清洗区域", "清洗方式", "计划日期", "作业人员", "用水吨数", "清洗后PR值", "清洗状态"]

const filterStore = useCleaningFilterStore()
const { filters } = storeToRefs(filterStore)

const rows = ref<Row[]>([])
const total = ref(0)
const loading = ref(false)
const errorMessage = ref('')
const options = ref<{ areas: string[]; methods: string[] }>({ areas: [], methods: [] })
const summary = ref<Summary>({ total_tasks: 0, total_water: 0, areas: [], status_counts: { 计划: 0, 执行中: 0, 已完成: 0 } })

const stats = computed(() => [
  { label: '命中任务数', value: summary.value.total_tasks },
  { label: '合计用水（吨）', value: summary.value.total_water },
  { label: '覆盖清洗区域', value: summary.value.areas.length },
  { label: '待处理任务', value: summary.value.status_counts['计划'] + summary.value.status_counts['执行中'] },
])

const hasFilter = computed(() =>
  Boolean(filters.value.area || filters.value.method || filters.value.dateFrom || filters.value.dateTo),
)
const emptyHint = computed(() =>
  hasFilter.value
    ? '当前检索条件下没有清洗任务，可调整条件后重试'
    : '暂无组件清洗数据，可先登记清洗任务',
)

// 状态沿 计划 → 执行中 → 已完成 依次推进；已完成再点执行退回执行中。
function actionOf(status: string | number | null): string | null {
  if (status === '计划') return '开始执行'
  if (status === '执行中') return '验收完成'
  if (status === '已完成') return '执行'
  return null
}
function actionLabelOf(status: string | number | null): string {
  if (status === '计划') return '开始执行'
  if (status === '执行中') return '验收完成'
  if (status === '已完成') return '退回执行'
  return ''
}

function resetFilters() {
  filterStore.reset()
  void reload()
}

function queryString(): string {
  const params: Record<string, string> = {}
  if (filters.value.area) params.area = filters.value.area
  if (filters.value.method) params.method = filters.value.method
  if (filters.value.dateFrom) params.date_from = filters.value.dateFrom
  if (filters.value.dateTo) params.date_to = filters.value.dateTo
  return new URLSearchParams(params).toString()
}

async function loadOptions() {
  try {
    const response = await request(`${ENDPOINT}/options`)
    if (response.ok) options.value = await response.json()
  } catch {
    // 选项拉取失败不阻塞列表
  }
}

async function reload() {
  // 条件变化即持久化，重新进入页面仍停在原条件。
  filterStore.persist()
  errorMessage.value = ''
  const query = queryString()
  loading.value = true
  try {
    const [listRes, summaryRes] = await Promise.all([
      request(`${ENDPOINT}?${query}`),
      request(`${ENDPOINT}/water-summary?${query}`),
    ])
    if (!listRes.ok) throw new Error('清洗任务列表读取失败')
    if (!summaryRes.ok) throw new Error('清洗用水汇总读取失败')
    const payload = await listRes.json()
    // 查不到就是空列表，绝不用上一次结果顶替。
    rows.value = payload.items ?? []
    total.value = payload.total ?? 0
    summary.value = await summaryRes.json()
  } catch (error) {
    rows.value = []
    total.value = 0
    errorMessage.value = error instanceof Error ? error.message : '组件清洗列表读取失败'
  } finally {
    loading.value = false
  }
}

function exportRows() {
  window.open(`${ENDPOINT}/export?${queryString()}`, '_blank')
}

// ---- 登记 ----
const createOpen = ref(false)
const createMessage = ref('')
const form = reactive({ taskNo: '', area: '', method: '', planDate: '', workers: '', waterTons: 0 })

function openCreate() {
  Object.assign(form, { taskNo: '', area: '', method: '', planDate: '', workers: '', waterTons: 0 })
  createMessage.value = ''
  createOpen.value = true
}
function closeCreate() {
  createOpen.value = false
}

async function submitCreate() {
  createMessage.value = ''
  const body: Record<string, unknown> = {
    任务编号: form.taskNo.trim(),
    清洗区域: form.area.trim(),
    清洗方式: form.method,
    计划日期: form.planDate,
    作业人员: form.workers.trim(),
    用水吨数: form.waterTons || 0,
  }
  try {
    const response = await request(ENDPOINT, { method: 'POST', body: JSON.stringify({ values: body }) })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      createMessage.value = payload?.detail?.[0]?.msg || payload?.message || '清洗任务登记失败'
      return
    }
    createOpen.value = false
    await Promise.all([loadOptions(), reload()])
  } catch (error) {
    createMessage.value = error instanceof Error ? error.message : '清洗任务登记失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || '组件清洗动作未生效，请稍后重试')
    }
    errorMessage.value = payload.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '组件清洗操作失败'
  }
}

onMounted(async () => {
  await loadOptions()
  await reload()
})
</script>

<style scoped>
.filter-item select,
.filter-item input,
.modal-item input,
.modal-item select {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 13px;
  min-width: 140px;
}
.water-panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
}
.water-title { margin: 0 0 8px; font-size: 14px; }
.water-total { margin: 0 0 8px; font-size: 13px; }
.water-total strong { color: var(--brand); font-size: 16px; }
.water-hint { color: var(--muted); font-size: 12px; margin-left: 6px; }
.action-done { color: var(--muted); font-size: 12px; }
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
  width: 380px;
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.modal h3 { margin: 0; }
.modal-item { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--muted); }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 4px; }
</style>
