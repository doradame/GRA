# Design: Installer interattivo per VPS Graph RAG Assistant

**Data:** 2026-06-19  
**Stato:** Approvato — pronto per implementazione  
**Autore:** Assistente Kimi Code  

## 1. Contesto e obiettivo

Il progetto Graph RAG Assistant è uno stack self-hosted composto da:

- Backend FastAPI + worker Celery
- Pannello admin React + Vite
- LibreChat come frontend chat
- Neo4j, Qdrant, PostgreSQL, MinIO, MongoDB, Meilisearch, Redis
- Caddy come reverse proxy con HTTPS automatico
- MCP Server esposto su sottodominio dedicato

L'obiettivo è creare uno script Bash modulare, interattivo e robusto che installi e configuri l'intero stack su un VPS Ubuntu 22.04/24.04 LTS nuovo, guidando l'utente nella raccolta delle configurazioni essenziali.

## 2. Requisiti raccolti

- Docker e Docker Compose devono essere già installati dall'utente; lo script li verifica e si ferma se mancano.
- Lo script deve funzionare in due modalità:
  1. **Autonoma:** clona il repository Git se non è già presente sul server.
  2. **In-place:** riconosce di essere eseguito dentro la cartella del progetto e configura solo i file.
- Deve chiedere all'utente:
  - Dominio root (es. `example.com`) e generare automaticamente i sottodomini.
  - OpenAI API Key (sempre richiesta, nessuna modalità demo).
  - Resend API Key.
  - Indirizzo e nome mittente email.
  - Credenziali admin del backend.
  - Credenziali admin di LibreChat.
- Deve generare automaticamente i secret interni (Postgres, Neo4j, MinIO, Meilisearch, JWT, MCP, LibreChat backend key).
- Deve creare le directory persistenti, scrivere i file di configurazione e avviare lo stack con `docker compose up -d`.
- Deve creare automaticamente l'utente admin del backend via API e tentare la creazione dell'admin LibreChat.
- Deve essere testato con `shellcheck` e validato in container Ubuntu locale.

## 3. Approccio scelto

**Approccio B: script bash modulare con entry point unico.**

Unico file eseguibile `scripts/install.sh` che carica moduli da `scripts/setup/`. All'utente risulta un comando semplice, ma il codice è organizzato in fasi isolate, facili da mantenere e testare.

## 4. Struttura dei file

```
scripts/
├── install.sh                 # entry point
└── setup/
    ├── lib/
    │   ├── colors.sh          # colori, banner, messaggi di stato
    │   ├── prompts.sh         # funzioni read sicure (password, conferme, validazione)
    │   └── validators.sh      # regex per dominio, email, api key, password
    ├── 00-preamble.sh         # banner, controllo OS, prerequisiti
    ├── 10-checks.sh           # verifica docker, docker compose, git, curl, openssl
    ├── 20-clone.sh            # clona repo se necessario
    ├── 30-input.sh            # raccoglie dominio, API key, email, credenziali admin
    ├── 40-secrets.sh          # genera secret interni
    ├── 50-config.sh           # scrive .env, Caddyfile, librechat/*.yaml, librechat/*.env
    ├── 60-data.sh             # crea directory data/
    ├── 70-launch.sh           # docker compose up -d + attesa container
    ├── 80-admin-user.sh       # crea utente admin backend e tenta admin LibreChat
    └── 99-summary.sh          # riepilogo finale
```

## 5. Flusso interattivo

1. **Benvenuto e modalità repo:** chiede se clonare il repository o usare la directory corrente.
2. **Dominio root:** richiede `example.com` e propone i sottodomini automatici.
3. **OpenAI API Key:** campo obbligatorio, validazione formato `sk-*`.
4. **Resend API Key:** campo obbligatorio, validazione formato `re_*`.
5. **Email mittente:** indirizzo e nome mittente per le email di LibreChat.
6. **Admin backend:** email e password (conferma password, minimo 12 caratteri).
7. **Admin LibreChat:** email e password (conferma); tentativo creazione automatica.
8. **Riepilogo:** mostra dominio, URL servizi, email admin; richiede conferma prima di scrivere.

## 6. Generazione dei file di configurazione

I file vengono generati da template embedded o da file template in `scripts/setup/templates/`.

### 6.1 `.env`

Contiene:
- `OPENAI_API_KEY`, `RESEND_API_KEY` forniti dall'utente.
- Modelli OpenAI ai default del progetto.
- Secret interni generati:
  - `SECRET_KEY`
  - `MCP_API_KEY`
  - `LIBRECHAT_BACKEND_API_KEY`
  - `POSTGRES_PASSWORD`
  - `NEO4J_PASSWORD`
  - `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`
  - `MEILI_MASTER_KEY`

### 6.2 `Caddyfile`

