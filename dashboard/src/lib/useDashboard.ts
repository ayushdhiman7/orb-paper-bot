import { useCallback, useEffect, useRef, useState } from "react";
import { loadDashboardData } from "./api";
import type { DashboardData, DashboardRange } from "./api";

const EMPTY: DashboardData = { trades: [], openPositions: [], controls: [], backtests: [] };

/** Loads dashboard data and refreshes it when the bot pushes an event (SSE). No polling. */
export function useDashboard(range: DashboardRange) {
  const [data, setData] = useState<DashboardData>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [live, setLive] = useState(false);
  const request = useRef(0);

  const refresh = useCallback(async () => {
    const id = ++request.current;
    try {
      const fresh = await loadDashboardData(range);
      if (id === request.current) { setData(fresh); setError(""); }
    } catch (e) {
      if (id === request.current) setError(e instanceof Error ? e.message : "Could not load dashboard data.");
    } finally {
      if (id === request.current) setLoading(false);
    }
  }, [range]);

  useEffect(() => { setLoading(true); void refresh(); return () => { request.current += 1; }; }, [refresh]);

  useEffect(() => {
    const source = new EventSource("/api/events/stream");
    const reload = () => void refresh();
    source.onopen = () => setLive(true);
    source.onerror = () => setLive(false);
    for (const name of ["ready", "trade.opened", "trade.closed", "bot.status_changed", "risk.alert", "session.summary", "resync"]) {
      source.addEventListener(name, reload);
    }
    return () => source.close();
  }, [refresh]);

  return { data, loading, error, live, refresh };
}
