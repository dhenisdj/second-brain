import { useEffect, useMemo, useState, type ReactNode } from 'react'
import axios from 'axios'
import { useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Clock,
  Lightbulb,
  Loader2,
  Rocket,
  Sparkles,
  Target,
} from 'lucide-react'
import { VerticalTimeline, VerticalTimelineElement } from 'react-vertical-timeline-component'
import toast from 'react-hot-toast'
import { useSummary, useStartSummaryGeneration, useJob } from '../hooks/queries'
import { getTodayDateInputValue } from '../utils/date'
import type { DailySummary, SummaryKnowledgeItem, SummaryProgressGroup, SummaryTimelineItem } from '../types'

const COLORS: Record<string, string> = {
  work: '#2563eb',
  study: '#7c3aed',
  life: '#059669',
  entertainment: '#d97706',
}

const LABELS: Record<string, string> = {
  work: '工作',
  study: '学习',
  life: '生活',
  entertainment: '娱乐',
}

const DISTRIBUTION_ORDER = ['work', 'study', 'life', 'entertainment']

const TIMELINE_TONES = [
  { background: 'linear-gradient(135deg, #38bdf8 0%, #2563eb 100%)', shadow: 'rgba(37, 99, 235, 0.16)' },
  { background: 'linear-gradient(135deg, #2dd4bf 0%, #0d9488 100%)', shadow: 'rgba(13, 148, 136, 0.16)' },
  { background: 'linear-gradient(135deg, #22c55e 0%, #16a34a 100%)', shadow: 'rgba(22, 163, 74, 0.16)' },
  { background: 'linear-gradient(135deg, #facc15 0%, #f97316 100%)', shadow: 'rgba(249, 115, 22, 0.18)' },
  { background: 'linear-gradient(135deg, #fb7185 0%, #e11d48 100%)', shadow: 'rgba(225, 29, 72, 0.16)' },
  { background: 'linear-gradient(135deg, #a78bfa 0%, #6d28d9 100%)', shadow: 'rgba(109, 40, 217, 0.16)' },
  { background: 'linear-gradient(135deg, #64748b 0%, #1e293b 100%)', shadow: 'rgba(30, 41, 59, 0.14)' },
]

