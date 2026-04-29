import { useRef, useState, useEffect, type ReactNode } from 'react'
import { Settings, Save, Loader2, Globe, Calendar, Upload, ExternalLink, GitBranch, Mail } from 'lucide-react'
import axios from 'axios'
import toast from 'react-hot-toast'
import { useSettings, useUpdateSettings, useUploadGoogleCredentials, useStartGoogleCalendarAuthorization } from '../hooks/queries'
import type { AppSettings, SettingsUpdatePayload } from '../types'

const NVIDIA_MODELS = [
  { id: 'deepseek-ai/deepseek-v3.2', name: 'DeepSeek V3.2' },
  { id: 'moonshotai/kimi-k2.5', name: 'Kimi K2.5' },
  { id: 'z-ai/glm4.7', name: 'GLM 4.7' },
]

const DEEPSEEK_MODELS = [
  { id: 'deepseek-v4-flash', name: 'DeepSeek V4 Flash', desc: '低延迟 / 日常分析' },
  { id: 'deepseek-v4-pro', name: 'DeepSeek V4 Pro', desc: '高质量 / 复杂推理' },
]

const PROVIDERS = [
  { id: 'nvidia' as const, name: 'NVIDIA', desc: '云端 API（DeepSeek / Kimi / GLM 等）' },
  { id: 'deepseek' as const, name: 'DeepSeek', desc: '云端 API（官方 OpenAI 兼容接口）' },
  { id: 'openai' as const, name: 'OpenAI', desc: '云端 API（GPT-4o 等）' },
  { id: 'ollama' as const, name: 'Ollama', desc: '本地模型（完全私有）' },
]

type SecretFieldKey = 'nvidia_api_key' | 'openai_api_key' | 'deepseek_api_key'
type SecretDrafts = Record<SecretFieldKey, string>
type ClearedSecretFlags = Record<`clear_${SecretFieldKey}`, boolean>

const EMPTY_SECRET_DRAFTS: SecretDrafts = {
  nvidia_api_key: '',
  openai_api_key: '',
  deepseek_api_key: '',
}

const EMPTY_CLEARED_FLAGS: ClearedSecretFlags = {
  clear_nvidia_api_key: false,
  clear_openai_api_key: false,
  clear_deepseek_api_key: false,
}

function openExternalUrl(url: string) {
  const nativeBridge = (window as unknown as {
    webkit?: {
      messageHandlers?: {
        secondBrainNative?: {
          postMessage: (payload: { type: string; url: string }) => void
        }
      }
    }
  }).webkit?.messageHandlers?.secondBrainNative

  if (nativeBridge) {
    nativeBridge.postMessage({ type: 'openExternal', url })
    return
  }

  const opened = window.open(url, '_blank', 'noopener,noreferrer')
  if (!opened) {
    window.location.assign(url)
  }
}

