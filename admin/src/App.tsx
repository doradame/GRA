import { useState, useEffect } from 'react'
import Login from './components/Login'
import Sidebar from './components/Sidebar'
import Documents from './components/Documents'
import GraphExplorer from './components/GraphExplorer'
import Upload from './components/Upload'
import KnowledgeBaseInfo from './components/KnowledgeBaseInfo'
import ApiUsage from './components/ApiUsage'
import ResetKB from './components/ResetKB'
import QueryLogs from './components/QueryLogs'

export type Page = 'dashboard' | 'documents' | 'graph' | 'logs' | 'settings'

const PAGE_TITLES: Record<Page, string> = {
  dashboard: 'Dashboard',
  documents: 'Documenti',
  graph: 'Knowledge Graph',
  logs: 'Log Interrogazioni',
  settings: 'Impostazioni',
}

function App() {
  const [token, setToken] = useState<string | null>(localStorage.getItem('token'))
  const [refreshCounter, setRefreshCounter] = useState(0)
  const [page, setPage] = useState<Page>('dashboard')

  useEffect(() => {
    if (token) {
      localStorage.setItem('token', token)
    } else {
      localStorage.removeItem('token')
    }
  }, [token])

  if (!token) {
    return <Login onLogin={setToken} />
  }

  const handleTokenInvalid = () => setToken(null)

  return (
    <div className="min-h-screen flex bg-slate-100">
      <Sidebar active={page} onNavigate={setPage} onLogout={handleTokenInvalid} />
      <div className="flex-1 flex flex-col min-w-0">
        <header className="bg-white border-b border-slate-200 px-6 md:px-8 py-4">
          <h1 className="text-lg font-semibold text-slate-800">{PAGE_TITLES[page]}</h1>
        </header>
        <main className="flex-1 w-full max-w-6xl mx-auto p-6 md:p-8 space-y-6">
          {page === 'dashboard' && (
            <>
              <KnowledgeBaseInfo key={refreshCounter} onTokenInvalid={handleTokenInvalid} />
              <ApiUsage onTokenInvalid={handleTokenInvalid} />
            </>
          )}

          {page === 'documents' && (
            <>
              <Upload
                onUploadSuccess={() => setRefreshCounter((c) => c + 1)}
                onTokenInvalid={handleTokenInvalid}
              />
              <Documents key={refreshCounter} onTokenInvalid={handleTokenInvalid} />
            </>
          )}

          {page === 'graph' && <GraphExplorer onTokenInvalid={handleTokenInvalid} />}

          {page === 'logs' && <QueryLogs onTokenInvalid={handleTokenInvalid} />}

          {page === 'settings' && (
            <ResetKB onReset={() => setRefreshCounter((c) => c + 1)} onTokenInvalid={handleTokenInvalid} />
          )}
        </main>
      </div>
    </div>
  )
}

export default App
