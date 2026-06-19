import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const api = axios.create({
  baseURL: `${API_URL}/api/v1`,
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export default api

export interface Document {
  id: string
  filename: string
  content_type: string
  size_bytes: number
  description: string | null
  category: string | null
  parser: string | null
  page_count: number | null
  text_chars: number | null
  ocr_used: boolean
  status: string
  error_message: string | null
  created_at: string
}

export interface IngestionJob {
  id: string
  document_id: string
  task_id: string | null
  status: string
  phase: string
  progress: number
  retry_count: number
  error_code: string | null
  error_message: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string

  started_parsing_at: string | null
  completed_parsing_at: string | null
  started_chunking_at: string | null
  completed_chunking_at: string | null
  started_embedding_at: string | null
  completed_embedding_at: string | null
  started_vector_indexing_at: string | null
  completed_vector_indexing_at: string | null
  started_graph_indexing_at: string | null
  completed_graph_indexing_at: string | null

  chunk_count: number | null
  entity_count: number | null
  relation_count: number | null
  input_tokens: number | null
  output_tokens: number | null
  cost_estimate_usd: number | null
}

export interface GraphEntity {
  id: string
  name: string
  type: string
}

export interface GraphRelation {
  source: string
  target: string
  type: string
}

export async function login(email: string, password: string) {
  const params = new URLSearchParams()
  params.append('username', email)
  params.append('password', password)
  const res = await axios.post(`${API_URL}/api/v1/auth/login`, params, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
  return res.data
}

export async function register(email: string, password: string) {
  return api.post('/auth/register', { email, password })
}

export async function fetchDocuments() {
  const res = await api.get('/documents/')
  return res.data.items as Document[]
}

export async function fetchRecentIngestionJobs(limit = 50) {
  const res = await api.get('/documents/jobs/recent', { params: { limit } })
  return res.data.items as IngestionJob[]
}

export async function fetchDocumentIngestionJobs(documentId: string) {
  const res = await api.get(`/documents/${documentId}/jobs`)
  return res.data.items as IngestionJob[]
}

export async function uploadDocument(file: File, description?: string, category?: string) {
  const form = new FormData()
  form.append('file', file)
  if (description) form.append('description', description)
  if (category) form.append('category', category)
  const res = await api.post('/documents/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return res.data as Document
}

export async function fetchDocumentCategories() {
  const res = await api.get('/documents/categories')
  return res.data.categories as string[]
}

export async function exploreGraph(entity: string) {
  const res = await api.get('/graph/explore', { params: { entity } })
  return res.data as { entities: GraphEntity[]; relations: GraphRelation[] }
}

export async function deleteDocument(id: string) {
  return api.delete(`/documents/${id}`)
}

export async function reindexDocument(id: string) {
  const res = await api.post(`/documents/${id}/reindex`)
  return res.data as Document
}

export async function resetKnowledgeBase() {
  return api.post('/documents/reset?confirm=true')
}

export interface KBInfo {
  documents: number
  chunks: number
  entities: number
  relations: number
  vectors: number
}

export async function fetchKnowledgeBaseInfo() {
  const res = await api.get('/kb/info')
  return res.data as KBInfo
}

export interface APIUsage {
  embeddings_calls: number
  extraction_calls: number
  contextual_retrieval_calls: number
  embeddings_tokens: number
  extraction_tokens: number
  contextual_retrieval_tokens: number
}

export async function fetchApiUsage() {
  const res = await api.get('/kb/usage')
  return res.data as APIUsage
}

export interface QueryLog {
  id: string
  source: string
  user_id: string | null
  user_email: string | null
  query: string
  intent: string | null
  reasoning: string | null
  answer: string | null
  citation_count: number
  error: string | null
  latency_ms: number | null
  created_at: string

  tool_used: string | null
  iteration_count: number | null
  input_tokens: number | null
  output_tokens: number | null
  cost_estimate_usd: number | null
}

export interface QueryLogFilters {
  source?: string
  intent?: string
  q?: string
  errors_only?: boolean
  skip?: number
  limit?: number
}

export async function fetchQueryLogs(filters: QueryLogFilters = {}) {
  const res = await api.get('/logs/queries', { params: filters })
  return res.data as { items: QueryLog[]; total: number }
}

export interface ServiceHealth {
  id: string
  service: string
  status: 'ok' | 'degraded' | 'error'
  latency_ms: number | null
  last_check_at: string
  error_message: string | null
}

export interface AdminMetrics {
  documents: Record<string, number>
  recent_ingestions: IngestionJob[]
  recent_queries: QueryLog[]
  services: ServiceHealth[]
  api_usage: APIUsage
}

export async function fetchAdminMetrics() {
  const res = await api.get('/admin/metrics')
  return res.data as AdminMetrics
}

export async function fetchAdminHealth() {
  const res = await api.get('/admin/health')
  return res.data as ServiceHealth[]
}

export async function forceHealthCheck() {
  const res = await api.post('/admin/health/check')
  return res.data as ServiceHealth[]
}
