import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { PenLine, Clock, Loader2, Plus, Trash2, X, Sparkles } from 'lucide-react'
import toast from 'react-hot-toast'
import { useCollectConfiguredSources, useIngestManual, useEvents, useSettings } from '../hooks/queries'
import type { ActivityEvent, CollectSourceResult, ManualEntry } from '../types'
import { getTodayDateInputValue } from '../utils/date'

const CATEGORY_COLORS: Record<string, string> = {
  work: 'bg-blue-100 text-blue-700', study: 'bg-violet-100 text-violet-700',
  life: 'bg-emerald-100 text-emerald-700', entertainment: 'bg-amber-100 text-amber-700',
}

const SOURCE_LABELS: Record<string, string> = {
  browser: '浏览器',
  chrome: 'Chrome',
  safari: 'Safari',
  gcal: '日历',
  git: 'Git',
  manual: '手动',
}

function HoverHint({ icon, text }: { icon: ReactNode; text: string }) {
  return (
    <span className="relative inline-flex group" title={text} aria-label={text}>
      <span className="cursor-help">{icon}</span>
      <span className="pointer-events-none absolute left-1/2 top-full z-20 mt-2 w-56 -translate-x-1/2 rounded-xl bg-gray-900 px-3 py-2 text-xs leading-5 text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
        {text}
      </span>
    </span>
  )
}

function getCollectResultTone(result: CollectSourceResult) {
  if (result.status === 'failed') return 'border-red-200 bg-red-50/70'
  if (result.status === 'misconfigured') return 'border-amber-200 bg-amber-50/70'
  if (result.status === 'disabled') return 'border-gray-200 bg-gray-50'
  if (result.imported_count > 0) return 'border-emerald-200 bg-emerald-50/70'
  return 'border-slate-200 bg-slate-50/70'
}

function getCollectResultStatus(result: CollectSourceResult) {
  if (result.status === 'failed') return '采集失败'
  if (result.status === 'misconfigured') return '待完善配置'
  if (result.status === 'disabled') return '已关闭'
  return result.imported_count > 0 ? '已导入数据' : '暂无新数据'
}

