import { useEffect, useRef, useState } from 'react'
import { CheckCircle2, ChevronDown, Clock3, ListTodo, Loader2, Network, Sparkles, TriangleAlert } from 'lucide-react'
import { useRecentJobs } from '../hooks/queries'
import type { AppJob } from '../types'

const STATUS_STYLES: Record<string, string> = {
  idle: 'bg-gray-100 text-gray-500',
  pending: 'bg-amber-50 text-amber-700',
  running: 'bg-blue-50 text-blue-700',
  completed: 'bg-emerald-50 text-emerald-700',
  failed: 'bg-rose-50 text-rose-700',
}

const STATUS_LABELS: Record<string, string> = {
  idle: '空闲',
  pending: '排队中',
  running: '执行中',
  completed: '已完成',
  failed: '失败',
}

function getJobMeta(job: AppJob) {
  const date = typeof job.payload?.date === 'string' ? job.payload.date : null

  switch (job.job_type) {
    case 'summary.generate':
      return { label: date ? `${date} 总结生成` : '总结生成', icon: <Sparkles className="w-4 h-4 text-blue-600" /> }
    case 'plan.generate':
      return { label: date ? `${date} 计划生成` : '计划生成', icon: <ListTodo className="w-4 h-4 text-emerald-600" /> }
    case 'graph.refresh':
      return { label: date ? `${date} 图谱刷新` : '图谱刷新', icon: <Network className="w-4 h-4 text-violet-600" /> }
    case 'graph.rebuild':
      return { label: '全量图谱重建', icon: <Network className="w-4 h-4 text-violet-600" /> }
    default:
      return { label: job.job_type, icon: <Clock3 className="w-4 h-4 text-gray-500" /> }
  }
}

function getStatusIcon(status: string) {
  if (status === 'pending' || status === 'running') {
    return <Loader2 className="w-3.5 h-3.5 animate-spin" />
  }
  if (status === 'completed') {
    return <CheckCircle2 className="w-3.5 h-3.5" />
  }
  if (status === 'failed') {
    return <TriangleAlert className="w-3.5 h-3.5" />
  }
  return <Clock3 className="w-3.5 h-3.5" />
}

export default function RecentJobsPanel() {
  const { data } = useRecentJobs(6)
  const items = data?.items ?? []
  const hasActiveJobs = items.some(job => job.status === 'pending' || job.status === 'running')
  const hasFailedJobs = items.some(job => job.status === 'failed')
  const activeCount = items.filter(job => job.status === 'pending' || job.status === 'running').length
  const [expanded, setExpanded] = useState(false)
  const prevHasActiveJobs = useRef(false)

  useEffect(() => {
    if (items.length === 0) {
      prevHasActiveJobs.current = false
      setExpanded(false)
      return
    }

    if (hasActiveJobs && !prevHasActiveJobs.current) {
      setExpanded(true)
    } else if (!hasActiveJobs && prevHasActiveJobs.current) {
      setExpanded(false)
    }

    prevHasActiveJobs.current = hasActiveJobs
  }, [hasActiveJobs, items.length])

  if (items.length === 0) return null

  const triggerTone = hasActiveJobs
    ? 'border-blue-200 bg-blue-50 text-blue-700'
    : hasFailedJobs
      ? 'border-rose-200 bg-rose-50 text-rose-700'
      : 'border-emerald-200 bg-emerald-50 text-emerald-700'

  const triggerIcon = hasActiveJobs
    ? <Loader2 className="w-4 h-4 animate-spin" />
    : hasFailedJobs
      ? <TriangleAlert className="w-4 h-4" />
      : <CheckCircle2 className="w-4 h-4" />

  if (!expanded) {
    return (
      <button
        onClick={() => setExpanded(true)}
        className={`fixed bottom-6 right-6 z-30 flex items-center gap-3 rounded-full border px-3 py-2 shadow-lg backdrop-blur-sm transition-all hover:shadow-xl ${triggerTone}`}
      >
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-white/80">
          {triggerIcon}
        </span>
        <span className="hidden sm:block text-left">
          <span className="block text-xs font-semibold">后台任务</span>
          <span className="block text-[11px] opacity-80">
            {hasActiveJobs ? `${activeCount} 个任务进行中` : `${items.length} 条最近记录`}
          </span>
        </span>
      </button>
    )
  }

  return (
    <section className="fixed bottom-6 right-6 z-30 w-[380px] max-w-[calc(100vw-2rem)] overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-2xl">
      <div className="flex items-start justify-between gap-3 border-b border-gray-100 px-4 py-3">
        <div>
          <p className="text-sm font-semibold text-gray-900">后台任务</p>
          <p className="text-xs text-gray-500">
            {hasActiveJobs
              ? `${activeCount} 个任务正在执行`
              : hasFailedJobs
                ? '任务已结束，包含失败项'
                : '最近任务已完成，面板已自动缩成图标'}
          </p>
        </div>
        <button
          onClick={() => setExpanded(false)}
          className="rounded-lg p-1.5 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
          aria-label="收起后台任务面板"
        >
          <ChevronDown className="w-4 h-4" />
        </button>
      </div>

      <div className="max-h-[60vh] overflow-y-auto px-3 py-3">
        <div className="space-y-2">
          {items.map(job => {
            const meta = getJobMeta(job)
            return (
              <div key={job.id ?? `${job.job_type}-${job.updated_at}`} className="rounded-xl border border-gray-100 bg-gray-50 px-3 py-2.5">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-start gap-2">
                    <div className="mt-0.5 shrink-0">{meta.icon}</div>
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-gray-800">{meta.label}</p>
                      <p className="text-xs text-gray-500">{job.updated_at ? new Date(job.updated_at).toLocaleString() : '刚刚更新'}</p>
                    </div>
                  </div>
                  <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${STATUS_STYLES[job.status] ?? STATUS_STYLES.idle}`}>
                    {getStatusIcon(job.status)}
                    {STATUS_LABELS[job.status] ?? job.status}
                  </span>
                </div>

                {job.error && <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-rose-600">{job.error}</p>}
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}
