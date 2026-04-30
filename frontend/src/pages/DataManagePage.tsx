import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  BarChart3,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Database,
  Loader2,
  Trash2,
  XCircle,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { useDataOverview, useEvents, useDeleteEvent, useDeleteDay } from '../hooks/queries'
import type { DayOverview, ActivityEvent } from '../types'
import { getRelativeDateInputValue, getTodayDateInputValue } from '../utils/date'

const SOURCE_LABELS: Record<ActivityEvent['source'], string> = {
  browser: '浏览器',
  chrome: 'Chrome',
  safari: 'Safari',
  gcal: '日历',
  gmail: 'Gmail',
  git: 'Git',
  manual: '手动',
}

const MONTH_LABELS = ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月']

type MonthArchive = {
  id: string
  year: number
  month: number
  label: string
  days: DayOverview[]
  eventCount: number
  analyzedCount: number
  summaryCount: number
}

type QuarterArchive = {
  id: string
  year: number
  quarter: number
  label: string
  rangeLabel: string
  months: MonthArchive[]
  dayCount: number
  eventCount: number
  analyzedCount: number
  summaryCount: number
}

export default function DataManagePage() {
  const today = getTodayDateInputValue()
  const thirtyDaysAgo = getRelativeDateInputValue(-30)
  const [start, setStart] = useState(thirtyDaysAgo)
  const [end, setEnd] = useState(today)
  const [expandedQuarters, setExpandedQuarters] = useState<string[]>([])
  const [expandedMonths, setExpandedMonths] = useState<string[]>([])
  const [expandedDay, setExpandedDay] = useState<string | null>(null)

  const { data: overview, isLoading } = useDataOverview(start, end)
  const deleteDayMut = useDeleteDay()

  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const archives = useMemo(() => buildArchives(overview?.days ?? []), [overview?.days])
  const totalEvents = archives.reduce((sum, group) => sum + group.eventCount, 0)
  const totalDays = archives.reduce((sum, group) => sum + group.dayCount, 0)
  const analyzedDays = archives.reduce((sum, group) => sum + group.analyzedCount, 0)
  const summaryDays = archives.reduce((sum, group) => sum + group.summaryCount, 0)

  useEffect(() => {
    if (archives.length === 0) {
      setExpandedQuarters([])
      setExpandedMonths([])
      setExpandedDay(null)
      return
    }

    setExpandedQuarters(current => {
      const available = new Set(archives.map(group => group.id))
      const next = current.filter(id => available.has(id))
      return next.length > 0 ? next : [archives[0].id]
    })

    setExpandedMonths(current => {
      const allMonths = archives.flatMap(group => group.months)
      const available = new Set(allMonths.map(month => month.id))
      const next = current.filter(id => available.has(id))
      return next.length > 0 ? next : allMonths[0] ? [allMonths[0].id] : []
    })
  }, [archives])

  const handleDeleteDay = (date: string) => {
    deleteDayMut.mutate(date, {
      onSuccess: (d: any) => {
        toast.success(`已删除 ${d.deleted?.events ?? 0} 条事件`)
        setConfirmDelete(null)
        setExpandedDay(null)
      },
    })
  }

  const toggleQuarter = (id: string) => {
    setExpandedQuarters(current => toggleInList(current, id))
  }

  const toggleMonth = (id: string) => {
    setExpandedMonths(current => toggleInList(current, id))
  }

  return (
    <div className="min-w-0 space-y-4">
      <section className="rounded-lg border border-slate-200 bg-white px-4 py-4 shadow-sm">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-950 text-white">
              <Database className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-xl font-semibold text-slate-950">整理下</h1>
              <p className="mt-1 text-sm text-slate-500">按季度、月份和日期归档已采集的数据</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input type="date" value={start} onChange={e => setStart(e.target.value)}
              className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-300 focus:ring-2 focus:ring-blue-100" />
            <span className="text-sm text-slate-400">至</span>
            <input type="date" value={end} onChange={e => setEnd(e.target.value)}
              className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-300 focus:ring-2 focus:ring-blue-100" />
          </div>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <ArchiveMetric icon={<Database className="h-4 w-4" />} label="事件" value={totalEvents} />
          <ArchiveMetric icon={<CalendarDays className="h-4 w-4" />} label="日期" value={totalDays} />
          <ArchiveMetric icon={<CheckCircle2 className="h-4 w-4" />} label="已分析" value={analyzedDays} />
          <ArchiveMetric icon={<BarChart3 className="h-4 w-4" />} label="已总结" value={summaryDays} />
        </div>
      </section>

      <section className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        {isLoading ? (
          <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>
        ) : archives.length === 0 ? (
          <div className="py-16 text-center">
            <Database className="mx-auto mb-2 h-10 w-10 text-slate-300" />
            <p className="text-sm text-slate-400">该时间范围内无数据</p>
          </div>
        ) : (
          <div className="space-y-3 bg-slate-50/60 p-3">
            {archives.map(group => (
              <QuarterBlock
                key={group.id}
                group={group}
                expanded={expandedQuarters.includes(group.id)}
                expandedMonths={expandedMonths}
                expandedDay={expandedDay}
                confirmDelete={confirmDelete}
                onToggleQuarter={toggleQuarter}
                onToggleMonth={toggleMonth}
                onToggleDay={date => setExpandedDay(expandedDay === date ? null : date)}
                onDeleteRequest={setConfirmDelete}
                onDeleteCancel={() => setConfirmDelete(null)}
                onDeleteDay={handleDeleteDay}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function QuarterBlock({
  group,
  expanded,
  expandedMonths,
  expandedDay,
  confirmDelete,
  onToggleQuarter,
  onToggleMonth,
  onToggleDay,
  onDeleteRequest,
  onDeleteCancel,
  onDeleteDay,
}: {
  group: QuarterArchive
  expanded: boolean
  expandedMonths: string[]
  expandedDay: string | null
  confirmDelete: string | null
  onToggleQuarter: (id: string) => void
  onToggleMonth: (id: string) => void
  onToggleDay: (date: string) => void
  onDeleteRequest: (date: string) => void
  onDeleteCancel: () => void
  onDeleteDay: (date: string) => void
}) {
  return (
    <article className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => onToggleQuarter(group.id)}
        className="flex w-full items-center gap-3 bg-gradient-to-r from-slate-50 via-white to-blue-50/70 px-4 py-4 text-left transition-colors hover:from-blue-50 hover:to-slate-50"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-600 text-white shadow-sm">
          {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-semibold text-slate-950">{group.label}</h2>
            <span className="rounded-md bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">{group.rangeLabel}</span>
          </div>
          <p className="mt-1 text-xs text-slate-500">{group.dayCount} 天 · {group.eventCount} 条事件</p>
        </div>
        <ArchiveProgress analyzed={group.analyzedCount} summarized={group.summaryCount} total={group.dayCount} />
      </button>

      {expanded && (
        <div className="space-y-3 border-t border-slate-100 bg-white px-3 py-3 sm:px-4">
          {group.months.map(month => (
            <MonthBlock
              key={month.id}
              month={month}
              expanded={expandedMonths.includes(month.id)}
              expandedDay={expandedDay}
              confirmDelete={confirmDelete}
              onToggleMonth={onToggleMonth}
              onToggleDay={onToggleDay}
              onDeleteRequest={onDeleteRequest}
              onDeleteCancel={onDeleteCancel}
              onDeleteDay={onDeleteDay}
            />
          ))}
        </div>
      )}
    </article>
  )
}

function MonthBlock({
  month,
  expanded,
  expandedDay,
  confirmDelete,
  onToggleMonth,
  onToggleDay,
  onDeleteRequest,
  onDeleteCancel,
  onDeleteDay,
}: {
  month: MonthArchive
  expanded: boolean
  expandedDay: string | null
  confirmDelete: string | null
  onToggleMonth: (id: string) => void
  onToggleDay: (date: string) => void
  onDeleteRequest: (date: string) => void
  onDeleteCancel: () => void
  onDeleteDay: (date: string) => void
}) {
  return (
    <section className="rounded-lg border border-slate-100 bg-slate-50/70">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => onToggleMonth(month.id)}
        className="flex w-full items-center gap-3 px-3 py-3 text-left transition-colors hover:bg-white"
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white text-slate-500 shadow-sm ring-1 ring-slate-200">
          {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-slate-900">{month.label}</h3>
          <p className="mt-0.5 text-xs text-slate-500">{month.days.length} 天 · {month.eventCount} 条事件</p>
        </div>
        <div className="hidden items-center gap-2 sm:flex">
          <StatusPill ok={month.analyzedCount === month.days.length} label={`分析 ${month.analyzedCount}/${month.days.length}`} />
          <StatusPill ok={month.summaryCount === month.days.length} label={`总结 ${month.summaryCount}/${month.days.length}`} />
        </div>
      </button>

      {expanded && (
        <div className="space-y-2 border-t border-slate-200/70 px-3 py-3">
          {month.days.map(day => (
            <DayRow
              key={day.date}
              day={day}
              expanded={expandedDay === day.date}
              confirming={confirmDelete === day.date}
              onToggleDay={onToggleDay}
              onDeleteRequest={onDeleteRequest}
              onDeleteCancel={onDeleteCancel}
              onDeleteDay={onDeleteDay}
            />
          ))}
        </div>
      )}
    </section>
  )
}

function DayRow({
  day,
  expanded,
  confirming,
  onToggleDay,
  onDeleteRequest,
  onDeleteCancel,
  onDeleteDay,
}: {
  day: DayOverview
  expanded: boolean
  confirming: boolean
  onToggleDay: (date: string) => void
  onDeleteRequest: (date: string) => void
  onDeleteCancel: () => void
  onDeleteDay: (date: string) => void
}) {
  const parts = parseDateParts(day.date)

  return (
    <article className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="flex w-full flex-col gap-3 px-3 py-3 transition-colors hover:bg-slate-50 lg:flex-row lg:items-center">
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => onToggleDay(day.date)}
          className="flex min-w-0 flex-1 items-center gap-3 text-left"
        >
          <span className="flex h-10 w-10 shrink-0 flex-col items-center justify-center rounded-lg bg-slate-900 text-white">
            <span className="text-sm font-semibold leading-none">{parts.day}</span>
            <span className="mt-0.5 text-[10px] text-slate-300">{parts.weekday}</span>
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-semibold text-slate-900">{formatDateTitle(day.date)}</p>
              {expanded ? <ChevronDown className="h-4 w-4 text-slate-400" /> : <ChevronRight className="h-4 w-4 text-slate-400" />}
            </div>
            <p className="mt-0.5 text-xs text-slate-500">{day.event_count} 条事件</p>
          </div>
        </button>

        <div className="flex flex-wrap items-center gap-2 lg:justify-end">
          {day.has_analysis ? <StatusPill ok label="已分析" /> : <StatusPill ok={false} label="未分析" />}
          {day.has_summary ? <StatusPill ok label="已总结" /> : <StatusPill ok={false} label="未总结" />}
          {confirming ? (
            <span className="flex items-center gap-1">
              <button onClick={e => { e.stopPropagation(); onDeleteDay(day.date) }}
                className="rounded-md bg-red-600 px-2 py-1 text-xs font-medium text-white hover:bg-red-700">确认删除</button>
              <button onClick={e => { e.stopPropagation(); onDeleteCancel() }}
                className="rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-200">取消</button>
            </span>
          ) : (
            <button onClick={e => { e.stopPropagation(); onDeleteRequest(day.date) }}
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600">
              <Trash2 className="h-3 w-3" /> 删除
            </button>
          )}
        </div>
      </div>
      {expanded && <ExpandedDayEvents date={day.date} />}
    </article>
  )
}

function ExpandedDayEvents({ date }: { date: string }) {
  const { data, isLoading } = useEvents(date, undefined, { aggregateBrowser: false })
  const deleteEventMut = useDeleteEvent()

  if (isLoading) return <div className="border-t border-slate-100 px-6 py-4"><Loader2 className="h-4 w-4 animate-spin text-slate-400" /></div>

  return (
    <div className="space-y-1 border-t border-slate-100 bg-slate-50 px-3 py-3 sm:px-6">
      {data?.items.map((ev: ActivityEvent) => (
        <div key={ev.id} className="flex items-center gap-3 rounded-lg px-3 py-2 text-xs transition-colors hover:bg-white">
          <span className="w-10 font-mono text-slate-400">{ev.timestamp.slice(11, 16)}</span>
          <span className="min-w-0 flex-1 break-words text-slate-700">{ev.title}</span>
          <span className="rounded-md bg-white px-2 py-0.5 text-slate-400 ring-1 ring-slate-100">{SOURCE_LABELS[ev.source] ?? ev.source}</span>
          <button
            onClick={() => {
              deleteEventMut.mutate(ev.id, {
                onSuccess: () => toast.success('已删除'),
                onError: () => toast.error('删除失败'),
              })
            }}
            disabled={deleteEventMut.isPending}
            className="text-slate-300 hover:text-red-500 disabled:opacity-50"
          >
            <Trash2 className="h-3 w-3" />
          </button>
        </div>
      ))}
    </div>
  )
}

function ArchiveMetric({ icon, label, value }: { icon: ReactNode; label: string; value: number }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-3 ring-1 ring-slate-100">
      <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
        <span className="text-blue-600">{icon}</span>
        {label}
      </div>
      <p className="mt-2 text-xl font-semibold tabular-nums text-slate-950">{value}</p>
    </div>
  )
}

function ArchiveProgress({ analyzed, summarized, total }: { analyzed: number; summarized: number; total: number }) {
  return (
    <div className="hidden min-w-[180px] space-y-1.5 lg:block">
      <ProgressLine label="分析" value={analyzed} total={total} color="bg-emerald-500" />
      <ProgressLine label="总结" value={summarized} total={total} color="bg-blue-500" />
    </div>
  )
}

function ProgressLine({ label, value, total, color }: { label: string; value: number; total: number; color: string }) {
  const width = total > 0 ? Math.round((value / total) * 100) : 0
  return (
    <div>
      <div className="mb-1 flex justify-between text-[11px] text-slate-500">
        <span>{label}</span>
        <span>{value}/{total}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-slate-200">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${width}%` }} />
      </div>
    </div>
  )
}

function StatusPill({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium ${ok ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-400'}`}>
      {ok ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
      {label}
    </span>
  )
}

function buildArchives(days: DayOverview[]): QuarterArchive[] {
  const quarters = new Map<string, QuarterArchive>()

  days
    .slice()
    .sort((left, right) => right.date.localeCompare(left.date))
    .forEach(day => {
      const { year, month } = parseDateParts(day.date)
      const quarter = getQuarter(month)
      const quarterId = `${year}-Q${quarter}`
      const monthId = `${year}-${String(month).padStart(2, '0')}`

      if (!quarters.has(quarterId)) {
        quarters.set(quarterId, {
          id: quarterId,
          year,
          quarter,
          label: `${year} Q${quarter}`,
          rangeLabel: getQuarterRangeLabel(quarter),
          months: [],
          dayCount: 0,
          eventCount: 0,
          analyzedCount: 0,
          summaryCount: 0,
        })
      }

      const quarterGroup = quarters.get(quarterId)!
      let monthGroup = quarterGroup.months.find(item => item.id === monthId)
      if (!monthGroup) {
        monthGroup = {
          id: monthId,
          year,
          month,
          label: MONTH_LABELS[month - 1],
          days: [],
          eventCount: 0,
          analyzedCount: 0,
          summaryCount: 0,
        }
        quarterGroup.months.push(monthGroup)
      }

      quarterGroup.dayCount += 1
      quarterGroup.eventCount += day.event_count
      if (day.has_analysis) quarterGroup.analyzedCount += 1
      if (day.has_summary) quarterGroup.summaryCount += 1

      monthGroup.days.push(day)
      monthGroup.eventCount += day.event_count
      if (day.has_analysis) monthGroup.analyzedCount += 1
      if (day.has_summary) monthGroup.summaryCount += 1
    })

  return Array.from(quarters.values()).map(group => ({
    ...group,
    months: group.months
      .sort((left, right) => right.month - left.month)
      .map(month => ({ ...month, days: month.days.sort((left, right) => right.date.localeCompare(left.date)) })),
  }))
}

function toggleInList(values: string[], target: string) {
  return values.includes(target) ? values.filter(value => value !== target) : [...values, target]
}

function parseDateParts(date: string) {
  const [year, month, day] = date.split('-').map(Number)
  const weekday = new Date(`${date}T00:00:00`).toLocaleDateString('zh-CN', { weekday: 'short' })
  return { year, month, day, weekday }
}

function getQuarter(month: number) {
  return Math.floor((month - 1) / 3) + 1
}

function getQuarterRangeLabel(quarter: number) {
  const startMonth = (quarter - 1) * 3 + 1
  return `${startMonth}-${startMonth + 2}月`
}

function formatDateTitle(date: string) {
  const parts = parseDateParts(date)
  return `${parts.year}年${parts.month}月${parts.day}日`
}
