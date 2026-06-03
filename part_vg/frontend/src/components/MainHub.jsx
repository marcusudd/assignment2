import { useRef, useEffect } from "react";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  Cloud,
  RotateCcw,
  SendHorizonal,
  Server,
  Shrink,
  XCircle,
} from "lucide-react";
import { useBifrost } from "../BifrostContext.jsx";
import LogEntry from "./LogEntry.jsx";
import RoutingBridge from "./RoutingBridge.jsx";

function RoutingFlow({
  routing,
  workers,
  fallbackDetected,
  localEnabled,
  cloudEnabled,
}) {
  const summary = routing?.summary ?? "Idle — submit a task to route";
  const hasLocalWorkers = (workers ?? []).some((w) => w.is_local);
  const hasCloudWorkers = (workers ?? []).some((w) => !w.is_local);
  const midgardLit =
    localEnabled && (hasLocalWorkers || routing?.mode === 1);
  const asgardLit =
    cloudEnabled &&
    (hasCloudWorkers || fallbackDetected || routing?.mode === 3);
  const bridgeLit = midgardLit && asgardLit;

  return (
    <div className="glass-card overflow-hidden p-4">
      <div className="mb-3 rounded-xl border border-bifrost/30 bg-bifrost/10 px-4 py-2.5 shadow-neon-soft backdrop-blur-md">
        <p className="text-center text-sm font-medium text-white/85">{summary}</p>
      </div>

      <div className="flex items-stretch gap-2">
        <div
          className={`flex w-[88px] shrink-0 flex-col items-center gap-2 px-2 py-3 transition-all duration-300 ${
            midgardLit ? "glass-realm-card-active" : "glass-realm-card opacity-55"
          }`}
        >
          <div className="flex h-10 w-10 items-center justify-center rounded-full border border-white/[0.08] bg-black/30 shadow-glass-inset">
            <Server
              className={`h-4 w-4 ${midgardLit ? "text-bifrost" : "text-slate-500"}`}
            />
          </div>
          <div className="flex items-center gap-1 text-[11px] font-medium text-white/80">
            <ArrowDown className="h-3 w-3 text-bifrost/80" />
            Midgard
          </div>
          <span className="text-center text-[9px] text-white/45">
            {!localEnabled ? "off" : "Local"}
          </span>
        </div>

        <RoutingBridge active={bridgeLit || midgardLit || asgardLit} compact />

        <div
          className={`flex w-[88px] shrink-0 flex-col items-center gap-2 px-2 py-3 transition-all duration-300 ${
            asgardLit ? "glass-realm-card-active" : "glass-realm-card opacity-55"
          }`}
        >
          <div className="flex h-10 w-10 items-center justify-center rounded-full border border-white/[0.08] bg-black/30 shadow-glass-inset">
            <Cloud
              className={`h-4 w-4 ${asgardLit ? "text-bifrost" : "text-slate-500"}`}
            />
          </div>
          <div className="flex items-center gap-1 text-[11px] font-medium text-white/80">
            <ArrowUp className="h-3 w-3 text-bifrost/80" />
            Asgard
          </div>
          <span className="text-center text-[9px] text-white/45">
            {!cloudEnabled ? "off" : "Cloud"}
          </span>
        </div>
      </div>
    </div>
  );
}

function WorkerRow({ worker }) {
  return (
    <div className="glass-card px-3 py-2.5">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-xs font-medium text-white/75">
          {worker.id}
        </span>
        <span
          className={`rounded-md px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${
            worker.is_local
              ? "bg-bifrost/15 text-bifrost"
              : "bg-white/5 text-white/50"
          }`}
        >
          {worker.is_local ? "midgard" : "asgard"}
        </span>
      </div>
      <p className="mt-1.5 truncate font-mono text-[11px] text-white/50">
        {worker.action || worker.status}
      </p>
    </div>
  );
}

