import { useEffect, useState, useCallback } from 'react'
import { fetchApiUsage, APIUsage } from '../lib/api'

interface Props {
  onTokenInvalid: () => void
}

export default function ApiUsage({ onTokenInvalid }: Props) {
  const [usage, setUsage] = useState<APIUsage | null>(null)

  const load = useCallback(() => {
    fetchApiUsage()
      .then(setUsage)
      .catch((err) => {
        if (err.response?.status === 401) onTokenInvalid()
      })
  }, [onTokenInvalid])

  useEffect(() => {
    load()
    const interval = setInterval(load, 5000)
    return () => clearInterval(interval)
  }, [load])

  if (!usage) {
    return <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200">Caricamento uso API...</div>
  }

  const totalCalls = usage.embeddings_calls + usage.extraction_calls
  const totalTokens = usage.embeddings_tokens + usage.extraction_tokens

  return (
    <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200 border-l-4 border-l-indigo-500">
      <h2 className="text-lg font-semibold mb-4 text-indigo-700">Uso API OpenAI</h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-indigo-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-indigo-700">{usage.embeddings_calls}</div>
          <div className="text-xs text-indigo-600">Chiamate Embeddings</div>
        </div>
        <div className="bg-pink-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-pink-700">{usage.extraction_calls}</div>
          <div className="text-xs text-pink-600">Chiamate Estrazione</div>
        </div>
        <div className="bg-teal-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-teal-700">{totalCalls}</div>
          <div className="text-xs text-teal-600">Totale Chiamate</div>
        </div>
        <div className="bg-amber-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-amber-700">{totalTokens.toLocaleString('it-IT')}</div>
          <div className="text-xs text-amber-600">Totale Token</div>
        </div>
      </div>
      <p className="mt-4 text-xs text-gray-500">
        Ogni chunk genera 2 chiamate: una per gli embeddings e una per l’estrazione di entità/relazioni.
        I contatori si azzerano con il reset della Knowledge Base.
      </p>
    </div>
  )
}
