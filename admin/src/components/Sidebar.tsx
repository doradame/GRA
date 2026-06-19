import type { Page } from '../App'

interface NavItem {
  id: Page
  label: string
}

const NAV_ITEMS: NavItem[] = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'documents', label: 'Documenti' },
  { id: 'graph', label: 'Knowledge Graph' },
  { id: 'logs', label: 'Log Interrogazioni' },
  { id: 'settings', label: 'Impostazioni' },
]

function NavIcon({ id }: { id: Page }) {
  const common = { className: 'w-5 h-5', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8 }
  switch (id) {
    case 'dashboard':
      return (
        <svg {...common} viewBox="0 0 24 24">
          <rect x="3" y="3" width="7" height="7" rx="1.5" />
          <rect x="14" y="3" width="7" height="7" rx="1.5" />
          <rect x="3" y="14" width="7" height="7" rx="1.5" />
          <rect x="14" y="14" width="7" height="7" rx="1.5" />
        </svg>
      )
    case 'documents':
      return (
        <svg {...common} viewBox="0 0 24 24">
          <path d="M6 3h8l4 4v14H6z" strokeLinejoin="round" />
          <path d="M14 3v4h4" strokeLinejoin="round" />
          <line x1="9" y1="12" x2="15" y2="12" />
          <line x1="9" y1="16" x2="15" y2="16" />
        </svg>
      )
    case 'graph':
      return (
        <svg {...common} viewBox="0 0 24 24">
          <circle cx="6" cy="6" r="2.5" />
          <circle cx="18" cy="6" r="2.5" />
          <circle cx="12" cy="18" r="2.5" />
          <line x1="8" y1="7.2" x2="10.2" y2="16" />
          <line x1="16" y1="7.2" x2="13.8" y2="16" />
          <line x1="8.5" y1="6" x2="15.5" y2="6" />
        </svg>
      )
    case 'logs':
      return (
        <svg {...common} viewBox="0 0 24 24">
          <rect x="3" y="4" width="18" height="16" rx="1.5" />
          <line x1="6.5" y1="9" x2="9" y2="11" />
          <line x1="6.5" y1="13" x2="9" y2="11" />
          <line x1="11" y1="14" x2="17.5" y2="14" />
        </svg>
      )
    case 'settings':
      return (
        <svg {...common} viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="3" />
          <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" />
        </svg>
      )
  }
}

interface Props {
  active: Page
  onNavigate: (page: Page) => void
  onLogout: () => void
}

export default function Sidebar({ active, onNavigate, onLogout }: Props) {
  return (
    <aside className="w-60 bg-slate-900 text-slate-300 flex flex-col shrink-0">
      <div className="px-5 py-5 border-b border-slate-800">
        <div className="text-white font-semibold leading-tight">Graph RAG</div>
        <div className="text-xs text-slate-400">Assistant — Admin</div>
      </div>
      <nav className="flex-1 px-3 py-4 space-y-1">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            onClick={() => onNavigate(item.id)}
            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
              active === item.id
                ? 'bg-slate-800 text-white'
                : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-100'
            }`}
          >
            <NavIcon id={item.id} />
            {item.label}
          </button>
        ))}
      </nav>
      <div className="px-3 py-4 border-t border-slate-800">
        <button
          onClick={onLogout}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-slate-400 hover:bg-slate-800/60 hover:text-slate-100"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
            <path d="M15 17l5-5-5-5M20 12H9M13 21H6a2 2 0 01-2-2V5a2 2 0 012-2h7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Logout
        </button>
      </div>
    </aside>
  )
}
