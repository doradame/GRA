# Repository Guidelines

## Project Structure & Module Organization

This repository contains a self-hosted Graph RAG stack. `backend/app/` is the FastAPI service: routers live in `backend/app/routers/`, shared configuration and infrastructure in `backend/app/core/`, SQLAlchemy and Pydantic models in `backend/app/models/`, RAG/storage logic in `backend/app/services/`, and Celery jobs in `backend/app/tasks/`. `admin/` is the React + Vite admin UI, with components in `admin/src/components/` and API helpers in `admin/src/lib/`. `mcp_server/` exposes the knowledge base through MCP. `librechat/`, `Caddyfile`, and `docker-compose.yml` configure the deployed stack. Persistent runtime data belongs under `data/`; avoid committing generated database, index, or document files.

## Build, Test, and Development Commands

- `docker compose up -d`: build and start the full stack.
- `docker compose logs -f backend worker`: inspect API and ingestion worker logs.
- `cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`: create the backend environment.
- `cd backend && uvicorn app.main:app --reload`: run the API locally.
- `cd admin && npm install`: install admin UI dependencies.
- `cd admin && npm run dev`: start Vite for local admin development.
- `cd admin && npm run build`: type-check and build the admin UI.

## Coding Style & Naming Conventions

Use Python 3 style with 4-space indentation, type hints where practical, and `snake_case` for modules, functions, variables, and Celery tasks. Keep FastAPI endpoints grouped by domain in router modules. Use TypeScript React function components with `PascalCase` filenames for components, `camelCase` variables, and Tailwind utility classes as used in the existing admin UI.

## Testing Guidelines

`pytest` and `pytest-asyncio` are available for backend tests, but no test tree is currently present. Add Python tests under `backend/tests/` with names like `test_auth.py` or `test_ingestion.py`, and run them with `cd backend && pytest`. For frontend changes, at minimum run `npm run build`; add component tests only after introducing a test runner.

## Commit & Pull Request Guidelines

Local Git history is not available in this checkout, so no repository-specific commit convention can be inferred. Use short, imperative commit subjects such as `Add ingestion status endpoint`, and keep unrelated changes separate. Pull requests should include a clear summary, affected services, configuration changes, test results, and screenshots for admin UI updates.

## Security & Configuration Tips

Copy `.env.example` to `.env` and set real secrets locally. Do not commit `.env`, API keys, database dumps, uploaded documents, or generated contents of `data/`. Use `OPENAI_API_KEY=sk-test` only for demo-mode validation.
