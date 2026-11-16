<template>
  <section class="page" data-module="compare">
    <header class="page-head">
      <div>
        <h2>同期对比分析管理</h2>
        <p class="page-desc">维护同期对比的周期选择、变化分析与原因归因，为同期对比分析提供可验证的数据工程流程。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记对比方案</button>
        <button class="btn" type="button" @click="exportRows">导出同期对比分析清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <!-- 预测结果核对：跨模块读取预测结果数据集 -->
    <section class="block">
      <h3>预测结果核对（读取经营预测模型的预测结果数据集）</h3>
      <p class="block-desc">
        按实际发生日期关联最终实际值；实际尚未到达的点标为待观测，不按零误差处理。
        每个预测点保留训练截止、输入可用时间、所用算法与误差分母。
      </p>
      <form class="filter-bar" @submit.prevent="loadCheck">
        <label class="filter-item">
          <span>预测版本</span>
          <select v-model="checkRunId">
            <option v-for="run in forecastRuns" :key="run.id" :value="run.id">
              {{ run.版本号 }} · {{ run.序列编号 }} · {{ fmtTime(run.创建时间) }}
            </option>
          </select>
        </label>
        <button class="btn primary" type="submit">加载核对视图</button>
      </form>
      <p v-if="!forecastRuns.length" class="block-desc">暂无预测版本，请先在经营预测模型模块运行滚动回测。</p>

      <template v-if="checkResult">
        <div class="stat-row">
          <article class="stat-card">
            <span class="stat-label">预测点数</span>
            <strong class="stat-value">{{ checkResult.摘要.预测点数 }}</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">已核对</span>
            <strong class="stat-value">{{ checkResult.摘要.已核对数 }}</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">待观测</span>
            <strong class="stat-value">{{ checkResult.摘要.待观测数 }}</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">迟到更正</span>
            <strong class="stat-value">{{ checkResult.摘要.迟到更正数 }} 期</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">最长连续缺期</span>
            <strong class="stat-value">{{ checkResult.摘要.连续缺期 }} 期</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">全零序列 / 短序列</span>
            <strong class="stat-value">
              {{ checkResult.摘要.全零序列 ? '全零' : '非全零' }} / {{ checkResult.摘要.短序列 ? '短序列' : '正常' }}
            </strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">未来样本检查</span>
            <strong class="stat-value" :class="checkResult.摘要.未来样本检查.通过 ? '' : 'warn-text'">
              {{ checkResult.摘要.未来样本检查.通过 ? '通过' : '未通过' }}
            </strong>
          </article>
        </div>

        <table class="data-table">
          <thead>
            <tr>
              <th>预测起点</th><th>训练截止</th><th>输入可用时间</th><th>目标期（实际发生日期）</th>
              <th>算法</th><th>预测值</th><th>预测区间</th><th>实际值</th><th>实际可用时间</th>
              <th>误差</th><th>相对误差</th><th>误差分母</th><th>核对状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(item, idx) in checkResult.items" :key="idx">
              <td>{{ item.预测起点 }}</td>
              <td>{{ item.训练截止期 }}</td>
              <td>{{ fmtTime(item.输入可用时间) }}</td>
              <td>{{ item.目标期 }}</td>
              <td>{{ item.算法名称 }}</td>
              <td>{{ fmtNum(item.预测值) }}</td>
              <td>{{ fmtInterval(item) }}</td>
              <td>{{ item.核对状态 === '待观测' ? '待观测' : fmtNum(item.实际值) }}</td>
              <td>{{ fmtTime(item.实际可用时间) }}</td>
              <td>{{ item.核对状态 === '待观测' ? '—' : fmtNum(item.误差) }}</td>
              <td>{{ item.核对状态 === '待观测' ? '—' : fmtPct(item.相对误差) }}</td>
              <td>{{ item.核对状态 === '待观测' ? '—' : fmtNum(item.误差分母) }}</td>
              <td>
                <span :class="item.核对状态 === '待观测' ? 'warn-text' : ''">{{ item.核对状态 }}</span>
                <span v-if="item.剔除原因" class="block-desc">{{ item.剔除原因 }}</span>
              </td>
            </tr>
            <tr v-if="!checkResult.items.length">
              <td colspan="13" class="empty-state">该版本没有预测点（可能全部折因训练样本不足被剔除）</td>
            </tr>
          </tbody>
        </table>

        <template v-if="checkResult.摘要.迟到更正.length">
          <h4>迟到更正明细</h4>
          <table class="data-table">
            <thead>
              <tr><th>观测期</th><th>版本数</th><th>首次可用时间</th><th>末次可用时间</th></tr>
            </thead>
            <tbody>
              <tr v-for="item in checkResult.摘要.迟到更正" :key="item.观测期">
                <td>{{ item.观测期 }}</td>
                <td>{{ item.版本数 }}</td>
                <td>{{ fmtTime(item.首次可用时间) }}</td>
                <td>{{ fmtTime(item.末次可用时间) }}</td>
              </tr>
            </tbody>
          </table>
        </template>

        <details class="snapshot">
          <summary>
            未来样本检查明细（{{ checkResult.摘要.未来样本检查.检查项数 }} 项，
            未通过 {{ checkResult.摘要.未来样本检查.未通过数 }} 项）
          </summary>
          <table class="data-table">
            <thead>
              <tr><th>对象</th><th>检查内容</th><th>是否通过</th></tr>
            </thead>
            <tbody>
              <tr v-for="(check, idx) in checkResult.摘要.未来样本检查.检查项" :key="idx">
                <td>{{ check.对象 }}</td>
                <td>{{ check.检查 }}</td>
                <td>{{ check.通过 ? '通过' : '未通过' }}</td>
              </tr>
            </tbody>
          </table>
        </details>
      </template>
    </section>

    <!-- 对比方案清单（原有功能） -->
    <section class="block">
      <h3>对比方案清单</h3>
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
            <th v-for="column in columns" :key="column">{{ column }}</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="String(row.id)">
            <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
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
            <td :colspan="columns.length + 1" class="empty-state">暂无同期对比分析数据，可先登记对比方案</td>
          </tr>
        </tbody>
      </table>

      <footer class="page-foot">
        <span>共 {{ total }} 条同期对比分析记录</span>
        <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      </footer>
    </section>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>