export default function MainHub() {
  const {
    payload,
    connected,
    streamError,
    isMock,
    task,
    setTask,
    cap,
    setCap,
    status,
    busy,
    running,
    handleRun,
    handleReset,
    handleCompact,
    localEnabled,
    cloudEnabled,
  } = useBifrost();
  const feedEndRef = useRef(null);

  useEffect(() => {
    feedEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [payload?.events, payload?.result, payload?.workers]);

  const events = payload?.events ?? [];
  const workers = payload?.workers ?? [];
  const costStopped = Boolean(payload?.cost?.stopped);
  const costOverCap =
    costStopped ||
    (payload?.cost &&
      (payload.cost.fraction >= 1 || payload.cost.total >= payload.cost.cap));
  const compactionCount = events.filter((e) => e.kind === "compaction").length;

  return (
    <main className="glass-panel flex h-full min-h-0 flex-col overflow-hidden">
      <div className="relative z-10 flex min-h-0 flex-1 flex-col p-4">
        <header className="mb-4 shrink-0">
          <div className="flex items-start justify-between gap-2">
            <div>
              <h1 className="text-base font-semibold tracking-tight text-white">
                Bifrost Router & Playground
              </h1>
              <p className="text-xs text-white/45">
                {running
                  ? `Running · ${payload?.phase ?? "…"}`
                  : connected
                    ? "Ready"
                    : streamError || "Waiting for backend"}
                {isMock && " · mock SSE"}
              </p>
            </div>
            <div className="flex items-center gap-1.5">
              {compactionCount > 0 && (
                <span
                  title="Context compaction events this run"
                  className="flex items-center gap-1 rounded-md bg-bifrost/15 px-1.5 py-0.5 text-[10px] font-medium text-bifrost"
                >
                  <Shrink className="h-3 w-3" />
                  compacted ×{compactionCount}
                </span>
              )}
              <button
                type="button"
                onClick={handleCompact}
                disabled={!running || isMock}
                title="Compact session"
                className="glass-card rounded-xl p-2 text-white/45 transition-all duration-300 hover:text-bifrost disabled:opacity-40"
              >
                <Shrink className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={handleReset}
                disabled={busy || running || isMock}
                title="Reset workspace"
                className="glass-card rounded-xl p-2 text-white/45 transition-all duration-300 hover:text-bifrost disabled:opacity-40"
              >
                <RotateCcw className="h-4 w-4" />
              </button>
            </div>
          </div>
          {status && (
            <p className="mt-2 text-xs text-bifrost">{status}</p>
          )}
          {payload?.log_path && (
            <p className="mt-1 font-mono text-[10px] text-white/40">
              Log: {payload.log_path}
            </p>
          )}
        </header>

        <section className="mb-4 shrink-0">
          <h2 className="section-label mb-3">Routing logic</h2>
          <RoutingFlow
            routing={payload?.routing}
            workers={workers}
            fallbackDetected={payload?.fallback_detected}
            localEnabled={localEnabled}
            cloudEnabled={cloudEnabled}
          />
        </section>

        <section className="flex min-h-0 flex-1 flex-col">
          <div className="mb-3 flex items-center justify-between gap-2">
            <h2 className="section-label">Agent activity</h2>
            {payload?.cost && (
              <span
                className={costOverCap ? "cost-badge-warn" : "cost-badge"}
              >
                ${payload.cost.total?.toFixed(4)} / ${payload.cost.cap}
              </span>
            )}
          </div>

          <div className="chat-grid-bg mb-3 min-h-0 flex-1 overflow-y-auto p-4 scrollbar-thin">
            {costStopped && (
              <div className="cap-banner mb-3">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" strokeWidth={2.25} />
                <span>
                  Budget cap reached — agent stopped. Raise the cap and run again to continue.
                </span>
              </div>
            )}
            {payload?.task && (
              <p className="mb-3 rounded-xl border border-white/[0.05] bg-white/[0.03] px-3 py-2 text-sm text-white/60">
                <span className="font-medium text-white/40">Task: </span>
                {payload.task}
              </p>
            )}
            {workers.length > 0 && (
              <div className="mb-3 space-y-2">
                {workers.map((w) => (
                  <WorkerRow key={w.id} worker={w} />
                ))}
              </div>
            )}
            {events.length > 0 && (
              <ul className="mb-3 space-y-2">
                {events.map((ev, i) => (
                  <LogEntry
                    key={i}
                    worker={ev.worker}
                    text={ev.text}
                    kind={ev.kind}
                  />
                ))}
              </ul>
            )}
            {payload?.result && (
              <div className="result-panel p-4">
                <p className="mb-2 text-[10px] font-bold uppercase tracking-[0.2em] text-bifrost">
                  Result
                </p>
                <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed text-white/75 scrollbar-thin">
                  {payload.result}
                </pre>
              </div>
            )}
            {payload?.error && (
              <div className="log-entry log-entry-error mt-2">
                <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-orange-400" />
                <span>{payload.error}</span>
              </div>
            )}
            {!payload?.task && events.length === 0 && !payload?.result && (
              <p className="text-sm text-white/45">
                Submit a task to start the orchestrator (backend on :8000).
              </p>
            )}
            <div ref={feedEndRef} />
          </div>

          <div className="flex gap-2">
            <label className="sr-only" htmlFor="cost-cap">
              Cost cap USD
            </label>
            <input
              id="cost-cap"
              type="text"
              value={cap}
              onChange={(e) => setCap(e.target.value)}
              placeholder="Cap $"
              className="input-glass w-24 px-3 py-3.5 text-sm font-mono text-white/70"
            />
            <input
              type="text"
              value={task}
              onChange={(e) => setTask(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleRun()}
              placeholder="Enter orchestrator task…"
              disabled={busy || running}
              className="input-glass flex-1 px-4 py-3.5 text-sm text-white/85 transition-all duration-300 placeholder:text-white/30 disabled:opacity-50"
            />
            <button
              type="button"
              onClick={handleRun}
              disabled={busy || running || !task.trim()}
              className="send-glossy flex items-center gap-2 px-6 py-3.5 text-sm font-semibold text-midgard transition-all duration-300 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <SendHorizonal className="h-5 w-5" strokeWidth={2.25} />
              Kör
            </button>
          </div>
        </section>
      </div>
    </main>
  );
}
