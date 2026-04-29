import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'react-hot-toast'
import Layout from './components/Layout'
import IngestPage from './pages/IngestPage'
import SummaryPage from './pages/SummaryPage'
import KnowledgePage from './pages/KnowledgePage'
import PlanPage from './pages/PlanPage'
import DataManagePage from './pages/DataManagePage'
import SettingsPage from './pages/SettingsPage'
import { useSettings } from './hooks/queries'

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1 } },
})

function SettingsPreflight() {
  useSettings()
  return null
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <SettingsPreflight />
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<IngestPage />} />
            <Route path="summary" element={<SummaryPage />} />
            <Route path="knowledge" element={<KnowledgePage />} />
            <Route path="plan" element={<PlanPage />} />
            <Route path="data" element={<DataManagePage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
      <Toaster position="top-right" toastOptions={{ duration: 3000, style: { fontSize: '14px' } }} />
    </QueryClientProvider>
  )
}
