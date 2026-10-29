# ORB Terminal Dashboard

A React + TypeScript dashboard for the ORB paper-trading bot. The existing `docs/` dashboard remains untouched while this app is built and verified.

## Stack
- React + TypeScript + Vite
- Tailwind CSS v4
- Recharts for analytics
- Lucide React icons
- Backend HTTP API (the backend owns Supabase/database access)

## Local development
```bash
cd dashboard
cp .env.example .env.local
npm install
npm run dev
```

Set `VITE_API_BASE_URL` to the base URL of your backend (for example, `http://localhost:8000`). The frontend calls `GET {VITE_API_BASE_URL}/api/dashboard`. Without this variable, the app stays in clearly labelled preview mode.

## Backend API contract

Implement an authenticated `GET /api/dashboard` route in your backend. It should return JSON shaped like:

```json
{
  "trades": [],
  "controls": [],
  "backtests": []
}
```

- `trades`: paper trade records used by Overview, Trade Journal and Risk Monitor.
- `controls`: no-AI control-group outcomes. Include `trade_id` only when the control outcome is genuinely linked to the corresponding AI-managed paper trade.
- `backtests`: saved backtest runs, each with `id`, `created_at`, `summary_md` and `result`.

The backend should authenticate the user, query Supabase with server-side credentials, validate access, and return only the user's permitted records. Keep service-role keys and database secrets on the backend; never add them to `VITE_*` variables or the browser bundle. Configure CORS on the backend if frontend and backend use different origins. This React app does not query Supabase directly.

## Build
```bash
npm run build
npm run preview
```

Dashboard metrics exclude open and estimated-exit records from realized P&L. AI vs no-AI comparison uses linked records only and keeps unpaired outcomes separate.

## Deployment status
This app is being built separately from the currently published `docs/` dashboard. GitHub Pages deployment will be switched only after the backend endpoint is implemented, authenticated, and verified against real data.
