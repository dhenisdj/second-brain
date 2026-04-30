import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import RecentJobsPanel from './RecentJobsPanel'

export default function Layout() {
  return (
    <div className="flex h-screen w-screen max-w-full overflow-hidden bg-slate-50">
      <Sidebar />
      <main className="relative w-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto">
        <RecentJobsPanel />
        <div className="mx-auto w-full max-w-7xl px-2 py-4 pb-24 sm:px-6 sm:py-6">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
