import { useRef, useState, useEffect, type ReactNode } from 'react'
import { Settings, Save, Loader2, Globe, Upload, ExternalLink, GitBranch, Mail } from 'lucide-react'
import axios from 'axios'
import toast from 'react-hot-toast'
import { useSettings, useUpdateSettings, useUploadGoogleCredentials, useStartGoogleCalendarAuthorization } from '../hooks/queries'
import type { AppSettings, SettingsUpdatePayload } from '../types'
import { openExternalUrl } from '../utils/openExternalUrl'

const DEEPSEEK_MODELS = [
  { id: 'deepseek-v4-flash', name: 'DeepSeek V4 Flash', desc: '低延迟 / 日常分析' },
  { id: 'deepseek-v4-pro', name: 'DeepSeek V4 Pro', desc: '高质量 / 复杂推理' },
]

const PROVIDERS = [
  { id: 'deepseek' as const, name: 'DeepSeek', desc: '云端 API（官方 OpenAI 兼容接口）' },
  { id: 'openai' as const, name: 'OpenAI', desc: '云端 API（GPT-4o 等）' },
  { id: 'ollama' as const, name: 'Ollama', desc: '本地模型（完全私有）' },
]

const FULL_DISK_ACCESS_SETTINGS_URL = 'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles'

type SecretFieldKey = 'openai_api_key' | 'deepseek_api_key'
type SecretDrafts = Record<SecretFieldKey, string>
type ClearedSecretFlags = Record<`clear_${SecretFieldKey}`, boolean>

const EMPTY_SECRET_DRAFTS: SecretDrafts = {
  openai_api_key: '',
  deepseek_api_key: '',
}

const EMPTY_CLEARED_FLAGS: ClearedSecretFlags = {
  clear_openai_api_key: false,
  clear_deepseek_api_key: false,
}

