import { useEffect, useState } from 'react'
import axios from 'axios'
import { useQueryClient } from '@tanstack/react-query'
import { BarChart3, Clock, Lightbulb, Rocket, Loader2, Sparkles } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts'
import toast from 'react-hot-toast'
import { useSummary, useStartSummaryGeneration, useJob } from '../hooks/queries'
import { getTodayDateInputValue } from '../utils/date'

const COLORS: Record<string, string> = { work: '#3b82f6', study: '#8b5cf6', life: '#10b981', entertainment: '#f59e0b' }
const LABELS: Record<string, string> = { work: '工作', study: '学习', life: '生活', entertainment: '娱乐' }

export default function SummaryPage() {
  const [date, setDate] = useState(getTodayDateInputValue())
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

  const pieData = summary?.time_distribution
    ? Object.entries(summary.time_distribution).map(([key, value]) => ({ name: LABELS[key] ?? key, value, color: COLORS[key] ?? '#94a3b8' }))
    : []

  const isWorking = summaryMut.isPending || !!jobDate

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold text-gray-900">总结下</h1>
        <div className="flex items-center gap-3">
          <input type="date" value={date} onChange={e => setDate(e.target.value)}
            className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm focus:ring-1 focus:ring-blue-500 outline-none" />
          <button onClick={handleGenerate} disabled={isWorking}
            className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1.5">
            {isWorking ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
            {step ?? '一键生成总结'}
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-20"><Loader2 className="w-6 h-6 animate-spin text-gray-400" /></div>
      ) : error || !summary ? (
        <div className="text-center py-20">
          <BarChart3 className="w-12 h-12 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-400 text-sm">该日期暂无总结</p>
          <p className="text-gray-400 text-xs mt-1">
            {jobDate === date ? '总结正在后台生成，完成后会自动刷新' : '请先导入数据，然后点击「一键生成总结」'}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          <Card icon={<Clock className="w-4 h-4 text-blue-500" />} title="时间线">
            <div className="prose prose-sm prose-gray max-w-none">
              <ReactMarkdown>{summary.timeline_md}</ReactMarkdown>
            </div>
          </Card>

          <Card icon={<Rocket className="w-4 h-4 text-emerald-500" />} title="事项进展">
            <div className="prose prose-sm prose-gray max-w-none">
              <ReactMarkdown>{summary.progress_md}</ReactMarkdown>
            </div>
          </Card>

          <Card icon={<Lightbulb className="w-4 h-4 text-amber-500" />} title="新知识">
            <div className="prose prose-sm prose-gray max-w-none">
              <ReactMarkdown>{summary.knowledge_md}</ReactMarkdown>
            </div>
          </Card>

          <Card icon={<BarChart3 className="w-4 h-4 text-violet-500" />} title="时间分布">
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie data={pieData} cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={3} dataKey="value"
                  label={({ name, value }) => `${name} ${value}%`} labelLine={false}>
                  {pieData.map((d, i) => <Cell key={i} fill={d.color} />)}
                </Pie>
                <Tooltip formatter={(v: number) => `${v}%`} />
              </PieChart>
            </ResponsiveContainer>
          </Card>
        </div>
      )}
    </div>
  )
}

function Card({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 min-h-[200px]">
      <div className="flex items-center gap-2 mb-3 pb-2 border-b border-gray-100">
        {icon}
        <h3 className="font-medium text-sm text-gray-700">{title}</h3>
      </div>
      {children}
    </div>
  )
}
