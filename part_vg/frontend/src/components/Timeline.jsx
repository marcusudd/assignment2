import { useEffect, useMemo, useRef } from "react";
import { actionStyle } from "../utils/actionStyle.js";
import { phaseLabel, shortModel } from "../utils/format.js";
import {
  effectiveEnd,
  useTimelineClock,
} from "../hooks/useTimelineClock.js";

export default function Timeline({ workers, phase, running, parallelOverlap }) {
  const useClientClock = import.meta.env.VITE_MOCK_SSE === "1";
  const { elapsedSec, resetEpoch } = useTimelineClock(running, useClientClock);
  const prevRunning = useRef(false);

  useEffect(() => {
    if (running && !prevRunning.current) {
      resetEpoch();
    }
    prevRunning.current = running;
  }, [running, resetEpoch]);

  const { bars, maxEnd } = useMemo(() => {
    const list = workers ?? [];
    if (!list.length) {
      return { bars: [], maxEnd: 1 };
    }
    const starts = list.map((w) => w.start).filter((s) => s != null);
    const minS = starts.length ? Math.min(...starts) : 0;
    const ends = list.map((w) => effectiveEnd(w, elapsedSec, minS, useClientClock));
    const maxE = Math.max(...ends, 0.1);
    const items = list.map((w) => {
      const start = w.start ?? 0;
      const end = effectiveEnd(w, elapsedSec, minS, useClientClock);
      const left = (start / maxE) * 100;
      const width = Math.max(((end - start) / maxE) * 100, 2);
      return { worker: w, left, width, elapsed: end - start };
    });
    return { bars: items, maxEnd: maxE };
  }, [workers, elapsedSec, useClientClock]);

  return (
    <section className="mb-4 rounded-xl border border-cyan-900/40 bg-slate-900/50 p-4 shadow-lg shadow-cyan-950/20">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-xs uppercase tracking-wider text-slate-500">
        <span className="font-semibold text-slate-400">Parallel timeline</span>
        <div className="flex items-center gap-2">
          {parallelOverlap && (
            <span className="rounded-full bg-emerald-900/60 px-2 py-0.5 text-[10px] font-bold text-emerald-300 ring-1 ring-emerald-600/40">
              VG.1 overlap
            </span>
          )}
          <span
            className={`rounded px-2 py-0.5 font-bold transition-colors ${
              phase === "fanout"
                ? "bg-cyan-900/70 text-cyan-200"
                : phase === "integration"
                  ? "bg-violet-900/70 text-violet-200"
                  : "bg-slate-800 text-slate-400"
            }`}
          >
            {phaseLabel(phase)}
          </span>
        </div>
      </div>

      {!bars.length ? (
        <p className="text-sm text-slate-500">No workers yet — run a task.</p>
      ) : (
        <ul className="space-y-3">
          {bars.map(({ worker: w, left, width, elapsed }) => {
            const icon = w.is_local ? "🏠" : "☁️";
            const lane = w.is_local ? "text-emerald-400" : "text-sky-400";
            const { bar, text } = actionStyle(w.action);
            const isRunning = w.status === "running";
            const label = w.action || w.status;
            return (
              <li
                key={w.id}
                className="grid grid-cols-[minmax(5rem,7rem)_1fr_3.5rem] items-center gap-2 sm:grid-cols-[7rem_1fr_3.5rem]"
              >
                <div className={`truncate text-xs font-medium ${lane}`}>
                  <span className="mr-0.5">{icon}</span>
                  {shortModel(w.model)}
                </div>
                <div className="relative h-7 overflow-hidden rounded-md bg-slate-800/90 ring-1 ring-slate-700/50">
                  <div
                    className={`absolute top-0 h-full rounded-md transition-all duration-300 ease-out ${bar} ${
                      isRunning ? "animate-bar-shimmer" : ""
                    }`}
                    style={{ left: `${left}%`, width: `${width}%` }}
                  />
                  <span
                    className={`relative z-10 block truncate px-2 py-1.5 text-[11px] leading-none ${text}`}
                  >
                    {label}
                  </span>
                </div>
                <span className="text-right text-xs tabular-nums text-slate-400">
                  {elapsed.toFixed(1)}s
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {maxEnd > 0 && bars.length > 0 && (
        <p className="mt-2 text-right text-[10px] text-slate-600">
          span {maxEnd.toFixed(1)}s · cloud lanes should overlap for mode 3
        </p>
      )}
    </section>
  );
}