function normalizeVisibleProvider(provider: AppSettings['llm_provider'] | undefined): AppSettings['llm_provider'] {
  return provider === 'nvidia' ? 'deepseek' : (provider ?? 'deepseek')
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
    setForm({ ...settings, llm_provider: normalizeVisibleProvider(settings.llm_provider) })
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
          case 'openai_api_key':
            payload.openai_api_key = value
            break
          case 'deepseek_api_key':
            payload.deepseek_api_key = value
            break
        }
      } else if (clearedSecrets[clearFlag]) {
        switch (clearFlag) {
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
  const googleCredentialsConfigured = !!form.google_credentials_configured
  const calendarEnabled = !!form.google_calendar_enabled
  const gmailEnabled = !!form.gmail_enabled
  const calendarAuthorized = !!form.google_calendar_authorized
  const gmailAuthorized = !!form.google_gmail_authorized
  const calendarApiReady = form.google_calendar_api_enabled === true
  const gmailApiReady = form.google_gmail_api_enabled === true
  const calendarAuthNeeded = calendarEnabled && !calendarAuthorized
  const gmailAuthNeeded = gmailEnabled && !gmailAuthorized
  const googleAuthNeeded = googleCredentialsConfigured && (calendarAuthNeeded || gmailAuthNeeded)
  const calendarApiCheckNeeded = googleCredentialsConfigured && calendarEnabled && calendarAuthorized && !calendarApiReady
  const gmailApiCheckNeeded = googleCredentialsConfigured && gmailEnabled && gmailAuthorized && !gmailApiReady
  const googleApiCheckNeeded = calendarApiCheckNeeded || gmailApiCheckNeeded
  const calendarReady = !!form.google_user_email && googleCredentialsConfigured && calendarAuthorized && calendarApiReady
  const gmailReady = !!form.google_user_email && googleCredentialsConfigured && gmailAuthorized && gmailApiReady

  const googleStatus = calendarConfigDirty
    ? '待保存'
    : !calendarEnabled
    ? '已关闭'
    : calendarReady
      ? '已启用'
      : form.google_user_email && googleCredentialsConfigured && calendarAuthorized
        ? form.google_calendar_api_enabled === false ? '待启用 API' : '待检查 API'
        : form.google_user_email && googleCredentialsConfigured
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
    : !gmailEnabled
    ? '已关闭'
    : gmailReady
      ? '已启用'
      : form.google_user_email && googleCredentialsConfigured && gmailAuthorized
        ? form.google_gmail_api_enabled === false ? '待启用 API' : '待检查 API'
        : form.google_user_email && googleCredentialsConfigured
          ? '待授权'
          : '待完善配置'
  const browserEnabledCount = [form.chrome_history_enabled, form.safari_history_enabled].filter(Boolean).length
  const googleEnabledCount = [calendarEnabled, gmailEnabled].filter(Boolean).length
  const googleAuthStatusText = calendarAuthNeeded && gmailAuthNeeded
    ? '日历与 Gmail 均未完成账号授权'
    : gmailAuthNeeded
      ? 'Gmail 只读未授权'
      : 'Google 日历未完成账号授权'
  const googleAuthButtonText = gmailAuthNeeded && calendarAuthorized
    ? '补全 Gmail 授权'
    : calendarAuthNeeded && gmailAuthorized
      ? '补全日历授权'
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
            <div className="grid gap-3 md:grid-cols-3">
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
              description="统一管理本机浏览器采集，Chrome 负责常规记录和内网明细，Safari 用于补齐系统浏览记录。"
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
                icon={<ChromeIcon className="w-5 h-5" />}
                title="Chrome"
                description="读取本地 Chrome 最近 2 天记录；一键采集后还会分批补充内网页面明细。"
                status={form.chrome_history_enabled ? '已启用' : '已关闭'}
                statusTone={form.chrome_history_enabled ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-100 text-gray-500'}
                enabled={!!form.chrome_history_enabled}
                onToggle={checked => setForm({ ...form, chrome_history_enabled: checked })}
              />
              <SourceToggleRow
                icon={<SafariIcon className="w-5 h-5" />}
                title="Safari"
                description="读取本地 Safari 最近 2 天记录；需要系统完全磁盘访问权限。"
                status={form.safari_history_enabled ? '已启用' : '已关闭'}
                statusTone={form.safari_history_enabled ? 'bg-sky-100 text-sky-700' : 'bg-gray-100 text-gray-500'}
                enabled={!!form.safari_history_enabled}
                onToggle={checked => setForm({ ...form, safari_history_enabled: checked })}
                actionLabel="打开完全磁盘访问"
                onAction={() => openExternalUrl(FULL_DISK_ACCESS_SETTINGS_URL)}
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
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
                <div className="w-full sm:w-80 lg:w-96">
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
                  className={`inline-flex h-10 items-center justify-center gap-1.5 whitespace-nowrap rounded-lg border border-gray-200 bg-white px-3 text-xs font-medium text-gray-700 hover:border-gray-300 sm:mt-5 ${
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

              {googleAuthNeeded && (
                <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <p className="text-xs font-medium text-gray-600">Google 数据源授权</p>
                      <p className="text-xs text-gray-400 mt-1">{googleAuthStatusText}</p>
                    </div>
                    <button
                      onClick={handleGoogleAuthorize}
                      disabled={startGoogleAuthMut.isPending}
                      className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs font-medium text-gray-700 hover:border-gray-300 disabled:opacity-50"
                    >
                      {startGoogleAuthMut.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ExternalLink className="w-3.5 h-3.5" />}
                      {googleAuthButtonText}
                    </button>
                  </div>
                </div>
              )}

              {googleApiCheckNeeded && (
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <p className="text-xs font-medium text-amber-800">Google API 前置权限</p>
                      <p className="text-xs text-amber-700 mt-1">
                        首次采集日历或 Gmail 前，需要在当前 OAuth 项目的 Google Cloud Console 中启用对应 API；开启后等待几分钟再一键采集。
                      </p>
                      {form.google_cloud_project_id && (
                        <p className="text-xs text-amber-700 mt-1">当前项目：{form.google_cloud_project_id}</p>
                      )}
                    </div>
                    <div className="flex flex-col gap-2 sm:flex-row">
                      {calendarApiCheckNeeded && form.google_calendar_api_enable_url && (
                        <button
                          type="button"
                          onClick={() => openExternalUrl(form.google_calendar_api_enable_url!)}
                          className="inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-lg border border-amber-200 bg-white px-3 py-2 text-xs font-medium text-amber-800 hover:border-amber-300"
                        >
                          <ExternalLink className="w-3.5 h-3.5" />
                          {form.google_calendar_api_enabled === false ? '开启日历 API' : '检查日历 API'}
                        </button>
                      )}
                      {gmailApiCheckNeeded && form.google_gmail_api_enable_url && (
                        <button
                          type="button"
                          onClick={() => openExternalUrl(form.google_gmail_api_enable_url!)}
                          className="inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-lg border border-amber-200 bg-white px-3 py-2 text-xs font-medium text-amber-800 hover:border-amber-300"
                        >
                          <ExternalLink className="w-3.5 h-3.5" />
                          {form.google_gmail_api_enabled === false ? '开启 Gmail API' : '检查 Gmail API'}
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {googleEnabledCount > 0 && !googleCredentialsConfigured && (
                <div className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-500">
                  上传 OAuth JSON 后会显示 Google Calendar API 和 Gmail API 的检查入口。
                </div>
              )}

              <div className="grid gap-3 md:grid-cols-2">
                <SourceToggleRow
                  icon={<GoogleCalendarIcon className="w-5 h-5" />}
                  title="Google 日历"
                  description="采集会议、预约和时间块。"
                  status={googleStatus}
                  statusTone={
                    calendarConfigDirty
                      ? 'bg-amber-100 text-amber-700'
                      : !calendarEnabled
                        ? 'bg-gray-100 text-gray-500'
                        : calendarReady
                          ? 'bg-orange-100 text-orange-700'
                          : 'bg-amber-100 text-amber-700'
                  }
                  enabled={calendarEnabled}
                  onToggle={checked => setForm({ ...form, google_calendar_enabled: checked })}
                />
                <SourceToggleRow
                  icon={<GmailIcon className="w-5 h-5" />}
                  title="Gmail"
                  description="采集邮件主题、收发件人、摘要和正文片段。"
                  status={gmailStatus}
                  statusTone={
                    gmailConfigDirty
                      ? 'bg-amber-100 text-amber-700'
                      : !gmailEnabled
                        ? 'bg-gray-100 text-gray-500'
                        : gmailReady
                          ? 'bg-rose-100 text-rose-700'
                          : 'bg-amber-100 text-amber-700'
                  }
                  enabled={gmailEnabled}
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

type BrandIconProps = {
  className?: string
}

function ChromeIcon({ className = 'w-4 h-4' }: BrandIconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="10" fill="#fff" />
      <path
        d="M12 2a10 10 0 0 1 8.66 5H12a5 5 0 0 0-4.33 2.5L3.34 7A10 10 0 0 1 12 2Z"
        fill="#EA4335"
      />
      <path
        d="M20.66 7A10 10 0 0 1 12 22l4.33-7.5A5 5 0 0 0 12 7h8.66Z"
        fill="#FBBC04"
      />
      <path
        d="M12 22A10 10 0 0 1 3.34 7l4.33 7.5A5 5 0 0 0 16.33 14.5L12 22Z"
        fill="#34A853"
      />
      <circle cx="12" cy="12" r="4.35" fill="#4285F4" />
      <circle cx="12" cy="12" r="2.35" fill="#D2E3FC" />
    </svg>
  )
}

function SafariIcon({ className = 'w-4 h-4' }: BrandIconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="10" fill="#0A84FF" />
      <circle cx="12" cy="12" r="8.1" fill="none" stroke="#fff" strokeOpacity="0.55" strokeWidth="0.8" />
      <path
        d="M12 4.9v1.8M12 17.3v1.8M4.9 12h1.8M17.3 12h1.8M6.95 6.95l1.25 1.25M15.8 15.8l1.25 1.25M17.05 6.95 15.8 8.2M8.2 15.8l-1.25 1.25"
        fill="none"
        stroke="#fff"
        strokeLinecap="round"
        strokeOpacity="0.72"
      />
      <path d="M16.45 6.55 13.25 13.25 6.55 16.45 10.75 10.75 16.45 6.55Z" fill="#fff" />
      <path d="M7.55 17.45 10.75 10.75 17.45 7.55 13.25 13.25 7.55 17.45Z" fill="#FF3B30" />
      <circle cx="12" cy="12" r="1.15" fill="#fff" />
    </svg>
  )
}

function GoogleCalendarIcon({ className = 'w-4 h-4' }: BrandIconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <rect x="4" y="3.5" width="16" height="17" rx="2.5" fill="#fff" />
      <path d="M6.5 3.5h11A2.5 2.5 0 0 1 20 6v2.1H4V6a2.5 2.5 0 0 1 2.5-2.5Z" fill="#1A73E8" />
      <path d="M4 8.1h4v12.4H6.5A2.5 2.5 0 0 1 4 18V8.1Z" fill="#34A853" />
      <path d="M16 8.1h4V18a2.5 2.5 0 0 1-2.5 2.5H16V8.1Z" fill="#FBBC04" />
      <path d="M6.5 20.5h11A2.5 2.5 0 0 0 20 18v-1.4H4V18a2.5 2.5 0 0 0 2.5 2.5Z" fill="#EA4335" />
      <rect x="6.1" y="8.1" width="11.8" height="9.8" rx="1.2" fill="#fff" />
      <text x="12" y="15.7" textAnchor="middle" fontSize="7" fontWeight="700" fill="#1A73E8">
        31
      </text>
    </svg>
  )
}

function GmailIcon({ className = 'w-4 h-4' }: BrandIconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <rect x="3" y="6" width="18" height="12" rx="2.4" fill="#fff" />
      <path d="M5.4 18H8V9.55L3.35 6.35A2.35 2.35 0 0 0 3 7.6v8A2.4 2.4 0 0 0 5.4 18Z" fill="#EA4335" />
      <path d="M16 18h2.6A2.4 2.4 0 0 0 21 15.6v-8c0-.45-.13-.88-.35-1.25L16 9.55V18Z" fill="#34A853" />
      <path d="M3.35 6.35 12 12.65l8.65-6.3A2.4 2.4 0 0 0 18.6 5H5.4a2.4 2.4 0 0 0-2.05 1.35Z" fill="#EA4335" />
      <path d="M3 8.2v2.9l5 3.6v-3.15L3 8.2Z" fill="#FBBC04" />
      <path d="M21 8.2v2.9l-5 3.6v-3.15l5-3.35Z" fill="#4285F4" />
    </svg>
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
  actionLabel,
  onAction,
}: {
  icon: ReactNode
  title: string
  description: string
  status: string
  statusTone: string
  enabled: boolean
  onToggle: (checked: boolean) => void
  actionLabel?: string
  onAction?: () => void
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
      <div className="flex shrink-0 items-center gap-2">
        {actionLabel && onAction && (
          <button
            type="button"
            onClick={onAction}
            className="hidden whitespace-nowrap rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-600 hover:border-gray-300 sm:inline-flex"
          >
            {actionLabel}
          </button>
        )}
        <Toggle checked={enabled} onChange={onToggle} />
      </div>
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
