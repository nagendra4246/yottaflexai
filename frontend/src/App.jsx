import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Link,
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { apiRequest, fetchAll, postJson } from "./api.js";
import {
  ConfirmDialog,
  DataTable,
  DetailLink,
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  MetricCard,
  PageHeader,
  StatusBadge,
  UnavailableNote,
} from "./components.jsx";

const navigation = [
  { label: "Dashboard", path: "/", icon: "◫" },
  { label: "Approval Queue", path: "/approvals", icon: "✓" },
  { label: "Leave Requests", path: "/leave", icon: "◷" },
  { label: "Expense Claims", path: "/expenses", icon: "▤" },
  { label: "Reimbursements", path: "/reimbursements", icon: "$" },
  { label: "Audit & Exceptions", path: "/audit", icon: "◉" },
  { label: "Employees", path: "/employees", icon: "♙" },
  { label: "Analytics", path: "/analytics", icon: "▥" },
];

const money = (value, currency = "USD") => {
  if (value === null || value === undefined || value === "") return "—";
  const amount = Number(value);
  if (!Number.isFinite(amount)) return String(value);
  return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(amount);
};

const formatDate = (value) => value
  ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(`${value.slice(0, 10)}T00:00:00`))
  : "—";

const formatDateTime = (value) => value
  ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value))
  : "—";

function useResource(loader, dependencies = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const [reloadKey, setReloadKey] = useState(0);
  const reload = useCallback(() => setReloadKey((key) => key + 1), []);

  useEffect(() => {
    let active = true;
    setState((current) => ({ ...current, loading: true, error: null }));
    loader()
      .then((data) => { if (active) setState({ data, error: null, loading: false }); })
      .catch((error) => { if (active) setState({ data: null, error, loading: false }); });
    return () => { active = false; };
  }, [...dependencies, reloadKey]);

  return { ...state, reload };
}

function useToast() {
  const [toast, setToast] = useState(null);
  useEffect(() => {
    if (!toast) return undefined;
    const timer = window.setTimeout(() => setToast(null), 4200);
    return () => window.clearTimeout(timer);
  }, [toast]);
  return { toast, showToast: (message, kind = "success") => setToast({ message, kind }) };
}

function Toast({ toast }) {
  if (!toast) return null;
  return <div className={`toast toast-${toast.kind}`} role="status">{toast.kind === "success" ? "✓" : "!"} {toast.message}</div>;
}

