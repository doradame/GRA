import { useState, useEffect } from 'react'
import Login from './components/Login'
import Documents from './components/Documents'
import GraphExplorer from './components/GraphExplorer'
import Upload from './components/Upload'
import KnowledgeBaseInfo from './components/KnowledgeBaseInfo'
import ApiUsage from './components/ApiUsage'
import ResetKB from './components/ResetKB'

function App() {
  const [token, setToken] = useState<string | null>(localStorage.getItem('token'))
  const [refreshCounter, setRefreshCounter] = useState(0)

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

  return (
    <div className="min-h-screen">
      <header className="bg-slate-800 text-white p-4 shadow">
        <div className="max-w-6xl mx-auto flex justify-between items-center">
          <h1 className="text-xl font-bold">Graph RAG Assistant — Admin</h1>
          <button
            onClick={() => setToken(null)}
            className="text-sm bg-slate-700 px-3 py-1 rounded hover:bg-slate-600"
          >
            Logout
          </button>
        </div>
      </header>
      <main className="max-w-6xl mx-auto p-6 space-y-8">
        <KnowledgeBaseInfo key={refreshCounter} onTokenInvalid={() => setToken(null)} />
        <ApiUsage onTokenInvalid={() => setToken(null)} />
        <Upload
          onUploadSuccess={() => setRefreshCounter((c) => c + 1)}
          onTokenInvalid={() => setToken(null)}
        />
        <Documents key={refreshCounter} onTokenInvalid={() => setToken(null)} />
        <GraphExplorer />
        <ResetKB
          onReset={() => setRefreshCounter((c) => c + 1)}
          onTokenInvalid={() => setToken(null)}
        />
      </main>
    </div>
  )
}

export default App