export default function SummaryPage() {
  const initialDate = new URLSearchParams(window.location.search).get('date') || getTodayDateInputValue()
  const [date, setDate] = useState(initialDate)
  const { data: summary, isLoading, error, refetch } = useSummary(date)
  const summaryMut = useStartSummaryGeneration()
  const qc = useQueryClient()
  const [step, setStep] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobDate, setJobDate] = useState<string | null>(null)
  const { data: jobStatus } = useJob(jobId, !!jobId)

  useEffect(() => {
    if (!jobId || !jobStatus) return

    if (jobStatus.status === 'completed') {
      if (jobDate === date) refetch()
      qc.invalidateQueries({ queryKey: ['events'] })
      qc.invalidateQueries({ queryKey: ['graph'] })
      setJobId(null)
      setJobDate(null)
      setStep(null)
      toast.success('总结生成完成')
      return
    }

    if (jobStatus.status === 'failed') {
      setJobId(null)
      setJobDate(null)
      setStep(null)
      toast.error(jobStatus.error || '总结生成失败')
    }
  }, [date, jobDate, jobId, jobStatus, qc, refetch])

  const handleGenerate = async () => {
    try {
      setStep('正在创建后台任务...')
      const job = await summaryMut.mutateAsync(date)
      setJobId(job.id)
      setJobDate(date)
      setStep('后台分析与总结中...')
      if (job.status === 'pending' || job.status === 'running') {
        toast.success('已开始后台分析与总结，完成后会自动刷新')
      } else if (job.status === 'completed') {
        setJobId(null)
        setJobDate(null)
        setStep(null)
        qc.invalidateQueries({ queryKey: ['graph'] })
        refetch()
        toast.success('总结生成完成')
      }
    } catch (error) {
      setJobId(null)
      setJobDate(null)
      setStep(null)
      const message = axios.isAxiosError(error)
        ? (error.response?.data?.detail || '生成失败，请确认该日期有数据且 LLM 已配置')
        : '生成失败，请确认该日期有数据且 LLM 已配置'
      toast.error(message)
    }
  }

  const timelineItems = useMemo(() => buildTimelineItems(summary), [summary])
  const progressGroups = useMemo(() => buildProgressGroups(summary), [summary])
  const knowledgeItems = useMemo(() => buildKnowledgeItems(summary), [summary])
  const distributionItems = useMemo(() => buildDistributionItems(summary), [summary])
  const isWorking = summaryMut.isPending || !!jobDate

  return (
    <div className="min-w-0 max-w-[calc(100vw-80px)] space-y-4 overflow-hidden sm:max-w-full">
      <section className="min-w-0 max-w-full overflow-hidden rounded-lg border border-slate-200 bg-white px-3 py-4 shadow-sm sm:px-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-950 text-white">
              <BarChart3 className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-xl font-semibold text-slate-950">总结下</h1>
              <p className="mt-1 text-sm text-slate-500">按时间、项目、知识和时间投入整理当天记录</p>
            </div>
          </div>
          <div className="flex min-w-0 flex-wrap items-center gap-3">
            <input
              type="date"
              value={date}
              onChange={e => {
                const nextDate = e.target.value
                setDate(nextDate)
                const nextUrl = new URL(window.location.href)
                nextUrl.searchParams.set('date', nextDate)
                window.history.replaceState(null, '', nextUrl)
              }}
              className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-300 focus:ring-2 focus:ring-blue-100"
            />
            <button
              onClick={handleGenerate}
              disabled={isWorking}
              className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3.5 text-sm font-medium text-slate-600 transition-colors hover:border-slate-300 hover:bg-slate-50 disabled:opacity-50"
            >
              {isWorking ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
              {step ?? '手动刷新总结'}
            </button>
          </div>
        </div>
      </section>

      {isLoading ? (
        <div className="flex justify-center py-20"><Loader2 className="h-6 w-6 animate-spin text-slate-400" /></div>
      ) : error || !summary ? (
        <div className="rounded-lg border border-slate-200 bg-white py-20 text-center shadow-sm">
          <BarChart3 className="mx-auto mb-3 h-12 w-12 text-slate-300" />
          <p className="text-sm text-slate-500">该日期暂无总结</p>
          <p className="mt-1 text-xs text-slate-400">
            {jobDate === date ? '总结正在后台生成，完成后会自动刷新' : '自动任务会生成总结，必要时可手动刷新'}
          </p>
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
          <div className="min-w-0 space-y-4">
            <TimelinePanel items={timelineItems} />
            <ProgressPanel groups={progressGroups} />
            <KnowledgePanel items={knowledgeItems} />
          </div>

          <aside className="space-y-4 xl:sticky xl:top-6 xl:self-start">
            <DistributionPanel items={distributionItems} />
            <CompactSummaryCard
              timelineCount={timelineItems.length}
              progressCount={progressGroups.length}
              knowledgeCount={knowledgeItems.length}
            />
          </aside>
        </div>
      )}
    </div>
  )
}

