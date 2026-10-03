# HoReCa Platform

Integration-first SaaS platform for HoReCa management and intelligence.

The platform is designed to integrate with existing POS systems rather than replace them.

## Current milestone

The first end-to-end module is **Company**:

`React UI → FastAPI API → SQLAlchemy → PostgreSQL`

Implemented operations:

- Create company
- List companies
- Read a company by ID
- Edit company
- Deactivate company
- Alembic migration for the initial database model

## Project structure

```
backend/
  app/
    api/          # HTTP endpoints
    core/         # configuration and database connection
    models/       # SQLAlchemy models
    schemas/      # Pydantic request/response schemas
  alembic/        # database migrations

frontend/
  src/            # React + TypeScript application

docker-compose.yml
```

## Run locally

### 1. Start PostgreSQL

Copy `.env.example` to `.env` and adjust credentials if needed.

Then:

```bash
docker compose up -d postgres
```

### 2. Start the backend

From `backend/`:

```bash
python -m venv .venv
# Windows:
.venv\\Scripts\\activate
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

API:

`http://localhost:8000`

Swagger:

`http://localhost:8000/docs`

### 3. Start the frontend

From `frontend/`:

```bash
npm install
npm run dev
```

The frontend expects the API at:

`http://localhost:8000/api`

To override it, create `frontend/.env`:

```text
VITE_API_URL=http://localhost:8000/api
```

## Next modules

1. Location management
2. User and authentication
3. POS integration layer
4. Sales/orders ingestion
5. Analytics and intelligence layer
