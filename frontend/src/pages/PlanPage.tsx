import { useEffect, useState } from 'react'
import axios from 'axios'
import { ListTodo, Sparkles, Loader2, Lightbulb, Zap, BookOpen, Heart, Target, Save, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { useJob, usePlan, useStartPlanGeneration, useUpdatePlan } from '../hooks/queries'
import type { Plan, PlanItem } from '../types'
import { getTodayDateInputValue } from '../utils/date'

const PRIORITY_STYLES: Record<string, string> = {
  high: 'bg-red-50 text-red-700 border-red-200',
  medium: 'bg-amber-50 text-amber-700 border-amber-200',
  low: 'bg-gray-50 text-gray-600 border-gray-200',
}
const PRIORITY_LABELS: Record<string, string> = { high: '高', medium: '中', low: '低' }
const STATUS_LABELS: Record<string, string> = { todo: '待办', done: '完成', carried_over: '顺延' }
const STATUS_STYLES: Record<string, string> = {
  todo: 'bg-gray-50 text-gray-600 border-gray-200',
  done: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  carried_over: 'bg-amber-50 text-amber-700 border-amber-200',
}
const SUGGESTION_ICONS: Record<string, React.ReactNode> = {
  attention: <Zap className="w-4 h-4 text-amber-500" />,
  review: <BookOpen className="w-4 h-4 text-violet-500" />,
  health: <Heart className="w-4 h-4 text-rose-500" />,
  goal: <Target className="w-4 h-4 text-blue-500" />,
}

export default function PlanPage() {
  const [date, setDate] = useState(getTodayDateInputValue())
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
    updateMut.mutate({ date, planId: plan.id, items: editItems }, {
      onSuccess: d => { setPlan(d); toast.success('计划已保存') },
      onError: () => toast.error('保存失败'),
    })
  }

  const removeItem = (idx: number) => setEditItems(editItems.filter((_, i) => i !== idx))

  const updateItem = <K extends keyof PlanItem>(idx: number, field: K, value: PlanItem[K]) => {
    const next = [...editItems]
    next[idx] = { ...next[idx], [field]: value }
    setEditItems(next)
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold text-gray-900">规划下</h1>
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-500">基于</span>
          <input type="date" value={date} onChange={e => setDate(e.target.value)}
            className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm focus:ring-1 focus:ring-blue-500 outline-none" />
          <span className="text-sm text-gray-500">的总结</span>
          <button onClick={handleGenerate} disabled={generateMut.isPending || !!jobId}
            className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1.5">
            {generateMut.isPending || jobId ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
            {jobId ? '计划生成中...' : '生成计划'}
          </button>
        </div>
      </div>

      {planLoading ? (
        <div className="flex justify-center py-20"><Loader2 className="w-5 h-5 animate-spin text-gray-400" /></div>
      ) : !plan ? (
        <div className="text-center py-20">
          <ListTodo className="w-12 h-12 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-400 text-sm">该日期还没有已保存计划</p>
          <p className="text-gray-400 text-xs mt-1">先生成总结，再生成并保存计划</p>
        </div>
      ) : (
        <div className="grid grid-cols-5 gap-4">
          {/* Plan Items */}
          <div className="col-span-3 bg-white rounded-xl border border-gray-200 p-5">
            <div className="flex items-center justify-between mb-4 pb-2 border-b border-gray-100">
              <h3 className="font-medium text-sm text-gray-700 flex items-center gap-2">
                <ListTodo className="w-4 h-4 text-blue-500" /> 明日计划
              </h3>
              <button onClick={handleSave} disabled={updateMut.isPending}
                className="px-2.5 py-1 bg-blue-600 text-white text-xs rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1">
                {updateMut.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
                保存修改
              </button>
            </div>
            <div className="space-y-2">
              {editItems.map((item, idx) => (
                <div key={idx} className="p-3 rounded-lg border border-gray-100 hover:border-gray-200 transition-colors">
                  <div className="flex items-start gap-3">
                    <select value={item.priority} onChange={e => updateItem(idx, 'priority', e.target.value as PlanItem['priority'])}
                      className={`shrink-0 px-2 py-0.5 rounded text-xs border font-medium ${PRIORITY_STYLES[item.priority]}`}>
                      {Object.entries(PRIORITY_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                    </select>
                    <select value={item.status ?? 'todo'} onChange={e => updateItem(idx, 'status', e.target.value as NonNullable<PlanItem['status']>)}
                      className={`shrink-0 px-2 py-0.5 rounded text-xs border font-medium ${STATUS_STYLES[item.status ?? 'todo']}`}>
                      {Object.entries(STATUS_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                    </select>
                    <div className="flex-1 min-w-0">
                      <input value={item.title} onChange={e => updateItem(idx, 'title', e.target.value)}
                        className="w-full text-sm text-gray-800 font-medium outline-none bg-transparent" />
                      <p className="text-xs text-gray-400 mt-0.5">{item.reason}</p>
                    </div>
                    <button onClick={() => removeItem(idx)} className="text-gray-300 hover:text-red-500 shrink-0 mt-0.5">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  <div className="flex items-center gap-2 mt-3 ml-[92px]">
                    <input
                      type="number"
                      min={0}
                      value={item.estimated_minutes ?? ''}
                      onChange={e => updateItem(idx, 'estimated_minutes', e.target.value ? Number(e.target.value) : null)}
                      placeholder="预计分钟"
                      className="w-28 px-2 py-1 border border-gray-200 rounded text-xs outline-none focus:ring-1 focus:ring-blue-500"
                    />
                    <input
                      value={item.scheduled_slot ?? ''}
                      onChange={e => updateItem(idx, 'scheduled_slot', e.target.value || null)}
                      placeholder="建议时段 09:30-10:30"
                      className="flex-1 px-2 py-1 border border-gray-200 rounded text-xs outline-none focus:ring-1 focus:ring-blue-500"
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Suggestions */}
          <div className="col-span-2 space-y-3">
            <div className="flex items-center gap-2 mb-1">
              <Lightbulb className="w-4 h-4 text-amber-500" />
              <h3 className="font-medium text-sm text-gray-700">优化建议</h3>
            </div>
            {plan.suggestions.map((sug, idx) => (
              <div key={idx} className="bg-white rounded-xl border border-gray-200 p-4">
                <div className="flex items-center gap-2 mb-2">
                  {SUGGESTION_ICONS[sug.type] || <Lightbulb className="w-4 h-4 text-gray-400" />}
                  <span className="text-xs font-medium text-gray-500 uppercase">{sug.type}</span>
                </div>
                <p className="text-sm text-gray-700 leading-relaxed">{sug.content}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