function TimelinePanel({ items }: { items: SummaryTimelineItem[] }) {
  return (
    <SectionShell
      icon={<Clock className="h-4 w-4 text-blue-600" />}
      title="工作日程"
      subtitle="按当天时间顺序排列，左侧时间点对应右侧事项"
    >
      {items.length === 0 ? (
        <EmptyState text="没有可展示的时间线" />
      ) : (
        <VerticalTimeline
          animate={false}
          className="summary-timeline"
          layout="1-column-left"
          lineColor="#dbeafe"
        >
          {items.map((item, index) => {
            const tone = getTimelineTone(index, items.length)
            return (
              <VerticalTimelineElement
                key={`${item.time}-${index}`}
                date={item.time || '--:--'}
                dateClassName="summary-timeline-date"
                icon={<span className="summary-timeline-dot-core" />}
                iconStyle={{
                  background: tone.background,
                  boxShadow: `0 0 0 3px #fff, 0 8px 16px ${tone.shadow}`,
                }}
                contentStyle={{
                  background: '#fff',
                  border: '1px solid #e2e8f0',
                  borderRadius: 8,
                  boxShadow: '0 10px 24px rgba(15, 23, 42, 0.05)',
                }}
                contentArrowStyle={{ borderRight: '7px solid #fff' }}
                visible
              >
                <p className="summary-timeline-copy">{formatTimelineCopy(item)}</p>
                {item.items && item.items.length > 0 && (
                  <ul className="summary-timeline-details">
                    {item.items.map((detail, detailIndex) => (
                      <li key={detailIndex}>{detail}</li>
                    ))}
                  </ul>
                )}
              </VerticalTimelineElement>
            )
          })}
        </VerticalTimeline>
      )}
    </SectionShell>
  )
}

function ProgressPanel({ groups }: { groups: SummaryProgressGroup[] }) {
  return (
    <SectionShell
      icon={<Rocket className="h-4 w-4 text-emerald-600" />}
      title="事项进展"
      subtitle="按项目聚合，再拆分为进展、问题、风险和下一步"
    >
      {groups.length === 0 ? (
        <EmptyState text="没有可展示的事项进展" />
      ) : (
        <div className="space-y-3">
          {groups.map((group, index) => {
            const buckets = [
              { icon: <CheckCircle2 className="h-3.5 w-3.5" />, label: '进展', tone: 'emerald' as const, items: group.progress },
              { icon: <AlertTriangle className="h-3.5 w-3.5" />, label: '问题', tone: 'amber' as const, items: group.issues },
              { icon: <AlertTriangle className="h-3.5 w-3.5" />, label: '风险', tone: 'rose' as const, items: group.risks },
              { icon: <Target className="h-3.5 w-3.5" />, label: '下一步', tone: 'blue' as const, items: group.next_steps },
            ].filter(bucket => bucket.items?.filter(Boolean).length)

            return (
              <article key={`${group.project}-${index}`} className="min-w-0 w-[calc(100vw-112px)] rounded-lg border border-slate-200 bg-white p-4 shadow-sm sm:w-auto">
                <div className="mb-3 flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />
                  <h3 className="break-words text-sm font-semibold text-slate-950 [overflow-wrap:anywhere]">{group.project || '未命名项目'}</h3>
                </div>
                <div className={`grid gap-3 ${buckets.length > 1 ? 'md:grid-cols-2' : ''}`}>
                  {buckets.map(bucket => (
                    <ProgressBucket
                      key={bucket.label}
                      icon={bucket.icon}
                      label={bucket.label}
                      tone={bucket.tone}
                      items={bucket.items}
                    />
                  ))}
                </div>
              </article>
            )
          })}
        </div>
      )}
    </SectionShell>
  )
}

