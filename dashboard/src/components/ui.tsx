import type { ReactNode } from "react";

export function Panel({ title, note, action, children }: { title?: string; note?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="panel">
      {(title || action) && (
        <header className="panel-head">
          <div>{title && <h3>{title}</h3>}{note && <p>{note}</p>}</div>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <strong className={`stat-value ${tone ?? ""}`}>{value}</strong>
      {sub && <span className="stat-sub">{sub}</span>}
    </div>
  );
}

export const Stats = ({ children }: { children: ReactNode }) => <div className="stats">{children}</div>;

export function Notice({ kind = "info", children, action }: { kind?: "info" | "error" | "ok"; children: ReactNode; action?: ReactNode }) {
  return <div className={`notice ${kind}`}><span>{children}</span>{action}</div>;
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return <div className="empty"><strong>{title}</strong>{hint && <span>{hint}</span>}</div>;
}

export function Badge({ children, kind }: { children: ReactNode; kind?: "buy" | "sell" | "take" | "skip" | "warn" }) {
  return <span className={`badge ${kind ?? ""}`}>{children}</span>;
}