export default function IngestPage() {
  const [date, setDate] = useState(getTodayDateInputValue())
  const [source, setSource] = useState<string>('')
  const [isManualOpen, setIsManualOpen] = useState(false)
  const [entries, setEntries] = useState<ManualEntry[]>([])
  const [form, setForm] = useState<ManualEntry>({ timestamp: '', title: '', content: '', duration_minutes: 30 })

  const { data: eventsData, isLoading: eventsLoading } = useEvents(date, source || undefined)
  const { data: settings, isLoading: settingsLoading } = useSettings()
  const collectMut = useCollectConfiguredSources()
  const manualMut = useIngestManual()

  const sourceConfigs = [
    {
      key: 'chrome',
      label: 'Chrome 历史',
      description: '读取本地 Chrome 最近 2 天的浏览记录。',
      enabled: settings?.chrome_history_enabled ?? false,
      ready: settings?.chrome_history_enabled ?? false,
    },
    {
      key: 'safari',
      label: 'Safari 历史',
      description: '读取本地 Safari 最近 2 天的浏览记录。',
      enabled: settings?.safari_history_enabled ?? false,
      ready: settings?.safari_history_enabled ?? false,
    },
    {
      key: 'git',
      label: 'Git 记录',
      description: settings?.git_repo_paths
        ? '读取已配置仓库或工作区最近 2 天的提交记录。'
        : '需要先在配置页填写 Git 仓库或工作区路径。',
      enabled: settings?.git_activity_enabled ?? false,
      ready: !!settings?.git_activity_enabled && !!settings?.git_repo_paths?.trim(),
    },
    {
      key: 'gcal',
      label: 'Google 日历',
      description: settings?.google_user_email && settings?.google_credentials_configured
        ? settings.google_calendar_authorized
          ? `读取 ${settings.google_user_email} 最近 2 天的日历事件。`
          : '需要先在配置页完成 Google 日历授权。'
        : settings?.google_user_email
          ? '需要先在配置页上传 Google OAuth JSON。'
          : '需要先在配置页填写 Google 邮箱地址并上传凭据。',
      enabled: settings?.google_calendar_enabled ?? false,
      ready: !!settings?.google_calendar_enabled && !!settings?.google_user_email && !!settings?.google_credentials_configured && !!settings?.google_calendar_authorized,
    },
  ] as const

  const hasEnabledSource = sourceConfigs.some(item => item.enabled)
  const hasReadySource = sourceConfigs.some(item => item.ready)
  const collectDisabledReason = settingsLoading
    ? '正在读取数据源配置...'
    : !hasEnabledSource
      ? '请先在配置页启用至少一个数据源'
      : !hasReadySource
        ? '已启用的数据源还未完成配置'
        : null

  const handleCollect = () => collectMut.mutate(2, {
    onSuccess: data => {
      if (data.imported_count > 0) {
        const importedSummary = data.source_results
          .filter(result => result.imported_count > 0)
          .map(result => `${result.label} ${result.imported_count} 条`)
          .join('，')

        toast.success(importedSummary ? `已完成采集：${importedSummary}` : '采集完成')
        if (data.date_range?.length) setDate(data.date_range[data.date_range.length - 1])
      } else if (data.warnings?.length) {
        toast.error(data.warnings[0])
      } else {
        toast('最近 2 天无新的可采集数据')
      }

      if (data.imported_count > 0 && data.warnings?.length) {
        toast(data.warnings[0])
      }
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? '采集失败，请检查数据源配置'),
  })

  const addEntry = () => {
    if (!form.timestamp || !form.title) { toast.error('请填写时间和标题'); return }
    setEntries([...entries, { ...form }])
    setForm({ timestamp: '', title: '', content: '', duration_minutes: 30 })
  }

  const submitManual = () => {
    if (entries.length === 0) { toast.error('请至少添加一条记录'); return }
    manualMut.mutate(entries, {
      onSuccess: d => {
        toast.success(`已导入 ${d.imported_count} 条记录`)
        setDate(entries[entries.length - 1].timestamp.slice(0, 10))
        setEntries([])
        setForm({ timestamp: '', title: '', content: '', duration_minutes: 30 })
        setIsManualOpen(false)
      },
    })
  }

  return (
    <div>
      <div className="flex items-start justify-between gap-4 mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">干了啥</h1>
        </div>
        <button
          onClick={() => setIsManualOpen(true)}
          className="shrink-0 px-3 py-2 bg-white border border-gray-200 text-sm rounded-xl hover:border-gray-300 hover:bg-gray-50 transition-colors flex items-center gap-2 text-gray-700"
        >
          <HoverHint
            icon={<PenLine className="w-4 h-4 text-violet-500" />}
            text="二级入口，只在补漏或纠错时使用，适合补录线下沟通、临时电话和深度工作。"
          />
          补记一条
          {entries.length > 0 && <span className="px-1.5 py-0.5 rounded-full bg-violet-100 text-violet-700 text-[11px]">{entries.length}</span>}
        </button>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-5 mb-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-blue-600" />
              <p className="text-sm font-medium text-gray-800">一键采集数据</p>
            </div>
            <p className="text-sm text-gray-500 mt-1">会采集最近 2 天的已启用数据源，并自动刷新下方事件列表。</p>
            <div className="flex flex-wrap gap-2 mt-3">
              {sourceConfigs.map(item => {
                const statusText = !item.enabled ? '已关闭' : item.ready ? '已启用' : '待配置'
                const statusTone = !item.enabled
                  ? 'bg-gray-100 text-gray-500'
                  : item.ready
                    ? 'bg-emerald-100 text-emerald-700'
                    : 'bg-amber-100 text-amber-700'

                return (
                  <span key={item.key} className={`px-2.5 py-1 rounded-full text-xs ${statusTone}`}>
                    {item.label} · {statusText}
                  </span>
                )
              })}
            </div>
          </div>

          <div className="flex flex-col sm:flex-row gap-2 shrink-0">
            <Link
              to="/settings"
              className="px-3.5 py-2 border border-gray-200 text-sm rounded-xl text-gray-700 hover:bg-gray-50 text-center"
            >
              配置数据源
            </Link>
            <button
              onClick={handleCollect}
              disabled={collectMut.isPending || !!collectDisabledReason}
              className="px-4 py-2 bg-blue-600 text-white text-sm rounded-xl hover:bg-blue-700 disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {collectMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
              {collectMut.isPending ? '采集中...' : '一键采集数据'}
            </button>
          </div>
        </div>

        {collectDisabledReason && (
          <p className="text-xs text-amber-600 mt-3">{collectDisabledReason}</p>
        )}

        {collectMut.data?.source_results?.length ? (
          <div className="grid gap-2 md:grid-cols-2 mt-4">
            {collectMut.data.source_results.map(result => (
              <div key={result.source} className={`rounded-xl border px-3 py-3 ${getCollectResultTone(result)}`}>
                <div className="flex items-center justify-between gap-2">
                  <p className="text-sm font-medium text-gray-800">{result.label}</p>
                  <span className="text-xs text-gray-500">{getCollectResultStatus(result)}</span>
                </div>
                <p className="text-xs text-gray-500 mt-1">
                  {result.imported_count > 0
                    ? `导入 ${result.imported_count} 条${result.skipped_count ? `，跳过 ${result.skipped_count} 条重复记录` : ''}`
                    : result.message ?? '本次没有新增数据'}
                </p>
              </div>
            ))}
          </div>
        ) : null}
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <div className="flex items-center justify-between mb-4 gap-3 flex-wrap">
          <div className="flex items-center gap-1">
            {[
              { value: '', label: '全部' },
              { value: 'gcal', label: '日历' },
              { value: 'git', label: 'Git' },
              { value: 'browser', label: '浏览器' },
              { value: 'manual', label: '手动' },
            ].map(filter => (
              <button
                key={filter.value}
                onClick={() => setSource(filter.value)}
                className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                  source === filter.value ? 'bg-blue-600 text-white' : 'text-gray-500 hover:bg-gray-100'
                }`}
              >
                {filter.label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <input
              type="date"
              value={date}
              onChange={e => setDate(e.target.value)}
              className="px-2.5 py-1.5 border border-gray-200 rounded-lg text-xs focus:ring-1 focus:ring-blue-500 outline-none"
            />
            <span className="text-xs text-gray-400">共 {eventsData?.total ?? 0} 条</span>
          </div>
        </div>

        {eventsLoading ? (
          <div className="flex justify-center py-8"><Loader2 className="w-5 h-5 animate-spin text-gray-400" /></div>
        ) : eventsData?.items.length === 0 ? (
          <p className="text-center text-sm text-gray-400 py-8">该日期暂无数据</p>
        ) : (
          <div className="space-y-0.5">
            {eventsData?.items.map((ev: ActivityEvent & { visit_count?: number }) => {
              const isAgg = ev.id?.startsWith('agg-')
              return (
                <div key={ev.id} className={`px-3 py-2.5 rounded-lg hover:bg-gray-50 transition-colors ${isAgg ? 'border-l-2 border-emerald-300' : ''}`}>
                  <div className="flex items-center gap-4">
                    <span className="text-xs text-gray-400 w-12 shrink-0 font-mono">{ev.timestamp.slice(11, 16)}</span>
                    <span className={`text-sm flex-1 truncate ${isAgg ? 'font-medium text-emerald-700' : 'text-gray-800'}`}>{ev.title}</span>
                    {isAgg && ev.visit_count && (
                      <span className="text-xs bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded-full shrink-0">{ev.visit_count} 次</span>
                    )}
                    {!isAgg && <span className="text-xs text-gray-400 shrink-0">{SOURCE_LABELS[ev.source] ?? ev.source}</span>}
                    {ev.analysis && (
                      <span className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${CATEGORY_COLORS[ev.analysis.category] ?? 'bg-gray-100 text-gray-600'}`}>
                        {ev.analysis.category}
                      </span>
                    )}
                    {ev.duration_minutes && (
                      <span className="text-xs text-gray-400 shrink-0 flex items-center gap-1"><Clock className="w-3 h-3" />{ev.duration_minutes}m</span>
                    )}
                  </div>
                  {(ev.content || ev.url) && (
                    <div className="ml-16 mt-1">
                      {ev.content && <p className="text-xs text-gray-500 line-clamp-2">{ev.content}</p>}
                      {ev.url && <a href={ev.url} target="_blank" rel="noreferrer" className="text-xs text-blue-400 hover:text-blue-600 truncate block">{ev.url}</a>}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {isManualOpen && (
        <div className="fixed inset-0 z-40">
          <div className="absolute inset-0 bg-slate-900/20 backdrop-blur-[1px]" onClick={() => setIsManualOpen(false)} />
          <div className="absolute inset-y-0 right-0 w-full max-w-md bg-white border-l border-gray-200 shadow-2xl flex flex-col">
            <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-gray-100">
              <div className="flex items-start gap-2">
                <HoverHint
                  icon={<PenLine className="w-4 h-4 text-violet-500 mt-0.5" />}
                  text="补漏或纠错时再用，适合补录线下沟通、临时电话、深度工作和自动采集遗漏的信息。"
                />
                <p className="text-base font-semibold text-gray-900">补记一条</p>
              </div>
              <button onClick={() => setIsManualOpen(false)} className="shrink-0 p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-4">
              <div className="space-y-2">
                <input
                  type="datetime-local"
                  value={form.timestamp}
                  onChange={e => setForm({ ...form, timestamp: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-200 rounded-xl text-sm focus:ring-1 focus:ring-blue-500 focus:border-blue-500 outline-none"
                />
                <input
                  placeholder="标题"
                  value={form.title}
                  onChange={e => setForm({ ...form, title: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-200 rounded-xl text-sm focus:ring-1 focus:ring-blue-500 focus:border-blue-500 outline-none"
                />
                <textarea
                  placeholder="内容（可选）"
                  value={form.content}
                  onChange={e => setForm({ ...form, content: e.target.value })}
                  rows={4}
                  className="w-full px-3 py-2 border border-gray-200 rounded-xl text-sm focus:ring-1 focus:ring-blue-500 focus:border-blue-500 outline-none resize-none"
                />
                <input
                  type="number"
                  placeholder="时长（分钟）"
                  value={form.duration_minutes ?? ''}
                  onChange={e => setForm({ ...form, duration_minutes: Number(e.target.value) })}
                  className="w-full px-3 py-2 border border-gray-200 rounded-xl text-sm focus:ring-1 focus:ring-blue-500 focus:border-blue-500 outline-none"
                />
                <button
                  onClick={addEntry}
                  className="w-full py-2 bg-gray-100 text-gray-700 text-sm rounded-xl hover:bg-gray-200 flex items-center justify-center gap-1.5"
                >
                  <Plus className="w-4 h-4" />
                  添加到待提交列表
                </button>
              </div>

              {entries.length > 0 && (
                <div className="mt-5">
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-sm font-medium text-gray-800">待提交记录</p>
                    <span className="text-xs text-gray-400">{entries.length} 条</span>
                  </div>
                  <div className="space-y-2">
                    {entries.map((entry, index) => (
                      <div key={`${entry.timestamp}-${index}`} className="rounded-xl border border-gray-100 bg-gray-50 px-3 py-2.5">
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="text-sm font-medium text-gray-800 truncate">{entry.title}</p>
                            <p className="text-xs text-gray-400 mt-1">{entry.timestamp.replace('T', ' ')}</p>
                            {entry.content && <p className="text-xs text-gray-500 mt-1 line-clamp-2">{entry.content}</p>}
                          </div>
                          <button onClick={() => setEntries(entries.filter((_, itemIndex) => itemIndex !== index))} className="shrink-0 text-gray-300 hover:text-red-500">
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="px-5 py-4 border-t border-gray-100 flex items-center gap-2">
              <button
                onClick={() => setIsManualOpen(false)}
                className="flex-1 py-2.5 border border-gray-200 text-gray-600 text-sm rounded-xl hover:bg-gray-50"
              >
                先收起
              </button>
              <button
                onClick={submitManual}
                disabled={manualMut.isPending || entries.length === 0}
                className="flex-1 py-2.5 bg-violet-600 text-white text-sm rounded-xl hover:bg-violet-700 disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {manualMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <PenLine className="w-4 h-4" />}
                {manualMut.isPending ? '提交中...' : `提交 ${entries.length} 条`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
