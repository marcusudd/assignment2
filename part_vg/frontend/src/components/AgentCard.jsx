import { actionStyle } from "../utils/actionStyle.js";
import { formatUsd, shortModel } from "../utils/format.js";

const STATUS_DOT = {
  pending: "bg-slate-500",
  running: "bg-cyan-400 animate-pulse",
  done: "bg-emerald-400",
  error: "bg-red-500",
  aborted: "bg-amber-400",
};

export default function AgentCard({ worker }) {
  const w = worker;
  const icon = w.is_local ? "🏠" : "☁️";
  const { text } = actionStyle(w.action);
  const dot = STATUS_DOT[w.status] || "bg-slate-500";
  const running = w.status === "running";

  return (
    <article
      className={`rounded-lg border bg-slate-900/60 p-3 transition-all duration-300 ${
        running
          ? "border-cyan-700/50 shadow-md shadow-cyan-950/30 animate-pulse-ring"
          : "border-slate-700/70"
      }`}
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="font-semibold text-slate-200">{w.id}</span>
        <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${dot}`} title={w.status} />
      </div>
      <p className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">
        {w.role}
      </p>
      <p className="mb-2 truncate text-xs">
        <span className={w.is_local ? "text-emerald-400" : "text-sky-400"}>
          {icon}
        </span>{" "}
        {shortModel(w.model)}
      </p>
      <p
        className={`mb-2 min-h-[2.25rem] line-clamp-2 text-xs transition-colors ${text}`}
      >
        {w.action || w.status}
      </p>
      <div className="flex justify-between border-t border-slate-800/80 pt-2 text-[11px] tabular-nums text-slate-400">
        <span>{w.tokens ?? 0} tok</span>
        <span>{formatUsd(w.cost)}</span>
      </div>
    </article>
  );
}
