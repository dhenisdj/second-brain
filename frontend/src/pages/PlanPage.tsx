import { useEffect, useState } from 'react'
import axios from 'axios'
import { ListTodo, Sparkles, Loader2, Lightbulb, Zap, BookOpen, Heart, Target, Save, Trash2, Plus } from 'lucide-react'
import toast from 'react-hot-toast'
import { useJob, usePlan, useStartPlanGeneration, useUpdatePlan } from '../hooks/queries'
import type { Plan, PlanItem } from '../types'
import { getRelativeDateInputValue } from '../utils/date'

const PRIORITY_STYLES: Record<string, string> = {
  high: 'bg-red-50 text-red-700 border-red-200',
  medium: 'bg-amber-50 text-amber-700 border-amber-200',
  low: 'bg-slate-50 text-slate-600 border-slate-200',
}
const PRIORITY_LABELS: Record<string, string> = { high: '高', medium: '中', low: '低' }
const STATUS_LABELS: Record<string, string> = { todo: '待办', done: '完成', carried_over: '顺延' }
const STATUS_STYLES: Record<string, string> = {
  todo: 'bg-slate-50 text-slate-600 border-slate-200',
  done: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  carried_over: 'bg-amber-50 text-amber-700 border-amber-200',
}
const SUGGESTION_ICONS: Record<string, React.ReactNode> = {
  attention: <Zap className="w-4 h-4 text-amber-500" />,
  review: <BookOpen className="w-4 h-4 text-violet-500" />,
  health: <Heart className="w-4 h-4 text-rose-500" />,
  goal: <Target className="w-4 h-4 text-blue-500" />,
}

const createBlankPlanItem = (): PlanItem => ({
  title: '',
  priority: 'medium',
  reason: '',
  status: 'todo',
  estimated_minutes: null,
  scheduled_slot: null,
})

