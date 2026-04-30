import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { PenLine, Clock, Loader2, Plus, Trash2, X, Sparkles, ExternalLink, Upload } from 'lucide-react'
import toast from 'react-hot-toast'
import { useCollectConfiguredSources, useIngestChromeDevtoolsHistory, useIngestManual, useEvents, useSettings } from '../hooks/queries'
import type { ActivityEvent, CollectSourceResult, ManualEntry } from '../types'
import { getTodayDateInputValue } from '../utils/date'
import { openExternalUrl } from '../utils/openExternalUrl'

const MCP_BATCH_SIZE = 10
const MCP_MAX_PAGES = 80

const CATEGORY_COLORS: Record<string, string> = {
  work: 'bg-blue-100 text-blue-700', study: 'bg-violet-100 text-violet-700',
  life: 'bg-emerald-100 text-emerald-700', entertainment: 'bg-amber-100 text-amber-700',
}

type McpProgress = {
  status: 'idle' | 'running' | 'done' | 'failed'
  batch: number
  imported: number
  updated: number
  skipped: number
  captured: number
  message?: string
}

const SOURCE_LABELS: Record<string, string> = {
  browser: '浏览器',
  chrome: 'Chrome',
  safari: 'Safari',
  gcal: '日历',
  gmail: 'Gmail',
  git: 'Git',
  manual: '手动',
}

function HoverHint({ icon, text }: { icon: ReactNode; text: string }) {
  return (
    <span className="relative inline-flex group" title={text} aria-label={text}>
      <span className="cursor-help">{icon}</span>
      <span className="pointer-events-none absolute left-1/2 top-full z-20 mt-2 w-56 -translate-x-1/2 rounded-lg bg-slate-900 px-3 py-2 text-xs leading-5 text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
        {text}
      </span>
    </span>
  )
}

function getCollectResultTone(result: CollectSourceResult) {
  if (result.status === 'failed') return 'border-red-200 bg-red-50/70'
  if (result.status === 'misconfigured') return 'border-amber-200 bg-amber-50/70'
  if (result.status === 'disabled') return 'border-slate-200 bg-slate-50'
  if (result.imported_count > 0) return 'border-emerald-200 bg-emerald-50/70'
  return 'border-slate-200 bg-slate-50/70'
}

function getCollectResultStatus(result: CollectSourceResult) {
  if (result.status === 'failed') return '采集失败'
  if (result.status === 'misconfigured') return '待完善配置'
  if (result.status === 'disabled') return '已关闭'
  return result.imported_count > 0 ? '已导入数据' : '暂无新数据'
}

function getAxiosErrorDetail(error: any) {
  const detail = error?.response?.data?.detail
  if (detail && typeof detail === 'object') {
    return detail.message ?? '采集失败，请检查数据源配置'
  }
  return detail ?? '采集失败，请检查数据源配置'
}

