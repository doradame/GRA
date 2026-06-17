import { useState } from 'react'
import { exploreGraph, GraphEntity, GraphRelation } from '../lib/api'

export default function GraphExplorer() {
  const [query, setQuery] = useState('')
  const [entities, setEntities] = useState<GraphEntity[]>([])
  const [relations, setRelations] = useState<GraphRelation[]>([])
  const [loading, setLoading] = useState(false)

  const search = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!query.trim()) return
    setLoading(true)
    try {
      const data = await exploreGraph(query)
      setEntities(data.entities)
      setRelations(data.relations)
    } catch (err) {
      alert('Errore nella ricerca del grafo')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="bg-white p-6 rounded shadow">
      <h2 className="text-lg font-semibold mb-4">Esplora Knowledge Graph</h2>
      <form onSubmit={search} className="flex gap-2 mb-4">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Cerca un'entità (es. garanzia, esclusione, prodotto)"
          className="flex-1 border rounded px-3 py-2"
        />
        <button
          type="submit"
          disabled={loading}
          className="bg-slate-800 text-white px-4 py-2 rounded hover:bg-slate-700 disabled:opacity-50"
        >
          {loading ? '...' : 'Cerca'}
        </button>
      </form>

      {entities.length > 0 && (
        <div className="mb-4">
          <h3 className="font-medium mb-2">Entità trovate</h3>
          <div className="flex flex-wrap gap-2">
            {entities.map((e) => (
              <span key={e.id} className="bg-blue-50 text-blue-800 px-3 py-1 rounded text-sm border border-blue-100">
                {e.name} <span className="text-xs text-blue-500">({e.type})</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {relations.length > 0 && (
        <div>
          <h3 className="font-medium mb-2">Relazioni</h3>
          <ul className="space-y-1 text-sm">
            {relations.map((rel, idx) => (
              <li key={idx} className="bg-gray-50 p-2 rounded">
                <span className="font-medium">{rel.source}</span>
                <span className="text-slate-500 mx-2">— {rel.type} →</span>
                <span className="font-medium">{rel.target}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
