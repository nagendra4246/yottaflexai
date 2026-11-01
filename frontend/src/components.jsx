import { Link } from "react-router-dom";

export function PageHeader({ eyebrow, title, description, action }) {
  return (
    <div className="page-header">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {description && <p className="page-description">{description}</p>}
      </div>
      {action && <div className="page-header-action">{action}</div>}
    </div>
  );
}

export function MetricCard({ label, value, note, icon, tone = "blue" }) {
  return (
    <article className={`metric-card tone-${tone}`}>
      <div className="metric-card-top">
        <span className="metric-icon" aria-hidden="true">{icon}</span>
        <span className="metric-label">{label}</span>
      </div>
      <strong className="metric-value">{value ?? "—"}</strong>
      {note && <span className="metric-note">{note}</span>}
    </article>
  );
}

export function StatusBadge({ status }) {
  const normalized = String(status || "Unknown").toLowerCase().replaceAll(" ", "-");
  return <span className={`status-badge status-${normalized}`}>{status || "Unknown"}</span>;
}

export function LoadingState({ label = "Loading live data…" }) {
  return (
    <div className="state-card" role="status">
      <span className="spinner" />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({ title = "Nothing here yet", children }) {
  return (
    <div className="state-card empty-state">
      <span className="empty-mark" aria-hidden="true">⌕</span>
      <strong>{title}</strong>
      <span>{children || "Records from the API will appear here."}</span>
    </div>
  );
}

export function ErrorState({ error, onRetry }) {
  return (
    <div className="error-card" role="alert">
      <div>
        <strong>Couldn’t load this data</strong>
        <p>{error?.message || "An unexpected error occurred."}</p>
        {error?.code && <small>{error.code}</small>}
      </div>
      {onRetry && <button className="button button-secondary" onClick={onRetry}>Try again</button>}
    </div>
  );
}

export function DataTable({ columns, rows, rowKey, emptyTitle, emptyMessage }) {
  if (!rows.length) {
    return <EmptyState title={emptyTitle} >{emptyMessage}</EmptyState>;
  }
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>{columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((column) => (
                <td key={column.key}>
                  {column.render ? column.render(row) : row[column.key] ?? "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DetailLink({ to, children }) {
  return <Link className="detail-link" to={to}>{children}<span aria-hidden="true">↗</span></Link>;
}

export function Field({ label, value, mono = false }) {
  return (
    <div className="detail-field">
      <span>{label}</span>
      <strong className={mono ? "mono" : ""}>{value ?? "—"}</strong>
    </div>
  );
}

export function UnavailableNote({ children = "This detail is not currently exposed by the FastAPI API." }) {
  return <div className="unavailable-note"><span aria-hidden="true">i</span>{children}</div>;
}

export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  onConfirm,
  onCancel,
  busy,
  confirmDisabled = false,
  confirmTone = "primary",
}) {
  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !busy) onCancel();
    }}>
      <section className="dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title">
        <h2 id="dialog-title">{title}</h2>
        {children}
        <div className="dialog-actions">
          <button className="button button-secondary" onClick={onCancel} disabled={busy}>Cancel</button>
          <button className={`button button-${confirmTone}`} onClick={onConfirm} disabled={busy || confirmDisabled}>
            {busy ? "Submitting…" : confirmLabel}
          </button>
        </div>
      </section>
    </div>
  );
}
