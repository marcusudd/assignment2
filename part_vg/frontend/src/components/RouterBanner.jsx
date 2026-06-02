export default function RouterBanner({ routing, workers, fallbackDetected }) {
  if (!routing?.summary && !routing?.mode) {
    return null;
  }

  const locals = workers?.filter((w) => w.is_local).length ?? 0;
  const clouds = workers?.filter((w) => !w.is_local).length ?? 0;
  const mode = routing.mode ?? "?";

  return (
    <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-slate-700/80 bg-slate-900/50 px-4 py-2 text-sm">
      <span className="rounded bg-violet-900/80 px-2 py-0.5 font-bold text-violet-200">
        ⬡ Mode {mode}
      </span>
      <span className="text-slate-300">{routing.summary}</span>
      {fallbackDetected && (
        <span className="rounded bg-amber-900/70 px-2 py-0.5 text-[11px] font-bold text-amber-300 ring-1 ring-amber-600/40">
          ⚠ local→cloud fallback
        </span>
      )}
      {workers?.length > 0 && (
        <span className="ml-auto text-xs text-slate-500">
          {locals > 0 && <span className="text-emerald-400">{locals}🏠</span>}
          {locals > 0 && clouds > 0 && " / "}
          {clouds > 0 && <span className="text-sky-400">{clouds}☁️</span>}
        </span>
      )}
    </div>
  );
}
