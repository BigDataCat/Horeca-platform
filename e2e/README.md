# Browser smoke test

Walks the main workflows in a real browser against a running stack: sign-up, receiving goods, CSV
import, recipe consumption, cancelling a sale (stock restored), filters, alerts, margins, password
change and sign-out.

```bash
# 1. start an EMPTY database and the API (see README), build the frontend against it:
cd frontend && VITE_API_URL=http://localhost:8000/api npm run build && npx vite preview --port 4173
# (the API needs CORS_ORIGINS=http://localhost:4173)

# 2. run the test
cd e2e && npm init -y && npm install playwright-core
CHROMIUM_PATH=/path/to/chrome node ../smoke.mjs   # or: BASE_URL=... API_URL=... node smoke.mjs
```

It creates a new company every run (unique e-mail) but leaves data behind: use a throwaway database.
