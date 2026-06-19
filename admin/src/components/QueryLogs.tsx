import { Fragment, useCallback, useEffect, useState } from 'react'
import { fetchQueryLogs, QueryLog } from '../lib/api'

interface Props {
  onTokenInvalid: () => void
}

const SOURCE_STYLES: Record<string, string> = {
  librechat: 'bg-indigo-100 text-indigo-800',
  mcp: 'bg-purple-100 text-purple-800',
  admin: 'bg-slate-100 text-slate-700',
  api: 'bg-slate-100 text-slate-700',
}

const INTENT_STYLES: Record<string, string> = {
  factual: 'bg-blue-100 text-blue-800',
  relational: 'bg-orange-100 text-orange-800',
  summary: 'bg-green-100 text-green-800',
  direct: 'bg-gray-100 text-gray-700',
}

const PAGE_SIZE = 25

export default function QueryLogs({ onTokenInvalid }: Props) {
  const [items, setItems] = useState<QueryLog[]>([])
  const [total, setTotal] = useState(0)
  const [skip, setSkip] = useState(0)
  const [source, setSource] = useState('')
  const [intent, setIntent] = useState('')
  const [search, setSearch] = useState('')
  const [errorsOnly, setErrorsOnly] = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    fetchQueryLogs({
      source: source || undefined,
      intent: intent || undefined,
      q: search || undefined,
      errors_only: errorsOnly || undefined,
      skip,
      limit: PAGE_SIZE,
    })
      .then(({ items, total }) => {
        setItems(items)
        setTotal(total)
      })
      .catch((err) => {
        if (err.response?.status === 401) onTokenInvalid()
      })
      .finally(() => setLoading(false))
  }, [source, intent, search, errorsOnly, skip, onTokenInvalid])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (!autoRefresh) return
    const interval = setInterval(load, 5000)
    return () => clearInterval(interval)
  }, [autoRefresh, load])

  useEffect(() => {
    setSkip(0)
  }, [source, intent, search, errorsOnly])

  const fmtTime = (iso: string) => new Date(iso).toLocaleString('it-IT')

  return (
    <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
      <div className="flex flex-wrap justify-between items-start gap-4 mb-4">
        <div>
          <h2 className="text-lg font-semibold">Log interrogazioni</h2>
          <p className="text-sm text-slate-500">
            Domande arrivate da LibreChat, MCP o altri client: instradamento dell'agente e risposta generata.
          </p>
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-600 whitespace-nowrap">
          <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} />
          Aggiornamento automatico
        </label>
      </div>

      <div className="flex flex-wrap gap-3 mb-4">
        <select
          value={source}
          onChange={(e) => setSource(e.target.value)}
          className="border border-slate-300 rounded px-3 py-1.5 text-sm"
        >
          <option value="">Tutte le origini</option>
          <option value="librechat">LibreChat</option>
          <option value="mcp">MCP</option>
          <option value="admin">Admin</option>
        </select>
        <select
          value={intent}
          onChange={(e) => setIntent(e.target.value)}
          className="border border-slate-300 rounded px-3 py-1.5 text-sm"
        >
          <option value="">Tutti gli intenti</option>
          <option value="factual">Factual</option>
          <option value="relational">Relational</option>
          <option value="summary">Summary</option>
          <option value="direct">Direct</option>
        </select>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Cerca nel testo della domanda..."
          className="border border-slate-300 rounded px-3 py-1.5 text-sm flex-1 min-w-48"
        />
        <label className="flex items-center gap-2 text-sm text-slate-600 whitespace-nowrap">
          <input type="checkbox" checked={errorsOnly} onChange={(e) => setErrorsOnly(e.target.checked)} />
          Solo errori
        </label>
        <button
          onClick={load}
          className="text-sm bg-slate-100 text-slate-700 px-3 py-1.5 rounded hover:bg-slate-200"
        >
          Aggiorna
        </button>
      </div>

      {loading ? (
        <div className="text-center py-8 text-slate-500">Caricamento...</div>
      ) : items.length === 0 ? (
        <p className="text-slate-500">Nessuna interrogazione trovata.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-slate-500">
                <th className="pb-2 pr-3 font-medium">Data/ora</th>
                <th className="pb-2 pr-3 font-medium">Origine</th>
                <th className="pb-2 pr-3 font-medium">Intento</th>
                <th className="pb-2 pr-3 font-medium">Domanda</th>
                <th className="pb-2 pr-3 font-medium">Citazioni</th>
                <th className="pb-2 pr-3 font-medium">Latenza</th>
                <th className="pb-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {items.map((log) => (
                <Fragment key={log.id}>
                  <tr
                    onClick={() => setExpanded(expanded === log.id ? null : log.id)}
                    className={`border-b last:border-0 cursor-pointer hover:bg-slate-50 ${
                      log.error ? 'bg-red-50/60' : ''
                    }`}
                  >
                    <td className="py-2 pr-3 whitespace-nowrap text-slate-500">{fmtTime(log.created_at)}</td>
                    <td className="py-2 pr-3">
                      <span className={`px-2 py-0.5 rounded text-xs ${SOURCE_STYLES[log.source] ?? 'bg-slate-100 text-slate-700'}`}>
                        {log.source}
                      </span>
                    </td>
                    <td className="py-2 pr-3">
                      {log.intent && (
                        <span className={`px-2 py-0.5 rounded text-xs ${INTENT_STYLES[log.intent] ?? 'bg-gray-100 text-gray-700'}`}>
                          {log.intent}
                        </span>
                      )}
                      {log.error && (
                        <span className="ml-1 px-2 py-0.5 rounded text-xs bg-red-100 text-red-700">errore</span>
                      )}
                    </td>
                    <td className="py-2 pr-3 max-w-md truncate">{log.query}</td>
                    <td className="py-2 pr-3">{log.citation_count}</td>
                    <td className="py-2 pr-3 text-slate-500 whitespace-nowrap">
                      {log.latency_ms != null ? `${log.latency_ms} ms` : '—'}
                    </td>
                    <td className="py-2 text-slate-400">{expanded === log.id ? '▲' : '▼'}</td>
                  </tr>
                  {expanded === log.id && (
                    <tr className="bg-slate-50 border-b">
                      <td colSpan={7} className="p-4">
                        <div className="grid md:grid-cols-2 gap-6 text-sm">
                          <div>
                            <div className="font-medium text-slate-700 mb-1">Domanda</div>
                            <p className="whitespace-pre-wrap text-slate-600">{log.query}</p>
                            {log.reasoning && (
                              <>
                                <div className="font-medium text-slate-700 mt-3 mb-1">Motivazione instradamento</div>
                                <p className="text-slate-600">{log.reasoning}</p>
                              </>
                            )}
                            {log.user_email && (
                              <p className="mt-3 text-xs text-slate-400">Utente: {log.user_email}</p>
                            )}
                          </div>
                          <div>
                            {log.error ? (
                              <>
                                <div className="font-medium text-red-700 mb-1">Errore</div>
                                <p className="text-red-600 whitespace-pre-wrap">{log.error}</p>
                              </>
                            ) : (
                              <>
                                <div className="font-medium text-slate-700 mb-1">Risposta</div>
                                <p className="whitespace-pre-wrap text-slate-600">{log.answer || '—'}</p>
                              </>
                            )}
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {total > PAGE_SIZE && (
        <div className="flex justify-between items-center mt-4 text-sm text-slate-500">
          <span>
            {skip + 1}-{Math.min(skip + PAGE_SIZE, total)} di {total}
          </span>
          <div className="flex gap-2">
            <button
              disabled={skip === 0}
              onClick={() => setSkip(Math.max(0, skip - PAGE_SIZE))}
              className="px-3 py-1 rounded border border-slate-300 disabled:opacity-40"
            >
              Precedente
            </button>
            <button
              disabled={skip + PAGE_SIZE >= total}
              onClick={() => setSkip(skip + PAGE_SIZE)}
              className="px-3 py-1 rounded border border-slate-300 disabled:opacity-40"
            >
              Successivo
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
