import { useEffect, useState, useCallback } from 'react'
import { fetchKnowledgeBaseInfo, KBInfo } from '../lib/api'

interface Props {
  onTokenInvalid: () => void
}

export default function KnowledgeBaseInfo({ onTokenInvalid }: Props) {
  const [info, setInfo] = useState<KBInfo | null>(null)

  const load = useCallback(() => {
    fetchKnowledgeBaseInfo()
      .then(setInfo)
      .catch((err) => {
        if (err.response?.status === 401) onTokenInvalid()
      })
  }, [onTokenInvalid])

  useEffect(() => {
    load()
    const interval = setInterval(load, 5000)
    return () => clearInterval(interval)
  }, [load])

  if (!info) {
    return <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200">Caricamento info...</div>
  }

  return (
    <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
      <h2 className="text-lg font-semibold mb-4 text-slate-800">Info Knowledge Base</h2>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <div className="bg-blue-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-blue-700">{info.documents}</div>
          <div className="text-xs text-blue-600">Documenti</div>
        </div>
        <div className="bg-green-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-green-700">{info.chunks}</div>
          <div className="text-xs text-green-600">Chunk</div>
        </div>
        <div className="bg-purple-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-purple-700">{info.entities}</div>
          <div className="text-xs text-purple-600">Entità</div>
        </div>
        <div className="bg-orange-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-orange-700">{info.relations}</div>
          <div className="text-xs text-orange-600">Relazioni</div>
        </div>
        <div className="bg-gray-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-gray-700">{info.vectors}</div>
          <div className="text-xs text-gray-600">Vettori</div>
        </div>
      </div>
    </div>
  )
}
