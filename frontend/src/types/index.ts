export interface ActivityEvent {
  id: string
  source: 'browser' | 'chrome' | 'safari' | 'manual' | 'gcal' | 'gmail' | 'git'
  timestamp: string
  title: string
  content?: string
  url?: string
  duration_minutes?: number
  analysis?: {
    category: 'work' | 'study' | 'life' | 'entertainment'
    intent: string
    tags: string[]
  } | null
}

export interface EventsResponse {
  items: ActivityEvent[]
  total: number
  page: number
}

export interface IngestResponse {
  imported_count: number
  skipped_count?: number
  updated_count?: number
  date_range?: string[]
  collected_sources?: string[]
  source_breakdown?: Record<string, number>
  warnings?: string[]
  candidate_count?: number
  captured_count?: number
  offset?: number
  batch_size?: number
  next_offset?: number
  has_more?: boolean
}

export type CollectSourceStatus = 'success' | 'disabled' | 'misconfigured' | 'failed'

export interface CollectSourceResult {
  source: 'chrome' | 'safari' | 'gcal' | 'gmail' | 'git'
  label: string
  status: CollectSourceStatus
  imported_count: number
  skipped_count: number
  updated_count?: number
  date_range: string[]
  message?: string | null
  warnings?: string[]
  collected_sources?: string[]
  source_breakdown?: Record<string, number>
  code?: string
  action_label?: string
  action_url?: string
  project_id?: string
}

export interface CollectSourcesResponse extends IngestResponse {
  source_results: CollectSourceResult[]
}

export interface AnalysisResponse {
  analyzed_count: number
  categories: Record<string, number>
}

export interface DailySummary {
  id: string
  date: string
  timeline_md: string
  progress_md: string
  knowledge_md: string
  time_distribution: Record<string, number>
}

export type JobStatus = 'idle' | 'pending' | 'running' | 'completed' | 'failed'

export interface AppJob {
  id: string | null
  job_type: string
  resource_key?: string | null
  status: JobStatus
  payload?: Record<string, unknown> | null
  result?: Record<string, unknown> | null
  error?: string | null
  created_at?: string | null
  updated_at: string
  started_at?: string | null
  finished_at?: string | null
}

export type SummaryJobStatus = AppJob

export interface KGNode {
  id: string
  name: string
  type: 'project' | 'person' | 'concept' | 'tool' | 'topic'
  mention_count: number
}

export interface KGEdge {
  source: string
  target: string
  relation: string
  weight: number
}

export interface GraphData {
  nodes: KGNode[]
  edges: KGEdge[]
}

export interface NodeDetail {
  node: KGNode & { properties: Record<string, unknown>; first_seen?: string; last_seen?: string }
  connected_nodes: { id: string; name: string; type: string }[]
  evidences: {
    source_type: 'summary' | 'event'
    mention_date?: string | null
    title?: string | null
    excerpt?: string | null
    summary_id?: string | null
    event_id?: string | null
  }[]
}

export interface PlanItem {
  title: string
  priority: 'high' | 'medium' | 'low'
  reason: string
  status?: 'todo' | 'done' | 'carried_over'
  estimated_minutes?: number | null
  scheduled_slot?: string | null
}

export interface Suggestion {
  type: 'attention' | 'review' | 'health' | 'goal'
  content: string
}

export interface Plan {
  id: string
  date: string
  items: PlanItem[]
  suggestions: Suggestion[]
}

export interface DayOverview {
  date: string
  event_count: number
  has_analysis: boolean
  has_summary: boolean
}

export interface AppSettings {
  llm_provider: 'openai' | 'nvidia' | 'deepseek' | 'ollama'
  openai_model: string
  openai_base_url: string
  deepseek_model: string
  deepseek_base_url: string
  nvidia_model: string
  ollama_base_url: string
  ollama_model: string
  google_user_email: string
  chrome_history_enabled: boolean
  safari_history_enabled: boolean
  google_calendar_enabled: boolean
  gmail_enabled: boolean
  git_activity_enabled: boolean
  git_repo_paths: string
  git_author_filter: string
  google_credentials_configured: boolean
  google_calendar_authorized: boolean
  google_gmail_authorized: boolean
  google_cloud_project_id?: string
  google_calendar_api_enable_url?: string
  google_gmail_api_enable_url?: string
  openai_api_key_configured: boolean
  deepseek_api_key_configured: boolean
  nvidia_api_key_configured: boolean
}

export interface SettingsUpdatePayload {
  llm_provider?: AppSettings['llm_provider']
  openai_api_key?: string
  clear_openai_api_key?: boolean
  openai_model?: string
  openai_base_url?: string
  deepseek_api_key?: string
  clear_deepseek_api_key?: boolean
  deepseek_model?: string
  deepseek_base_url?: string
  nvidia_api_key?: string
  clear_nvidia_api_key?: boolean
  nvidia_model?: string
  ollama_base_url?: string
  ollama_model?: string
  google_user_email?: string
  chrome_history_enabled?: boolean
  safari_history_enabled?: boolean
  google_calendar_enabled?: boolean
  gmail_enabled?: boolean
  git_activity_enabled?: boolean
  git_repo_paths?: string
  git_author_filter?: string
}

export interface ManualEntry {
  timestamp: string
  title: string
  content?: string
  duration_minutes?: number
}