Template con i sottodomini:
- `admin.<dominio>` → admin:80
- `api.<dominio>` → backend:8000
- `chat.<dominio>` → librechat:3080
- `chat-admin.<dominio>` → librechat-admin:3000
- `mcp.<dominio>` → mcp:8000 (protetto da header `X-MCP-API-Key`)
- `<dominio>` root → redirect a `admin.<dominio>`

### 6.3 `librechat/librechat.yaml`

Aggiornato con:
- `apiKey` = `LIBRECHAT_BACKEND_API_KEY`
- `baseURL` = `http://backend:8000/api/v1`
- `modelDisplayLabel` e modelli default

### 6.4 `librechat/librechat.env`

Imposta:
- `DOMAIN_CLIENT`, `DOMAIN_SERVER`, `ADMIN_PANEL_URL`
- `EMAIL_FROM`, `EMAIL_FROM_NAME`, `EMAIL_PASSWORD`
- Secret LibreChat (`JWT_SECRET`, `JWT_REFRESH_SECRET`, `CREDS_KEY`, `CREDS_IV`, `MEILI_MASTER_KEY`)

### 6.5 `librechat/admin.env`

Imposta:
- `VITE_API_BASE_URL`, `API_SERVER_URL`, `SESSION_SECRET`

### 6.6 Backup

Prima di sovrascrivere file esistenti, lo script crea un backup con suffisso `.bak.YYYYMMDD-HHMMSS`.

## 7. Gestione errori, avvio e verifica

- `set -euo pipefail` e `trap` per intercettare errori e stampare il passo fallito.
- Verifica prerequisiti: `docker`, `docker compose`, `git`, `curl`, `openssl`.
- Verifica OS: Ubuntu 22.04/24.04 LTS (warning se diverso, ma non bloccante).
- Creazione directory persistenti in `data/` con permessi corretti.
- `docker compose up -d` con attesa che i container siano `running`.
- Health check sugli endpoint pubblici entro timeout di 2-3 minuti.
- Se un endpoint non risponde, mostra log di Caddy/backend e chiede se continuare.

## 8. Creazione utenti admin

### 8.1 Admin backend

Chiamata HTTP:

```bash
POST https://api.<dominio>/api/v1/auth/register
Content-Type: application/json

{"email":"<admin_email>","password":"<admin_password>"}
```

Se l'utente esiste già, gestisce l'errore e offre di riprovare o continuare.

### 8.2 Admin LibreChat

Lo script tenta la creazione automatica se esiste un endpoint sicuro; altrimenti fornisce istruzioni manuali nel riepilogo finale.

## 9. Riepilogo finale

Al termine, lo script stampa:

```
✅ Graph RAG Assistant installato!

Pannello Admin:     https://admin.example.com
API Backend:        https://api.example.com
LibreChat:          https://chat.example.com
LibreChat Admin:    https://chat-admin.example.com
MCP Server:         https://mcp.example.com/sse

Admin backend:      admin@example.com
Admin LibreChat:    libreadmin@example.com

Prossimi passi:
1. Verifica che i DNS puntino correttamente al VPS.
2. Accedi al pannello admin e carica i tuoi documenti.
3. Accedi a LibreChat e inizia a chattare con Graph RAG Assistant.
```

## 10. Testing

- Eseguire `shellcheck` su tutti i file `.sh`.
- Testare in container Ubuntu 22.04/24.04 locale con Docker e Compose.
- Verificare la generazione corretta di `.env`, `Caddyfile` e file LibreChat.
- Testare la creazione dell'utente admin backend contro un backend in esecuzione.
- Validare il `Caddyfile` generato con `caddy validate`.
- Non testare Let's Encrypt in locale (richiede dominio pubblico).

## 11. Note di manutenzione

- Aggiornare il README con il comando one-liner di installazione.
- Mantenere i template allineati ai file di esempio del progetto (`.env.example`, `Caddyfile`, `librechat/librechat.yaml`, `librechat/librechat.env.example`, `librechat/admin.env.example`).
- Documentare ogni nuovo campo aggiunto al setup nei commenti dei moduli.

## 12. Decisioni prese

| Argomento | Decisione |
|---|---|
| Tipo di script | Bash modulare (approccio B) |
| Docker/Compose | Verifica presenza, non installa automaticamente |
| Modalità repo | Autonoma (clona) o in-place (directory corrente) |
| Domini | Dominio root + sottodomini automatici |
| OpenAI API Key | Sempre richiesta, nessuna modalità demo |
| Modelli OpenAI | Default del progetto |
| Secret interni | Generati automaticamente con `openssl rand` |
| Avvio stack | Sì, con `docker compose up -d` e health check |
| Admin backend | Creato automaticamente via API |
| Admin LibreChat | Chiesto e tentato automaticamente, con fallback manuale |
| OS target | Ubuntu 22.04/24.04 LTS |
