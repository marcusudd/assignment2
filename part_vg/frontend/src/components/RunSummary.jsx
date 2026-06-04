import { FilePlus, FilePen } from "lucide-react";

export default function RunSummary({ built, runSummary, logPath, phase }) {
  if (phase !== "done") return null;

  const created = built?.created ?? [];
  const modified = built?.modified ?? [];
  const hasFiles = created.length > 0 || modified.length > 0;
  const hasSummary = runSummary && Object.keys(runSummary).length > 0;

  if (!hasFiles && !hasSummary && !logPath) return null;

  return (
    <div className="run-summary-panel mb-3 rounded-xl border border-bifrost/20 bg-bifrost/5 p-3">
      {hasSummary && (
        <p className="mb-2 font-mono text-[11px] text-bifrost/90">
          {runSummary.workers} workers · {runSummary.span_sec?.toFixed(1)}s · $
          {runSummary.cost_usd?.toFixed(4)} / ${runSummary.cap_usd} cap
          {runSummary.stopped && " · cap stopped"}
          {(runSummary.files_created > 0 || runSummary.files_modified > 0) &&
            ` · ${runSummary.files_created}+ ${runSummary.files_modified}~ files`}
        </p>
      )}
      {hasFiles && (
        <>
          <p className="mb-1.5 text-[10px] font-bold uppercase tracking-[0.15em] text-bifrost/80">
            Built in workspace
          </p>
          <ul className="max-h-28 space-y-0.5 overflow-y-auto font-mono text-[10px] scrollbar-thin">
            {created.map((f) => (
              <li key={`+${f}`} className="flex items-center gap-1 text-bifrost/85">
                <FilePlus className="h-3 w-3 shrink-0 opacity-70" />
                {f}
              </li>
            ))}
            {modified.map((f) => (
              <li key={`~${f}`} className="flex items-center gap-1 text-white/65">
                <FilePen className="h-3 w-3 shrink-0 opacity-70" />
                {f}
              </li>
            ))}
          </ul>
        </>
      )}
      {!hasFiles && phase === "done" && (
        <p className="text-[10px] text-white/40">No workspace file changes detected.</p>
      )}
      {logPath && (
        <p className="mt-2 truncate font-mono text-[9px] text-white/35" title={logPath}>
          Log: {logPath}
        </p>
      )}
    </div>
  );
}
