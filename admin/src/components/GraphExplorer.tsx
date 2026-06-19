import { useState } from 'react'
import { exploreGraph, GraphEntity, GraphRelation } from '../lib/api'

interface Props {
  onTokenInvalid: () => void
}

export default function GraphExplorer({ onTokenInvalid }: Props) {
  const [query, setQuery] = useState('')
  const [entities, setEntities] = useState<GraphEntity[]>([])
  const [relations, setRelations] = useState<GraphRelation[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [searchedFor, setSearchedFor] = useState<string | null>(null)

  const search = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!query.trim()) return
    setLoading(true)
    setError('')
    try {
      const data = await exploreGraph(query)
      setEntities(data.entities)
      setRelations(data.relations)
      setSearchedFor(query)
    } catch (err: any) {
      if (err.response?.status === 401) {
        onTokenInvalid()
      } else {
        setError('Errore nella ricerca del grafo. Riprova.')
      }
    } finally {
      setLoading(false)
    }
  }

  const noResults = searchedFor !== null && !loading && !error && entities.length === 0

  return (
    <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
      <h2 className="text-lg font-semibold mb-1 text-slate-800">Esplora Knowledge Graph</h2>
      <p className="text-sm text-slate-500 mb-4">
        Cerca un'entità per nome (persona, organizzazione, concetto, ecc.) così come compare nei documenti caricati.
      </p>
      <form onSubmit={search} className="flex gap-2 mb-4">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Es. un nome di persona, organizzazione o concetto presente nei documenti"
          className="flex-1 border border-slate-300 rounded px-3 py-2"
        />
        <button
          type="submit"
          disabled={loading || !query.trim()}
          className="bg-slate-800 text-white px-4 py-2 rounded hover:bg-slate-700 disabled:opacity-50"
        >
          {loading ? '...' : 'Cerca'}
        </button>
      </form>

      {error && <div className="bg-red-100 text-red-700 p-3 rounded mb-4 text-sm">{error}</div>}

      {noResults && (
        <p className="text-slate-500 text-sm">
          Nessuna entità trovata per "{searchedFor}". Prova con un altro termine: la ricerca confronta il testo
          digitato con il nome esatto delle entità estratte dai documenti.
        </p>
      )}

      {entities.length > 0 && (
        <div className="mb-4">
          <h3 className="font-medium mb-2 text-slate-700">Entità trovate</h3>
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
          <h3 className="font-medium mb-2 text-slate-700">Relazioni</h3>
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

      {entities.length > 0 && relations.length === 0 && (
        <p className="mt-3 text-xs text-slate-400">
          Nessuna relazione diretta tra entità trovata per questo termine (l'entità compare nei documenti ma non è
          ancora collegata ad altre entità nel grafo).
        </p>
      )}
    </div>
  )
}