const ENDPOINT = '/api/compare'
const columns = ["方案编号", "对比指标", "基准周期", "对比周期", "变化幅度", "变化方向", "原因分析", "方案状态"]
const actions = ["执行对比", "原因分析", "归档方案"]
const statuses = ["草稿", "已对比", "已分析", "已归档"]
const stats = [{"label": "对比方案总数", "value": 0}, {"label": "已对比方案", "value": 0}, {"label": "已分析方案", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

// 预测结果核对（跨模块读取预测结果数据集）
const forecastRuns = ref<Row[]>([])
const checkRunId = ref<number | null>(null)
const checkResult = ref<Row | null>(null)

function fmtNum(value: unknown, digits = 2): string {
  if (value === null || value === undefined || value === '') return '—'
  return Number(value).toFixed(digits)
}

function fmtPct(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  return `${(Number(value) * 100).toFixed(1)}%`
}

function fmtTime(value: unknown): string {
  if (!value) return '—'
  return String(value).replace('T', ' ')
}

function fmtInterval(item: Row): string {
  if (item.区间下限 === null || item.区间下限 === undefined) return '不提供'
  return `[${fmtNum(item.区间下限)}, ${fmtNum(item.区间上限)}]`
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '对比方案登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('同期对比分析动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '同期对比分析操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('对比方案列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '同期对比分析列表读取失败'
  }
}

async function loadForecastRuns() {
  try {
    const response = await request(`${ENDPOINT}/forecast-runs`)
    if (!response.ok) throw new Error('预测版本清单读取失败')
    const payload = await response.json()
    forecastRuns.value = payload.items ?? []
    if (forecastRuns.value.length && checkRunId.value === null) {
      checkRunId.value = forecastRuns.value[0].id
      await loadCheck()
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '预测版本清单读取失败'
  }
}

async function loadCheck() {
  errorMessage.value = ''
  if (checkRunId.value === null) return
  try {
    const response = await request(`${ENDPOINT}/forecast-check/${checkRunId.value}`)
    if (!response.ok) throw new Error('预测核对视图读取失败')
    checkResult.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '预测核对视图读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadForecastRuns()
})
</script>

<style scoped>
.block { margin-bottom: 24px; }
.block h3 { margin: 16px 0 8px; font-size: 15px; }
.block h4 { margin: 14px 0 6px; font-size: 13px; }
.block-desc { color: var(--muted); font-size: 12px; margin: 4px 0 8px; }
.warn-text { color: #b45309; }
.snapshot { margin-top: 8px; }
.snapshot summary { cursor: pointer; color: var(--muted); font-size: 12px; }
</style>
