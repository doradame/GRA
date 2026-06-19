import { useState, useCallback, useEffect } from 'react'
import { fetchDocumentCategories, uploadDocument } from '../lib/api'

interface Props {
  onUploadSuccess: () => void
  onTokenInvalid: () => void
}

const OTHER_CATEGORY = 'Altro'

export default function Upload({ onUploadSuccess, onTokenInvalid }: Props) {
  const [file, setFile] = useState<File | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [status, setStatus] = useState<'idle' | 'uploading' | 'success' | 'error'>('idle')
  const [message, setMessage] = useState('')
  const [description, setDescription] = useState('')
  const [categories, setCategories] = useState<string[]>([])
  const [selectedCategory, setSelectedCategory] = useState('')
  const [customCategory, setCustomCategory] = useState('')

  useEffect(() => {
    fetchDocumentCategories()
      .then(setCategories)
      .catch(() => setCategories([]))
  }, [])

  const handleFile = (selected: File | null) => {
    if (!selected) return
    setFile(selected)
    setStatus('idle')
    setMessage('')
  }

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    handleFile(e.dataTransfer.files?.[0] || null)
  }, [])

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(true)
  }, [])

  const onDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
  }, [])

  const resolvedCategory = selectedCategory === OTHER_CATEGORY ? customCategory.trim() : selectedCategory

  const submit = async () => {
    if (!file) return
    setStatus('uploading')
    setMessage('Caricamento in corso...')
    try {
      await uploadDocument(file, description.trim() || undefined, resolvedCategory || undefined)
      setStatus('success')
      setMessage(`"${file.name}" caricato. L'ingestion è in corso in automatico.`)
      setFile(null)
      setDescription('')
      setSelectedCategory('')
      setCustomCategory('')
      onUploadSuccess()
    } catch (err: any) {
      setStatus('error')
      const detail = err.response?.data?.detail
      if (err.response?.status === 401) {
        setMessage('Sessione scaduta. Effettua di nuovo il login.')
        onTokenInvalid()
      } else {
        setMessage(detail || 'Errore durante il caricamento.')
      }
    }
  }

  return (
    <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
      <h2 className="text-lg font-semibold mb-4 text-slate-800">Carica documento</h2>
      <div
        onDrop={onDrop}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
          dragOver ? 'border-blue-500 bg-blue-50' : 'border-gray-300 bg-gray-50'
        }`}
      >
        <p className="text-gray-600 mb-4">
          Trascina qui un file oppure{' '}
          <label className="text-blue-600 underline cursor-pointer">
            selezionalo
            <input
              type="file"
              className="hidden"
              onChange={(e) => handleFile(e.target.files?.[0] || null)}
            />
          </label>
        </p>
        {file && (
          <div className="text-sm text-gray-800 bg-white border rounded px-3 py-2 inline-block">
            Selezionato: <span className="font-medium">{file.name}</span> ({(file.size / 1024).toFixed(1)} KB)
          </div>
        )}
      </div>

      <div className="mt-4 grid md:grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium mb-1 text-slate-700">
            Categoria <span className="text-slate-400 font-normal">(opzionale)</span>
          </label>
          <select
            value={selectedCategory}
            onChange={(e) => setSelectedCategory(e.target.value)}
            className="w-full border border-slate-300 rounded px-3 py-2 text-sm"
          >
            <option value="">Nessuna categoria</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          {selectedCategory === OTHER_CATEGORY && (
            <input
              type="text"
              value={customCategory}
              onChange={(e) => setCustomCategory(e.target.value)}
              placeholder="Specifica la categoria"
              className="mt-2 w-full border border-slate-300 rounded px-3 py-2 text-sm"
            />
          )}
        </div>
        <div>
          <label className="block text-sm font-medium mb-1 text-slate-700">
            Descrizione <span className="text-slate-400 font-normal">(opzionale)</span>
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Poche righe su cosa contiene questo documento: aiuta la ricerca a capire il contesto."
            className="w-full border border-slate-300 rounded px-3 py-2 text-sm h-[74px] resize-none"
          />
        </div>
      </div>

      <button
        onClick={submit}
        disabled={!file || status === 'uploading'}
        className="mt-4 w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {status === 'uploading' ? 'Caricamento...' : 'Carica e avvia ingestion'}
      </button>

      {message && (
        <div
          className={`mt-4 p-3 rounded text-sm ${
            status === 'success'
              ? 'bg-green-100 text-green-800'
              : status === 'error'
              ? 'bg-red-100 text-red-800'
              : 'bg-blue-100 text-blue-800'
          }`}
        >
          {message}
        </div>
      )}
    </div>
  )
}
