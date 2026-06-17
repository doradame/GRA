# Graph RAG Assistant

Sistema Graph RAG self-hosted per interrogare qualsiasi insieme di documenti tramite linguaggio naturale.

L’assistente diventa esperto della knowledge base che gli viene fornita: manuali tecnici, criteri assuntivi, regolamenti, contratti, documentazione aziendale, articoli scientifici, ecc.

## Architettura

- **Backend**: FastAPI (Python) — ingestion, Graph RAG, API compatibile OpenAI.
- **Knowledge Base**: Neo4j (grafo) + Qdrant (vettori) + MinIO (documenti originali).
- **Frontend Chat**: LibreChat (self-hosted), connesso al backend come API OpenAI custom.
- **Pannello Admin**: React + Vite — upload, monitoraggio ingestion, esplorazione grafo.
- **MCP Server**: server MCP per riusare la KB in altri LLM/agenti compatibili.
- **Reverse Proxy**: Caddy con HTTPS automatico via Let's Encrypt.

## Prerequisiti

- Docker + Docker Compose
- OpenAI API Key (consigliato per embedding e risposte LLM)
- Un dominio puntato al server (es. `matamune.4nk.eu`)

## Avvio rapido

1. Copia e configura le variabili d'ambiente:

```bash
cp .env.example .env
# Modifica OPENAI_API_KEY, SECRET_KEY, NEO4J_PASSWORD, MCP_API_KEY, MEILI_MASTER_KEY
```

2. Crea le directory per i dati persistenti:

```bash
mkdir -p data/{postgres,neo4j/{data,logs},qdrant,minio,caddy/{data,config},mongo,meilisearch,documents}
```

3. Avvia tutto lo stack:

```bash
docker compose up -d
```

4. Crea un utente tramite l'API:

```bash
curl -X POST https://api.matamune.4nk.eu/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"secret"}'
```

5. Accedi al pannello admin: https://admin.matamune.4nk.eu

6. Carica i tuoi documenti PDF/DOCX/TXT/HTML dal pannello admin. L’ingestion parte automaticamente.

7. Accedi a LibreChat: https://chat.matamune.4nk.eu

## URL esposti

| Servizio | URL pubblico |
|---|---|
| Pannello Admin | https://admin.matamune.4nk.eu |
| API Backend | https://api.matamune.4nk.eu |
| Chat (LibreChat) | https://chat.matamune.4nk.eu |
| MCP Server | https://mcp.matamune.4nk.eu/sse |

## Persistenza

Tutti i dati sono salvati in bind mount sotto `./data/`:
- `postgres/` — database utenti e documenti
- `neo4j/` — grafo entità e relazioni
- `qdrant/` — vettori dei chunk
- `minio/` — documenti originali
- `mongo/` — dati LibreChat
- `meilisearch/` — indici di ricerca LibreChat
- `caddy/` — certificati HTTPS e configurazione

## Configurare LibreChat

LibreChat è già configurato tramite `librechat/librechat.yaml` per usare il backend come endpoint OpenAI custom. Dopo il primo avvio:

1. Vai su https://chat.matamune.4nk.eu
2. Registrati / accedi
3. In alto a sinistra scegli il modello **Graph RAG Assistant**
4. Inizia a chattare

## MCP Server

Il server MCP è esposto su `https://mcp.matamune.4nk.eu/sse`.
L'accesso pubblico richiede l'header `X-MCP-API-Key` configurato in `MCP_API_KEY`.
LibreChat usa invece il server MCP interno Docker (`http://mcp:8000/sse`).

Tools disponibili:
- `search_knowledge_base(query, top_k)`
- `answer_knowledge_base(query)`
- `query_knowledge_base(query)`
- `explore_graph(entity)`

Esempio di configurazione client MCP:

```json
{
  "mcpServers": {
    "graph-rag-assistant": {
      "url": "https://mcp.matamune.4nk.eu/sse"
    }
  }
}
```

## Test senza chiave OpenAI

Se imposti `OPENAI_API_KEY=sk-test`, il sistema funziona in modalità dimostrativa con embedding e risposte LLM fittizie. Utile per verificare che lo stack sia attivo, ma le risposte non saranno intelligenti finché non configuri una chiave valida.

## Sviluppo

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Test e migrazioni:

```bash
cd backend
pytest
alembic upgrade head
```

### Admin panel

```bash
cd admin
npm install
npm run dev
```

## Note

- Il backend crea le tabelle PostgreSQL all'avvio (modalità dev). In produzione usa Alembic.
- Per production, configura backup regolari della directory `./data/`.
- Caddy richiede che le porte 80 e 443 siano raggiungibili da internet per ottenere i certificati Let's Encrypt.
