import { formatUsd } from "../utils/format.js";

export default function Header({
  task,
  onTaskChange,
  cap,
  onCapChange,
  onRun,
  onReset,
  busy,
  connected,
  cost,
  status,
  streamError,
  isMock,
  running,
}) {
  const fraction = cost?.fraction ?? 0;
  const pct = Math.min(100, Math.round(fraction * 100));

  return (
    <header className="mb-4 space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="bg-gradient-to-r from-cyan-300 to-violet-300 bg-clip-text text-2xl font-bold tracking-tight text-transparent">
          BIFROST
        </h1>
        {isMock && (
          <span className="rounded bg-violet-900/70 px-2 py-0.5 text-[10px] font-bold text-violet-200">
            MOCK SSE
          </span>
        )}
        <span
          className={`rounded px-2 py-0.5 text-xs font-medium transition-colors ${
            connected
              ? "bg-emerald-900/80 text-emerald-200"
              : "bg-red-900/80 text-red-200"
          }`}
        >
          {connected ? "● live" : "○ reconnecting"}
        </span>
        {running && (
          <span className="rounded bg-cyan-900/50 px-2 py-0.5 text-xs text-cyan-200">
            run active
          </span>
        )}
        {cost && (
          <span
            className={`ml-auto rounded-full px-3 py-1 text-xs font-semibold tabular-nums transition-colors ${
              cost.stopped
                ? "bg-red-900 text-red-100"
                : cost.warning
                  ? "bg-amber-900 text-amber-100"
                  : "bg-slate-800 text-slate-200"
            }`}
          >
            {formatUsd(cost.total)} / {formatUsd(cost.cap)} ({pct}%)
          </span>
        )}
      </div>

      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
        <input
          type="text"
          value={task}
          onChange={(e) => onTaskChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !busy && !isMock) onRun();
          }}
          placeholder="Task description…"
          disabled={isMock}
          className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-900/90 px-3 py-2.5 text-slate-100 placeholder:text-slate-500 focus:border-cyan-600 focus:outline-none focus:ring-1 focus:ring-cyan-600/50 disabled:opacity-50"
        />
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-slate-400">
            cap $
            <input
              type="number"
              step="0.01"
              min="0"
              value={cap}
              onChange={(e) => onCapChange(e.target.value)}
              disabled={isMock}
              className="w-20 rounded-lg border border-slate-700 bg-slate-900/90 px-2 py-2.5 tabular-nums text-slate-100 focus:border-cyan-600 focus:outline-none disabled:opacity-50"
            />
          </label>
          <button
            type="button"
            onClick={onRun}
            disabled={busy || isMock}
            className="rounded-lg bg-cyan-600 px-5 py-2.5 font-semibold text-white shadow-lg shadow-cyan-900/30 transition hover:bg-cyan-500 active:scale-[0.98] disabled:opacity-40"
          >
            ▶ Run
          </button>
          <button
            type="button"
            onClick={onReset}
            disabled={busy || isMock}
            className="rounded-lg border border-slate-600 px-4 py-2.5 transition hover:bg-slate-800 active:scale-[0.98] disabled:opacity-40"
          >
            Reset workspace
          </button>
        </div>
      </div>

      {(status || streamError) && (
        <p className="text-xs text-amber-300/90">
          {status}
          {streamError ? ` · ${streamError}` : ""}
        </p>
      )}
    </header>
  );
}
