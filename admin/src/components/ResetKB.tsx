import { useState } from 'react'
import { resetKnowledgeBase } from '../lib/api'

interface Props {
  onReset: () => void
  onTokenInvalid: () => void
}

export default function ResetKB({ onReset, onTokenInvalid }: Props) {
  const [status, setStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle')
  const [message, setMessage] = useState('')

  const handleReset = async () => {
    if (!confirm('ATTENZIONE: questa operazione cancellerà TUTTI i documenti, chunk, entità e relazioni. Sei sicuro?')) {
      return
    }
    setStatus('loading')
    try {
      await resetKnowledgeBase()
      setStatus('success')
      setMessage('Knowledge base resettata con successo.')
      onReset()
    } catch (err: any) {
      setStatus('error')
      if (err.response?.status === 403) {
        setMessage('Operazione riservata agli amministratori.')
      } else {
        setMessage(err.response?.data?.detail || 'Errore durante il reset.')
      }
      if (err.response?.status === 401) onTokenInvalid()
    }
  }

  return (
    <div className="bg-white p-6 rounded shadow border-l-4 border-red-500">
      <h2 className="text-lg font-semibold mb-2 text-red-700">Zona pericolosa</h2>
      <p className="text-sm text-gray-600 mb-4">
        Cancella tutti i documenti, chunk, vettori, entità e relazioni. Irreversibile.
      </p>
      <button
        onClick={handleReset}
        disabled={status === 'loading'}
        className="bg-red-600 text-white px-4 py-2 rounded hover:bg-red-700 disabled:opacity-50"
      >
        {status === 'loading' ? 'Reset in corso...' : 'Resetta Knowledge Base'}
      </button>
      {message && (
        <div
          className={`mt-3 p-3 rounded text-sm ${
            status === 'success' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
          }`}
        >
          {message}
        </div>
      )}
    </div>
  )
}