export default function PlanPage() {
  const [date, setDate] = useState(getRelativeDateInputValue(-1))
  const [plan, setPlan] = useState<Plan | null>(null)
  const [editItems, setEditItems] = useState<PlanItem[]>([])
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobDate, setJobDate] = useState<string | null>(null)
  const { data: savedPlan, isLoading: planLoading, refetch } = usePlan(date)
  const generateMut = useStartPlanGeneration()
  const updateMut = useUpdatePlan()
  const { data: planJob } = useJob(jobId, !!jobId)

  useEffect(() => {
    setPlan(savedPlan ?? null)
    setEditItems(savedPlan?.items ? [...savedPlan.items] : [])
  }, [savedPlan, date])

  useEffect(() => {
    if (!jobId || !planJob) return

    if (planJob.status === 'completed') {
      if (jobDate === date) refetch()
      setJobId(null)
      setJobDate(null)
      toast.success('计划生成完成')
      return
    }

    if (planJob.status === 'failed') {
      setJobId(null)
      setJobDate(null)
      toast.error(planJob.error || '计划生成失败')
    }
  }, [date, jobDate, jobId, planJob, refetch])

  const handleGenerate = async () => {
    try {
      const job = await generateMut.mutateAsync(date)
      setJobId(job.id)
      setJobDate(date)
      if (job.status === 'pending' || job.status === 'running') {
        toast.success('计划已进入后台生成')
      } else if (job.status === 'completed') {
        setJobId(null)
        setJobDate(null)
        refetch()
        toast.success('计划生成完成')
      }
    } catch (error) {
      const message = axios.isAxiosError(error)
        ? (error.response?.data?.detail || '请先生成该日期的总结')
        : '请先生成该日期的总结'
      toast.error(message)
    }
  }

  const handleSave = () => {
    if (!plan) return
    const itemsToSave = editItems.map(item => ({
      ...item,
      title: item.title.trim(),
      reason: item.reason.trim(),
    }))
    if (itemsToSave.some(item => !item.title)) {
      toast.error('请先填写计划事项')
      return
    }
    updateMut.mutate({ date, planId: plan.id, items: itemsToSave }, {
      onSuccess: d => { setPlan(d); toast.success('计划已保存') },
      onError: () => toast.error('保存失败'),
    })
  }

  const removeItem = (idx: number) => setEditItems(editItems.filter((_, i) => i !== idx))

  const addItem = () => setEditItems([...editItems, createBlankPlanItem()])

  const updateItem = <K extends keyof PlanItem>(idx: number, field: K, value: PlanItem[K]) => {
    const next = [...editItems]
    next[idx] = { ...next[idx], [field]: value }
    setEditItems(next)
  }

  return (
    <div className="min-w-0 max-w-full space-y-4 overflow-hidden">
      <section className="rounded-lg border border-slate-200 bg-white px-4 py-4 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-950 text-white">
              <ListTodo className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-xl font-semibold text-slate-950">规划下</h1>
              <p className="mt-1 text-sm text-slate-500">基于前一天总结生成和维护下一天计划</p>
            </div>
          </div>
          <div className="flex w-full min-w-0 flex-wrap items-center gap-3 lg:w-auto">
            <span className="text-sm text-slate-500">总结日期</span>
            <input type="date" value={date} onChange={e => setDate(e.target.value)}
              className="h-9 min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-300 focus:ring-2 focus:ring-blue-100 sm:flex-none" />
            <span className="text-sm text-slate-500">生成次日计划</span>
            <button onClick={handleGenerate} disabled={generateMut.isPending || !!jobId}
              className="inline-flex h-9 w-full items-center justify-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3.5 text-sm font-medium text-slate-600 transition-colors hover:border-slate-300 hover:bg-slate-50 disabled:opacity-50 sm:w-auto">
              {generateMut.isPending || jobId ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
              {jobId ? '计划生成中...' : '手动生成计划'}
            </button>
          </div>
        </div>
      </section>

      {planLoading ? (
        <div className="flex justify-center py-20"><Loader2 className="w-5 h-5 animate-spin text-slate-400" /></div>
      ) : !plan ? (
        <div className="rounded-lg border border-slate-200 bg-white py-20 text-center shadow-sm">
          <ListTodo className="w-12 h-12 text-slate-300 mx-auto mb-3" />
          <p className="text-slate-500 text-sm">该日期还没有已保存计划</p>
          <p className="text-slate-400 text-xs mt-1">先生成该日期总结，再生成下一天计划</p>
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-5">
          {/* Plan Items */}
          <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm xl:col-span-3">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3">
              <h3 className="font-medium text-sm text-slate-800 flex items-center gap-2">
                <ListTodo className="w-4 h-4 text-blue-500" /> {plan.date} 计划
              </h3>
              <button onClick={handleSave} disabled={updateMut.isPending}
                className="flex w-full items-center justify-center gap-1 rounded-lg bg-blue-600 px-2.5 py-1 text-xs text-white hover:bg-blue-700 disabled:opacity-50 sm:w-auto">
                {updateMut.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
                保存修改
              </button>
            </div>
            <div className="space-y-2">
              {editItems.map((item, idx) => (
                <div key={idx} className="min-w-0 rounded-lg border border-slate-100 p-3 transition-colors hover:border-slate-200">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:gap-3">
                    <div className="flex shrink-0 flex-wrap gap-2">
                      <select value={item.priority} onChange={e => updateItem(idx, 'priority', e.target.value as PlanItem['priority'])}
                        className={`rounded border px-2 py-0.5 text-xs font-medium ${PRIORITY_STYLES[item.priority]}`}>
                        {Object.entries(PRIORITY_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                      </select>
                      <select value={item.status ?? 'todo'} onChange={e => updateItem(idx, 'status', e.target.value as NonNullable<PlanItem['status']>)}
                        className={`rounded border px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[item.status ?? 'todo']}`}>
                        {Object.entries(STATUS_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                      </select>
                    </div>
                    <div className="min-w-0 flex-1">
                      <input value={item.title} onChange={e => updateItem(idx, 'title', e.target.value)}
                        placeholder="计划事项"
                        className="min-w-0 max-w-full truncate bg-transparent text-sm font-medium text-slate-800 outline-none" />
                      <input
                        value={item.reason}
                        onChange={e => updateItem(idx, 'reason', e.target.value)}
                        placeholder="原因/备注"
                        className="mt-0.5 min-w-0 w-full bg-transparent text-xs text-slate-400 outline-none placeholder:text-slate-300"
                      />
                    </div>
                    <button onClick={() => removeItem(idx)} className="mt-0.5 shrink-0 text-slate-300 hover:text-red-500">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  <div className="mt-3 grid gap-2 sm:ml-[92px] sm:flex sm:items-center">
                    <input
                      type="number"
                      min={0}
                      value={item.estimated_minutes ?? ''}
                      onChange={e => updateItem(idx, 'estimated_minutes', e.target.value ? Number(e.target.value) : null)}
                      placeholder="预计分钟"
                      className="w-full rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-700 outline-none focus:border-blue-300 focus:ring-2 focus:ring-blue-100 sm:w-28"
                    />
                    <input
                      value={item.scheduled_slot ?? ''}
                      onChange={e => updateItem(idx, 'scheduled_slot', e.target.value || null)}
                      placeholder="建议时段 09:30-10:30"
                      className="w-full rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-700 outline-none focus:border-blue-300 focus:ring-2 focus:ring-blue-100 sm:flex-1"
                    />
                  </div>
                </div>
              ))}
              <button
                type="button"
                onClick={addItem}
                className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-slate-200 bg-slate-50/70 px-3 py-2 text-sm font-medium text-slate-500 transition-colors hover:border-slate-300 hover:bg-slate-100"
              >
                <Plus className="h-4 w-4" />
                新增计划
              </button>
            </div>
          </div>

          {/* Suggestions */}
          <div className="space-y-3 xl:col-span-2">
            <div className="flex items-center gap-2 mb-1">
              <Lightbulb className="w-4 h-4 text-amber-500" />
              <h3 className="font-medium text-sm text-slate-800">优化建议</h3>
            </div>
            {plan.suggestions.map((sug, idx) => (
              <div key={idx} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                <div className="flex items-center gap-2 mb-2">
                  {SUGGESTION_ICONS[sug.type] || <Lightbulb className="w-4 h-4 text-slate-400" />}
                  <span className="text-xs font-medium uppercase text-slate-500">{sug.type}</span>
                </div>
                <p className="text-sm text-slate-700 leading-relaxed">{sug.content}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
