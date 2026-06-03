import { useRef, useEffect, useCallback, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  ChevronDown,
  Cloud,
  Loader2,
  RotateCcw,
  SendHorizonal,
  Server,
  Shrink,
  XCircle,
} from "lucide-react";
import { useBifrost } from "../BifrostContext.jsx";
import LogEntry from "./LogEntry.jsx";
import RoutingBridge from "./RoutingBridge.jsx";
import { sortEventsByTs } from "../utils/logFormat.js";
import { workerDisplayLabel } from "../utils/workerLabel.js";

const SCROLL_THRESHOLD = 80;
const TEXTAREA_MAX_ROWS = 6;

function WorkerChip({ worker }) {
  const isRunning = worker.status === "running";
  const isDone =
    worker.status === "done" ||
    worker.status === "completed" ||
    worker.status === "finished";

  return (
    <div
      className={`routing-worker-chip ${isRunning ? "routing-worker-chip-active worker-active" : ""} ${
        isDone ? "opacity-75" : ""
      }`}
      title={worker.id}
    >
      <div className="flex items-start justify-between gap-1.5">
        <div className="flex min-w-0 items-center gap-1.5">
          <WorkerPulse active={isRunning} />
          <span className="truncate text-[11px] font-medium text-white/80">
            {worker.label || workerDisplayLabel(worker)}
          </span>
        </div>
        {isDone && (
          <CheckCircle2 className="h-3 w-3 shrink-0 text-bifrost/70" strokeWidth={2} />
        )}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-1">
        <span className="rounded bg-white/5 px-1 py-px text-[9px] font-medium uppercase text-white/45">
          {worker.role || "worker"}
        </span>
        <span className="truncate font-mono text-[9px] text-white/40">
          {worker.action || worker.status}
        </span>
      </div>
    </div>
  );
}

function RealmWorkerColumn({ title, workers, emptyHint }) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-2">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-white/45">
        {title} · {workers.length}
      </p>
      {workers.length === 0 ? (
        <p className="rounded-lg border border-dashed border-white/[0.06] px-2 py-3 text-center text-[10px] text-white/30">
          {emptyHint}
        </p>
      ) : (
        <div className="space-y-1.5">
          {workers.map((w) => (
            <WorkerChip key={w.id} worker={w} />
          ))}
        </div>
      )}
    </div>
  );
}

function RoutingFlow({
  routing,
  workers,
  workerMetrics,
  fallbackDetected,
  localEnabled,
  cloudEnabled,
}) {
  const summary = routing?.summary ?? "Idle — submit a task to route";
  const localWorkers = (workers ?? []).filter((w) => w.is_local);
  const cloudWorkers = (workers ?? []).filter((w) => !w.is_local);
  const hasLocalWorkers = localWorkers.length > 0;
  const hasCloudWorkers = cloudWorkers.length > 0;
  const midgardLit =
    localEnabled && (hasLocalWorkers || routing?.mode === 1);
  const asgardLit =
    cloudEnabled &&
    (hasCloudWorkers || fallbackDetected || routing?.mode === 3);
  const bridgeLit = midgardLit && asgardLit;
  const localCount = workerMetrics?.local ?? localWorkers.length;
  const cloudCount = workerMetrics?.cloud ?? cloudWorkers.length;

  return (
    <div className="glass-card overflow-hidden p-3">
      <div className="mb-2 rounded-lg border border-bifrost/25 bg-bifrost/8 px-3 py-1.5">
        <p className="truncate text-center text-xs font-medium text-white/80" title={summary}>
          {summary}
        </p>
        {(workerMetrics?.total ?? workers?.length ?? 0) > 0 && (
          <p className="mt-1 text-center font-mono text-[10px] text-bifrost/70">
            {workerMetrics?.total ?? workers.length} workers
            {localCount > 0 && ` · ${localCount} local`}
            {cloudCount > 0 && ` · ${cloudCount} cloud`}
          </p>
        )}
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
            {!localEnabled ? "off" : localCount > 0 ? `${localCount} active` : "Local"}
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
            {!cloudEnabled ? "off" : cloudCount > 0 ? `${cloudCount} active` : "Cloud"}
          </span>
        </div>
      </div>

      {(workers?.length ?? 0) > 0 ? (
        <div className="mt-3 grid max-h-[100px] gap-3 overflow-y-auto border-t border-white/[0.06] pt-3 scrollbar-thin sm:grid-cols-2">
          <RealmWorkerColumn
            title="Midgard"
            workers={localWorkers}
            emptyHint="Inga lokala workers"
          />
          <RealmWorkerColumn
            title="Asgard"
            workers={cloudWorkers}
            emptyHint="Inga cloud-workers"
          />
        </div>
      ) : (
        <p className="mt-3 border-t border-white/[0.06] pt-3 text-center text-[11px] text-white/35">
          Inga workers ännu — starta en uppgift
        </p>
      )}
    </div>
  );
}

