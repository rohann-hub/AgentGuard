import { useState } from "react";
import type { Approval, ApprovalState } from "../api";
import { formatTime, formatValue, relative } from "../lib";
import { Card, Empty, Loading, Mono, Notice, PageHeader, StatusBadge, useAction, useLoad } from "../ui";

const FILTERS: { id: ApprovalState | "all"; label: string }[] = [
  { id: "pending", label: "Waiting" },
  { id: "approved", label: "Approved" },
  { id: "used", label: "Used" },
  { id: "rejected", label: "Rejected" },
  { id: "expired", label: "Expired" },
  { id: "all", label: "All" },
];

export function ApprovalsView() {
  const [filter, setFilter] = useState<ApprovalState | "all">("pending");
  const approvals = useLoad((api) => api.approvals(filter === "all" ? undefined : filter), [filter]);
  const agents = useLoad((api) => api.agents());
  const action = useAction();
  const names = new Map(agents.data?.map((a) => [a.id, a.name]));

  async function decide(a: Approval, verdict: "approve" | "reject") {
    const done = await action.run(a.id + verdict, (api) =>
      verdict === "approve" ? api.approve(a.id) : api.reject(a.id),
    );
    if (done) approvals.reload();
  }

  return (
    <>
      <PageHeader
        title="Approvals"
        lead="Requests that policy held for a person. Approving lets the agent resubmit the same request once, within the hour. Policy runs again when it does."
        actions={
          <button type="button" className="btn btn--secondary" onClick={approvals.reload}>
            Refresh
          </button>
        }
      />
      {(approvals.error || action.error) && (
        <Notice onDismiss={action.error ? action.clearError : undefined}>
          {action.error ?? approvals.error}
        </Notice>
      )}

      <div role="group" aria-label="Show approvals" className="mb-5 flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            aria-pressed={filter === f.id}
            onClick={() => setFilter(f.id)}
            className="h-9 rounded-md border border-line-strong px-3 text-[14px] font-medium text-text transition-colors duration-150 hover:border-ink hover:text-ink aria-pressed:border-ink aria-pressed:bg-ink aria-pressed:text-on-ink"
          >
            {f.label}
          </button>
        ))}
      </div>

      {approvals.loading && !approvals.data ? (
        <Card>
          <Loading />
        </Card>
      ) : !approvals.data?.length ? (
        <Card>
          <Empty title={filter === "pending" ? "Nothing is waiting for you" : "No approvals here"}>
            {filter === "pending"
              ? "When policy holds a request, such as a refund over ₹5,000, it shows up here."
              : "Try another filter."}
          </Empty>
        </Card>
      ) : (
        <ul className="grid gap-4">
          {approvals.data.map((a) => (
            <li key={a.id}>
              <Card>
                <div className="flex flex-col gap-5 px-5 py-5 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-3">
                      <StatusBadge value={a.status} />
                      <h2 className="text-[17px] font-medium text-ink">
                        <Mono>
                          {a.tool_name}.{a.action}
                        </Mono>
                      </h2>
                      <span className="text-[14px] text-muted">
                        by {names.get(a.agent_id) ?? "unknown agent"}
                      </span>
                    </div>
                    <p className="mt-3 text-[15px] leading-relaxed text-text">{a.reason}</p>
                    <dl className="mt-4 grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-[14px]">
                      {Object.entries(a.arguments).map(([k, v]) => (
                        <div key={k} className="contents">
                          <dt className="text-muted">{k}</dt>
                          <dd className="min-w-0 font-mono text-[13px] break-all text-ink">{formatValue(v)}</dd>
                        </div>
                      ))}
                    </dl>
                    <p className="mt-4 text-[13px] text-muted">
                      Request <Mono>{a.request_id}</Mono> · held {formatTime(a.created_at)}
                      {a.status === "pending" && <> · expires {relative(a.expires_at)}</>}
                      {a.decided_at && <> · decided {formatTime(a.decided_at)}</>}
                    </p>
                  </div>
                  {a.status === "pending" && (
                    <div className="flex shrink-0 gap-3">
                      <button
                        type="button"
                        className="btn btn--primary"
                        disabled={action.busy !== null}
                        onClick={() => decide(a, "approve")}
                      >
                        {action.busy === a.id + "approve" ? "Approving…" : "Approve request"}
                      </button>
                      <button
                        type="button"
                        className="btn btn--danger"
                        disabled={action.busy !== null}
                        onClick={() => decide(a, "reject")}
                      >
                        {action.busy === a.id + "reject" ? "Rejecting…" : "Reject"}
                      </button>
                    </div>
                  )}
                </div>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
