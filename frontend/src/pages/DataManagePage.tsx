import { useState } from 'react'
import { Database, Trash2, Loader2, CheckCircle2, XCircle, ChevronDown, ChevronRight } from 'lucide-react'
import toast from 'react-hot-toast'
import { useDataOverview, useEvents, useDeleteEvent, useDeleteDay } from '../hooks/queries'
import type { DayOverview, ActivityEvent } from '../types'
import { getRelativeDateInputValue, getTodayDateInputValue } from '../utils/date'

const SOURCE_LABELS: Record<ActivityEvent['source'], string> = {
  browser: '浏览器',
  chrome: 'Chrome',
  safari: 'Safari',
  gcal: '日历',
  git: 'Git',
  manual: '手动',
}

export default function DataManagePage() {
  const today = getTodayDateInputValue()
  const thirtyDaysAgo = getRelativeDateInputValue(-30)
  const [start, setStart] = useState(thirtyDaysAgo)
  const [end, setEnd] = useState(today)
  const [expandedDay, setExpandedDay] = useState<string | null>(null)

  const { data: overview, isLoading } = useDataOverview(start, end)
  const deleteDayMut = useDeleteDay()

  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  const handleDeleteDay = (date: string) => {
    deleteDayMut.mutate(date, {
      onSuccess: (d: any) => {
        toast.success(`已删除 ${d.deleted?.events ?? 0} 条事件`)
        setConfirmDelete(null)
        setExpandedDay(null)
      },
    })
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold text-gray-900">整理下</h1>
        <div className="flex items-center gap-2">
          <input type="date" value={start} onChange={e => setStart(e.target.value)}
            className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm outline-none focus:ring-1 focus:ring-blue-500" />
          <span className="text-gray-400 text-sm">至</span>
          <input type="date" value={end} onChange={e => setEnd(e.target.value)}
            className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm outline-none focus:ring-1 focus:ring-blue-500" />
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-200">
        {isLoading ? (
          <div className="flex justify-center py-12"><Loader2 className="w-5 h-5 animate-spin text-gray-400" /></div>
        ) : !overview?.days.length ? (
          <div className="text-center py-12">
            <Database className="w-10 h-10 text-gray-300 mx-auto mb-2" />
            <p className="text-sm text-gray-400">该时间范围内无数据</p>
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {overview.days.map((day: DayOverview) => (
              <div key={day.date}>
                <div className="flex items-center gap-4 px-5 py-3 hover:bg-gray-50 cursor-pointer transition-colors"
                  onClick={() => setExpandedDay(expandedDay === day.date ? null : day.date)}>
                  {expandedDay === day.date ? <ChevronDown className="w-4 h-4 text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400" />}
                  <span className="text-sm font-medium text-gray-800 w-28">{day.date}</span>
                  <span className="text-xs text-gray-500">{day.event_count} 条事件</span>
                  <div className="flex items-center gap-3 ml-auto">
                    {day.has_analysis ? <span className="flex items-center gap-1 text-xs text-emerald-600"><CheckCircle2 className="w-3 h-3" />已分析</span>
                      : <span className="flex items-center gap-1 text-xs text-gray-400"><XCircle className="w-3 h-3" />未分析</span>}
                    {day.has_summary ? <span className="flex items-center gap-1 text-xs text-emerald-600"><CheckCircle2 className="w-3 h-3" />已总结</span>
                      : <span className="flex items-center gap-1 text-xs text-gray-400"><XCircle className="w-3 h-3" />未总结</span>}
                    {confirmDelete === day.date ? (
                      <div className="flex items-center gap-1">
                        <button onClick={e => { e.stopPropagation(); handleDeleteDay(day.date) }}
                          className="px-2 py-0.5 bg-red-600 text-white text-xs rounded hover:bg-red-700">确认删除</button>
                        <button onClick={e => { e.stopPropagation(); setConfirmDelete(null) }}
                          className="px-2 py-0.5 bg-gray-100 text-gray-600 text-xs rounded hover:bg-gray-200">取消</button>
                      </div>
                    ) : (
                      <button onClick={e => { e.stopPropagation(); setConfirmDelete(day.date) }}
                        className="flex items-center gap-1 text-xs text-gray-400 hover:text-red-500 transition-colors">
                        <Trash2 className="w-3 h-3" /> 删除整天
                      </button>
                    )}
                  </div>
                </div>
                {expandedDay === day.date && <ExpandedDayEvents date={day.date} />}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function ExpandedDayEvents({ date }: { date: string }) {
  const { data, isLoading } = useEvents(date, undefined, { aggregateBrowser: false })
  const deleteEventMut = useDeleteEvent()

  if (isLoading) return <div className="px-12 py-4"><Loader2 className="w-4 h-4 animate-spin text-gray-400" /></div>

  return (
    <div className="bg-gray-50 px-12 py-3 space-y-1">
      {data?.items.map((ev: ActivityEvent) => (
        <div key={ev.id} className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-white transition-colors text-xs">
          <span className="text-gray-400 font-mono w-10">{ev.timestamp.slice(11, 16)}</span>
          <span className="text-gray-700 flex-1">{ev.title}</span>
          <span className="text-gray-400">{SOURCE_LABELS[ev.source] ?? ev.source}</span>
          <button
            onClick={() => {
              deleteEventMut.mutate(ev.id, {
                onSuccess: () => toast.success('已删除'),
                onError: () => toast.error('删除失败'),
              })
            }}
            disabled={deleteEventMut.isPending}
            className="text-gray-300 hover:text-red-500 disabled:opacity-50"
          >
            <Trash2 className="w-3 h-3" />
          </button>
        </div>
      ))}
    </div>
  )
}