function KnowledgePanel({ items }: { items: SummaryKnowledgeItem[] }) {
  return (
    <SectionShell
      icon={<Lightbulb className="h-4 w-4 text-amber-600" />}
      title="知识沉淀"
      subtitle="按概念或工具聚合，保留关键 takeaway 和证据来源"
    >
      {items.length === 0 ? (
        <EmptyState text="没有可展示的新知识" />
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {items.map((item, index) => (
            <article key={`${item.topic}-${index}`} className="min-w-0 w-[calc(100vw-112px)] rounded-lg border border-slate-200 bg-white p-4 shadow-sm sm:w-auto">
              <h3 className="break-words text-sm font-semibold text-slate-950 [overflow-wrap:anywhere]">{item.topic || '未命名知识点'}</h3>
              {item.summary && <p className="mt-2 break-words text-sm leading-6 text-slate-600 [overflow-wrap:anywhere]">{item.summary}</p>}
              {item.takeaways && item.takeaways.length > 0 && (
                <ul className="mt-3 space-y-2">
                  {item.takeaways.map((takeaway, takeawayIndex) => (
                    <li key={takeawayIndex} className="flex gap-2 break-words text-sm leading-6 text-slate-600 [overflow-wrap:anywhere]">
                      <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" />
                      <span>{takeaway}</span>
                    </li>
                  ))}
                </ul>
              )}
              {item.evidence && (
                <p className="mt-3 break-words rounded-md bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-700 [overflow-wrap:anywhere]">证据：{item.evidence}</p>
              )}
            </article>
          ))}
        </div>
      )}
    </SectionShell>
  )
}