export default function IngestPage() {
  const [date, setDate] = useState(getTodayDateInputValue())
  const [source, setSource] = useState<string>('')
  const [isManualOpen, setIsManualOpen] = useState(false)
  const [entries, setEntries] = useState<ManualEntry[]>([])
  const [form, setForm] = useState<ManualEntry>({ timestamp: '', title: '', content: '', duration_minutes: 30 })
  const [mcpProgress, setMcpProgress] = useState<McpProgress>({
    status: 'idle',
    batch: 0,
    imported: 0,
    updated: 0,
    skipped: 0,
    captured: 0,
  })

  const { data: eventsData, isLoading: eventsLoading } = useEvents(date, source || undefined)
  const { data: settings, isLoading: settingsLoading } = useSettings()
  const collectMut = useCollectConfiguredSources()
  const chromeDevtoolsHistoryMut = useIngestChromeDevtoolsHistory()
  const manualMut = useIngestManual()
  const isMcpCollecting = mcpProgress.status === 'running'
  const isCollecting = collectMut.isPending || isMcpCollecting

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
    {
      key: 'gmail',
      label: 'Gmail',
      description: settings?.google_user_email && settings?.google_credentials_configured
        ? settings.google_gmail_authorized
          ? `读取 ${settings.google_user_email} 最近 2 天的邮件。`
          : '需要先在配置页完成 Google 数据源授权。'
        : settings?.google_user_email
          ? '需要先在配置页上传 Google OAuth JSON。'
          : '需要先在配置页填写 Google 邮箱地址并上传凭据。',
      enabled: settings?.gmail_enabled ?? false,
      ready: !!settings?.gmail_enabled && !!settings?.google_user_email && !!settings?.google_credentials_configured && !!settings?.google_gmail_authorized,
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

  const handleCollect = async () => {
    setMcpProgress({
      status: 'idle',
      batch: 0,
      imported: 0,
      updated: 0,
      skipped: 0,
      captured: 0,
    })

    let mcpStarted = false
    try {
      const data = await collectMut.mutateAsync(2)
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

      if (settings?.chrome_history_enabled) {
        mcpStarted = true
        let offset = 0
        let batch = 0
        let imported = 0
        let updated = 0
        let skipped = 0
        let captured = 0
        let hasMore = true

        setMcpProgress({
          status: 'running',
          batch,
          imported,
          updated,
          skipped,
          captured,
          message: 'Chrome MCP 内网明细开始分批采集，普通数据已先刷新。',
        })

        while (hasMore && offset < MCP_MAX_PAGES) {
          const currentBatchSize = Math.min(MCP_BATCH_SIZE, MCP_MAX_PAGES - offset)
          const batchData = await chromeDevtoolsHistoryMut.mutateAsync({
            days: 2,
            maxPages: currentBatchSize,
            offset,
          })

          batch += 1
          imported += batchData.imported_count ?? 0
          updated += batchData.updated_count ?? 0
          skipped += batchData.skipped_count ?? 0
          captured += batchData.captured_count ?? 0
          if (batchData.date_range?.length) setDate(batchData.date_range[batchData.date_range.length - 1])

          const nextOffset = batchData.next_offset ?? offset + currentBatchSize
          hasMore = !!batchData.has_more && nextOffset > offset && nextOffset < MCP_MAX_PAGES
          offset = nextOffset

          setMcpProgress({
            status: hasMore ? 'running' : 'done',
            batch,
            imported,
            updated,
            skipped,
            captured,
            message: hasMore
              ? `已完成 ${batch} 批，正在继续读取后续内网页面。`
              : `内网明细采集完成，共处理 ${captured} 个页面。`,
          })
        }

        const changed = imported + updated
        if (changed > 0) {
          toast.success(`内网明细已补充：新增 ${imported} 条，更新 ${updated} 条`)
        } else if (captured > 0) {
          toast('内网明细已检查，没有新的内容需要写入')
        }
      }
    } catch (e: any) {
      const detail = getAxiosErrorDetail(e)
      if (mcpStarted) {
        setMcpProgress(current => ({
          ...current,
          status: 'failed',
          message: detail || 'Chrome MCP 内网明细采集失败，可稍后重试。',
        }))
      }
      toast.error(detail)
    }
  }

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
    <div className="min-w-0 max-w-full space-y-4 overflow-hidden">
      <section className="rounded-lg border border-slate-200 bg-white px-4 py-4 shadow-sm">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-950 text-white">
              <Upload className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-xl font-semibold text-slate-950">干了啥</h1>
              <p className="mt-1 text-sm text-slate-500">采集、补记和查看当天活动记录</p>
            </div>
          </div>
          <button
            onClick={() => setIsManualOpen(true)}
            className="inline-flex h-9 shrink-0 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 shadow-sm transition-colors hover:border-slate-300 hover:bg-slate-50"
          >
            <HoverHint
              icon={<PenLine className="w-4 h-4 text-violet-500" />}
              text="二级入口，只在补漏或纠错时使用，适合补录线下沟通、临时电话和深度工作。"
            />
            补记一条
            {entries.length > 0 && <span className="px-1.5 py-0.5 rounded-full bg-violet-100 text-violet-700 text-[11px]">{entries.length}</span>}
          </button>
        </div>
      </section>

      <section className="rounded-lg border border-dashed border-slate-200 bg-slate-50/80 p-3">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-slate-400" />
              <p className="text-sm font-medium text-slate-700">手动补采</p>
            </div>
            <p className="mt-1 text-xs text-slate-500">自动任务会定时刷新；缺数据时可手动补采最近 2 天的数据源。</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {sourceConfigs.map(item => {
                const statusText = !item.enabled ? '已关闭' : item.ready ? '已启用' : '待配置'
                const statusTone = !item.enabled
                  ? 'bg-slate-100 text-slate-500'
                  : item.ready
                    ? 'bg-emerald-100 text-emerald-700'
                    : 'bg-amber-100 text-amber-700'

                return (
                  <span key={item.key} className={`rounded-full px-2.5 py-1 text-xs ${statusTone}`}>
                    {item.label} · {statusText}
                  </span>
                )
              })}
            </div>
          </div>

          <div className="flex shrink-0 flex-col gap-2 sm:flex-row">
            <Link
              to="/settings"
              className="inline-flex h-8 items-center justify-center rounded-lg border border-slate-200 bg-white px-3 text-xs font-medium text-slate-600 transition-colors hover:border-slate-300 hover:bg-slate-50"
            >
              配置数据源
            </Link>
            <button
              onClick={handleCollect}
              disabled={isCollecting || !!collectDisabledReason}
              className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 text-xs font-medium text-slate-600 transition-colors hover:border-slate-300 hover:bg-slate-50 disabled:opacity-50"
            >
              {isCollecting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
              {isMcpCollecting ? '补充内网明细...' : collectMut.isPending ? '采集中...' : '手动补采'}
            </button>
          </div>
        </div>

        {collectDisabledReason && (
          <p className="text-xs text-amber-600 mt-3">{collectDisabledReason}</p>
        )}

        {mcpProgress.status !== 'idle' && (
          <div className={`mt-4 rounded-lg border px-3 py-3 ${
            mcpProgress.status === 'failed'
              ? 'border-red-200 bg-red-50/70'
              : mcpProgress.status === 'done'
                ? 'border-emerald-200 bg-emerald-50/70'
                : 'border-blue-200 bg-blue-50/70'
          }`}>
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-medium text-slate-800">Chrome 内网明细</p>
              <span className="text-xs text-slate-500">
                {mcpProgress.status === 'running' ? `第 ${mcpProgress.batch + 1} 批进行中` : mcpProgress.status === 'done' ? '已完成' : '采集失败'}
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-1">{mcpProgress.message}</p>
            <div className="flex flex-wrap gap-2 mt-2 text-xs text-slate-500">
              <span>已抓取 {mcpProgress.captured} 页</span>
              <span>新增 {mcpProgress.imported} 条</span>
              <span>更新 {mcpProgress.updated} 条</span>
              <span>跳过 {mcpProgress.skipped} 条</span>
            </div>
          </div>
        )}

        {collectMut.data?.source_results?.length ? (
          <div className="grid gap-2 md:grid-cols-2 mt-4">
            {collectMut.data.source_results.map(result => (
              <div key={result.source} className={`rounded-lg border px-3 py-3 ${getCollectResultTone(result)}`}>
                <div className="flex items-center justify-between gap-2">
                  <p className="text-sm font-medium text-slate-800">{result.label}</p>
                  <span className="text-xs text-slate-500">{getCollectResultStatus(result)}</span>
                </div>
                <p className="text-xs text-slate-500 mt-1">
                  {result.imported_count > 0
                    ? `导入 ${result.imported_count} 条${result.skipped_count ? `，跳过 ${result.skipped_count} 条重复记录` : ''}`
                    : result.message ?? '本次没有新增数据'}
                </p>
                {result.action_url && (
                  <button
                    type="button"
                    onClick={() => openExternalUrl(result.action_url!)}
                    className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-amber-200 bg-white px-2.5 py-1.5 text-xs font-medium text-amber-800 hover:border-amber-300"
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                    {result.action_label ?? '打开处理'}
                  </button>
                )}
              </div>
            ))}
          </div>
        ) : null}
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex items-center justify-between mb-4 gap-3 flex-wrap">
          <div className="flex items-center gap-1">
            {[
              { value: '', label: '全部' },
              { value: 'gcal', label: '日历' },
              { value: 'gmail', label: 'Gmail' },
              { value: 'git', label: 'Git' },
              { value: 'browser', label: '浏览器' },
              { value: 'manual', label: '手动' },
            ].map(filter => (
              <button
                key={filter.value}
                onClick={() => setSource(filter.value)}
                className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                  source === filter.value ? 'bg-blue-600 text-white' : 'text-slate-500 hover:bg-slate-100'
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
              className="h-8 rounded-lg border border-slate-200 bg-white px-2.5 text-xs text-slate-700 outline-none focus:border-blue-300 focus:ring-2 focus:ring-blue-100"
            />
            <span className="text-xs text-slate-400">共 {eventsData?.total ?? 0} 条</span>
          </div>
        </div>

        {eventsLoading ? (
          <div className="flex justify-center py-8"><Loader2 className="w-5 h-5 animate-spin text-slate-400" /></div>
        ) : eventsData?.items.length === 0 ? (
          <p className="text-center text-sm text-slate-400 py-8">该日期暂无数据</p>
        ) : (
          <div className="space-y-0.5">
            {eventsData?.items.map((ev: ActivityEvent & { visit_count?: number }) => {
              const isAgg = ev.id?.startsWith('agg-')
              return (
                <div key={ev.id} className={`rounded-lg px-3 py-2.5 transition-colors hover:bg-slate-50 ${isAgg ? 'border-l-2 border-emerald-300' : ''}`}>
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                    <span className="w-12 shrink-0 font-mono text-xs text-slate-400">{ev.timestamp.slice(11, 16)}</span>
                    <span className={`min-w-0 basis-[calc(100%-4rem)] truncate text-sm sm:basis-auto sm:flex-1 ${isAgg ? 'font-medium text-emerald-700' : 'text-slate-800'}`}>{ev.title}</span>
                    {isAgg && ev.visit_count && (
                      <span className="text-xs bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded-full shrink-0">{ev.visit_count} 次</span>
                    )}
                    {!isAgg && <span className="shrink-0 text-xs text-slate-400">{SOURCE_LABELS[ev.source] ?? ev.source}</span>}
                    {ev.analysis && (
                      <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${CATEGORY_COLORS[ev.analysis.category] ?? 'bg-slate-100 text-slate-600'}`}>
                        {ev.analysis.category}
                      </span>
                    )}
                    {ev.duration_minutes && (
                      <span className="flex shrink-0 items-center gap-1 text-xs text-slate-400"><Clock className="w-3 h-3" />{ev.duration_minutes}m</span>
                    )}
                  </div>
                  {(ev.content || ev.url) && (
                    <div className="ml-16 mt-1">
                      {ev.content && <p className="line-clamp-2 text-xs text-slate-500">{ev.content}</p>}
                      {ev.url && <a href={ev.url} target="_blank" rel="noreferrer" className="text-xs text-blue-400 hover:text-blue-600 truncate block">{ev.url}</a>}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </section>

      {isManualOpen && (
        <div className="fixed inset-0 z-40">
          <div className="absolute inset-0 bg-slate-900/20 backdrop-blur-[1px]" onClick={() => setIsManualOpen(false)} />
          <div className="absolute inset-y-0 right-0 flex w-full max-w-md flex-col border-l border-slate-200 bg-white shadow-2xl">
            <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
              <div className="flex items-start gap-2">
                <HoverHint
                  icon={<PenLine className="w-4 h-4 text-violet-500 mt-0.5" />}
                  text="补漏或纠错时再用，适合补录线下沟通、临时电话、深度工作和自动采集遗漏的信息。"
                />
                <p className="text-base font-semibold text-slate-900">补记一条</p>
              </div>
              <button onClick={() => setIsManualOpen(false)} className="shrink-0 rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-4">
              <div className="space-y-2">
                <input
                  type="datetime-local"
                  value={form.timestamp}
                  onChange={e => setForm({ ...form, timestamp: e.target.value })}
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800 outline-none focus:border-blue-300 focus:ring-2 focus:ring-blue-100"
                />
                <input
                  placeholder="标题"
                  value={form.title}
                  onChange={e => setForm({ ...form, title: e.target.value })}
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800 outline-none focus:border-blue-300 focus:ring-2 focus:ring-blue-100"
                />
                <textarea
                  placeholder="内容（可选）"
                  value={form.content}
                  onChange={e => setForm({ ...form, content: e.target.value })}
                  rows={4}
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800 outline-none resize-none focus:border-blue-300 focus:ring-2 focus:ring-blue-100"
                />
                <input
                  type="number"
                  placeholder="时长（分钟）"
                  value={form.duration_minutes ?? ''}
                  onChange={e => setForm({ ...form, duration_minutes: Number(e.target.value) })}
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800 outline-none focus:border-blue-300 focus:ring-2 focus:ring-blue-100"
                />
                <button
                  onClick={addEntry}
                  className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-slate-100 py-2 text-sm text-slate-700 hover:bg-slate-200"
                >
                  <Plus className="w-4 h-4" />
                  添加到待提交列表
                </button>
              </div>

              {entries.length > 0 && (
                <div className="mt-5">
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-sm font-medium text-slate-800">待提交记录</p>
                    <span className="text-xs text-slate-400">{entries.length} 条</span>
                  </div>
                  <div className="space-y-2">
                    {entries.map((entry, index) => (
                      <div key={`${entry.timestamp}-${index}`} className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2.5">
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="truncate text-sm font-medium text-slate-800">{entry.title}</p>
                            <p className="mt-1 text-xs text-slate-400">{entry.timestamp.replace('T', ' ')}</p>
                            {entry.content && <p className="mt-1 line-clamp-2 text-xs text-slate-500">{entry.content}</p>}
                          </div>
                          <button onClick={() => setEntries(entries.filter((_, itemIndex) => itemIndex !== index))} className="shrink-0 text-slate-300 hover:text-red-500">
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="flex items-center gap-2 border-t border-slate-100 px-5 py-4">
              <button
                onClick={() => setIsManualOpen(false)}
                className="flex-1 rounded-lg border border-slate-200 py-2.5 text-sm text-slate-600 hover:bg-slate-50"
              >
                先收起
              </button>
              <button
                onClick={submitManual}
                disabled={manualMut.isPending || entries.length === 0}
                className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-violet-600 py-2.5 text-sm text-white hover:bg-violet-700 disabled:opacity-50"
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
