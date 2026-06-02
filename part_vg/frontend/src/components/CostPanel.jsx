import { formatUsd, shortModel } from "../utils/format.js";

export default function CostPanel({ cost, savings }) {
  if (!cost) return null;

  const pct = Math.min(100, Math.round((cost.fraction ?? 0) * 100));
  const warnAt = 75;

  return (
    <section className="rounded-xl border border-slate-700/80 bg-slate-900/40 p-4">
      <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
        Cost &amp; savings
      </h2>

      <div className="mb-1 flex justify-between text-sm">
        <span
          className={`font-semibold transition-colors ${
            cost.stopped
              ? "text-red-300"
              : cost.warning
                ? "text-amber-300"
                : "text-slate-200"
          }`}
        >
          {formatUsd(cost.total)}
        </span>
        <span className="text-slate-400">/ {formatUsd(cost.cap)}</span>
      </div>

      <div className="relative mb-2 h-4 overflow-hidden rounded-full bg-slate-800 ring-1 ring-slate-700/50">
        <div
          className="pointer-events-none absolute inset-y-0 left-0 bg-amber-600/25"
          style={{ width: `${warnAt}%` }}
        />
        <div
          className="pointer-events-none absolute inset-y-0 bg-red-600/20"
          style={{ left: `${warnAt}%`, right: 0 }}
        />
        <div
          className={`relative h-full rounded-full transition-all duration-500 ease-out ${
            cost.stopped
              ? "bg-red-500"
              : cost.warning
                ? "bg-amber-500"
                : "bg-cyan-500"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>

      <p className="mb-4 text-[11px] text-slate-500">
        {cost.stopped && (
          <span className="font-semibold text-red-400">■ hard cap — stopped </span>
        )}
        {cost.warning && !cost.stopped && (
          <span className="font-semibold text-amber-400">⚠ warning (75%) </span>
        )}
        <span className="tabular-nums">{pct}%</span> of cap (VG.3)
      </p>

      <div className="max-h-40 space-y-2 overflow-y-auto scrollbar-thin">
        {(savings ?? []).slice(0, 6).map((row) => {
          const maxSave = Math.max(
            ...(savings ?? []).map((s) => Math.abs(s.saved)),
            0.001,
          );
          const w = Math.max(4, (Math.abs(row.saved) / maxSave) * 100);
          return (
            <div key={row.model}>
              <div className="flex justify-between gap-2 text-[11px] text-slate-400">
                <span className="truncate">{shortModel(row.model)}</span>
                <span className="shrink-0 tabular-nums">
                  {formatUsd(row.would_cost)}{" "}
                  <span className="text-emerald-500/90">
                    (−{formatUsd(row.saved)})
                  </span>
                </span>
              </div>
              <div className="mt-0.5 h-1.5 overflow-hidden rounded bg-slate-800">
                <div
                  className="h-full rounded bg-violet-600/70 transition-all duration-500"
                  style={{ width: `${w}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
