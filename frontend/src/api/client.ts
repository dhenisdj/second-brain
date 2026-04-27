import axios from 'axios'
import type {
  IngestResponse, CollectSourcesResponse, EventsResponse, AnalysisResponse,
  DailySummary, SummaryJobStatus, GraphData, NodeDetail, Plan, PlanItem,
  AppJob,
  DayOverview, AppSettings, ManualEntry, SettingsUpdatePayload,
} from '../types'

const api = axios.create({ baseURL: '/api' })

export const ingestBrowserLocal = (days = 2) =>
  api.post<IngestResponse>('/ingest/browser-local', { days }).then(r => r.data)

export const ingestChrome = (file: File) => {
  const form = new FormData()
  form.append('file', file)
  return api.post<IngestResponse>('/ingest/chrome', form).then(r => r.data)
}

export const ingestGCal = (days = 2) =>
  api.post<IngestResponse>('/ingest/gcal', { days }).then(r => r.data)

export const collectConfiguredSources = (days = 2) =>
  api.post<CollectSourcesResponse>('/ingest/collect', { days }).then(r => r.data)

export const ingestManual = (entries: ManualEntry[]) =>
  api.post<IngestResponse>('/ingest/manual', { entries }).then(r => r.data)

export const getEvents = (
  date: string,
  page = 1,
  size = 50,
  source?: string,
  options?: { aggregateBrowser?: boolean },
) =>
  api.get<EventsResponse>('/events', {
    params: {
      date,
      page,
      size,
      source: source || undefined,
      aggregate_browser: options?.aggregateBrowser ?? true,
    },
  }).then(r => r.data)

export const runAnalysis = (date: string) =>
  api.post<AnalysisResponse>('/analysis/run', { date }).then(r => r.data)

export const generateSummary = (date: string) =>
  api.post<DailySummary>('/summary/generate', { date }).then(r => r.data)

export const startSummaryGeneration = (date: string) =>
  api.post<SummaryJobStatus>('/summary/generate-async', { date }).then(r => r.data)

export const getSummary = (date: string) =>
  api.get<DailySummary>(`/summary/${date}`).then(r => r.data)

export const getSummaryGenerationStatus = (date: string) =>
  api.get<SummaryJobStatus>(`/summary/status/${date}`).then(r => r.data)

export const getJob = (jobId: string) =>
  api.get<AppJob>(`/jobs/${jobId}`).then(r => r.data)

export const getJobs = (limit = 10) =>
  api.get<{ items: AppJob[] }>('/jobs', { params: { limit } }).then(r => r.data)

export const getGraph = (limit = 100) =>
  api.get<GraphData>('/knowledge/graph', { params: { limit } }).then(r => r.data)

export const getNodeDetail = (nodeId: string) =>
  api.get<NodeDetail>(`/knowledge/node/${nodeId}`).then(r => r.data)

export const startGraphRebuild = () =>
  api.post<AppJob>('/knowledge/rebuild-async').then(r => r.data)

export const generatePlan = (date: string) =>
  api.post<Plan>('/plan/generate', { date }).then(r => r.data)

export const startPlanGeneration = (date: string) =>
  api.post<AppJob>('/plan/generate-async', { date }).then(r => r.data)

export const getPlanBySummary = async (date: string) => {
  try {
    const resp = await api.get<Plan>(`/plan/by-summary/${date}`)
    return resp.data
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 404) {
      return null
    }
    throw error
  }
}

export const updatePlan = (planId: string, items: PlanItem[]) =>
  api.put<Plan>(`/plan/${planId}`, { items }).then(r => r.data)

export const getDataOverview = (start: string, end: string) =>
  api.get<{ days: DayOverview[] }>('/data/overview', { params: { start, end } }).then(r => r.data)

export const deleteEvent = (eventId: string) =>
  api.delete(`/data/events/${eventId}`).then(r => r.data)

export const deleteDay = (date: string) =>
  api.delete<{ deleted: Record<string, number> }>(`/data/day/${date}`).then(r => r.data)

export const getSettings = () =>
  api.get<AppSettings>('/settings').then(r => r.data)

export const updateSettings = (settings: SettingsUpdatePayload) =>
  api.put<AppSettings>('/settings', settings).then(r => r.data)

export const uploadGoogleCredentials = (file: File) => {
  const form = new FormData()
  form.append('file', file)
  return api.post<{ google_credentials_configured: boolean; client_id: string }>('/settings/google-credentials', form).then(r => r.data)
}

export const startGoogleCalendarAuthorization = () =>
  api.post<{ authorization_url: string }>('/settings/google-calendar/authorize').then(r => r.data)
