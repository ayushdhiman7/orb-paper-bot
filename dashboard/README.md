# ORB Terminal Dashboard

A React + TypeScript dashboard for the ORB paper-trading bot. The existing `docs/` static page remains untouched while this app is built and verified.

## Stack
- React + TypeScript + Vite
- Tailwind CSS v4
- Recharts for analytics
- Lucide React icons
- Supabase JS client (browser publishable/anon key only)

## Local development
```bash
cd dashboard
cp .env.example .env.local
npm install
npm run dev
```

Set `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` in `.env.local`. Never use `SUPABASE_KEY`/service-role credentials in frontend code. Without these values, the app shows clearly labeled preview data.

## Build
```bash
npm run build
npm run preview
```

The app currently reads `paper_trades` and completed `no_ai_control` rows from `shadow_trades`. Supabase RLS/grants must permit the intended read-only access. Dashboard metrics exclude open and estimated-exit records from realized P&L.

## Deployment status
This app is being built separately from the currently published `docs/` dashboard. GitHub Pages deployment will be switched only after the new build and data reads are verified.