function WorkerPulse({ active }) {
  return (
    <span className={`relative flex h-2 w-2 shrink-0 ${active ? "" : "opacity-40"}`}>
      {active && (
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-bifrost opacity-40" />
      )}
      <span
        className={`relative inline-flex h-2 w-2 rounded-full ${
          active ? "bg-bifrost shadow-neon-soft" : "bg-white/25"
        }`}
      />
    </span>
  );
}

function MissionStrip({ task, phase, running }) {
  const [expanded, setExpanded] = useState(false);
  if (!task) return null;

  return (
    <div className="mission-strip mb-2 shrink-0">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        title={task}
        className="flex w-full min-w-0 items-center gap-2 text-left"
      >
        <span className="shrink-0 text-[9px] font-semibold uppercase tracking-[0.15em] text-bifrost/70">
          Mission
        </span>
        <span className="min-w-0 flex-1 truncate text-xs text-white/75">
          {task.replace(/\s+/g, " ")}
        </span>
        {running && phase && (
          <span className="shrink-0 rounded bg-bifrost/10 px-1.5 py-0.5 font-mono text-[9px] text-bifrost/80">
            {phase}
          </span>
        )}
        <ChevronDown
          className={`h-3.5 w-3.5 shrink-0 text-white/35 transition-transform duration-200 ${
            expanded ? "rotate-180" : ""
          }`}
        />
      </button>
      {expanded && (
        <p className="mission-strip-expanded mt-1.5 max-h-20 overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed text-white/65 scrollbar-thin">
          {task}
        </p>
      )}
    </div>
  );
}

function RunButton({ busy, running, hasTask, onClick }) {
  const isRunning = busy || running;
  const isDisabled = isRunning || !hasTask;

  let className = "send-glossy flex shrink-0 items-center gap-2 px-6 py-3.5 text-sm font-semibold transition-all duration-300 ";
  if (isRunning) {
    className += "send-running cursor-wait";
  } else if (!hasTask) {
    className += "send-disabled cursor-not-allowed";
  } else {
    className += "text-midgard";
  }

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={isDisabled}
      aria-busy={isRunning}
      className={className}
    >
      {isRunning ? (
        <>
          <Loader2 className="h-5 w-5 animate-spin" strokeWidth={2.25} />
          Arbetar…
        </>
      ) : (
        <>
          <SendHorizonal className="h-5 w-5" strokeWidth={2.25} />
          Kör
        </>
      )}
    </button>
  );
}

