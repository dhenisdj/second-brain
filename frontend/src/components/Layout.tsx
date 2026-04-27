import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import RecentJobsPanel from './RecentJobsPanel'

export default function Layout() {
  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <Sidebar />
      <main className="relative flex-1 overflow-y-auto">
        <RecentJobsPanel />
        <div className="max-w-7xl mx-auto px-6 py-6 pb-24">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
