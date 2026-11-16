<template>
  <section class="page" data-module="forecast">
    <header class="page-head">
      <div>
        <h2>经营预测模型管理</h2>
        <p class="page-desc">维护经营预测的算法选择、结果输出与实际对比，为经营预测模型提供可验证的数据工程流程。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记预测任务</button>
        <button class="btn" type="button" @click="exportRows">导出经营预测模型清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <!-- 观测序列与数据质量 -->
    <section class="block">
      <h3>观测序列与数据质量</h3>
      <p class="block-desc">
        观测报告带「观测日期 + 可用时间」双时间轴；缺期（采集遗漏）保留为缺期不补零，节假日停业的零值是真实观测。
      </p>
      <table class="data-table">
        <thead>
          <tr>
            <th>序列编号</th><th>序列名称</th><th>报告数</th><th>有效值数</th><th>缺期数</th>
            <th>最长连续缺期</th><th>迟到更正</th><th>全零序列</th><th>短序列</th><th>最新可用时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in seriesList" :key="item.序列编号">
            <td>{{ item.序列编号 }}</td>
            <td>{{ item.序列名称 }}</td>
            <td>{{ item.报告数 }}</td>
            <td>{{ item.有效值数 }}</td>
            <td>{{ item.缺期总数 }}</td>
            <td>{{ item.最长连续缺期 }}</td>
            <td>{{ item.迟到更正数 }}</td>
            <td>{{ item.全零序列 ? '是' : '否' }}</td>
            <td>{{ item.短序列 ? '是' : '否' }}</td>
            <td>{{ fmtTime(item.最新可用时间) }}</td>
          </tr>
          <tr v-if="!seriesList.length">
            <td colspan="10" class="empty-state">暂无观测序列</td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 观测登记 -->
    <section class="block">
      <h3>登记观测 / 更正</h3>
      <p class="block-desc">
        同一观测日期再次登记即形成更正版本；历史回测截点不会被回填，更正只在下次回测形成新预测版本。
        采集遗漏不填数值；节假日停业的数值只能为 0；可用时间留空表示当前时间。
      </p>
      <form class="filter-bar" @submit.prevent="submitObservation">
        <label class="filter-item">
          <span>序列编号</span>
          <input v-model="obsForm.序列编号" list="series-options" placeholder="如 SER-0001" />
          <datalist id="series-options">
            <option v-for="item in seriesList" :key="item.序列编号" :value="item.序列编号" />
          </datalist>
        </label>
        <label class="filter-item">
          <span>观测日期</span>
          <input v-model="obsForm.观测日期" type="date" />
        </label>
        <label class="filter-item">
          <span>记录类型</span>
          <select v-model="obsForm.记录类型">
            <option v-for="kind in recordTypes" :key="kind" :value="kind">{{ kind }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>数值</span>
          <input v-model="obsForm.数值" type="number" step="any" :disabled="obsForm.记录类型 === '采集遗漏'" placeholder="采集遗漏留空" />
        </label>
        <label class="filter-item">
          <span>可用时间</span>
          <input v-model="obsForm.可用时间" type="datetime-local" />
        </label>
        <button class="btn primary" type="submit">登记观测</button>
      </form>
      <table class="data-table">
        <thead>
          <tr><th>序列编号</th><th>观测日期</th><th>数值</th><th>记录类型</th><th>可用时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in observations" :key="row.id">
            <td>{{ row.序列编号 }}</td>
            <td>{{ row.观测日期 }}</td>
            <td>{{ row.数值 ?? '—' }}</td>
            <td>{{ row.记录类型 }}</td>
            <td>{{ fmtTime(row.可用时间) }}</td>
          </tr>
          <tr v-if="!observations.length">
            <td colspan="5" class="empty-state">暂无观测报告</td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 滚动回测 -->
    <section class="block">
      <h3>滚动回测</h3>
      <p class="block-desc">
        按周期频率与预测步长滚动设置训练截点，逐截点只用当时可见的观测训练；
        回测比较相同截点和步长下各基线算法的误差，并报告有效样本数与覆盖情况。
      </p>
      <form class="filter-bar" @submit.prevent="submitBacktest">
        <label class="filter-item">
          <span>序列编号</span>
          <select v-model="backtestForm.序列编号">
            <option v-for="item in seriesList" :key="item.序列编号" :value="item.序列编号">{{ item.序列编号 }} {{ item.序列名称 }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>周期频率</span>
          <select v-model="backtestForm.频率">
            <option v-for="freq in frequencies" :key="freq" :value="freq">{{ freq }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>预测步长</span>
          <input v-model.number="backtestForm.预测步长" type="number" min="1" max="12" />
        </label>
        <label class="filter-item">
          <span>回测折数</span>
          <input v-model.number="backtestForm.折数" type="number" min="1" max="24" />
        </label>
        <label class="filter-item">
          <span>移动平均窗口</span>
          <input v-model.number="backtestForm.移动平均窗口" type="number" min="2" max="12" />
        </label>
        <label class="filter-item">
          <span>季节周期</span>
          <input v-model.number="backtestForm.季节周期" type="number" min="2" max="24" />
        </label>
        <label class="filter-item">
          <span>最小训练样本</span>
          <input v-model.number="backtestForm.最小训练样本" type="number" min="2" max="60" />
        </label>
        <label class="filter-item">
          <span>置信水平</span>
          <input v-model.number="backtestForm.置信水平" type="number" min="0.5" max="0.99" step="0.05" />
        </label>
        <fieldset class="algo-picker">
          <legend>基线算法（至少两种可比较）</legend>
          <label v-for="algo in algorithmOptions" :key="algo.value">
            <input v-model="backtestForm.算法" type="checkbox" :value="algo.value" />
            {{ algo.label }}
          </label>
        </fieldset>
        <button class="btn primary" type="submit">运行滚动回测</button>
      </form>
      <p v-if="backtestMessage" class="block-desc">{{ backtestMessage }}</p>

      <table class="data-table">
        <thead>
          <tr>
            <th>版本号</th><th>序列编号</th><th>频率</th><th>步长</th><th>折数</th>
            <th>预测点数</th><th>数据截面时间</th><th>状态</th><th>创建时间</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="run in runs" :key="run.id">
            <td>{{ run.版本号 }}</td>
            <td>{{ run.序列编号 }}</td>
            <td>{{ run.配置.频率 }}</td>
            <td>{{ run.配置.预测步长 }}</td>
            <td>{{ run.时间折数 }}</td>
            <td>{{ run.预测点数 }}</td>
            <td>{{ fmtTime(run.数据截面时间) }}</td>
            <td>{{ run.状态 }}</td>
            <td>{{ fmtTime(run.创建时间) }}</td>
            <td><button class="link" type="button" @click="openRun(run.id)">查看</button></td>
          </tr>
          <tr v-if="!runs.length">
            <td colspan="10" class="empty-state">暂无回测版本，请先运行滚动回测</td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 回测结果 -->
    <section v-if="runDetail" class="block">
      <h3>回测结果 {{ runDetail.版本号 }}（{{ runDetail.序列编号 }}）</h3>

      <h4>算法汇总（相同截点与步长下比较）</h4>
      <table class="data-table">
        <thead>
          <tr>
            <th>算法</th><th>预测点数</th><th>有效样本数</th><th>待观测</th><th>剔除</th>
            <th>MAE</th><th>平均相对误差</th><th>区间覆盖率</th><th>区间提供率</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in runDetail.算法汇总" :key="item.算法">
            <td>{{ item.算法名称 }}</td>
            <td>{{ item.预测点数 }}</td>
            <td>{{ item.有效样本数 }}</td>
            <td>{{ item.待观测数 }}</td>
            <td>{{ item.剔除数 }}</td>
            <td>{{ fmtNum(item.MAE) }}</td>
            <td>{{ fmtPct(item.平均相对误差) }}</td>
            <td>{{ fmtPct(item.区间覆盖率) }}</td>
            <td>{{ fmtPct(item.区间提供率) }}</td>
          </tr>
        </tbody>
      </table>

      <h4>各时间折覆盖情况</h4>
      <table class="data-table">
        <thead>
          <tr>
            <th>折</th><th>训练截止期</th><th>目标期</th><th>截点可用时间</th>
            <th>有效训练样本</th><th>缺期</th><th>最长连续缺期</th><th>训练覆盖率</th><th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="fold in runDetail.folds" :key="fold.折序号">
            <td>{{ fold.折序号 }}</td>
            <td>{{ fold.训练截止期 }}</td>
            <td>{{ fold.目标期 }}</td>
            <td>{{ fmtTime(fold.截点可用时间) }}</td>
            <td>{{ fold.有效训练样本数 }}</td>
            <td>{{ fold.缺期数 }}</td>
            <td>{{ fold.最长连续缺期 }}</td>
            <td>
              <div class="coverage-bar" :title="fmtPct(fold.训练覆盖率)">
                <div class="coverage-fill" :style="{ width: fmtPct(fold.训练覆盖率) }" />
              </div>
              {{ fmtPct(fold.训练覆盖率) }}
            </td>
            <td>
              <span v-if="fold.状态 === '完成'">完成</span>
              <span v-else class="warn-text">{{ fold.剔除原因 }}</span>
            </td>
          </tr>
        </tbody>
      </table>

      <h4>回测视图（按预测起点分组）</h4>
      <p class="block-desc">
        每个预测起点只使用该截点当时可见的观测；不同训练截点的结果分组展示，不排列成一条看似连续的预测线。
      </p>
      <div v-for="fold in runDetail.folds" :key="`view-${fold.折序号}`" class="fold-card">
        <h5>预测起点 {{ fold.训练截止期 }} → 目标期 {{ fold.目标期 }}</h5>
        <p v-if="fold.状态 === '已剔除'" class="warn-text">本折已剔除：{{ fold.剔除原因 }}</p>
        <table v-else class="data-table">
          <thead>
            <tr>
              <th>算法</th><th>预测值</th><th>预测区间</th><th>区间依据</th>
              <th>真实值</th><th>误差</th><th>相对误差</th><th>误差分母</th><th>核对状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="point in pointsOf(fold.折序号)" :key="`${fold.折序号}-${point.算法}`">
              <td>{{ point.算法名称 }}</td>
              <td>{{ fmtNum(point.预测值) }}</td>
              <td>{{ fmtInterval(point) }}</td>
              <td>{{ point.区间依据 }}</td>
              <td>{{ point.核对状态 === '待观测' ? '待观测' : fmtNum(point.实际值) }}</td>
              <td>{{ point.核对状态 === '待观测' ? '—' : fmtNum(point.误差) }}</td>
              <td>{{ point.核对状态 === '待观测' ? '—' : fmtPct(point.相对误差) }}</td>
              <td>{{ point.核对状态 === '待观测' ? '—' : fmtNum(point.误差分母) }}</td>
              <td>
                <span :class="point.核对状态 === '待观测' ? 'warn-text' : ''">{{ point.核对状态 }}</span>
                <span v-if="point.剔除原因" class="block-desc">{{ point.剔除原因 }}</span>
              </td>
            </tr>
          </tbody>
        </table>
        <details class="snapshot">
          <summary>截点可见观测快照（{{ fold.可见观测.length }} 期，不回填后续更正）</summary>
          <table class="data-table">
            <thead>
              <tr><th>观测期</th><th>状态</th><th>数值</th><th>可用时间</th><th>版本数</th></tr>
            </thead>
            <tbody>
              <tr v-for="obs in fold.可见观测" :key="`${fold.折序号}-${obs.观测期}`">
                <td>{{ obs.观测期 }}</td>
                <td>{{ obs.状态 }}</td>
                <td>{{ obs.数值 ?? '—' }}</td>
                <td>{{ fmtTime(obs.可用时间) }}</td>
                <td>{{ obs.版本数 }}</td>
              </tr>
            </tbody>
          </table>
        </details>
      </div>

      <h4>数据质量与未来样本检查</h4>
      <div class="stat-row">
        <article class="stat-card">
          <span class="stat-label">迟到更正</span>
          <strong class="stat-value">{{ runDetail.数据质量.迟到更正数 }} 期</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">最长连续缺期</span>
          <strong class="stat-value">{{ runDetail.数据质量.连续缺期 }} 期</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">全零序列</span>
          <strong class="stat-value">{{ runDetail.数据质量.全零序列 ? '是' : '否' }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">短序列</span>
          <strong class="stat-value">{{ runDetail.数据质量.短序列 ? '是' : '否' }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">未来样本检查</span>
          <strong class="stat-value" :class="runDetail.未来样本检查.通过 ? '' : 'warn-text'">
            {{ runDetail.未来样本检查.通过 ? '通过' : '未通过' }}
          </strong>
        </article>
      </div>
      <table v-if="runDetail.数据质量.迟到更正.length" class="data-table">
        <thead>
          <tr><th>观测期</th><th>版本数</th><th>首次可用时间</th><th>末次可用时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in runDetail.数据质量.迟到更正" :key="item.观测期">
            <td>{{ item.观测期 }}</td>
            <td>{{ item.版本数 }}</td>
            <td>{{ fmtTime(item.首次可用时间) }}</td>
            <td>{{ fmtTime(item.末次可用时间) }}</td>
          </tr>
        </tbody>
      </table>
      <details class="snapshot">
        <summary>未来样本检查明细（{{ runDetail.未来样本检查.检查项数 }} 项，未通过 {{ runDetail.未来样本检查.未通过数 }} 项）</summary>
        <table class="data-table">
          <thead>
            <tr><th>对象</th><th>检查内容</th><th>是否通过</th></tr>
          </thead>
          <tbody>
            <tr v-for="(check, idx) in runDetail.未来样本检查.检查项" :key="idx">
              <td>{{ check.对象 }}</td>
              <td>{{ check.检查 }}</td>
              <td>{{ check.通过 ? '通过' : '未通过' }}</td>
            </tr>
          </tbody>
        </table>
      </details>
    </section>

    <!-- 预测任务清单（原有功能） -->
    <section class="block">
      <h3>预测任务清单</h3>
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
            <td :colspan="columns.length + 1" class="empty-state">暂无经营预测模型数据，可先登记预测任务</td>
          </tr>
        </tbody>
      </table>

      <footer class="page-foot">
        <span>共 {{ total }} 条经营预测模型记录</span>
        <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      </footer>
    </section>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>

const ENDPOINT = '/api/forecast'
const columns = ["任务编号", "预测对象", "预测周期", "预测算法", "预测结果", "置信区间", "实际对比", "任务状态"]
const actions = ["生成预测", "验证结果", "归档任务"]
const statuses = ["待预测", "预测中", "已生成", "已验证"]
const stats = [{"label": "预测任务总数", "value": 0}, {"label": "已生成预测", "value": 0}, {"label": "已验证预测", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

// 观测序列与数据质量
const seriesList = ref<Row[]>([])
const observations = ref<Row[]>([])
const recordTypes = ["正常", "节假日停业", "采集遗漏"]
const obsForm = ref<Row>({ 序列编号: '', 观测日期: '', 数值: '', 可用时间: '', 记录类型: '正常' })

// 滚动回测
const frequencies = ["月", "周", "日"]
const algorithmOptions = [
  { value: 'naive', label: '朴素法（上一期值）' },
  { value: 'moving_average', label: '移动平均' },
  { value: 'seasonal_naive', label: '季节朴素' },
]
const backtestForm = ref<Row>({
  序列编号: '', 频率: '月', 预测步长: 1, 折数: 6,
  移动平均窗口: 3, 季节周期: 12, 最小训练样本: 8, 置信水平: 0.9,
  算法: ['naive', 'moving_average', 'seasonal_naive'],
})
const backtestMessage = ref('')
const runs = ref<Row[]>([])
const runDetail = ref<Row | null>(null)

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

function fmtInterval(point: Row): string {
  if (point.区间下限 === null || point.区间下限 === undefined) return '不提供'
  return `[${fmtNum(point.区间下限)}, ${fmtNum(point.区间上限)}]`
}

function pointsOf(foldIndex: number): Row[] {
  if (!runDetail.value) return []
  return runDetail.value.points.filter((point: Row) => point.折序号 === foldIndex)
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '预测任务登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('经营预测模型动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '经营预测模型操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('预测任务列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '经营预测模型列表读取失败'
  }
}

async function loadSeries() {
  try {
    const response = await request(`${ENDPOINT}/series`)
    if (!response.ok) throw new Error('序列质量读取失败')
    const payload = await response.json()
    seriesList.value = payload.items ?? []
    if (!backtestForm.value.序列编号 && seriesList.value.length) {
      backtestForm.value.序列编号 = seriesList.value[0].序列编号
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '序列质量读取失败'
  }
}

async function loadObservations() {
  try {
    const response = await request(`${ENDPOINT}/observations?size=10`)
    if (!response.ok) throw new Error('观测报告读取失败')
    const payload = await response.json()
    observations.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '观测报告读取失败'
  }
}

async function submitObservation() {
  errorMessage.value = ''
  backtestMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/observations`, {
      method: 'POST',
      body: JSON.stringify({ values: obsForm.value }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || '观测登记失败')
    }
    backtestMessage.value = payload.message
    obsForm.value = { 序列编号: obsForm.value.序列编号, 观测日期: '', 数值: '', 可用时间: '', 记录类型: '正常' }
    await Promise.all([loadSeries(), loadObservations()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '观测登记失败'
  }
}

async function submitBacktest() {
  errorMessage.value = ''
  backtestMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/backtests`, {
      method: 'POST',
      body: JSON.stringify({ values: backtestForm.value }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || '滚动回测执行失败')
    }
    backtestMessage.value = payload.message
    await loadRuns()
    if (payload.entry?.id) {
      await openRun(payload.entry.id)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '滚动回测执行失败'
  }
}

async function loadRuns() {
  try {
    const response = await request(`${ENDPOINT}/backtests`)
    if (!response.ok) throw new Error('回测版本读取失败')
    const payload = await response.json()
    runs.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '回测版本读取失败'
  }
}

async function openRun(runId: number) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/backtests/${runId}`)
    if (!response.ok) throw new Error('回测明细读取失败')
    runDetail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '回测明细读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadSeries()
  void loadObservations()
  void loadRuns()
})
</script>

<style scoped>
.block { margin-bottom: 24px; }
.block h3 { margin: 16px 0 8px; font-size: 15px; }
.block h4 { margin: 14px 0 6px; font-size: 13px; }
.block h5 { margin: 10px 0 6px; font-size: 13px; }
.block-desc { color: var(--muted); font-size: 12px; margin: 4px 0 8px; }
.algo-picker { border: 1px solid var(--border); border-radius: 6px; padding: 6px 10px; display: flex; gap: 12px; font-size: 13px; }
.algo-picker legend { font-size: 12px; color: var(--muted); }
.coverage-bar { background: #eef2f7; border-radius: 4px; height: 8px; width: 120px; overflow: hidden; margin-bottom: 2px; }
.coverage-fill { background: var(--brand); height: 100%; }
.fold-card { border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; margin-bottom: 10px; background: #fff; }
.warn-text { color: #b45309; }
.snapshot { margin-top: 8px; }
.snapshot summary { cursor: pointer; color: var(--muted); font-size: 12px; }
</style>
