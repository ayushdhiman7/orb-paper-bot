# ORB Dashboard API

This is the source for the standalone FastAPI service deployed at `/home/ubuntu/orb-dashboard-api`.

## Range behavior

- `1D`: current Indian calendar date.
- `7D`: the latest 7 XNSE trading sessions, including today when it is a session.
- `30D`: the latest 30 XNSE trading sessions, including today when it is a session.
- `ALL`: all available trade and control rows, fetched in 1,000-row pages.

The service calculates session dates in `Asia/Kolkata` and converts midnight boundaries to UTC before querying Supabase. Backtest history is independent of the selected trade range.

## Deploy on EC2

From the bot repository checkout:

```bash
git fetch origin
git checkout fix/dashboard-range-loader

# Back up the currently running API source first.
cp /home/ubuntu/orb-dashboard-api/app.py /home/ubuntu/orb-dashboard-api/app.py.bak.$(date -u +%Y%m%d%H%M%S)

# Install the additional NSE calendar dependency in the existing API environment.
 /home/ubuntu/orb-dashboard-api/.venv/bin/pip install -r dashboard-api/requirements.txt

# Copy the reviewed API source into the standalone API project.
cp dashboard-api/app.py /home/ubuntu/orb-dashboard-api/app.py
```

Build the frontend before deployment:

```bash
cd dashboard
npm install
npm run build
```

Restart only the dashboard API process after the API source and dependency are installed. Do not restart `orb-bot.service`.
