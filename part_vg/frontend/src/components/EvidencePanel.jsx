import { useMemo, useState } from "react";
import { ChevronDown, ShieldAlert } from "lucide-react";
import { useBifrost } from "../BifrostContext.jsx";
import { workerDisplayLabel } from "../utils/workerLabel.js";

function ModeLabel({ mode }) {
  if (mode == null) return "—";
  const labels = { 1: "Mode 1 · local/simple", 2: "Mode 2 · single worker", 3: "Mode 3 · parallel fan-out" };
  return labels[mode] ?? `Mode ${mode}`;
}

export default function EvidencePanel() {
  const { payload, running } = useBifrost();
  const [open, setOpen] = useState(true);

  const routing = payload?.routing;
  const workers = payload?.workers ?? [];
  const evidence = payload?.evidence ?? { tools: [], blocks: [] };
  const cost = payload?.cost;
  const wm = payload?.metrics?.workers;

  const workerPlans = useMemo(
    () =>
      workers.map((w) => ({
        id: w.id,
        label: workerDisplayLabel(w),
        role: w.role,
        backend: w.backend,
        model: w.model,
        owned: (w.owned_files ?? []).join(", ") || "—",
        status: w.status,
        is_local: w.is_local,
      })),
    [workers],
  );

  const hasContent =
    running ||
    routing?.mode != null ||
    workerPlans.length > 0 ||
    evidence.tools?.length > 0 ||
    evidence.blocks?.length > 0 ||
    payload?.log_path;

  if (!hasContent) {
    return (
      <div className="glass-card p-3">
        <p className="text-xs font-medium text-white/45">Evidence / proof</p>
        <p className="mt-1 text-[11px] text-white/35">
          Routing, worker plans, tool calls, and safety blocks appear during a run.
        </p>
      </div>
    );
  }

  return (
    <div className="evidence-panel glass-card overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="evidence-panel-header flex w-full items-center justify-between gap-2 px-3 py-2 text-left"
      >
        <span className="text-xs font-semibold uppercase tracking-wide text-bifrost/80">
          Evidence / proof
        </span>
        <ChevronDown
          className={`h-3.5 w-3.5 text-white/40 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && (
        <div className="evidence-panel-body space-y-3 border-t border-white/[0.06] px-3 py-2 scrollbar-thin">
          <section>
            <p className="evidence-section-label">Routing</p>
            <p className="font-mono text-[11px] text-bifrost/90">
              <ModeLabel mode={routing?.mode} />
              {wm?.total > 0 && (
                <span className="text-white/55">
                  {" "}
                  · {wm.total} workers ({wm.local}L / {wm.cloud}C)
                </span>
              )}
            </p>
            {routing?.reasoning && (
              <p className="mt-0.5 text-[10px] text-white/50">{routing.reasoning}</p>
            )}
            {routing?.summary && (
              <p className="mt-0.5 truncate text-[10px] text-white/40" title={routing.summary}>
                {routing.summary}
              </p>
            )}
          </section>

          {workerPlans.length > 0 && (
            <section>
              <p className="evidence-section-label">Worker plan</p>
              <ul className="max-h-32 space-y-1 overflow-y-auto scrollbar-thin">
                {workerPlans.map((w) => (
                  <li
                    key={w.id}
                    className="rounded border border-white/[0.05] bg-black/20 px-2 py-1 text-[10px]"
                  >
                    <span className="font-medium text-white/70">{w.label}</span>
                    <span className="text-white/40">
                      {" "}
                      · {w.role} · {w.is_local ? "local" : "cloud"} · {w.model}
                    </span>
                    <p className="truncate font-mono text-white/45" title={w.owned}>
                      owns: {w.owned}
                    </p>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {evidence.tools?.length > 0 && (
            <section>
              <p className="evidence-section-label">Tool activity</p>
              <ul className="max-h-28 space-y-0.5 overflow-y-auto font-mono text-[9px] text-white/55 scrollbar-thin">
                {evidence.tools.slice(-12).map((t, i) => (
                  <li key={i} className="truncate" title={t.text}>
                    <span className="text-bifrost/80">{t.tool}</span> {t.text.slice(0, 72)}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {evidence.blocks?.length > 0 && (
            <section>
              <p className="evidence-section-label flex items-center gap-1 text-red-400/90">
                <ShieldAlert className="h-3 w-3" />
                Safety blocks
              </p>
              <ul className="space-y-1">
                {evidence.blocks.map((b, i) => (
                  <li
                    key={i}
                    className="rounded border border-red-500/20 bg-red-500/10 px-2 py-1 text-[10px] text-red-200/90"
                  >
                    {b.text}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {cost && (
            <section>
              <p className="evidence-section-label">Cost</p>
              <p className="font-mono text-[10px] text-white/60">
                ${cost.total?.toFixed(4)} / ${cost.cap} cap
                {cost.warning && " · warning"}
                {cost.stopped && " · stopped"}
              </p>
            </section>
          )}

          {payload?.log_path && (
            <section>
              <p className="evidence-section-label">Session log</p>
              <p className="break-all font-mono text-[9px] text-white/45">{payload.log_path}</p>
              {payload?.run_id && (
                <p className="font-mono text-[9px] text-white/35">run_id: {payload.run_id}</p>
              )}
            </section>
          )}
        </div>
      )}
    </div>
  );
}
