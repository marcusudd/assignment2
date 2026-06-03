import { useMemo, useState, useEffect } from "react";
import { Activity } from "lucide-react";
import { useBifrost } from "../BifrostContext.jsx";
import LogEntry from "./LogEntry.jsx";
import { sortEventsByTs } from "../utils/logFormat.js";
import { workerDisplayLabel, workerShortId } from "../utils/workerLabel.js";

function TimeSeriesChart({ title, points, yMax, ySuffix = "", emptyHint }) {
  const width = 280;
  const height = 88;
  const values = points.map((p) => p.v);
  const hasData = values.length > 0;
  const max = Math.max(yMax ?? 0, ...values, 1);
  const min = 0;
  const range = max - min || 1;

  const coords = points.map((p, i) => {
    const x = (i / Math.max(points.length - 1, 1)) * width;
    const y = height - ((p.v - min) / range) * (height - 10) - 5;
    return `${x},${y}`;
  });

  const linePath = coords.length ? `M ${coords.join(" L ")}` : "";
  const areaPath = linePath
    ? `${linePath} L ${width},${height} L 0,${height} Z`
    : "";

  const latest = points[points.length - 1];

  return (
    <div className="chart-card">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <p className="text-xs font-medium text-white/45">{title}</p>
        {latest != null && (
          <span className="font-mono text-sm font-semibold text-bifrost">
            {latest.v.toFixed(1)}
            {ySuffix}
          </span>
        )}
      </div>
      {!hasData ? (
        <p className="py-6 text-center text-[11px] text-white/35">{emptyHint}</p>
      ) : (
        <svg viewBox={`0 0 ${width} ${height}`} className="w-full" aria-hidden>
          <defs>
            <linearGradient id="tsFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#7dff5a" stopOpacity="0.35" />
              <stop offset="100%" stopColor="#1b4322" stopOpacity="0" />
            </linearGradient>
            <linearGradient id="tsLine" x1="0" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#1b4322" />
              <stop offset="50%" stopColor="#39ff14" />
              <stop offset="100%" stopColor="#7dff5a" />
            </linearGradient>
          </defs>
          {[0.25, 0.5, 0.75, 1].map((frac) => (
            <line
              key={frac}
              x1="0"
              y1={height - frac * (height - 10) - 5}
              x2={width}
              y2={height - frac * (height - 10) - 5}
              stroke="rgba(255,255,255,0.04)"
              strokeWidth="1"
            />
          ))}
          {areaPath && <path d={areaPath} fill="url(#tsFill)" />}
          {linePath && (
            <path
              d={linePath}
              fill="none"
              stroke="url(#tsLine)"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}
        </svg>
      )}
      {hasData && (
        <p className="mt-1 font-mono text-[9px] text-white/30">
          elapsed {latest?.t?.toFixed(1) ?? 0}s · {points.length} samples
        </p>
      )}
    </div>
  );
}

function useLiveMetricHistory(runId, elapsed, value, resetWhen, live = true) {
  const [points, setPoints] = useState([]);

  useEffect(() => {
    setPoints([]);
  }, [runId, resetWhen]);

  useEffect(() => {
    if (!live || value == null || Number.isNaN(value)) return;
    setPoints((prev) => {
      const last = prev[prev.length - 1];
      if (
        last &&
        Math.abs(last.v - value) < 0.05 &&
        Math.abs(last.t - elapsed) < 0.15
      ) {
        return prev;
      }
      return [...prev, { t: elapsed, v: value }].slice(-80);
    });
  }, [value, elapsed, live]);

  return points;
}

function LatencyGauge({ value, max = 200, live = true }) {
  const pct = Math.min(100, (value / max) * 100);
  const r = 36;
  const circ = 2 * Math.PI * r;
  const offset = circ - (pct / 100) * circ * 0.75;

  return (
    <div className="chart-card flex items-center gap-4">
      <div className="relative h-20 w-20 shrink-0">
        <svg viewBox="0 0 88 88" className="h-full w-full -rotate-[135deg]">
          <defs>
            <linearGradient id="gaugeGrad" x1="0%" y1="100%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#1b4322" />
              <stop offset="45%" stopColor="#2d8a24" />
              <stop offset="100%" stopColor="#7dff5a" />
            </linearGradient>
            <filter id="gaugeGlow">
              <feGaussianBlur stdDeviation="1.2" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>
          <circle
            cx="44"
            cy="44"
            r={r}
            fill="none"
            stroke="rgba(27,67,34,0.55)"
            strokeWidth="7"
            strokeDasharray={`${circ * 0.75} ${circ}`}
            strokeLinecap="round"
          />
          <circle
            cx="44"
            cy="44"
            r={r}
            fill="none"
            stroke="url(#gaugeGrad)"
            strokeWidth="7"
            strokeDasharray={`${circ * 0.75} ${circ}`}
            strokeDashoffset={offset}
            strokeLinecap="round"
            filter="url(#gaugeGlow)"
            className="transition-all duration-500"
          />
        </svg>
        <span className="absolute inset-0 flex items-center justify-center font-mono text-sm font-medium text-bifrost">
          {Math.round(value)}
        </span>
      </div>
      <div>
        <p className="text-sm font-medium text-slate-300">
          Worker span{live ? "" : " · frozen"}
        </p>
        <p className="font-mono text-xs text-slate-500">
          {live ? "max lane duration (live)" : "final run duration"}
        </p>
        <p className="mt-1 text-lg font-semibold text-bifrost/90">
          {Math.round(value)}
          <span className="text-xs font-normal text-slate-500"> s</span>
        </p>
      </div>
    </div>
  );
}

function TokensBarChart({ workers }) {
  const bars = workers.slice(0, 8);
  const maxTokens = Math.max(...bars.map((w) => w.tokens), 1);
  const total = bars.reduce((s, w) => s + w.tokens, 0);

  return (
    <div className="chart-card">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-sm font-medium text-white/70">Tokens / worker</p>
        <span className="font-mono text-sm font-semibold text-bifrost">{total}</span>
      </div>
      {bars.length === 0 ? (
        <p className="text-xs text-white/35">No workers yet</p>
      ) : (
        <>
          <div className="mb-3 flex h-24 items-end justify-between gap-1.5">
            {bars.map((w) => {
              const h = Math.min(100, (w.tokens / maxTokens) * 100);
              const pct = total ? Math.round((w.tokens / total) * 100) : 0;
              return (
                <div
                  key={w.id}
                  className="flex min-w-0 flex-1 flex-col items-center gap-1"
                  title={`${workerDisplayLabel(w)} (${w.id})\n${w.tokens} tokens · ${pct}% of run\n${w.prompt_tokens ?? "?"} in / ${w.completion_tokens ?? "?"} out\n${w.model}`}
                >
                  <span className="font-mono text-[10px] font-semibold text-bifrost/90">
                    {w.tokens > 999 ? `${(w.tokens / 1000).toFixed(1)}k` : w.tokens}
                  </span>
                  <div
                    className={`bar-glow w-full transition-all duration-500 ${
                      w.is_local ? "" : "opacity-90"
                    }`}
                    style={{
                      height: `${Math.max(h, 10)}%`,
                      minHeight: "8px",
                      background: w.is_local
                        ? "linear-gradient(180deg, #7dff5a 0%, #39ff14 35%, rgba(27,67,34,0.85) 100%)"
                        : "linear-gradient(180deg, #9ec8ff 0%, #5a9fd4 40%, rgba(27,67,34,0.85) 100%)",
                    }}
                  />
                  <span className="w-full truncate text-center text-[9px] font-medium text-white/55">
                    {workerShortId(w)}
                  </span>
                  <span className="font-mono text-[8px] text-white/35">{pct}%</span>
                </div>
              );
            })}
          </div>
          <ul className="space-y-1.5 border-t border-white/[0.06] pt-2">
            {bars.map((w) => (
              <li
                key={`row-${w.id}`}
                className="flex items-center justify-between gap-2 text-[10px]"
              >
                <span className="min-w-0 truncate font-mono text-[10px] text-white/65">
                  {w.id}
                </span>
                <span className="shrink-0 font-mono text-bifrost/80">
                  {w.tokens.toLocaleString()}
                  {(w.prompt_tokens != null || w.completion_tokens != null) && (
                    <span className="text-white/35">
                      {" "}
                      ({w.prompt_tokens ?? 0}+{w.completion_tokens ?? 0})
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function WorkerLogTabs({ workers, events }) {
  const lanes = useMemo(() => {
    const map = new Map();
    for (const w of workers) {
      map.set(w.id, { worker: w, events: [] });
    }
    for (const ev of events) {
      const wid = ev.worker || "_run";
      if (!map.has(wid)) {
        map.set(wid, { worker: { id: wid, label: wid }, events: [] });
      }
      map.get(wid).events.push(ev);
    }
    return [...map.values()].sort((a, b) => {
      const aRun = a.worker.status === "running" ? 0 : 1;
      const bRun = b.worker.status === "running" ? 0 : 1;
      return aRun - bRun || a.worker.id.localeCompare(b.worker.id);
    });
  }, [workers, events]);

  const [activeTab, setActiveTab] = useState("all");
  const [realmFilter, setRealmFilter] = useState("all");

  useEffect(() => {
    if (activeTab === "all") return;
    if (!lanes.some((lane) => lane.worker.id === activeTab)) {
      setActiveTab("all");
    }
  }, [lanes, activeTab]);

  const realmFilteredEvents = useMemo(() => {
    if (realmFilter === "all") return events;
    if (realmFilter === "bifrost") {
      return events.filter((ev) => ev.realm === "bifrost" || ev.kind === "routing");
    }
    return events.filter((ev) => ev.realm === realmFilter);
  }, [events, realmFilter]);

  const filteredEvents = useMemo(() => {
    const base =
      activeTab === "all"
        ? realmFilteredEvents
        : lanes.find((lane) => lane.worker.id === activeTab)?.events ?? [];
    return sortEventsByTs(base);
  }, [activeTab, lanes, realmFilteredEvents]);

  if (events.length === 0 && lanes.length === 0) {
    return (
      <div className="glass-card p-3">
        <p className="mb-2 text-xs font-medium text-white/45">Worker logs</p>
        <p className="text-[11px] text-white/35">
          Events appear when a run is active.
        </p>
      </div>
    );
  }

  return (
    <div className="glass-card p-3">
      <p className="mb-2 text-xs font-medium text-white/45">Worker logs</p>
      <div className="mb-2 flex flex-wrap gap-1.5">
        {[
          ["all", "All realms"],
          ["bifrost", "Router"],
          ["midgard", "Midgard"],
          ["asgard", "Asgard"],
        ].map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setRealmFilter(id)}
            className={`worker-tab ${realmFilter === id ? "worker-tab-active" : ""}`}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="mb-3 flex flex-wrap gap-1.5">
        <button
          type="button"
          onClick={() => setActiveTab("all")}
          className={`worker-tab ${activeTab === "all" ? "worker-tab-active" : ""}`}
        >
          All ({events.length})
        </button>
        {lanes.map(({ worker, events: laneEvents }) => {
          const isRunning = worker.status === "running";
          return (
            <button
              key={worker.id}
              type="button"
              onClick={() => setActiveTab(worker.id)}
              title={worker.id}
              className={`worker-tab max-w-[120px] truncate ${
                activeTab === worker.id ? "worker-tab-active" : ""
              } ${isRunning ? "worker-tab-running" : ""}`}
            >
              {workerDisplayLabel(worker)} ({laneEvents.length})
            </button>
          );
        })}
      </div>
      <ul className="max-h-56 space-y-2 overflow-y-auto scrollbar-thin">
        {filteredEvents.length === 0 ? (
          <li className="text-[11px] text-white/35">No events for this worker.</li>
        ) : (
          filteredEvents.map((ev, i) => (
            <LogEntry
              key={`${activeTab}-${realmFilter}-${i}`}
              worker={activeTab === "all" ? ev.worker : null}
              text={ev.text}
              kind={ev.kind}
              ts={ev.ts}
              realm={ev.realm}
            />
          ))
        )}
      </ul>
      <p className="mt-2 text-[9px] leading-relaxed text-white/30">
        Filter by realm (Router / Midgard / Asgard) or pick a worker tab.
        Router shows delegation; Midgard/Asgard show lane activity.
      </p>
    </div>
  );
}

function shortModelId(id) {
  const parts = id.split("/");
  return parts.length > 1 ? parts[parts.length - 1] : id;
}

export default function Analytics() {
  const {
    payload,
    isMock,
    comparisonModel,
    setComparisonModel,
    comparisonModels,
  } = useBifrost();

  const workers = payload?.workers ?? [];
  const cost = payload?.cost;
  const savings = payload?.savings ?? [];
  const events = payload?.events ?? [];

  const workerSpanSec = payload?.metrics?.span_sec ?? 0;
  const spanLive = payload?.metrics?.span_live ?? false;

  const selectedSaving = useMemo(
    () => savings.find((s) => s.model === comparisonModel),
    [savings, comparisonModel],
  );
  const costSaved = selectedSaving?.saved ?? 0;
  const cloudBaseline = selectedSaving?.would_cost ?? 0;
  const localSaved = selectedSaving?.local_saved ?? 0;
  const routingSaved = selectedSaving?.routing_saved ?? 0;
  const savePct = cloudBaseline
    ? Math.min(100, Math.max(0, (costSaved / cloudBaseline) * 100))
    : 0;
  const budgetPct = Math.min(100, (cost?.fraction ?? 0) * 100);
  const costIsNegative = costSaved <= 0 && cloudBaseline > 0;

  const savingsHistory = useLiveMetricHistory(
    payload?.run_id,
    workerSpanSec,
    savePct,
    comparisonModel,
    spanLive,
  );
  const spendHistory = useLiveMetricHistory(
    payload?.run_id,
    workerSpanSec,
    budgetPct,
    "budget",
    spanLive,
  );

  return (
    <aside className="glass-panel flex h-full min-h-0 flex-col overflow-hidden">
      <div className="relative z-10 flex min-h-0 flex-1 flex-col overflow-y-auto p-4 scrollbar-thin">
        <header className="mb-4">
          <div className="mb-1 flex items-center gap-2">
            <Activity className="h-4 w-4 text-bifrost/90" />
            <h1 className="text-base font-semibold tracking-tight text-slate-100">
              Heimdall&apos;s Watch
            </h1>
          </div>
          <p className="text-xs text-slate-500">
            Live from SSE{isMock && " · mock"}
          </p>
        </header>

        <div className="mb-4 space-y-4">
          <TimeSeriesChart
            title={`Savings vs ${shortModelId(comparisonModel)} (live %)`}
            points={savingsHistory}
            yMax={100}
            ySuffix="%"
            emptyHint="Start a run to track savings % over time"
          />
          <TimeSeriesChart
            title="Budget cap used (live %)"
            points={spendHistory}
            yMax={100}
            ySuffix="%"
            emptyHint="Budget usage appears during a run"
          />
          <LatencyGauge value={workerSpanSec} max={15} live={spanLive} />
          <TokensBarChart workers={workers} />
          <WorkerLogTabs workers={workers} events={events} />

          <div className="glass-card overflow-hidden p-4">
            <div className="mb-2 flex items-center justify-between gap-2">
              <p className="text-xs font-medium text-slate-500">
                Saved vs all-{shortModelId(comparisonModel)}, no Bifrost
              </p>
              <select
                value={comparisonModel}
                onChange={(e) => setComparisonModel(e.target.value)}
                className="select-glass max-w-[140px] truncate text-[10px] font-mono"
                aria-label="Comparison model"
              >
                {comparisonModels.map((m) => (
                  <option key={m} value={m}>
                    {shortModelId(m)}
                  </option>
                ))}
              </select>
            </div>

            {costIsNegative ? (
              <p className="mb-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-white/50">
                Bifrost costs more than {shortModelId(comparisonModel)} on this baseline
                — switch to a premium model (e.g. Opus, GPT-5) to see the saving.
              </p>
            ) : (
              <>
                <div className="mb-1 flex items-baseline gap-2">
                  <p className="metric-glow-text text-4xl font-semibold tracking-tight text-bifrost">
                    ${costSaved.toFixed(2)}
                  </p>
                  {savePct > 0 && (
                    <span className="text-lg font-semibold text-bifrost/70">
                      {Math.round(savePct)}% cheaper
                    </span>
                  )}
                </div>
                {(localSaved > 0 || routingSaved > 0) && (
                  <div className="mb-2 space-y-1 rounded-lg border border-white/[0.06] bg-white/[0.03] px-3 py-2">
                    <div className="flex justify-between text-[10px]">
                      <span className="text-white/45">Local execution (free tokens)</span>
                      <span className="font-mono font-medium text-bifrost/80">
                        +${localSaved.toFixed(3)}
                      </span>
                    </div>
                    <div className="flex justify-between text-[10px]">
                      <span className="text-white/45">Model routing (cloud tier)</span>
                      <span className="font-mono font-medium text-bifrost/80">
                        +${routingSaved > 0 ? routingSaved.toFixed(3) : "0.000"}
                      </span>
                    </div>
                  </div>
                )}
              </>
            )}

            <p className="mb-1 text-xs text-slate-500">
              Actual spend: ${(cost?.total ?? 0).toFixed(4)}
              {" · "}baseline: ${cloudBaseline > 0 ? cloudBaseline.toFixed(2) : "—"}
              {" · "}budget: {Math.round(budgetPct)}% of cap
              {cost?.warning && " · ⚠ near cap"}
              {cost?.stopped && " · 🛑 cap hit"}
            </p>
            <div className="h-2 overflow-hidden rounded-full bg-midgard/80 shadow-glass-inset">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{
                  width: `${budgetPct}%`,
                  background:
                    budgetPct >= 90
                      ? "linear-gradient(90deg, #7f1d1d 0%, #ef4444 70%, #fca5a5 100%)"
                      : "linear-gradient(90deg, #1b4322 0%, #39ff14 70%, #5dff4a 100%)",
                  boxShadow:
                    budgetPct >= 90
                      ? "0 0 12px rgba(239,68,68,0.35)"
                      : "0 0 12px rgba(57,255,20,0.35)",
                }}
              />
            </div>
            <div className="mt-2 flex justify-between font-mono text-[10px] text-slate-600">
              <span>$0 spent</span>
              <span>${cost?.cap?.toFixed(2) ?? "—"} cap</span>
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
}
