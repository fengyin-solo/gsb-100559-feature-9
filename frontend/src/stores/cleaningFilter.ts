import { defineStore } from 'pinia'

/**
 * 组件清洗检索条件：按清洗区域、清洗方式、计划日期组合检索。
 * 条件落在 localStorage，切换菜单或重新进入页面仍停在原来的条件下。
 */
export type CleaningFilters = {
  area: string
  method: string
  dateFrom: string
  dateTo: string
}

const STORAGE_KEY = 'cleaning-filters'

const EMPTY: CleaningFilters = { area: '', method: '', dateFrom: '', dateTo: '' }

function load(): CleaningFilters {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...EMPTY }
    const parsed = JSON.parse(raw) as Partial<CleaningFilters>
    return { ...EMPTY, ...parsed }
  } catch {
    return { ...EMPTY }
  }
}

export const useCleaningFilterStore = defineStore('cleaning-filter', {
  state: () => ({
    filters: load() as CleaningFilters,
  }),
  actions: {
    update(patch: Partial<CleaningFilters>) {
      this.filters = { ...this.filters, ...patch }
      this.persist()
    },
    reset() {
      this.filters = { ...EMPTY }
      this.persist()
    },
    persist() {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(this.filters))
      } catch {
        // 隐私模式等场景写不进 localStorage 时不影响检索本身
      }
    },
  },
})