function AppLayout({ children, toast }) {
  const location = useLocation();
  const currentLabel = navigation.find((item) => item.path === location.pathname)?.label
    || (location.pathname.startsWith("/leave/") ? "Leave Request Details" : "Expense Details");
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link to="/" className="brand">
          <span className="brand-mark">Y</span>
          <span><strong>YottaFlex</strong><small>PEOPLE OPERATIONS</small></span>
        </Link>
        <div className="nav-section-label">WORKSPACE</div>
        <nav className="side-nav" aria-label="Main navigation">
          {navigation.map((item) => (
            <NavLink key={item.path} to={item.path} end={item.path === "/"} className={({ isActive }) => `nav-link${isActive ? " nav-link-active" : ""}`}>
              <span className="nav-icon" aria-hidden="true">{item.icon}</span>
              <span>{item.label}</span>
              {item.path === "/approvals" && <span className="nav-dot" />}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="connection-indicator"><span /> API-connected workspace</div>
          <div className="sidebar-footnote">All workspace data is loaded from FastAPI.</div>
        </div>
      </aside>
      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumb"><span>Workspace</span><b>/</b><strong>{currentLabel}</strong></div>
          <div className="topbar-right">
            <span className="live-pill"><i /> Live API</span>
            <a className="docs-link" href={`${import.meta.env.VITE_API_BASE_URL || "/api"}/docs`} target="_blank" rel="noreferrer">API docs ↗</a>
          </div>
        </header>
        <div className="content-area">{children}</div>
      </main>
      <Toast toast={toast} />
    </div>
  );
}

function DashboardPage() {
  const load = useCallback(async () => {
    const [summary, exceptions, reimbursements] = await Promise.all([
      apiRequest("/analytics/summary"),
      fetchAll("/audit/events", { exceptions_only: true }),
      fetchAll("/reimbursements"),
    ]);
    const exceptionCodes = exceptions.map((event) => event.exception_code).filter(Boolean);
    const policyCodes = new Set([
      "EXPENSE_POLICY_NOT_APPLICABLE",
      "EXPENSE_POLICY_EXPIRED",
      "POLICY_LIMIT_EXCEEDED",
      "BUDGET_EXCEEDED",
      "RECEIPT_REQUIRED",
      "LEAVE_POLICY_NOT_FOUND",
      "LEAVE_POLICY_NOT_APPLICABLE",
    ]);
    return {
      summary,
      exceptionCount: exceptions.length,
      duplicateReceiptCount: exceptionCodes.filter((code) => code === "DUPLICATE_RECEIPT").length,
      policyViolationCount: exceptionCodes.filter((code) => policyCodes.has(code)).length,
      pendingReimbursementAmount: reimbursements.filter((item) => item.status === "Pending")
        .reduce((sum, item) => sum + Number(item.amount), 0),
      processedReimbursementAmount: reimbursements.filter((item) => item.status === "Processed")
        .reduce((sum, item) => sum + Number(item.amount), 0),
    };
  }, []);
  const { data, error, loading, reload } = useResource(load, []);

  return (
    <>
      <PageHeader eyebrow="OVERVIEW" title="Good day" description="A live view of people operations and approval activity." action={<span className="date-chip">{new Intl.DateTimeFormat(undefined, { dateStyle: "full" }).format(new Date())}</span>} />
      {loading && <LoadingState />}
      {error && <ErrorState error={error} onRetry={reload} />}
      {data && (
        <>
          <div className="section-heading"><h2>Workforce</h2><span>Current headcount</span></div>
          <div className="metric-grid metric-grid-4">
            <MetricCard label="Employees" value={data.summary.employees_total.toLocaleString()} note={`${data.summary.employees_active.toLocaleString()} active`} icon="♙" tone="blue" />
            <MetricCard label="Pending leave" value={data.summary.leave_requests_by_status.Pending || 0} note="Awaiting decision" icon="◷" tone="amber" />
            <MetricCard label="Approved leave" value={data.summary.leave_requests_by_status.Approved || 0} note="Requests approved" icon="✓" tone="green" />
            <MetricCard label="Rejected leave" value={data.summary.leave_requests_by_status.Rejected || 0} note="Requests declined" icon="×" tone="rose" />
          </div>
          <div className="section-heading section-heading-spaced"><h2>Finance & controls</h2><span>Live workflow totals</span></div>
          <div className="metric-grid metric-grid-4">
            <MetricCard label="Pending expenses" value={data.summary.expense_claims_by_status.Pending || 0} note="Claims in review" icon="▤" tone="amber" />
            <MetricCard label="Approved expenses" value={data.summary.expense_claims_by_status.Approved || 0} note="Ready for reimbursement" icon="✓" tone="green" />
            <MetricCard label="Rejected expenses" value={data.summary.expense_claims_by_status.Rejected || 0} note="Claims declined" icon="×" tone="rose" />
            <MetricCard label="Total claimed" value={money(data.summary.expense_claims_total_amount)} note="All expense claims" icon="$" tone="blue" />
          </div>
          <div className="metric-grid metric-grid-4 metric-grid-bottom">
            <MetricCard label="Reimbursements pending" value={money(data.pendingReimbursementAmount)} note={`${data.summary.reimbursements_by_status.Pending || 0} awaiting processing`} icon="◷" tone="amber" />
            <MetricCard label="Reimbursements processed" value={money(data.processedReimbursementAmount)} note={`${data.summary.reimbursements_by_status.Processed || 0} processed`} icon="$" tone="green" />
            <MetricCard label="Exceptions" value={data.exceptionCount} note="Recorded exception events" icon="!" tone="rose" />
            <MetricCard label="Duplicate receipts" value={data.duplicateReceiptCount} note={`Policy violations: ${data.policyViolationCount}`} icon="⌕" tone="violet" />
          </div>
          <p className="data-note">Metrics reflect records returned by the FastAPI service; exception figures are based on persisted audit events.</p>
        </>
      )}
    </>
  );
}

function AnalyticsPage() {
  const { data, error, loading, reload } = useResource(
    () => apiRequest("/analytics/summary"), [],
  );
  const groups = useMemo(() => data ? [
    { title: "Leave request status", values: data.leave_requests_by_status, color: "var(--blue)" },
    { title: "Expense claim status", values: data.expense_claims_by_status, color: "var(--green)" },
    { title: "Reimbursement status", values: data.reimbursements_by_status, color: "var(--violet)" },
  ] : [], [data]);
  return (
    <>
      <PageHeader eyebrow="INSIGHTS" title="Analytics" description="Operational metrics from the current FastAPI summary." />
      {loading && <LoadingState />}
      {error && <ErrorState error={error} onRetry={reload} />}
      {data && <>
        <div className="metric-grid metric-grid-3">
          <MetricCard label="Total employees" value={data.employees_total.toLocaleString()} note={`${data.employees_active.toLocaleString()} active`} icon="♙" />
          <MetricCard label="Expense claim value" value={money(data.expense_claims_total_amount)} note="Across all claim statuses" icon="$" tone="green" />
          <MetricCard label="Items in active workflows" value={(data.leave_requests_by_status.Pending || 0) + (data.expense_claims_by_status.Pending || 0)} note="Pending leave and expense" icon="◷" tone="amber" />
        </div>
        <div className="analytics-grid">
          {groups.map((group) => {
            const total = Object.values(group.values).reduce((sum, value) => sum + value, 0);
            return (
              <section className="panel analytics-panel" key={group.title}>
                <div className="panel-heading"><div><h2>{group.title}</h2><p>{total.toLocaleString()} records</p></div></div>
                <div className="bar-list">
                  {Object.entries(group.values).length === 0 && <EmptyState title="No status data" />}
                  {Object.entries(group.values).map(([label, count]) => (
                    <div className="bar-row" key={label}>
                      <div className="bar-label"><span>{label}</span><strong>{count}</strong></div>
                      <div className="bar-track"><span style={{ width: `${total ? (count / total) * 100 : 0}%`, background: group.color }} /></div>
                    </div>
                  ))}
                </div>
              </section>
            );
          })}
        </div>
        <UnavailableNote>Trend history and policy-level analytics are not exposed by the current API.</UnavailableNote>
      </>}
    </>
  );
}

function LeaveRequestsPage({ showToast }) {
  const navigate = useNavigate();
  const [showSubmit, setShowSubmit] = useState(false);
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") || "");
  const [status, setStatus] = useState(params.get("status") || "");
  const load = useCallback(async () => {
    const [requests, employees] = await Promise.all([
      fetchAll("/leave/requests"),
      fetchAll("/employees"),
    ]);
    const policies = await apiRequest("/leave/policies");
    return { requests, employees, policies };
  }, []);
  const { data, error, loading, reload } = useResource(load, []);
  const employeeMap = useMemo(() => new Map((data?.employees || []).map((employee) => [employee.employee_id, employee])), [data]);
  const rows = useMemo(() => (data?.requests || []).filter((request) => {
    const employee = employeeMap.get(request.employee_id);
    const query = search.trim().toLowerCase();
    const matchesSearch = !query || [request.request_id, request.employee_id, employee?.name, request.leave_type]
      .some((value) => String(value || "").toLowerCase().includes(query));
    return matchesSearch && (!status || request.status === status);
  }), [data, employeeMap, search, status]);
  function updateSearch(value) {
    setSearch(value);
    const next = new URLSearchParams(params);
    if (value) next.set("q", value); else next.delete("q");
    setParams(next, { replace: true });
  }
  function updateStatus(value) {
    setStatus(value);
    const next = new URLSearchParams(params);
    if (value) next.set("status", value); else next.delete("status");
    setParams(next, { replace: true });
  }
  const columns = [
    { key: "request_id", label: "Request", render: (row) => <DetailLink to={`/leave/${row.request_id}`}>{row.request_id}</DetailLink> },
    { key: "employee_id", label: "Employee", render: (row) => <span><strong>{employeeMap.get(row.employee_id)?.name || row.employee_id}</strong><small className="cell-subtitle">{row.employee_id}</small></span> },
    { key: "leave_type", label: "Leave type" },
    { key: "start_date", label: "Dates", render: (row) => <span>{formatDate(row.start_date)}<small className="cell-subtitle">to {formatDate(row.end_date)}</small></span> },
    { key: "total_days", label: "Business days", render: (row) => `${row.total_days} days` },
    { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
  ];
  return (
    <>
      <PageHeader
        eyebrow="PEOPLE"
        title="Leave requests"
        description="Search and review employee leave requests."
        action={<button className="button button-primary" onClick={() => setShowSubmit((value) => !value)}>Submit leave request</button>}
      />
      {showSubmit && data && <LeaveRequestForm
        employees={data.employees}
        policies={data.policies}
        onCancel={() => setShowSubmit(false)}
        onSubmitted={(request) => {
          setShowSubmit(false);
          showToast("Leave request submitted for approval.");
          navigate(`/leave/${request.request_id}`);
        }}
      />}
      <section className="panel">
        <div className="toolbar">
          <label className="search-field"><span aria-hidden="true">⌕</span><input value={search} onChange={(event) => updateSearch(event.target.value)} placeholder="Search request, employee, leave type…" /></label>
          <select className="filter-select" value={status} onChange={(event) => updateStatus(event.target.value)} aria-label="Filter by status">
            <option value="">All statuses</option>
            {["Pending", "Approved", "Rejected", "Cancelled", "Draft"].map((item) => <option key={item}>{item}</option>)}
          </select>
          <span className="result-count">{rows.length} requests</span>
        </div>
        {loading && <LoadingState />}
        {error && <ErrorState error={error} onRetry={reload} />}
        {data && <DataTable columns={columns} rows={rows} rowKey={(row) => row.request_id} emptyTitle="No leave requests" emptyMessage="Try changing your search or status filter." />}
      </section>
    </>
  );
}

function LeaveRequestForm({ employees, policies, onCancel, onSubmitted }) {
  const activeEmployees = employees.filter((person) => person.status === "Active");
  const [employeeId, setEmployeeId] = useState(activeEmployees[0]?.employee_id || "");
  const [policyId, setPolicyId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [leaveType, setLeaveType] = useState("Annual");
  const [balance, setBalance] = useState(null);
  const [balanceError, setBalanceError] = useState(null);
  const [submitError, setSubmitError] = useState(null);
  const [busy, setBusy] = useState(false);
  const employee = activeEmployees.find((person) => person.employee_id === employeeId);
  const applicablePolicies = useMemo(() => policies.filter((policy) => (
    policy.country_code === employee?.country
    && (!startDate || policy.effective_from <= startDate)
    && (!endDate || !policy.effective_to || policy.effective_to >= endDate)
  )), [policies, employee?.country, startDate, endDate]);

  useEffect(() => {
    if (!applicablePolicies.some((policy) => policy.policy_id === policyId)) {
      setPolicyId(applicablePolicies[0]?.policy_id || "");
    }
  }, [applicablePolicies, policyId]);

  useEffect(() => {
    let active = true;
    setBalance(null);
    setBalanceError(null);
    if (!employeeId) return () => { active = false; };
    apiRequest(`/employees/${encodeURIComponent(employeeId)}/leave-balances`)
      .then((items) => {
        if (active) setBalance(items.find((item) => item.policy_id === policyId) || null);
      })
      .catch((error) => { if (active) setBalanceError(error.message); });
    return () => { active = false; };
  }, [employeeId, policyId]);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setSubmitError(null);
    try {
      const request = await postJson("/leave/requests", {
        employee_id: employeeId,
        policy_id: policyId,
        start_date: startDate,
        end_date: endDate,
        leave_type: leaveType,
      });
      onSubmitted(request);
    } catch (error) {
      setSubmitError(error.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="panel workflow-form" onSubmit={submit}>
      <div className="panel-heading"><div><h2>New leave request</h2><p>Policy, employment, balance, and approval rules are validated by the API.</p></div></div>
      <div className="form-grid">
        <label className="form-label">Employee
          <select className="form-control" value={employeeId} onChange={(event) => setEmployeeId(event.target.value)} required>
            {activeEmployees.map((person) => <option key={person.employee_id} value={person.employee_id}>{person.name} · {person.employee_id}</option>)}
          </select>
        </label>
        <label className="form-label">Leave policy
          <select className="form-control" value={policyId} onChange={(event) => setPolicyId(event.target.value)} required disabled={!applicablePolicies.length}>
            {applicablePolicies.map((policy) => <option key={policy.policy_id} value={policy.policy_id}>{policy.policy_name} · {policy.policy_id}</option>)}
          </select>
        </label>
        <label className="form-label">Start date<input className="form-control" type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} required /></label>
        <label className="form-label">End date<input className="form-control" type="date" value={endDate} min={startDate || undefined} onChange={(event) => setEndDate(event.target.value)} required /></label>
        <label className="form-label">Leave type
          <select className="form-control" value={leaveType} onChange={(event) => setLeaveType(event.target.value)}>
            {["Annual", "Sick", "Personal"].map((item) => <option key={item}>{item}</option>)}
          </select>
        </label>
        <div className="form-label">Available balance
          <strong className="form-readout">{balance ? `${balance.available_balance} days as of ${formatDate(balance.effective_date)}` : balanceError || "Loading balance…"}</strong>
        </div>
      </div>
      {!applicablePolicies.length && <p className="form-error">No policy covers this employee and date range.</p>}
      {submitError && <p className="form-error" role="alert">{submitError}</p>}
      <div className="form-actions">
        <button type="button" className="button button-secondary" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="submit" className="button button-primary" disabled={busy || !policyId}>{busy ? "Submitting…" : "Submit request"}</button>
      </div>
    </form>
  );
}

function LeaveDetailPage({ showToast }) {
  const { requestId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [decision, setDecision] = useState(null);
  const [reason, setReason] = useState("");
  const [approverId, setApproverId] = useState("");
  const load = useCallback(async () => {
    const [request, events, employees, workflow] = await Promise.all([
      apiRequest(`/leave/requests/${encodeURIComponent(requestId)}`),
      fetchAll("/audit/events", { entity_type: "LeaveRequest", entity_id: requestId }),
      fetchAll("/employees"),
      apiRequest(`/leave/requests/${encodeURIComponent(requestId)}/workflow`),
    ]);
    return { request, events, employees, workflow };
  }, [requestId]);
  const { data, error, loading, reload } = useResource(load, [requestId]);
  useEffect(() => {
    if (!approverId && data?.employees?.length) {
      setApproverId(searchParams.get("approver") || data.employees[0].employee_id);
    }
  }, [approverId, data, searchParams]);
  const employee = data?.employees.find((item) => item.employee_id === data.request.employee_id);
  const manager = data?.employees.find((item) => item.employee_id === employee?.manager_id);
  async function submitDecision() {
    try {
      const request = data.request;
      await postJson(`/leave/requests/${encodeURIComponent(requestId)}/${decision}`, {
        approver_id: approverId,
        ...(decision === "reject" ? { reason } : {}),
      });
      showToast(`Leave request ${decision === "approve" ? "approved" : "rejected"}.`);
      setDecision(null);
      setReason("");
      reload();
    } catch (submitError) {
      showToast(submitError.message, "error");
    }
  }
  return (
    <>
      <PageHeader eyebrow="LEAVE REQUEST" title={requestId} description="Request details and recorded decision history." action={<button className="button button-secondary" onClick={() => navigate("/leave")}>← All requests</button>} />
      {loading && <LoadingState />}
      {error && <ErrorState error={error} onRetry={reload} />}
      {data && <>
        <div className="detail-layout">
          <section className="panel detail-main">
            <div className="panel-heading"><div><h2>Request information</h2><p>Submitted {formatDateTime(data.request.requested_at)}</p></div><StatusBadge status={data.request.status} /></div>
            <div className="field-grid">
              <Field label="Employee" value={`${employee?.name || data.request.employee_id} · ${data.request.employee_id}`} />
              <Field label="Manager" value={manager ? `${manager.name} · ${manager.employee_id}` : "Not listed"} />
              <Field label="Leave type" value={data.request.leave_type} />
              <Field label="Policy" value={data.request.policy_id} />
              <Field label="Start date" value={formatDate(data.request.start_date)} />
              <Field label="End date" value={formatDate(data.request.end_date)} />
              <Field label="Requested business days" value={`${data.request.total_days} days`} />
              <Field label="Decision reason" value={data.request.decision_reason || "No decision reason recorded"} />
            </div>
            <div className="section-heading"><h2>Balance snapshot</h2><span>As of {formatDate(data.workflow.balance.effective_date)}</span></div>
            <div className="field-grid">
              <Field label="Accrued" value={`${data.workflow.balance.accrued_balance} days`} />
              <Field label="Used" value={`${data.workflow.balance.used_balance} days`} />
              <Field label="Pending" value={`${data.workflow.balance.pending_balance} days`} />
              <Field label="Available" value={`${data.workflow.balance.available_balance} days`} />
            </div>
          </section>
          <section className="panel detail-side">
            <div className="panel-heading"><div><h2>Decision</h2><p>Submit to backend approval rules</p></div></div>
            {data.request.status === "Pending" ? <>
              <label className="form-label">Acting approver ID
                <select className="form-control" value={approverId} onChange={(event) => setApproverId(event.target.value)}>
                  {data.employees.map((person) => <option key={person.employee_id} value={person.employee_id}>{person.name} · {person.employee_id}</option>)}
                </select>
              </label>
              <p className="helper-text">Authentication is not enabled. The API validates assigned approver and sequence.</p>
              <div className="button-stack">
                <button className="button button-primary" onClick={() => setDecision("approve")}>Approve request</button>
                <button className="button button-danger" onClick={() => setDecision("reject")}>Reject request</button>
              </div>
            </> : <EmptyState title="No action available">This request is {data.request.status.toLowerCase()}.</EmptyState>}
          </section>
          <section className="panel detail-wide">
            <div className="panel-heading"><div><h2>Approval path</h2><p>Ordered approvers and recorded decisions</p></div></div>
            <ApprovalSteps steps={data.workflow.approval_steps} />
          </section>
          <section className="panel detail-wide">
            <div className="panel-heading"><div><h2>Audit history</h2><p>Persisted events for this request</p></div><span className="count-pill">{data.events.length} events</span></div>
            <AuditTimeline events={data.events} />
          </section>
        </div>
      </>}
      {decision && <ConfirmDialog title={decision === "approve" ? "Approve leave request?" : "Reject leave request?"} confirmLabel={decision === "approve" ? "Confirm approval" : "Confirm rejection"} confirmTone={decision === "reject" ? "danger" : "primary"} onConfirm={submitDecision} onCancel={() => { setDecision(null); setReason(""); }} confirmDisabled={decision === "reject" && !reason.trim()}>
        <p>This action is submitted to the backend and cannot be undone here.</p>
        {decision === "reject" && <label className="form-label">Reason for rejection<textarea className="form-control" rows="3" maxLength="2000" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Enter a reason" /></label>}
        {decision === "reject" && !reason.trim() && <small className="form-error">A rejection reason is required.</small>}
      </ConfirmDialog>}
    </>
  );
}

function ExpenseClaimsPage({ showToast }) {
  const navigate = useNavigate();
  const [showSubmit, setShowSubmit] = useState(false);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const load = useCallback(async () => {
    const [claims, employees, exceptionEvents, policies, costCenters] = await Promise.all([
      fetchAll("/expenses/claims"),
      fetchAll("/employees"),
      fetchAll("/audit/events", { exceptions_only: true }),
      apiRequest("/expenses/policies"),
      apiRequest("/cost-centers"),
    ]);
    return { claims, employees, exceptionEvents, policies, costCenters };
  }, []);
  const { data, error, loading, reload } = useResource(load, []);
  const employeeMap = useMemo(() => new Map((data?.employees || []).map((employee) => [employee.employee_id, employee])), [data]);
  const rows = useMemo(() => (data?.claims || []).filter((claim) => {
    const query = search.toLowerCase().trim();
    return (!status || claim.status === status)
      && (!query || [claim.claim_id, claim.employee_id, employeeMap.get(claim.employee_id)?.name, claim.cost_center_id]
        .some((value) => String(value || "").toLowerCase().includes(query)));
  }), [data, employeeMap, search, status]);
  const columns = [
    { key: "claim_id", label: "Claim", render: (row) => <DetailLink to={`/expenses/${row.claim_id}`}>{row.claim_id}</DetailLink> },
    { key: "employee_id", label: "Employee", render: (row) => <span><strong>{employeeMap.get(row.employee_id)?.name || row.employee_id}</strong><small className="cell-subtitle">{row.employee_id}</small></span> },
    { key: "total_amount", label: "Total", render: (row) => money(row.total_amount, row.currency) },
    { key: "category", label: "Category", render: () => <span className="muted">Not exposed by API</span> },
    { key: "cost_center_id", label: "Cost center" },
    { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
    { key: "exceptions", label: "Exceptions", render: (row) => {
      const count = data.exceptionEvents.filter((event) => event.entity_id === row.claim_id).length;
      return count ? <span className="exception-count">{count} recorded</span> : <span className="muted">None recorded</span>;
    } },
  ];
  return (
    <>
      <PageHeader
        eyebrow="FINANCE"
        title="Expense claims"
        description="Review submitted claims, status, and recorded exceptions."
        action={<button className="button button-primary" onClick={() => setShowSubmit((value) => !value)}>Submit expense claim</button>}
      />
      {showSubmit && data && <ExpenseClaimForm
        employees={data.employees}
        policies={data.policies}
        costCenters={data.costCenters}
        onCancel={() => setShowSubmit(false)}
        onSubmitted={(claim) => {
          setShowSubmit(false);
          showToast("Expense claim submitted for approval.");
          navigate(`/expenses/${claim.claim_id}`);
        }}
      />}
      <section className="panel">
        <div className="toolbar">
          <label className="search-field"><span aria-hidden="true">⌕</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search claim, employee, cost center…" /></label>
          <select className="filter-select" value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Filter by status"><option value="">All statuses</option>{["Pending", "Approved", "Rejected", "Paid", "Draft"].map((item) => <option key={item}>{item}</option>)}</select>
          {data && <span className="result-count">{rows.length} claims</span>}
        </div>
        {loading && <LoadingState />}
        {error && <ErrorState error={error} onRetry={reload} />}
        {data && <DataTable columns={columns} rows={rows} rowKey={(row) => row.claim_id} emptyTitle="No expense claims" emptyMessage="Try changing your search or status filter." />}
      </section>
    </>
  );
}

function ExpenseClaimForm({ employees, policies, costCenters, onCancel, onSubmitted }) {
  const activeEmployees = employees.filter((person) => person.status === "Active");
  const [employeeId, setEmployeeId] = useState(activeEmployees[0]?.employee_id || "");
  const [costCenterId, setCostCenterId] = useState(costCenters[0]?.cost_center_id || "");
  const [currency, setCurrency] = useState("USD");
  const [submissionDate, setSubmissionDate] = useState(new Date().toISOString().slice(0, 10));
  const [lines, setLines] = useState([{
    policy_id: "",
    amount: "",
    description: "",
    expense_date: new Date().toISOString().slice(0, 10),
    receipt_hash: "",
    receipt_url: "",
  }]);
  const [submitError, setSubmitError] = useState(null);
  const [busy, setBusy] = useState(false);
  const employee = activeEmployees.find((person) => person.employee_id === employeeId);
  const applicablePolicies = useMemo(() => policies.filter((policy) => (
    policy.country_code === "GLOBAL" || policy.country_code === employee?.country
  )), [policies, employee?.country]);

  useEffect(() => {
    setLines((current) => current.map((line) => (
      applicablePolicies.some((policy) => policy.policy_id === line.policy_id)
        ? line
        : { ...line, policy_id: applicablePolicies[0]?.policy_id || "" }
    )));
  }, [applicablePolicies]);

  function updateLine(index, key, value) {
    setLines((current) => current.map((line, lineIndex) => (
      lineIndex === index ? { ...line, [key]: value } : line
    )));
  }

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setSubmitError(null);
    try {
      const claim = await postJson("/expenses/claims", {
        employee_id: employeeId,
        cost_center_id: costCenterId,
        currency,
        submission_date: submissionDate,
        lines: lines.map((line) => ({
          ...line,
          amount: line.amount,
          receipt_hash: line.receipt_hash || null,
          receipt_url: line.receipt_url || null,
        })),
      });
      onSubmitted(claim);
    } catch (error) {
      setSubmitError(error.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="panel workflow-form" onSubmit={submit}>
      <div className="panel-heading"><div><h2>New expense claim</h2><p>Line totals, policy limits, receipts, budgets, and routing are validated by the API.</p></div></div>
      <div className="form-grid">
        <label className="form-label">Employee
          <select className="form-control" value={employeeId} onChange={(event) => setEmployeeId(event.target.value)} required>
            {activeEmployees.map((person) => <option key={person.employee_id} value={person.employee_id}>{person.name} · {person.employee_id}</option>)}
          </select>
        </label>
        <label className="form-label">Cost center
          <select className="form-control" value={costCenterId} onChange={(event) => setCostCenterId(event.target.value)} required>
            {costCenters.map((center) => <option key={center.cost_center_id} value={center.cost_center_id}>{center.name} · {center.cost_center_id}</option>)}
          </select>
        </label>
        <label className="form-label">Currency<input className="form-control" value={currency} onChange={(event) => setCurrency(event.target.value.toUpperCase())} minLength="3" maxLength="3" required /></label>
        <label className="form-label">Submission date<input className="form-control" type="date" value={submissionDate} onChange={(event) => setSubmissionDate(event.target.value)} required /></label>
      </div>
      <div className="form-lines-heading"><strong>Expense lines</strong><button type="button" className="button button-secondary" disabled={lines.length >= 10} onClick={() => setLines((current) => [...current, {
        policy_id: applicablePolicies[0]?.policy_id || "",
        amount: "",
        description: "",
        expense_date: submissionDate,
        receipt_hash: "",
        receipt_url: "",
      }])}>Add line</button></div>
      {lines.map((line, index) => <fieldset className="expense-line-form" key={index}>
        <legend>Line {index + 1}</legend>
        <div className="form-grid">
          <label className="form-label">Policy
            <select className="form-control" value={line.policy_id} onChange={(event) => updateLine(index, "policy_id", event.target.value)} required>
              {applicablePolicies.map((policy) => <option key={policy.policy_id} value={policy.policy_id}>{policy.category} · limit {policy.max_amount} {currency}</option>)}
            </select>
          </label>
          <label className="form-label">Amount<input className="form-control" type="number" min="0.01" step="0.01" value={line.amount} onChange={(event) => updateLine(index, "amount", event.target.value)} required /></label>
          <label className="form-label">Expense date<input className="form-control" type="date" value={line.expense_date} onChange={(event) => updateLine(index, "expense_date", event.target.value)} required /></label>
          <label className="form-label">Description<input className="form-control" value={line.description} onChange={(event) => updateLine(index, "description", event.target.value)} maxLength="1000" required /></label>
          <label className="form-label">Receipt hash<input className="form-control" value={line.receipt_hash} onChange={(event) => updateLine(index, "receipt_hash", event.target.value)} maxLength="128" /></label>
          <label className="form-label">Receipt URL<input className="form-control" type="url" value={line.receipt_url} onChange={(event) => updateLine(index, "receipt_url", event.target.value)} maxLength="2048" placeholder="https://…" /></label>
        </div>
        {lines.length > 1 && <button type="button" className="button button-text-danger" onClick={() => setLines((current) => current.filter((_, lineIndex) => lineIndex !== index))}>Remove line</button>}
      </fieldset>)}
      {!applicablePolicies.length && <p className="form-error">No expense policy applies to this employee.</p>}
      {submitError && <p className="form-error" role="alert">{submitError}</p>}
      <div className="form-actions">
        <button type="button" className="button button-secondary" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="submit" className="button button-primary" disabled={busy || !applicablePolicies.length || !costCenters.length}>{busy ? "Submitting…" : "Submit claim"}</button>
      </div>
    </form>
  );
}

function ExpenseDetailPage({ showToast }) {
  const { claimId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [decision, setDecision] = useState(null);
  const [reason, setReason] = useState("");
  const [approverId, setApproverId] = useState("");
  const [reimbursementForm, setReimbursementForm] = useState(false);
  const [paymentDate, setPaymentDate] = useState(new Date().toISOString().slice(0, 10));
  const [transactionRef, setTransactionRef] = useState("");
  const [reimbursementError, setReimbursementError] = useState(null);
  const [reimbursementBusy, setReimbursementBusy] = useState(false);
  const load = useCallback(async () => {
    const [claim, events, reimbursements, employees, workflow] = await Promise.all([
      apiRequest(`/expenses/claims/${encodeURIComponent(claimId)}`),
      fetchAll("/audit/events", { entity_type: "ExpenseClaim", entity_id: claimId }),
      fetchAll("/reimbursements"),
      fetchAll("/employees"),
      apiRequest(`/expenses/claims/${encodeURIComponent(claimId)}/workflow`),
    ]);
    return { claim, events, reimbursements: reimbursements.filter((item) => item.claim_id === claimId), employees, workflow };
  }, [claimId]);
  const { data, error, loading, reload } = useResource(load, [claimId]);
  useEffect(() => {
    if (!approverId && data?.employees?.length) {
      setApproverId(searchParams.get("approver") || data.employees[0].employee_id);
    }
  }, [approverId, data, searchParams]);
  const employee = data?.employees.find((person) => person.employee_id === data.claim.employee_id);
  async function submitDecision() {
    try {
      await postJson(`/expenses/claims/${encodeURIComponent(claimId)}/${decision}`, {
        approver_id: approverId,
        ...(decision === "reject" ? { reason } : {}),
      });
      showToast(`Expense claim ${decision === "approve" ? "approved" : "rejected"}.`);
      setDecision(null);
      setReason("");
      reload();
    } catch (submitError) {
      showToast(submitError.message, "error");
    }
    async function createReimbursement(event) {
      event.preventDefault();
      setReimbursementBusy(true);
      setReimbursementError(null);
      try {
        await postJson(`/expenses/claims/${encodeURIComponent(claimId)}/reimbursements`, {
          amount: data.claim.total_amount,
          payment_date: paymentDate,
          transaction_ref: transactionRef,
        });
        showToast("Reimbursement created.");
        setReimbursementForm(false);
        setTransactionRef("");
        reload();
      } catch (error) {
        setReimbursementError(error.message);
      } finally {
        setReimbursementBusy(false);
      }
    }
  }
  return (
    <>
      <PageHeader eyebrow="EXPENSE CLAIM" title={claimId} description="Claim information, audit events, and reimbursement status." action={<button className="button button-secondary" onClick={() => navigate("/expenses")}>← All claims</button>} />
      {loading && <LoadingState />}
      {error && <ErrorState error={error} onRetry={reload} />}
      {data && <>
        <div className="detail-layout">
          <section className="panel detail-main">
            <div className="panel-heading"><div><h2>Claim information</h2><p>Submitted {formatDate(data.claim.submission_date)}</p></div><StatusBadge status={data.claim.status} /></div>
            <div className="field-grid">
              <Field label="Employee" value={`${employee?.name || data.claim.employee_id} · ${data.claim.employee_id}`} />
              <Field label="Total amount" value={money(data.claim.total_amount, data.claim.currency)} />
              <Field label="Cost center" value={data.claim.cost_center_id} />
              <Field label="Currency" value={data.claim.currency} />
              <Field label="Decision reason" value={data.claim.decision_reason || "No decision reason recorded"} />
              <Field label="Budget" value={money(data.workflow.cost_center_budget, data.claim.currency)} />
              <Field label="Budget remaining" value={money(data.workflow.budget_remaining, data.claim.currency)} />
            </div>
          </section>
          <section className="panel detail-side">
            <div className="panel-heading"><div><h2>Reimbursement</h2><p>Linked payment records</p></div></div>
            {data.reimbursements.length ? data.reimbursements.map((item) => <div className="reimbursement-card" key={item.reimbursement_id}>
              <DetailLink to="/reimbursements">{item.reimbursement_id}</DetailLink>
              <strong>{money(item.amount, data.claim.currency)}</strong><StatusBadge status={item.status} />
              <small>Payment date {formatDate(item.payment_date)}</small>
            </div>) : <EmptyState title="No reimbursement">There is no reimbursement record linked to this claim.</EmptyState>}
          </section>
          <section className="panel detail-wide">
            <div className="panel-heading"><div><h2>Expense lines & controls</h2><p>Policy and receipt metadata captured at submission</p></div></div>
            <DataTable columns={[
              { key: "line_id", label: "Line", render: (line) => <span className="mono">{line.line_id}</span> },
              { key: "policy_category", label: "Category", render: (line) => <span>{line.policy_category}<small className="cell-subtitle">Limit {money(line.policy_max_amount, data.claim.currency)}</small></span> },
              { key: "description", label: "Description" },
              { key: "expense_date", label: "Date", render: (line) => formatDate(line.expense_date) },
              { key: "amount", label: "Amount", render: (line) => money(line.amount, data.claim.currency) },
              { key: "receipt_hash", label: "Receipt", render: (line) => line.receipt_hash ? <span className="mono">{line.receipt_hash}</span> : line.receipt_url || "Missing" },
            ]} rows={data.workflow.lines} rowKey={(line) => line.line_id} />
          </section>
          <section className="panel detail-wide">
            <div className="panel-heading"><div><h2>Approval path</h2><p>Ordered approvers and recorded decisions</p></div></div>
            <ApprovalSteps steps={data.workflow.approval_steps} />
          </section>
          <section className="panel detail-wide">
            <div className="panel-heading"><div><h2>Audit history</h2><p>Persisted events for this claim</p></div><span className="count-pill">{data.events.length} events</span></div>
            <AuditTimeline events={data.events} />
          </section>
          {data.claim.status === "Pending" && <section className="panel detail-wide decision-panel">
            <div className="panel-heading"><div><h2>Decision actions</h2><p>Backend validates authority, assignment, and sequence.</p></div></div>
            <div className="decision-controls">
              <label className="form-label">Acting approver ID<select className="form-control" value={approverId} onChange={(event) => setApproverId(event.target.value)}>{data.employees.map((person) => <option key={person.employee_id} value={person.employee_id}>{person.name} · {person.employee_id}</option>)}</select></label>
              <button className="button button-primary" onClick={() => setDecision("approve")}>Approve</button>
              <button className="button button-danger" onClick={() => setDecision("reject")}>Reject</button>
            </div>
            <p className="helper-text">Authentication is not enabled; the acting ID is not verified by a login session.</p>
          </section>}
          {data.claim.status === "Approved" && data.reimbursements.length === 0 && <section className="panel detail-wide">
            {!reimbursementForm ? <button className="button button-primary" onClick={() => setReimbursementForm(true)}>Create reimbursement</button> : <form className="form-grid reimbursement-form" onSubmit={createReimbursement}>
              <label className="form-label">Amount<input className="form-control" value={data.claim.total_amount} readOnly /></label>
              <label className="form-label">Payment date<input className="form-control" type="date" value={paymentDate} onChange={(event) => setPaymentDate(event.target.value)} required /></label>
              <label className="form-label">Transaction reference<input className="form-control" value={transactionRef} onChange={(event) => setTransactionRef(event.target.value)} maxLength="160" required /></label>
              {reimbursementError && <p className="form-error" role="alert">{reimbursementError}</p>}
              <div className="form-actions">
                <button type="button" className="button button-secondary" onClick={() => setReimbursementForm(false)} disabled={reimbursementBusy}>Cancel</button>
                <button type="submit" className="button button-primary" disabled={reimbursementBusy}>{reimbursementBusy ? "Creating…" : "Create reimbursement"}</button>
              </div>
            </form>}
          </section>}
        </div>
      </>}
      {decision && <ConfirmDialog title={decision === "approve" ? "Approve expense claim?" : "Reject expense claim?"} confirmLabel={decision === "approve" ? "Confirm approval" : "Confirm rejection"} confirmTone={decision === "reject" ? "danger" : "primary"} onConfirm={submitDecision} onCancel={() => { setDecision(null); setReason(""); }} confirmDisabled={decision === "reject" && !reason.trim()}>
        <p>This action is sent to the backend approval workflow.</p>
        {decision === "reject" && <label className="form-label">Reason for rejection<textarea className="form-control" rows="3" maxLength="2000" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Enter a reason" /></label>}
        {decision === "reject" && !reason.trim() && <small className="form-error">A rejection reason is required.</small>}
      </ConfirmDialog>}
    </>
  );
}

function ApprovalQueuePage() {
  const [approverId, setApproverId] = useState("");
  const load = useCallback(async () => {
    const employees = await fetchAll("/employees");
    const queue = approverId
      ? await apiRequest(`/approvals/queue?approver_id=${encodeURIComponent(approverId)}`)
      : [];
    return { queue, employees };
  }, [approverId]);
  const { data, error, loading, reload } = useResource(load, [approverId]);
  const rows = useMemo(() => {
    if (!data) return [];
    const names = new Map(data.employees.map((person) => [person.employee_id, person.name]));
    const actingApprover = encodeURIComponent(approverId);
    return data.queue.map((item) => ({
      ...item,
      kind: item.entity_type,
      id: item.request_id,
      amount: item.entity_type === "Leave"
        ? `${item.total_days} days`
        : money(item.amount, item.currency),
      requester: names.get(item.employee_id) || item.employee_id,
      route: `/${item.entity_type.toLowerCase() === "leave" ? "leave" : "expenses"}/${item.request_id}?approver=${actingApprover}`,
      status: "Pending",
    }));
  }, [data, approverId]);
  useEffect(() => {
    if (!approverId && data?.employees?.length) setApproverId(data.employees[0].employee_id);
  }, [approverId, data]);
  return (
    <>
      <PageHeader eyebrow="WORKFLOW" title="Approval queue" description="Pending leave and expense items awaiting an approval decision." />
      <div className="notice-banner"><span>i</span><p>The queue includes only pending approval steps assigned to the selected approver. Sign-in is not enabled; the API still verifies assignment and step sequence for each decision.</p></div>
      <section className="panel">
        <div className="toolbar">
          {data && <label className="form-label inline-label">Acting approver
            <select className="filter-select" value={approverId} onChange={(event) => setApproverId(event.target.value)}>{data.employees.map((person) => <option key={person.employee_id} value={person.employee_id}>{person.name} · {person.employee_id}</option>)}</select>
          </label>}
          <span className="result-count">{rows.length} pending items</span>
        </div>
        {loading && <LoadingState />}
        {error && <ErrorState error={error} onRetry={reload} />}
        {data && <DataTable columns={[
          { key: "id", label: "Request", render: (row) => <DetailLink to={row.route}>{row.id}</DetailLink> },
          { key: "kind", label: "Type", render: (row) => <span className="type-pill">{row.kind}</span> },
          { key: "requester", label: "Requester" },
          { key: "amount", label: "Amount / days" },
          { key: "sequence", label: "Approval step", render: (row) => `Step ${row.sequence} · ${row.step_id}` },
          { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
        ]} rows={rows} rowKey={(row) => row.id} emptyTitle="Queue is clear" emptyMessage="There are no pending leave requests or expense claims." />}
      </section>
    </>
  );
}

function ReimbursementsPage({ showToast }) {
  const { data, error, loading, reload } = useResource(() => fetchAll("/reimbursements"), []);
  const claims = useResource(() => fetchAll("/expenses/claims"), []);
  const claimMap = useMemo(() => new Map((claims.data || []).map((claim) => [claim.claim_id, claim])), [claims.data]);
  const rows = data || [];
  async function processReimbursement(reimbursementId) {
    try {
      await postJson(`/reimbursements/${encodeURIComponent(reimbursementId)}/process`, {});
      showToast("Reimbursement processed.");
      reload();
      claims.reload();
    } catch (error) {
      showToast(error.message, "error");
    }
  }
  const columns = [
    { key: "reimbursement_id", label: "Reimbursement", render: (row) => <span className="mono">{row.reimbursement_id}</span> },
    { key: "claim_id", label: "Claim", render: (row) => <DetailLink to={`/expenses/${row.claim_id}`}>{row.claim_id}</DetailLink> },
    { key: "amount", label: "Amount", render: (row) => money(row.amount, claimMap.get(row.claim_id)?.currency) },
    { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
    { key: "payment_state", label: "Payment state", render: (row) => row.processed_at ? `Processed ${formatDateTime(row.processed_at)}` : `Scheduled ${formatDate(row.payment_date)}` },
    { key: "transaction_ref", label: "Reference", render: (row) => <span className="mono">{row.transaction_ref}</span> },
    { key: "action", label: "Action", render: (row) => row.status === "Pending"
      ? <button className="button button-primary" onClick={() => processReimbursement(row.reimbursement_id)}>Process</button>
      : <span className="muted">Complete</span> },
  ];
  return (
    <>
      <PageHeader eyebrow="FINANCE" title="Reimbursements" description="Track payment records and processing state." />
      <section className="panel">
        <div className="toolbar"><span className="result-count">{rows.length} reimbursements</span></div>
        {(loading || claims.loading) && <LoadingState />}
        {(error || claims.error) && <ErrorState error={error || claims.error} onRetry={() => { reload(); claims.reload(); }} />}
        {data && claims.data && <DataTable columns={columns} rows={rows} rowKey={(row) => row.reimbursement_id} emptyTitle="No reimbursements" emptyMessage="Reimbursement records created by the API will appear here." />}
      </section>
    </>
  );
}

function ApprovalSteps({ steps }) {
  if (!steps.length) return <EmptyState title="No approval steps">No approvers were assigned to this workflow.</EmptyState>;
  return <DataTable
    columns={[
      { key: "sequence", label: "Step", render: (step) => `${step.sequence} · ${step.step_id}` },
      { key: "approver_id", label: "Approver", render: (step) => <span className="mono">{step.approver_id}</span> },
      { key: "status", label: "Status", render: (step) => <StatusBadge status={step.status} /> },
      { key: "action_date", label: "Decided", render: (step) => formatDateTime(step.action_date) },
      { key: "decision_reason", label: "Reason" },
      { key: "comments", label: "Comments" },
    ]}
    rows={steps}
    rowKey={(step) => step.step_id}
  />;
}

function AuditTimeline({ events }) {
  if (!events.length) return <EmptyState title="No audit events">No audit records were returned for this entity.</EmptyState>;
  return (
    <div className="timeline">
      {events.map((event) => (
        <article className="timeline-item" key={event.event_id}>
          <span className={`timeline-dot${event.is_exception ? " timeline-dot-warning" : ""}`} />
          <div className="timeline-content">
            <div className="timeline-title"><strong>{event.event_type.replaceAll("_", " ")}</strong>{event.is_exception && <span className="severity-badge">Exception</span>}</div>
            <p>{event.reason || event.exception_code || "No reason recorded"}</p>
            <small>{formatDateTime(event.occurred_at)} · {event.actor_employee_id || "System"}</small>
          </div>
        </article>
      ))}
    </div>
  );
}

function AuditPage() {
  const [search, setSearch] = useState("");
  const [exceptionsOnly, setExceptionsOnly] = useState(false);
  const load = useCallback(() => fetchAll("/audit/events", exceptionsOnly ? { exceptions_only: true } : {}), [exceptionsOnly]);
  const { data, error, loading, reload } = useResource(load, [exceptionsOnly]);
  const rows = useMemo(() => (data || []).filter((event) => {
    const query = search.trim().toLowerCase();
    return !query || [event.entity_type, event.entity_id, event.event_type, event.exception_code, event.reason]
      .some((value) => String(value || "").toLowerCase().includes(query));
  }), [data, search]);
  return (
    <>
      <PageHeader eyebrow="GOVERNANCE" title="Audit & exceptions" description="Trace decisions and review issues recorded by backend workflows." />
      <section className="panel">
        <div className="toolbar">
          <label className="search-field"><span aria-hidden="true">⌕</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search entity, event, issue, reason…" /></label>
          <label className="toggle-label"><input type="checkbox" checked={exceptionsOnly} onChange={(event) => setExceptionsOnly(event.target.checked)} /> Exceptions only</label>
          {data && <span className="result-count">{rows.length} events</span>}
        </div>
        {loading && <LoadingState />}
        {error && <ErrorState error={error} onRetry={reload} />}
        {data && <DataTable columns={[
          { key: "entity_type", label: "Entity", render: (row) => <span><strong>{row.entity_type}</strong><small className="cell-subtitle mono">{row.entity_id}</small></span> },
          { key: "event_type", label: "Event", render: (row) => row.event_type.replaceAll("_", " ") },
          { key: "exception_code", label: "Issue type", render: (row) => row.exception_code || "—" },
          { key: "severity", label: "Severity", render: (row) => <span className={row.is_exception ? "severity-badge" : "muted"}>{row.is_exception ? "Not assigned" : "—"}</span> },
          { key: "reason", label: "Reason", render: (row) => row.reason || "No reason recorded" },
          { key: "occurred_at", label: "Timestamp", render: (row) => formatDateTime(row.occurred_at) },
        ]} rows={rows} rowKey={(row) => row.event_id} emptyTitle="No audit events" emptyMessage="No events matched the selected filter." />}
      </section>
      <UnavailableNote>Severity levels are not assigned by the backend and are not inferred in this UI.</UnavailableNote>
    </>
  );
}

function EmployeesPage() {
  const { data, error, loading, reload } = useResource(() => fetchAll("/employees"), []);
  const [search, setSearch] = useState("");
  const employees = useMemo(() => data || [], [data]);
  const employeeMap = useMemo(() => new Map(employees.map((employee) => [employee.employee_id, employee])), [employees]);
  const rows = useMemo(() => {
    const query = search.trim().toLowerCase();
    const filtered = employees.filter((person) => !query || [person.employee_id, person.name, person.email, person.department, person.country]
      .some((value) => String(value || "").toLowerCase().includes(query)));
    const depth = (person) => {
      let level = 0;
      let managerId = person.manager_id;
      const seen = new Set([person.employee_id]);
      while (managerId && employeeMap.has(managerId) && !seen.has(managerId)) {
        seen.add(managerId);
        level += 1;
        managerId = employeeMap.get(managerId).manager_id;
      }
      return level;
    };
    return filtered
      .map((person) => ({ ...person, hierarchyDepth: depth(person) }))
      .sort((a, b) => a.hierarchyDepth - b.hierarchyDepth || a.name.localeCompare(b.name));
  }, [employees, employeeMap, search]);
  const columns = [
    { key: "name", label: "Employee", render: (row) => <span className="employee-name-cell" style={{ marginLeft: `${Math.min(row.hierarchyDepth * 13, 39)}px` }}><span className="avatar">{row.name.slice(0, 1).toUpperCase()}</span><span><strong>{row.name}</strong><small className="cell-subtitle">{row.employee_id}</small></span></span> },
    { key: "manager_id", label: "Reports to", render: (row) => row.manager_id ? <span>{employeeMap.get(row.manager_id)?.name || row.manager_id}<small className="cell-subtitle">{row.manager_id}</small></span> : <span className="top-level-label">Top level</span> },
    { key: "department", label: "Department" },
    { key: "country", label: "Country" },
    { key: "hire_date", label: "Hire date", render: (row) => formatDate(row.hire_date) },
    { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
  ];
  return (
    <>
      <PageHeader eyebrow="PEOPLE" title="Employees" description="Employee directory with manager relationships from the API." />
      <section className="panel">
        <div className="toolbar"><label className="search-field"><span aria-hidden="true">⌕</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search name, ID, department, country…" /></label>{data && <span className="result-count">{rows.length} employees</span>}</div>
        {loading && <LoadingState />}
        {error && <ErrorState error={error} onRetry={reload} />}
        {data && <DataTable columns={columns} rows={rows} rowKey={(row) => row.employee_id} emptyTitle="No employees found" emptyMessage="Try a different search term." />}
      </section>
    </>
  );
}

export default function App() {
  const { toast, showToast } = useToast();
  return (
    <AppLayout toast={toast}>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/approvals" element={<ApprovalQueuePage />} />
        <Route path="/leave" element={<LeaveRequestsPage showToast={showToast} />} />
        <Route path="/leave/:requestId" element={<LeaveDetailPage showToast={showToast} />} />
        <Route path="/expenses" element={<ExpenseClaimsPage showToast={showToast} />} />
        <Route path="/expenses/:claimId" element={<ExpenseDetailPage showToast={showToast} />} />
        <Route path="/reimbursements" element={<ReimbursementsPage showToast={showToast} />} />
        <Route path="/audit" element={<AuditPage />} />
        <Route path="/employees" element={<EmployeesPage />} />
        <Route path="/analytics" element={<AnalyticsPage />} />
        <Route path="*" element={<main className="not-found"><h1>Page not found</h1><Link to="/">Return to dashboard</Link></main>} />
      </Routes>
    </AppLayout>
  );
}
