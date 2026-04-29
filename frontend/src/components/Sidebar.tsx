import { NavLink } from 'react-router-dom'
import { useState } from 'react'
import { Upload, BarChart3, Network, ListTodo, Database, Settings, ChevronLeft, ChevronRight, Brain } from 'lucide-react'

const navItems = [
  { to: '/', icon: Upload, label: '干了啥' },
  { to: '/summary', icon: BarChart3, label: '总结下' },
  { to: '/knowledge', icon: Network, label: '沉淀下' },
  { to: '/plan', icon: ListTodo, label: '规划下' },
  { to: '/data', icon: Database, label: '整理下' },
  { to: '/settings', icon: Settings, label: '配置下' },
]

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <aside className={`${collapsed ? 'w-16' : 'w-16 sm:w-60'} h-screen bg-white border-r border-gray-200 flex flex-col transition-all duration-200 shrink-0`}>
      <div className={`flex items-center gap-2 px-4 h-14 border-b border-gray-100 ${collapsed ? 'justify-center' : 'justify-center sm:justify-start'}`}>
        <Brain className="w-6 h-6 text-blue-600 shrink-0" />
        {!collapsed && <span className="hidden font-semibold text-gray-800 text-sm sm:inline">多了脑子</span>}
      </div>

      <nav className="flex-1 py-2 space-y-0.5 px-2">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                isActive
                  ? 'bg-blue-50 text-blue-700 font-medium'
                  : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
              } ${collapsed ? 'justify-center' : 'justify-center sm:justify-start'}`
            }
          >
            <Icon className="w-[18px] h-[18px] shrink-0" />
            {!collapsed && <span className="hidden sm:inline">{label}</span>}
          </NavLink>
        ))}
      </nav>

      <button
        onClick={() => setCollapsed(!collapsed)}
        className="hidden sm:flex items-center justify-center h-10 border-t border-gray-100 text-gray-400 hover:text-gray-600 transition-colors"
      >
        {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
      </button>
    </aside>
  )
}