function DistributionPanel({ items }: { items: Array<{ key: string; label: string; value: number; color: string }> }) {
  return (
    <SectionShell icon={<BarChart3 className="h-4 w-4 text-violet-600" />} title="时间分布">
      {items.length === 0 ? (
        <EmptyState text="没有时间分布数据" />
      ) : (
        <div className="space-y-4">
          <div className="flex h-3 overflow-hidden rounded-full bg-slate-100">
            {items.map(item => (
              <span key={item.key} style={{ width: `${item.value}%`, backgroundColor: item.color }} />
            ))}
          </div>
          <div className="space-y-3">
            {items.map(item => (
              <div key={item.key}>
                <div className="mb-1.5 flex items-center justify-between gap-3 text-sm">
                  <span className="inline-flex items-center gap-2 font-medium text-slate-700">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: item.color }} />
                    {item.label}
                  </span>
                  <span className="font-semibold tabular-nums text-slate-900">{item.value}%</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                  <div className="h-full rounded-full" style={{ width: `${item.value}%`, backgroundColor: item.color }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </SectionShell>
  )
}

function CompactSummaryCard({
  timelineCount,
  progressCount,
  knowledgeCount,
}: {
  timelineCount: number
  progressCount: number
  knowledgeCount: number
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-sm font-semibold text-slate-800">结构概览</p>
      <div className="mt-3 grid grid-cols-3 gap-2">
        <MiniStat label="时间点" value={timelineCount} />
        <MiniStat label="项目" value={progressCount} />
        <MiniStat label="知识" value={knowledgeCount} />
      </div>
    </div>
  )
}

function SectionShell({
  icon,
  title,
  subtitle,
  children,
}: {
  icon: ReactNode
  title: string
  subtitle?: string
  children: ReactNode
}) {
  return (
    <section className="min-w-0 overflow-hidden rounded-lg border border-slate-200 bg-white p-3 shadow-sm sm:p-4">
      <div className="mb-4 flex items-start gap-3 border-b border-slate-100 pb-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-50">{icon}</div>
        <div>
          <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
          {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
        </div>
      </div>
      {children}
    </section>
  )
}

function ProgressBucket({
  icon,
  label,
  tone,
  items,
}: {
  icon: ReactNode
  label: string
  tone: 'emerald' | 'amber' | 'rose' | 'blue'
  items?: string[]
}) {
  const colors = {
    emerald: 'border-emerald-100 bg-emerald-50 text-emerald-700',
    amber: 'border-amber-100 bg-amber-50 text-amber-700',
    rose: 'border-rose-100 bg-rose-50 text-rose-700',
    blue: 'border-blue-100 bg-blue-50 text-blue-700',
  }
  const safeItems = items?.filter(Boolean) ?? []

  return (
    <div className="min-w-0 max-w-full overflow-hidden rounded-lg border border-slate-100 bg-slate-50/50 p-3">
      <div className={`mb-2 inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium ${colors[tone]}`}>
        {icon}
        {label}
      </div>
      <ul className="space-y-1.5 border-l border-slate-200 pl-3">
        {safeItems.map((item, index) => (
            <li key={index} className="break-words text-xs leading-5 text-slate-600 [overflow-wrap:anywhere]">{item}</li>
        ))}
      </ul>
    </div>
  )
}

function MiniStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2">
      <p className="text-[11px] text-slate-400">{label}</p>
      <p className="mt-1 text-base font-semibold text-slate-900">{value}</p>
    </div>
  )
}

function EmptyState({ text }: { text: string }) {
  return <div className="rounded-lg bg-slate-50 px-4 py-6 text-center text-sm text-slate-400">{text}</div>
}

function buildTimelineItems(summary?: DailySummary): SummaryTimelineItem[] {
  if (!summary) return []
  if (summary.timeline && summary.timeline.length > 0) return summary.timeline.filter(item => item && (item.time || item.title))
  return parseTimelineMarkdown(summary.timeline_md)
}

function buildProgressGroups(summary?: DailySummary): SummaryProgressGroup[] {
  if (!summary) return []
  if (summary.progress && summary.progress.length > 0) return summary.progress.filter(item => item && item.project)
  return parseProgressMarkdown(summary.progress_md)
}

function buildKnowledgeItems(summary?: DailySummary): SummaryKnowledgeItem[] {
  if (!summary) return []
  if (summary.knowledge && summary.knowledge.length > 0) return summary.knowledge.filter(item => item && item.topic)
  return parseKnowledgeMarkdown(summary.knowledge_md)
}

function buildDistributionItems(summary?: DailySummary) {
  const distribution = summary?.time_distribution ?? {}
  return Object.entries(distribution)
    .filter(([, value]) => Number(value) > 0)
    .sort(([left], [right]) => {
      const leftIndex = DISTRIBUTION_ORDER.indexOf(left)
      const rightIndex = DISTRIBUTION_ORDER.indexOf(right)
      return (leftIndex === -1 ? 99 : leftIndex) - (rightIndex === -1 ? 99 : rightIndex)
    })
    .map(([key, value]) => ({
      key,
      label: LABELS[key] ?? key,
      value: Number(value),
      color: COLORS[key] ?? '#64748b',
    }))
}

function getTimelineTone(index: number, total: number) {
  if (total <= 1) return TIMELINE_TONES[0]
  const toneIndex = Math.round((index / (total - 1)) * (TIMELINE_TONES.length - 1))
  return TIMELINE_TONES[toneIndex] ?? TIMELINE_TONES[0]
}

function formatTimelineCopy(item: SummaryTimelineItem) {
  const title = cleanText(item.title || '')
  const summary = cleanText(item.summary || '')
  if (title && summary) return `${title}：${summary}`
  return title || summary || '未命名事项'
}

function stripSectionHeadings(markdown: string, titles: string[]) {
  const titleSet = new Set(titles)
  return (markdown || '')
    .split('\n')
    .filter(line => {
      const match = line.trim().match(/^#{1,3}\s+(.+)$/)
      return !match || !titleSet.has(cleanText(match[1]))
    })
    .join('\n')
}

function cleanText(value: string) {
  return value
    .replace(/^[-*]\s+/, '')
    .replace(/^#+\s*/, '')
    .replace(/\*\*/g, '')
    .replace(/`/g, '')
    .replace(/^[|｜]\s*/, '')
    .trim()
}

function splitTitleSummary(value: string) {
  const [title, ...rest] = value.split(/[：:]/)
  return {
    title: cleanText(title || value),
    summary: cleanText(rest.join('：')),
  }
}

function normalizeTimeLabel(value: string) {
  return value.replace(/\s*(?:-|~|–|—)\s*/g, '-').trim()
}

function isGenericProgressHeading(title: string) {
  return /^(事项|重点工作|其他事项|工作事项|项目进展|进展汇总|今日进展)$/i.test(title)
}

function getOrCreateProgressGroup(groups: SummaryProgressGroup[], project: string) {
  const normalizedProject = cleanText(project) || '事项'
  const existing = groups.find(group => group.project === normalizedProject)
  if (existing) return existing

  const group: SummaryProgressGroup = {
    project: normalizedProject,
    progress: [],
    issues: [],
    risks: [],
    next_steps: [],
  }
  groups.push(group)
  return group
}

function parseTimelineMarkdown(markdown: string): SummaryTimelineItem[] {
  const lines = stripSectionHeadings(markdown, ['时间线', 'Timeline'])
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)

  const items = lines.flatMap(line => {
    const cleaned = cleanText(line)
    const match = cleaned.match(/^(\d{1,2}:\d{2}(?:\s*(?:-|~|–|—)\s*\d{1,2}:\d{2})?)\s*(?:[|｜:：，,、-]\s*)?(.+)$/)
    if (!match) return []
    const parsed = splitTitleSummary(match[2])
    return [{
      time: normalizeTimeLabel(match[1]),
      title: parsed.title,
      summary: parsed.summary,
    }]
  })

  if (items.length > 0) return items
  const fallback = lines.map(cleanText).filter(Boolean).slice(0, 6)
  return fallback.map((line, index) => ({ time: `${index + 1}`, title: line }))
}

function parseProgressMarkdown(markdown: string): SummaryProgressGroup[] {
  const lines = stripSectionHeadings(markdown, ['事项进展', '进展', 'Progress'])
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)

  const groups: SummaryProgressGroup[] = []
  let current: SummaryProgressGroup | null = null
  let bucket: keyof Pick<SummaryProgressGroup, 'progress' | 'issues' | 'risks' | 'next_steps'> = 'progress'

  const ensureCurrent = () => {
    if (!current) {
      current = getOrCreateProgressGroup(groups, '事项')
    }
    return current
  }

  for (const line of lines) {
    const heading = line.match(/^#{2,5}\s+(.+)$/)
    if (heading) {
      const title = cleanText(heading[1])
      if (/问题|阻塞|困难/.test(title)) bucket = 'issues'
      else if (/风险|隐患/.test(title)) bucket = 'risks'
      else if (/下一步|后续|计划|待办/.test(title)) bucket = 'next_steps'
      else if (/进展|完成|推进/.test(title)) bucket = 'progress'
      else {
        current = getOrCreateProgressGroup(groups, title)
        bucket = 'progress'
      }
      continue
    }

    const item = cleanText(line)
    if (!item) continue

    if (!current || isGenericProgressHeading(current.project)) {
      const parsed = splitTitleSummary(item)
      if (parsed.summary && parsed.title.length <= 80) {
        getOrCreateProgressGroup(groups, parsed.title).progress?.push(parsed.summary)
        continue
      }
    }

    ensureCurrent()[bucket]?.push(item)
  }

  return groups.filter(group =>
    group.progress?.length ||
    group.issues?.length ||
    group.risks?.length ||
    group.next_steps?.length,
  )
}

function parseKnowledgeMarkdown(markdown: string): SummaryKnowledgeItem[] {
  const lines = stripSectionHeadings(markdown, ['新知识', '知识', 'Knowledge'])
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)

  const items: SummaryKnowledgeItem[] = []
  let current: SummaryKnowledgeItem | null = null

  for (const line of lines) {
    const heading = line.match(/^#{2,5}\s+(.+)$/)
    if (heading) {
      current = { topic: cleanText(heading[1]), takeaways: [] }
      items.push(current)
      continue
    }

    const cleaned = cleanText(line)
    if (!cleaned) continue
    if (!current) {
      const parsed = splitTitleSummary(cleaned)
      current = { topic: parsed.title, summary: parsed.summary, takeaways: [] }
      items.push(current)
      continue
    }
    current.takeaways = [...(current.takeaways ?? []), cleaned]
  }

  return items
}
