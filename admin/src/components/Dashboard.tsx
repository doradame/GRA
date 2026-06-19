import { useEffect, useState, useCallback } from 'react'
import KnowledgeBaseInfo from './KnowledgeBaseInfo'
import ApiUsage from './ApiUsage'
import {
  fetchAdminMetrics,
  fetchAdminHealth,
  forceHealthCheck,
  AdminMetrics,
  ServiceHealth,
} from '../lib/api'

interface Props {
  onTokenInvalid: () => void
  refreshCounter: number
}

export default function Dashboard({ onTokenInvalid, refreshCounter }: Props) {
  const [metrics, setMetrics] = useState<AdminMetrics | null>(null)
  const [health, setHealth] = useState<ServiceHealth[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const [m, h] = await Promise.all([fetchAdminMetrics(), fetchAdminHealth()])
      setMetrics(m)
      setHealth(h)
    } catch (err: any) {
      if (err.response?.status === 401) onTokenInvalid()
    } finally {
      setLoading(false)
    }
  }, [onTokenInvalid])

  useEffect(() => {
    load()
    const interval = setInterval(load, 5000)
    return () => clearInterval(interval)
  }, [load, refreshCounter])

  const handleRefreshHealth = async () => {
    setLoading(true)
    try {
      const h = await forceHealthCheck()
      setHealth(h)
    } finally {
      setLoading(false)
    }
  }

  const serviceColor = (status: string) => {
    switch (status) {
      case 'ok':
        return 'bg-green-500'
      case 'degraded':
        return 'bg-yellow-500'
      case 'error':
        return 'bg-red-500'
      default:
        return 'bg-gray-400'
    }
  }

  if (loading && !metrics) {
    return <div className="p-6 text-slate-500">Caricamento dashboard...</div>
  }

  const errorCount = metrics?.documents.error ?? 0

  return (
    <div className="space-y-6">
      {errorCount > 0 && (
        <div className="bg-red-50 border border-red-200 text-red-800 px-4 py-3 rounded-lg">
          Attenzione: {errorCount} documento/i in errore.
        </div>
      )}

      <KnowledgeBaseInfo onTokenInvalid={onTokenInvalid} />

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="Documenti completati"
          value={metrics?.documents.completed ?? 0}
        />
        <MetricCard
          label="Ingestion attive"
          value={
            (metrics?.documents.parsing ?? 0) +
            (metrics?.documents.chunking ?? 0) +
            (metrics?.documents.embedding ?? 0) +
            (metrics?.documents.vector_indexing ?? 0) +
            (metrics?.documents.graph_indexing ?? 0)
          }
        />
        <MetricCard
          label="Query 24h"
          value={metrics?.recent_queries.length ?? 0}
        />
        <MetricCard
          label="Servizi down"
          value={health.filter((s) => s.status === 'error').length}
        />
      </div>

      <ApiUsage onTokenInvalid={onTokenInvalid} />

      <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
        <div className="flex justify-between items-center mb-4">
          <h3 className="font-semibold text-slate-800">Stato servizi</h3>
          <button
            onClick={handleRefreshHealth}
            className="text-sm bg-slate-100 text-slate-700 px-3 py-1 rounded hover:bg-slate-200"
          >
            Aggiorna ora
          </button>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          {health.map((svc) => (
            <div key={svc.service} className="border rounded-lg p-3">
              <div className="flex items-center gap-2">
                <div className={`w-3 h-3 rounded-full ${serviceColor(svc.status)}`} />
                <span className="font-medium capitalize">{svc.service}</span>
              </div>
              <div className="text-sm text-slate-500 mt-1">
                {svc.latency_ms !== null ? `${svc.latency_ms} ms` : 'N/A'}
              </div>
              {svc.error_message && (
                <div className="text-xs text-red-600 mt-1">{svc.error_message}</div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
        <h3 className="font-semibold text-slate-800 mb-4">Ingestion recenti</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left">
                <th className="pb-2">Fase</th>
                <th className="pb-2">Progresso</th>
                <th className="pb-2">Chunk</th>
                <th className="pb-2">Entità</th>
                <th className="pb-2">Relazioni</th>
                <th className="pb-2">Costo</th>
              </tr>
            </thead>
            <tbody>
              {(metrics?.recent_ingestions ?? []).map((job) => (
                <tr key={job.id} className="border-b last:border-0">
                  <td className="py-2">{job.phase}</td>
                  <td className="py-2">{job.progress}%</td>
                  <td className="py-2">{job.chunk_count ?? '-'}</td>
                  <td className="py-2">{job.entity_count ?? '-'}</td>
                  <td className="py-2">{job.relation_count ?? '-'}</td>
                  <td className="py-2">
                    ${job.cost_estimate_usd?.toFixed(4) ?? '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
        <h3 className="font-semibold text-slate-800 mb-4">Query recenti</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left">
                <th className="pb-2">Query</th>
                <th className="pb-2">Intent</th>
                <th className="pb-2">Tool</th>
                <th className="pb-2">Iterazioni</th>
                <th className="pb-2">Latenza</th>
              </tr>
            </thead>
            <tbody>
              {(metrics?.recent_queries ?? []).map((q) => (
                <tr key={q.id} className="border-b last:border-0">
                  <td className="py-2 max-w-xs truncate">{q.query}</td>
                  <td className="py-2">{q.intent ?? '-'}</td>
                  <td className="py-2">{q.tool_used ?? '-'}</td>
                  <td className="py-2">{q.iteration_count ?? '-'}</td>
                  <td className="py-2">
                    {q.latency_ms ? `${q.latency_ms} ms` : '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function MetricCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-white p-4 rounded-xl shadow-sm border border-slate-200">
      <div className="text-2xl font-semibold text-slate-800">{value}</div>
      <div className="text-sm text-slate-500">{label}</div>
    </div>
  )
}