export default function SettingsPage() {
  const { data: settings, isLoading, refetch: refetchSettings } = useSettings()
  const updateMut = useUpdateSettings()
  const uploadGoogleCredentialsMut = useUploadGoogleCredentials()
  const startGoogleAuthMut = useStartGoogleCalendarAuthorization()
  const googleCredentialsInputRef = useRef<HTMLInputElement | null>(null)
  const googleAuthPollRef = useRef<number | null>(null)
  const [form, setForm] = useState<Partial<AppSettings>>({})
  const [secretDrafts, setSecretDrafts] = useState<SecretDrafts>(EMPTY_SECRET_DRAFTS)
  const [clearedSecrets, setClearedSecrets] = useState<ClearedSecretFlags>(EMPTY_CLEARED_FLAGS)

  useEffect(() => {
    if (!settings) return
    setForm(settings)
    setSecretDrafts(EMPTY_SECRET_DRAFTS)
    setClearedSecrets(EMPTY_CLEARED_FLAGS)
  }, [settings])

  useEffect(() => () => {
    if (googleAuthPollRef.current) {
      window.clearInterval(googleAuthPollRef.current)
    }
  }, [])

  const updateSecretDraft = (key: SecretFieldKey, value: string) => {
    const clearKey = `clear_${key}` as const
    setSecretDrafts(current => ({ ...current, [key]: value }))
    if (value.trim()) {
      setClearedSecrets(current => ({ ...current, [clearKey]: false }))
    }
  }

  const clearSavedSecret = (key: SecretFieldKey) => {
    const clearKey = `clear_${key}` as const
    setSecretDrafts(current => ({ ...current, [key]: '' }))
    setClearedSecrets(current => ({ ...current, [clearKey]: true }))
  }

  const handleSave = () => {
    const payload: SettingsUpdatePayload = {
      llm_provider: form.llm_provider,
      openai_model: form.openai_model,
      openai_base_url: form.openai_base_url,
      deepseek_model: form.deepseek_model,
      deepseek_base_url: form.deepseek_base_url,
      nvidia_model: form.nvidia_model,
      ollama_base_url: form.ollama_base_url,
      ollama_model: form.ollama_model,
      google_user_email: form.google_user_email,
      chrome_history_enabled: form.chrome_history_enabled,
      safari_history_enabled: form.safari_history_enabled,
      google_calendar_enabled: form.google_calendar_enabled,
      gmail_enabled: form.gmail_enabled,
      git_activity_enabled: form.git_activity_enabled,
      git_repo_paths: form.git_repo_paths,
      git_author_filter: form.git_author_filter,
    }
    for (const key of Object.keys(secretDrafts) as SecretFieldKey[]) {
      const value = secretDrafts[key].trim()
      const clearFlag = `clear_${key}` as const
      if (value) {
        switch (key) {
          case 'nvidia_api_key':
            payload.nvidia_api_key = value
            break
          case 'openai_api_key':
            payload.openai_api_key = value
            break
          case 'deepseek_api_key':
            payload.deepseek_api_key = value
            break
        }
      } else if (clearedSecrets[clearFlag]) {
        switch (clearFlag) {
          case 'clear_nvidia_api_key':
            payload.clear_nvidia_api_key = true
            break
          case 'clear_openai_api_key':
            payload.clear_openai_api_key = true
            break
          case 'clear_deepseek_api_key':
            payload.clear_deepseek_api_key = true
            break
        }
      }
    }

    updateMut.mutate(payload, {
      onSuccess: saved => {
        setForm(saved)
        toast.success('设置已保存')
      },
      onError: () => toast.error('保存失败'),
    })
  }

  const handleGoogleCredentialsChange = (file: File | undefined) => {
    if (!file) return
    uploadGoogleCredentialsMut.mutate(file, {
      onSuccess: () => toast.success('Google 凭据已保存'),
      onError: error => {
        const detail = axios.isAxiosError(error) ? error.response?.data?.detail : null
        const message = detail || (error instanceof Error ? error.message : 'Google 凭据保存失败')
        toast.error(message)
      },
      onSettled: () => {
        if (googleCredentialsInputRef.current) {
          googleCredentialsInputRef.current.value = ''
        }
      },
    })
  }

  const handleGoogleAuthorize = () => {
    startGoogleAuthMut.mutate(undefined, {
      onSuccess: data => {
        openExternalUrl(data.authorization_url)
        toast('授权完成后回到配置页，状态会自动刷新')
        const startedAt = Date.now()
        if (googleAuthPollRef.current) {
          window.clearInterval(googleAuthPollRef.current)
        }
        googleAuthPollRef.current = window.setInterval(async () => {
          const result = await refetchSettings()
          if (
            (result.data?.google_calendar_authorized && result.data?.google_gmail_authorized)
            || Date.now() - startedAt > 120000
          ) {
            if (googleAuthPollRef.current) {
              window.clearInterval(googleAuthPollRef.current)
              googleAuthPollRef.current = null
            }
          }
        }, 3000)
      },
      onError: error => {
        const detail = axios.isAxiosError(error) ? error.response?.data?.detail : null
        const message = detail || (error instanceof Error ? error.message : 'Google 数据源授权发起失败')
        toast.error(message)
      },
    })
  }

  if (isLoading) return <div className="flex justify-center py-20"><Loader2 className="w-5 h-5 animate-spin text-gray-400" /></div>

  const sourceConfigDirty = !!settings && (
    form.chrome_history_enabled !== settings.chrome_history_enabled ||
    form.safari_history_enabled !== settings.safari_history_enabled ||
    form.google_calendar_enabled !== settings.google_calendar_enabled ||
    form.gmail_enabled !== settings.gmail_enabled ||
    form.google_user_email !== settings.google_user_email ||
    form.git_activity_enabled !== settings.git_activity_enabled ||
    (form.git_repo_paths ?? '') !== (settings.git_repo_paths ?? '') ||
    (form.git_author_filter ?? '') !== (settings.git_author_filter ?? '')
  )
  const gitConfigDirty = !!settings && (
    form.git_activity_enabled !== settings.git_activity_enabled ||
    (form.git_repo_paths ?? '') !== (settings.git_repo_paths ?? '') ||
    (form.git_author_filter ?? '') !== (settings.git_author_filter ?? '')
  )
  const browserConfigDirty = !!settings && (
    form.chrome_history_enabled !== settings.chrome_history_enabled ||
    form.safari_history_enabled !== settings.safari_history_enabled
  )
  const calendarConfigDirty = !!settings && (
    form.google_calendar_enabled !== settings.google_calendar_enabled ||
    form.google_user_email !== settings.google_user_email
  )
  const gmailConfigDirty = !!settings && (
    form.gmail_enabled !== settings.gmail_enabled ||
    form.google_user_email !== settings.google_user_email
  )
  const googleConfigDirty = calendarConfigDirty || gmailConfigDirty

  const googleStatus = calendarConfigDirty
    ? '待保存'
    : !form.google_calendar_enabled
    ? '已关闭'
    : form.google_user_email && form.google_credentials_configured && form.google_calendar_authorized
      ? '已启用'
      : form.google_user_email && form.google_credentials_configured
        ? '待授权'
        : '待完善配置'
  const gitStatus = gitConfigDirty
    ? '待保存'
    : !form.git_activity_enabled
    ? '已关闭'
    : form.git_repo_paths?.trim()
      ? '已启用'
      : '待填写仓库'
  const gmailStatus = gmailConfigDirty
    ? '待保存'
    : !form.gmail_enabled
    ? '已关闭'
    : form.google_user_email && form.google_credentials_configured && form.google_gmail_authorized
      ? '已启用'
      : form.google_user_email && form.google_credentials_configured
        ? '待授权'
        : '待完善配置'
  const googleAuthComplete = !!form.google_calendar_authorized && !!form.google_gmail_authorized
  const browserEnabledCount = [form.chrome_history_enabled, form.safari_history_enabled].filter(Boolean).length
  const googleEnabledCount = [form.google_calendar_enabled, form.gmail_enabled].filter(Boolean).length
  const googleAuthStatusText = googleAuthComplete
    ? '已保存日历与 Gmail 授权 token'
    : form.google_calendar_authorized
      ? '已保存日历授权；Gmail 只读未授权'
      : '未完成账号授权'
  const googleAuthButtonText = googleAuthComplete
    ? '重新授权'
    : form.google_calendar_authorized
      ? '重新授权补全 Gmail'
      : '授权 Google 数据源'

  return (
    <div>
      <h1 className="text-xl font-semibold text-gray-900 mb-6">配置下</h1>

      <div className="max-w-4xl space-y-6">
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <div className="flex items-center gap-2 mb-5 pb-3 border-b border-gray-100">
            <Settings className="w-4 h-4 text-gray-500" />
            <h3 className="font-medium text-sm text-gray-700">LLM 配置</h3>
          </div>

          <div className="mb-6">
            <label className="block text-xs font-medium text-gray-500 mb-2">AI 模型提供者</label>
            <div className="grid gap-3 md:grid-cols-2">
              {PROVIDERS.map(p => (
                <label key={p.id} className={`flex items-center gap-2 px-4 py-3 rounded-lg border-2 cursor-pointer transition-colors ${
                  form.llm_provider === p.id ? 'border-blue-500 bg-blue-50' : 'border-gray-200 hover:border-gray-300'
                }`}>
                  <input
                    type="radio"
                    name="provider"
                    value={p.id}
                    checked={form.llm_provider === p.id}
                    onChange={() => setForm({ ...form, llm_provider: p.id })}
                    className="sr-only"
                  />
                  <div>
                    <p className="text-sm font-medium text-gray-800">{p.name}</p>
                    <p className="text-xs text-gray-500">{p.desc}</p>
                  </div>
                </label>
              ))}
            </div>
          </div>

          {form.llm_provider === 'nvidia' && (
            <div className="space-y-4 mb-6 p-4 bg-gray-50 rounded-lg">
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">API Key</label>
                <input
                  type="password"
                  value={secretDrafts.nvidia_api_key}
                  onChange={e => updateSecretDraft('nvidia_api_key', e.target.value)}
                  placeholder={form.nvidia_api_key_configured ? '已配置，留空表示保持不变' : 'nvapi-...'}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm outline-none focus:ring-1 focus:ring-blue-500"
                />
                <SecretStatusRow
                  configured={!!form.nvidia_api_key_configured}
                  cleared={clearedSecrets.clear_nvidia_api_key}
                  onClear={() => clearSavedSecret('nvidia_api_key')}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">模型</label>
                <select
                  value={form.nvidia_model ?? NVIDIA_MODELS[0].id}
                  onChange={e => setForm({ ...form, nvidia_model: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm outline-none focus:ring-1 focus:ring-blue-500 bg-white"
                >
                  {NVIDIA_MODELS.map(m => <option key={m.id} value={m.id}>{m.name}（{m.id}）</option>)}
                </select>
              </div>
              <p className="text-xs text-gray-400">Base URL: https://integrate.api.nvidia.com/v1（自动配置）</p>
            </div>
          )}

          {form.llm_provider === 'openai' && (
            <div className="space-y-4 mb-6 p-4 bg-gray-50 rounded-lg">
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">API Key</label>
                <input
                  type="password"
                  value={secretDrafts.openai_api_key}
                  onChange={e => updateSecretDraft('openai_api_key', e.target.value)}
                  placeholder={form.openai_api_key_configured ? '已配置，留空表示保持不变' : 'sk-...'}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm outline-none focus:ring-1 focus:ring-blue-500"
                />
                <SecretStatusRow
                  configured={!!form.openai_api_key_configured}
                  cleared={clearedSecrets.clear_openai_api_key}
                  onClear={() => clearSavedSecret('openai_api_key')}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">模型</label>
                <select
                  value={form.openai_model ?? 'gpt-4o'}
                  onChange={e => setForm({ ...form, openai_model: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm outline-none focus:ring-1 focus:ring-blue-500 bg-white"
                >
                  <option value="gpt-4o">GPT-4o</option>
                  <option value="gpt-4o-mini">GPT-4o Mini</option>
                  <option value="gpt-4-turbo">GPT-4 Turbo</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">Base URL（可选，留空使用官方）</label>
                <input
                  value={form.openai_base_url ?? ''}
                  onChange={e => setForm({ ...form, openai_base_url: e.target.value })}
                  placeholder="https://api.openai.com/v1"
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
            </div>
          )}

          {form.llm_provider === 'deepseek' && (
            <div className="space-y-4 mb-6 p-4 bg-gray-50 rounded-lg">
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">API Key</label>
                <input
                  type="password"
                  value={secretDrafts.deepseek_api_key}
                  onChange={e => updateSecretDraft('deepseek_api_key', e.target.value)}
                  placeholder={form.deepseek_api_key_configured ? '已配置，留空表示保持不变' : 'sk-...'}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm outline-none focus:ring-1 focus:ring-blue-500"
                />
                <SecretStatusRow
                  configured={!!form.deepseek_api_key_configured}
                  cleared={clearedSecrets.clear_deepseek_api_key}
                  onClear={() => clearSavedSecret('deepseek_api_key')}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">模型</label>
                <select
                  value={form.deepseek_model ?? DEEPSEEK_MODELS[0].id}
                  onChange={e => setForm({ ...form, deepseek_model: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm outline-none focus:ring-1 focus:ring-blue-500 bg-white"
                >
                  {DEEPSEEK_MODELS.map(m => <option key={m.id} value={m.id}>{m.name}（{m.id}，{m.desc}）</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">Base URL</label>
                <input
                  value={form.deepseek_base_url ?? 'https://api.deepseek.com'}
                  onChange={e => setForm({ ...form, deepseek_base_url: e.target.value })}
                  placeholder="https://api.deepseek.com"
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
              <p className="text-xs text-gray-400">兼容 OpenAI SDK：`OpenAI(api_key=..., base_url=&quot;https://api.deepseek.com&quot;)`</p>
            </div>
          )}

          {form.llm_provider === 'ollama' && (
            <div className="space-y-4 mb-6 p-4 bg-gray-50 rounded-lg">
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">Base URL</label>
                <input
                  value={form.ollama_base_url ?? ''}
                  onChange={e => setForm({ ...form, ollama_base_url: e.target.value })}
                  placeholder="http://localhost:11434"
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">模型名称</label>
                <input
                  value={form.ollama_model ?? ''}
                  onChange={e => setForm({ ...form, ollama_model: e.target.value })}
                  placeholder="qwen2.5"
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
            </div>
          )}

          <button
            onClick={handleSave}
            disabled={updateMut.isPending}
            className="w-full py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {updateMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            保存 LLM 配置
          </button>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <div className="flex flex-col gap-3 mb-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2">
              <Settings className="w-4 h-4 text-gray-500" />
              <h3 className="font-medium text-sm text-gray-700">数据源配置</h3>
              {sourceConfigDirty && <span className="px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 text-[11px]">有未保存改动</span>}
            </div>
            <button
              onClick={handleSave}
              disabled={updateMut.isPending || !sourceConfigDirty}
              className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-blue-600 px-3 py-2 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {updateMut.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
              保存数据源配置
            </button>
          </div>
          <p className="text-xs text-gray-400 mb-5">`干了啥` 页面的一键采集会读取这里已启用且已完成配置的数据源。</p>
          {sourceConfigDirty && (
            <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
              当前改动还只在页面表单里，保存后才会写入后端并被一键采集使用。
            </div>
          )}

          <div className="space-y-4">
            <DataSourceGroup
              icon={<Globe className="w-4 h-4 text-emerald-600" />}
              title="浏览器"
              description="统一管理本机浏览器历史采集，Chrome 负责常规历史和内网明细，Safari 用于补齐系统浏览记录。"
              status={browserConfigDirty ? '待保存' : browserEnabledCount > 0 ? `${browserEnabledCount}/2 已启用` : '已关闭'}
              statusTone={
                browserConfigDirty
                  ? 'bg-amber-100 text-amber-700'
                  : browserEnabledCount > 0
                    ? 'bg-emerald-100 text-emerald-700'
                    : 'bg-gray-100 text-gray-500'
              }
            >
              <SourceToggleRow
                icon={<Globe className="w-4 h-4 text-emerald-600" />}
                title="Chrome 历史"
                description="读取本地 Chrome 最近 2 天历史；一键采集后还会分批补充内网页面明细。"
                status={form.chrome_history_enabled ? '已启用' : '已关闭'}
                statusTone={form.chrome_history_enabled ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-100 text-gray-500'}
                enabled={!!form.chrome_history_enabled}
                onToggle={checked => setForm({ ...form, chrome_history_enabled: checked })}
              />
              <SourceToggleRow
                icon={<Globe className="w-4 h-4 text-sky-600" />}
                title="Safari 历史"
                description="读取本地 Safari 最近 2 天历史；需要系统完全磁盘访问权限。"
                status={form.safari_history_enabled ? '已启用' : '已关闭'}
                statusTone={form.safari_history_enabled ? 'bg-sky-100 text-sky-700' : 'bg-gray-100 text-gray-500'}
                enabled={!!form.safari_history_enabled}
                onToggle={checked => setForm({ ...form, safari_history_enabled: checked })}
              />
              <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
                浏览器组不需要额外账号配置；Chrome 内网明细依赖已配置的 Chrome MCP Native Messaging Bridge。
              </div>
            </DataSourceGroup>

            <DataSourceGroup
              icon={<Mail className="w-4 h-4 text-rose-600" />}
              title="Google"
              description="一套 Google 邮箱、OAuth JSON 和授权 token，可同时服务日历、Gmail 等 Google 数据源。"
              status={googleConfigDirty ? '待保存' : googleEnabledCount > 0 ? `${googleEnabledCount}/2 已启用` : '已关闭'}
              statusTone={
                googleConfigDirty
                  ? 'bg-amber-100 text-amber-700'
                  : googleEnabledCount > 0
                    ? 'bg-rose-100 text-rose-700'
                    : 'bg-gray-100 text-gray-500'
              }
            >
              <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">Google 邮箱地址</label>
                  <input
                    value={form.google_user_email ?? ''}
                    onChange={e => setForm({ ...form, google_user_email: e.target.value })}
                    placeholder="your.name@company.com"
                    className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm outline-none focus:ring-1 focus:ring-blue-500"
                  />
                  <p className="text-xs text-gray-400 mt-1">日历和 Gmail 共用这一个账号。</p>
                </div>
                <input
                  id="google-credentials-file"
                  ref={googleCredentialsInputRef}
                  type="file"
                  accept="application/json,.json"
                  disabled={uploadGoogleCredentialsMut.isPending}
                  onChange={event => handleGoogleCredentialsChange(event.target.files?.[0])}
                  className="sr-only"
                />
                <label
                  htmlFor="google-credentials-file"
                  className={`inline-flex h-10 items-center justify-center gap-1.5 whitespace-nowrap rounded-lg border border-gray-200 bg-white px-3 text-xs font-medium text-gray-700 hover:border-gray-300 ${
                    uploadGoogleCredentialsMut.isPending ? 'pointer-events-none opacity-50' : 'cursor-pointer'
                  }`}
                >
                  {uploadGoogleCredentialsMut.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
                  {uploadGoogleCredentialsMut.isPending
                    ? '上传中'
                    : form.google_credentials_configured
                      ? '已上传，点击更新'
                      : '上传 OAuth JSON'}
                </label>
              </div>

              <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="text-xs font-medium text-gray-600">Google 数据源授权</p>
                    <p className="text-xs text-gray-400 mt-1">{googleAuthStatusText}</p>
                  </div>
                  <button
                    onClick={handleGoogleAuthorize}
                    disabled={!form.google_credentials_configured || startGoogleAuthMut.isPending}
                    className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs font-medium text-gray-700 hover:border-gray-300 disabled:opacity-50"
                  >
                    {startGoogleAuthMut.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ExternalLink className="w-3.5 h-3.5" />}
                    {googleAuthButtonText}
                  </button>
                </div>
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                <SourceToggleRow
                  icon={<Calendar className="w-4 h-4 text-orange-600" />}
                  title="Google 日历"
                  description="采集会议、预约和时间块。"
                  status={googleStatus}
                  statusTone={
                    calendarConfigDirty
                      ? 'bg-amber-100 text-amber-700'
                      : !form.google_calendar_enabled
                        ? 'bg-gray-100 text-gray-500'
                        : form.google_user_email && form.google_credentials_configured && form.google_calendar_authorized
                          ? 'bg-orange-100 text-orange-700'
                          : 'bg-amber-100 text-amber-700'
                  }
                  enabled={!!form.google_calendar_enabled}
                  onToggle={checked => setForm({ ...form, google_calendar_enabled: checked })}
                />
                <SourceToggleRow
                  icon={<Mail className="w-4 h-4 text-rose-600" />}
                  title="Gmail / IM"
                  description="采集邮件主题、收发件人、摘要和正文片段；后续 IM 类 Google 数据源可复用同一授权。"
                  status={gmailStatus}
                  statusTone={
                    gmailConfigDirty
                      ? 'bg-amber-100 text-amber-700'
                      : !form.gmail_enabled
                        ? 'bg-gray-100 text-gray-500'
                        : form.google_user_email && form.google_credentials_configured && form.google_gmail_authorized
                          ? 'bg-rose-100 text-rose-700'
                          : 'bg-amber-100 text-amber-700'
                  }
                  enabled={!!form.gmail_enabled}
                  onToggle={checked => setForm({ ...form, gmail_enabled: checked })}
                />
              </div>
            </DataSourceGroup>

            <DataSourceGroup
              icon={<GitBranch className="w-4 h-4 text-slate-700" />}
              title="Git"
              description="统一采集本地已克隆仓库的提交记录，支持 GitHub、GitLab 和本地工作区多路径。"
              status={gitStatus}
              statusTone={
                gitConfigDirty
                  ? 'bg-amber-100 text-amber-700'
                  : !form.git_activity_enabled
                  ? 'bg-gray-100 text-gray-500'
                  : form.git_repo_paths?.trim()
                    ? 'bg-slate-100 text-slate-700'
                    : 'bg-amber-100 text-amber-700'
              }
              enabled={!!form.git_activity_enabled}
              onToggle={checked => setForm({ ...form, git_activity_enabled: checked })}
            >
              <div className="space-y-3">
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">仓库或工作区路径（可多行）</label>
                  <textarea
                    value={form.git_repo_paths ?? ''}
                    onChange={e => setForm({ ...form, git_repo_paths: e.target.value })}
                    placeholder={'/Users/you/workspace/github-projects\n/Users/you/workspace/gitlab-projects\n/Users/you/project-a'}
                    rows={5}
                    className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm outline-none focus:ring-1 focus:ring-blue-500 resize-none font-mono"
                  />
                  <p className="text-xs text-gray-400 mt-1">一行一个本地路径；可以填单个仓库，也可以填 GitHub/GitLab 的克隆目录或工作区目录，系统会自动发现子仓库。</p>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">作者过滤</label>
                  <input
                    value={form.git_author_filter ?? ''}
                    onChange={e => setForm({ ...form, git_author_filter: e.target.value })}
                    placeholder="name@example.com 或 Dejun Shi"
                    className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm outline-none focus:ring-1 focus:ring-blue-500"
                  />
                  <p className="text-xs text-gray-400 mt-1">留空会采集仓库中所有作者的提交。</p>
                </div>
              </div>
            </DataSourceGroup>
          </div>

          <button
            onClick={handleSave}
            disabled={updateMut.isPending}
            className="w-full mt-5 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {updateMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            保存数据源配置
          </button>
        </div>
      </div>
    </div>
  )
}

function DataSourceGroup({
  icon,
  title,
  description,
  status,
  statusTone,
  enabled,
  onToggle,
  children,
}: {
  icon: ReactNode
  title: string
  description: string
  status: string
  statusTone: string
  enabled?: boolean
  onToggle?: (checked: boolean) => void
  children: ReactNode
}) {
  const hasGroupToggle = typeof enabled === 'boolean' && !!onToggle

  return (
    <div className="rounded-xl border border-gray-200 p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-xl bg-gray-50 border border-gray-100 flex items-center justify-center shrink-0">
            {icon}
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <p className="text-sm font-medium text-gray-800">{title}</p>
              <span className={`px-2 py-0.5 rounded-full text-[11px] ${statusTone}`}>{status}</span>
            </div>
            <p className="text-xs text-gray-500 mt-1">{description}</p>
          </div>
        </div>
        {hasGroupToggle && <Toggle checked={enabled} onChange={onToggle} />}
      </div>

      <div className="mt-4 space-y-3 md:pl-[52px]">
        {children}
      </div>
    </div>
  )
}

function SourceToggleRow({
  icon,
  title,
  description,
  status,
  statusTone,
  enabled,
  onToggle,
}: {
  icon: ReactNode
  title: string
  description: string
  status: string
  statusTone: string
  enabled: boolean
  onToggle: (checked: boolean) => void
}) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-lg border border-gray-100 bg-white px-3 py-3">
      <div className="flex min-w-0 items-start gap-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-gray-100 bg-gray-50">
          {icon}
        </div>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium text-gray-800">{title}</p>
            <span className={`px-2 py-0.5 rounded-full text-[11px] ${statusTone}`}>{status}</span>
          </div>
          <p className="mt-1 text-xs leading-5 text-gray-500">{description}</p>
        </div>
      </div>
      <Toggle checked={enabled} onChange={onToggle} />
    </div>
  )
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors ${
        checked ? 'bg-blue-600' : 'bg-gray-200'
      }`}
    >
      <span
        className={`inline-block h-5 w-5 transform rounded-full bg-white transition-transform ${
          checked ? 'translate-x-5' : 'translate-x-1'
        }`}
      />
    </button>
  )
}

function SecretStatusRow({
  configured,
  cleared,
  onClear,
}: {
  configured: boolean
  cleared: boolean
  onClear: () => void
}) {
  return (
    <div className="mt-1.5 flex items-center justify-between gap-3">
      <p className={`text-xs ${cleared ? 'text-amber-600' : configured ? 'text-emerald-600' : 'text-gray-400'}`}>
        {cleared ? '保存后将清空当前密钥。' : configured ? '当前已配置密钥，留空表示保持不变。' : '当前未配置密钥。'}
      </p>
      <button
        type="button"
        onClick={onClear}
        disabled={!configured}
        className="text-xs text-gray-500 hover:text-red-600 disabled:opacity-40"
      >
        清空已保存密钥
      </button>
    </div>
  )
}
