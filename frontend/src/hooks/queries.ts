import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as api from '../api/client'
import type { ManualEntry, PlanItem, AppSettings, SettingsUpdatePayload } from '../types'

export const useEvents = (date: string, source?: string, options?: { aggregateBrowser?: boolean }) =>
  useQuery({
    queryKey: ['events', date, source, options?.aggregateBrowser ?? true],
    queryFn: () => api.getEvents(date, 1, 50, source, options),
    enabled: !!date,
  })

export const useSummary = (date: string) =>
  useQuery({ queryKey: ['summary', date], queryFn: () => api.getSummary(date), enabled: !!date, retry: false })

export const useSummaryGenerationStatus = (date: string | null, enabled = false) =>
  useQuery({
    queryKey: ['summary-status', date],
    queryFn: () => api.getSummaryGenerationStatus(date!),
    enabled: enabled && !!date,
    retry: false,
    refetchInterval: enabled ? 3000 : false,
  })

export const useJob = (jobId: string | null, enabled = false) =>
  useQuery({
    queryKey: ['job', jobId],
    queryFn: () => api.getJob(jobId!),
    enabled: enabled && !!jobId,
    retry: false,
    refetchInterval: query => {
      const status = query.state.data?.status
      return enabled && status && ['pending', 'running'].includes(status) ? 3000 : false
    },
  })

export const useRecentJobs = (limit = 6) =>
  useQuery({
    queryKey: ['jobs', limit],
    queryFn: () => api.getJobs(limit),
    refetchInterval: 3000,
  })

export const useGraph = (limit = 300) =>
  useQuery({ queryKey: ['graph', limit], queryFn: () => api.getGraph(limit) })

export const useNodeDetail = (nodeId: string | null) =>
  useQuery({ queryKey: ['node', nodeId], queryFn: () => api.getNodeDetail(nodeId!), enabled: !!nodeId })

export const usePlan = (date: string) =>
  useQuery({ queryKey: ['plan', date], queryFn: () => api.getPlanBySummary(date), enabled: !!date, retry: false })

export const useDataOverview = (start: string, end: string) =>
  useQuery({ queryKey: ['overview', start, end], queryFn: () => api.getDataOverview(start, end), enabled: !!start && !!end })

export const useSettings = () =>
  useQuery({ queryKey: ['settings'], queryFn: api.getSettings })

export const useIngestBrowserLocal = () => {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (days?: number) => api.ingestBrowserLocal(days), onSuccess: () => qc.invalidateQueries({ queryKey: ['events'] }) })
}

export const useIngestGCal = () => {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (days?: number) => api.ingestGCal(days), onSuccess: () => qc.invalidateQueries({ queryKey: ['events'] }) })
}

export const useCollectConfiguredSources = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (days?: number) => api.collectConfiguredSources(days),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['events'] }),
  })
}

export const useIngestManual = () => {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (entries: ManualEntry[]) => api.ingestManual(entries), onSuccess: () => qc.invalidateQueries({ queryKey: ['events'] }) })
}

export const useRunAnalysis = () => {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (date: string) => api.runAnalysis(date), onSuccess: () => qc.invalidateQueries({ queryKey: ['events'] }) })
}

export const useGenerateSummary = () => {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (date: string) => api.generateSummary(date), onSuccess: (_, date) => { qc.invalidateQueries({ queryKey: ['summary', date] }); qc.invalidateQueries({ queryKey: ['graph'] }) } })
}

export const useStartSummaryGeneration = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (date: string) => api.startSummaryGeneration(date),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  })
}

export const useGeneratePlan = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (date: string) => api.generatePlan(date),
    onSuccess: (_, date) => qc.invalidateQueries({ queryKey: ['plan', date] }),
  })
}

export const useStartPlanGeneration = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (date: string) => api.startPlanGeneration(date),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  })
}

export const useUpdatePlan = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ date, planId, items }: { date: string; planId: string; items: PlanItem[] }) => api.updatePlan(planId, items),
    onSuccess: (_, vars) => qc.invalidateQueries({ queryKey: ['plan', vars.date] }),
  })
}

export const useDeleteEvent = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (eventId: string) => api.deleteEvent(eventId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['events'] })
      qc.invalidateQueries({ queryKey: ['overview'] })
      qc.invalidateQueries({ queryKey: ['node'] })
    },
  })
}

export const useDeleteDay = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (date: string) => api.deleteDay(date),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['events'] })
      qc.invalidateQueries({ queryKey: ['overview'] })
      qc.invalidateQueries({ queryKey: ['summary'] })
      qc.invalidateQueries({ queryKey: ['plan'] })
      qc.invalidateQueries({ queryKey: ['graph'] })
      qc.invalidateQueries({ queryKey: ['node'] })
    },
  })
}

export const useStartGraphRebuild = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.startGraphRebuild,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  })
}

export const useUpdateSettings = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (s: SettingsUpdatePayload) => api.updateSettings(s),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings'] }),
  })
}

export const useUploadGoogleCredentials = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => api.uploadGoogleCredentials(file),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings'] }),
  })
}

export const useStartGoogleCalendarAuthorization = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.startGoogleCalendarAuthorization,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings'] }),
  })
}
