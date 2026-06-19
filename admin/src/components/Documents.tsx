import { useEffect, useState, useCallback } from 'react'
import {
  fetchDocuments,
  fetchRecentIngestionJobs,
  deleteDocument,
  reindexDocument,
  Document,
  IngestionJob,
} from '../lib/api'

interface Props {
  onTokenInvalid: () => void
}

export default function Documents({ onTokenInvalid }: Props) {
  const [docs, setDocs] = useState<Document[]>([])
  const [jobsByDocument, setJobsByDocument] = useState<Record<string, IngestionJob>>({})
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    Promise.all([fetchDocuments(), fetchRecentIngestionJobs()])
      .then(([documents, jobs]) => {
        setDocs(documents)
        const latest: Record<string, IngestionJob> = {}
        for (const job of jobs) {
          if (!latest[job.document_id]) latest[job.document_id] = job
        }
        setJobsByDocument(latest)
      })
      .catch((err) => {
        if (err.response?.status === 401) onTokenInvalid()
      })
      .finally(() => setLoading(false))
  }, [onTokenInvalid])

  useEffect(() => {
    load()
    const interval = setInterval(load, 3000)
    return () => clearInterval(interval)
  }, [load])

  const statusColor = (status: string) => {
    switch (status) {
      case 'completed':
        return 'bg-green-100 text-green-800'
      case 'uploaded':
      case 'parsing':
      case 'chunking':
      case 'embedding':
      case 'vector_indexing':
      case 'graph_indexing':
        return 'bg-yellow-100 text-yellow-800'
      case 'error':
        return 'bg-red-100 text-red-800'
      default:
        return 'bg-gray-100 text-gray-800'
    }
  }

  const handleDelete = async (id: string, filename: string) => {
    if (!confirm(`Eliminare il documento "${filename}" dalla knowledge base?`)) return
    try {
      await deleteDocument(id)
      load()
    } catch (err) {
      alert('Errore durante l\'eliminazione')
    }
  }

  const handleReindex = async (id: string, filename: string) => {
    if (!confirm(`Reindicizzare il documento "${filename}"?`)) return
    try {
      await reindexDocument(id)
      load()
    } catch (err) {
      alert('Errore durante la reindicizzazione')
    }
  }

  if (loading) return <div className="text-center py-8 text-slate-500">Caricamento...</div>

  return (
    <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-semibold text-slate-800">Documenti caricati</h2>
        <button
          onClick={load}
          className="text-sm bg-slate-100 text-slate-700 px-3 py-1 rounded hover:bg-slate-200"
        >
          Aggiorna
        </button>
      </div>

      {docs.length === 0 ? (
        <p className="text-gray-500">Nessun documento caricato.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left">
              <th className="pb-2">Nome</th>
              <th className="pb-2">Tipo</th>
              <th className="pb-2">Dimensione</th>
              <th className="pb-2">Stato</th>
              <th className="pb-2">Data</th>
              <th className="pb-2">Azioni</th>
            </tr>
          </thead>
          <tbody>
            {docs.map((doc) => {
              const job = jobsByDocument[doc.id]
              const progress = job?.progress ?? (doc.status === 'completed' ? 100 : 0)
              return (
                <tr key={doc.id} className="border-b last:border-0">
                  <td className="py-2">{doc.filename}</td>
                  <td className="py-2">
                    <div>{doc.content_type}</div>
                    {doc.parser && (
                      <div className="text-xs text-slate-500">
                        {doc.parser}
                        {doc.page_count ? ` · ${doc.page_count}p` : ''}
                        {doc.text_chars ? ` · ${doc.text_chars} chars` : ''}
                        {doc.ocr_used ? ' · OCR' : ''}
                      </div>
                    )}
                  </td>
                  <td className="py-2">{(doc.size_bytes / 1024).toFixed(1)} KB</td>
                  <td className="py-2 min-w-40">
                    <span className={`px-2 py-1 rounded text-xs ${statusColor(doc.status)}`}>
                      {job?.phase ?? doc.status}
                    </span>
                    <div className="mt-2 h-1.5 w-32 bg-slate-100 rounded overflow-hidden">
                      <div
                        className="h-full bg-slate-700"
                        style={{ width: `${Math.min(Math.max(progress, 0), 100)}%` }}
                      />
                    </div>
                    {job?.error_message && (
                      <div className="mt-1 text-xs text-red-700 max-w-xs truncate">
                        {job.error_message}
                      </div>
                    )}
                  </td>
                  <td className="py-2">{new Date(doc.created_at).toLocaleString('it-IT')}</td>
                  <td className="py-2">
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleReindex(doc.id, doc.filename)}
                        className="text-xs bg-slate-100 text-slate-700 px-2 py-1 rounded hover:bg-slate-200"
                      >
                        Reindex
                      </button>
                      <button
                        onClick={() => handleDelete(doc.id, doc.filename)}
                        className="text-xs bg-red-100 text-red-700 px-2 py-1 rounded hover:bg-red-200"
                      >
                        Elimina
                      </button>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      <p className="mt-4 text-xs text-gray-500">
        L’ingestion parte automaticamente dopo il caricamento e mostra la fase corrente.
      </p>
    </div>
  )
}
