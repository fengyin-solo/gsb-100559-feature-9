<template>
  <section class="page" data-module="patrol">
    <header class="page-head">
      <div>
        <h2>巡视检查管理</h2>
        <p class="page-desc">清洗验收完成的任务会自动生成巡视待办；可按来源筛选人工登记与清洗联动记录。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记巡视记录</button>
        <button class="btn" type="button" @click="exportRows">导出巡视检查清单</button>
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
        <span>记录编号</span>
        <input v-model.trim="draft.keyword" placeholder="按记录编号检索" />
      </label>
      <label class="filter-item">
        <span>巡视状态</span>
        <select v-model="draft.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>待办来源</span>
        <select v-model="draft.source">
          <option value="">全部来源</option>
          <option value="cleaning">清洗验收待办</option>
          <option value="manual">人工登记</option>
        </select>
      </label>
      <button class="btn primary" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

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
          <td :colspan="columns.length + 1" class="empty-state">{{ emptyText }}</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条巡视记录</span>
      <span v-if="infoMessage" class="info-text">{{ infoMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type Filters = { keyword: string; status: string; source: string }

const ENDPOINT = '/api/patrol'
const columns = ["记录编号", "巡视区域", "巡视日期", "巡视人员", "发现缺陷数", "红外测温结果", "接线端子温度", "来源", "巡视状态"]
const actions = ["开始巡视", "提交记录", "归档记录"]
const statuses = ["待巡视", "巡视中", "已记录", "已归档"]

const emptyFilters = (): Filters => ({ keyword: '', status: '', source: '' })
const draft = reactive<Filters>(emptyFilters())
const applied = ref<Filters>(emptyFilters())

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const infoMessage = ref('')

const stats = computed(() => [
  { label: '当前记录数', value: total.value },
  { label: '待巡视', value: rows.value.filter((row) => row.巡视状态 === '待巡视').length },
  { label: '清洗验收待办', value: rows.value.filter((row) => Boolean(row.source_task) && row.巡视状态 === '待巡视').length },
])

const hasFilters = computed(() => Object.values(applied.value).some(Boolean))
const emptyText = computed(() =>
  hasFilters.value ? '当前筛选条件下没有匹配的巡视记录' : '暂无巡视记录，清洗验收完成后会自动生成待办',
)

function toQuery(filters: Filters): string {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value) query.set(key, value)
  }
  return query.toString()
}

function applyFilters() {
  applied.value = { ...draft }
  void reload()
}

function resetFilters() {
  Object.assign(draft, emptyFilters())
  applied.value = emptyFilters()
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '巡视记录登记入口尚未接入审批流'
}

function formatCell(row: Row, column: string): string {
  const value = row[column]
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
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
      throw new Error(payload?.detail || payload?.message || '巡视检查动作未生效，请稍后重试')
    }
    infoMessage.value = payload.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡视检查操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  rows.value = []
  total.value = 0
  try {
    const response = await request(`${ENDPOINT}?${toQuery(applied.value)}`)
    if (!response.ok) {
      throw new Error('巡视记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡视检查列表读取失败'
  }
}

onMounted(reload)
</script>