function AutoGrowTextarea({ value, onChange, onSubmit, disabled, placeholder }) {
  const ref = useRef(null);

  const resize = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    const lineHeight = 22;
    const maxHeight = lineHeight * TEXTAREA_MAX_ROWS + 16;
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`;
  }, []);

  useEffect(() => {
    resize();
  }, [value, resize]);

  return (
    <textarea
      ref={ref}
      value={value}
      onChange={(e) => {
        onChange(e.target.value);
        resize();
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          onSubmit();
        }
      }}
      placeholder={placeholder}
      disabled={disabled}
      rows={1}
      className="input-glass min-h-[46px] flex-1 resize-none overflow-y-auto px-4 py-3 text-sm leading-[22px] text-white/85 transition-all duration-300 placeholder:text-white/30 disabled:opacity-50"
    />
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
    currentTask,
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

  const feedRef = useRef(null);
  const feedEndRef = useRef(null);
  const stickToBottomRef = useRef(true);
  const [showNewActivity, setShowNewActivity] = useState(false);

  const events = useMemo(
    () => sortEventsByTs(payload?.events),
    [payload?.events],
  );
  const workers = payload?.workers ?? [];
  const displayTask = currentTask || payload?.task;
  const costStopped = Boolean(payload?.cost?.stopped);
  const costOverCap =
    costStopped ||
    (payload?.cost &&
      (payload.cost.fraction >= 1 || payload.cost.total >= payload.cost.cap));
  const compactionCount = events.filter((e) => e.kind === "compaction").length;

  const scrollToBottom = useCallback((behavior = "smooth") => {
    feedEndRef.current?.scrollIntoView({ behavior });
    stickToBottomRef.current = true;
    setShowNewActivity(false);
  }, []);

  const handleFeedScroll = useCallback(() => {
    const el = feedRef.current;
    if (!el) return;
    const nearBottom =
      el.scrollHeight - el.scrollTop - el.clientHeight < SCROLL_THRESHOLD;
    stickToBottomRef.current = nearBottom;
    if (nearBottom) setShowNewActivity(false);
  }, []);

  useEffect(() => {
    if (stickToBottomRef.current) {
      feedEndRef.current?.scrollIntoView({ behavior: "smooth" });
      setShowNewActivity(false);
    } else {
      setShowNewActivity(true);
    }
  }, [payload?.events, payload?.result, payload?.workers]);

  return (
    <main className="glass-panel flex h-full min-h-0 flex-col overflow-hidden">
      <div className="relative z-10 flex min-h-0 flex-1 flex-col p-4">
        <header className="mb-2 shrink-0">
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

        <MissionStrip
          task={displayTask}
          phase={payload?.phase}
          running={running}
        />

        <section className="mb-2 shrink-0">
          <h2 className="section-label mb-2">Routing logic</h2>
          <RoutingFlow
            routing={payload?.routing}
            workers={workers}
            workerMetrics={payload?.metrics?.workers}
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

          <div className="relative min-h-0 flex-1">
            <div
              ref={feedRef}
              onScroll={handleFeedScroll}
              className="chat-grid-bg mb-3 h-full min-h-[200px] overflow-y-auto p-4 scrollbar-thin"
            >
              {costStopped && (
                <div className="cap-banner mb-3">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" strokeWidth={2.25} />
                  <span>
                    Budget cap reached — agent stopped. Raise the cap and run again to continue.
                  </span>
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
                      ts={ev.ts}
                      realm={ev.realm}
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
              {!displayTask && events.length === 0 && !payload?.result && (
                <p className="text-sm text-white/45">
                  Submit a task to start the orchestrator (backend on :8000).
                </p>
              )}
              <div ref={feedEndRef} />
            </div>

            {showNewActivity && (
              <button
                type="button"
                onClick={() => scrollToBottom("smooth")}
                className="new-activity-pill absolute bottom-6 left-1/2 z-20 flex -translate-x-1/2 items-center gap-1.5"
              >
                <ChevronDown className="h-3.5 w-3.5" />
                New activity
              </button>
            )}
          </div>

          <div className="flex shrink-0 items-end gap-2">
            <div className="flex shrink-0 flex-col gap-1">
              <label
                htmlFor="cost-cap"
                className="text-[10px] font-medium uppercase tracking-wide text-white/40"
              >
                Budget cap
              </label>
              <div className="input-glass flex items-center gap-1 px-3 py-3">
                <span className="font-mono text-sm text-bifrost/70">$</span>
                <input
                  id="cost-cap"
                  type="text"
                  value={cap}
                  onChange={(e) => setCap(e.target.value)}
                  title="Maximum spend in USD for this run"
                  className="w-16 border-0 bg-transparent p-0 text-sm font-mono text-white/70 outline-none"
                />
              </div>
            </div>
            <AutoGrowTextarea
              value={task}
              onChange={setTask}
              onSubmit={handleRun}
              disabled={busy}
              placeholder={
                running
                  ? "Write a follow-up prompt…"
                  : "Enter orchestrator task…"
              }
            />
            <RunButton
              busy={busy}
              running={running}
              hasTask={Boolean(task.trim())}
              onClick={handleRun}
            />
          </div>
        </section>
      </div>
    </main>
  );
}
