import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import RecentJobsPanel from './RecentJobsPanel'

export default function Layout() {
  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <Sidebar />
      <main className="relative min-w-0 flex-1 overflow-x-hidden overflow-y-auto">
        <RecentJobsPanel />
        <div className="mx-auto w-full max-w-7xl px-4 py-6 pb-24 sm:px-6">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
