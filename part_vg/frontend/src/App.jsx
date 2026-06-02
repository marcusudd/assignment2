import { useCallback, useEffect, useState } from "react";
import {
  fetchConfig,
  resetWorkspace,
  runTask,
} from "./api/bifrost.js";
import ActivityFeed from "./components/ActivityFeed.jsx";
import AgentGrid from "./components/AgentGrid.jsx";
import CostPanel from "./components/CostPanel.jsx";
import CriteriaStrip from "./components/CriteriaStrip.jsx";
import Header from "./components/Header.jsx";
import RouterBanner from "./components/RouterBanner.jsx";
import Timeline from "./components/Timeline.jsx";
import { useEventStream } from "./hooks/useEventStream.js";

export default function App() {
  const { payload, connected, streamError, isMock } = useEventStream();
  const [task, setTask] = useState("");
  const [cap, setCap] = useState("");
  const [defaultCap, setDefaultCap] = useState("0.20");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (isMock) return;
    fetchConfig()
      .then((cfg) => {
        setDefaultCap(String(cfg.cost_cap_usd ?? "0.20"));
        setCap((prev) => prev || String(cfg.cost_cap_usd ?? "0.20"));
      })
      .catch((e) => setStatus(e.message));
  }, [isMock]);

  const handleRun = useCallback(async () => {
    if (!task.trim()) {
      setStatus("Enter a task first");
      return;
    }
    setBusy(true);
    setStatus("");
    try {
      const { run_id } = await runTask(task.trim(), cap || defaultCap);
      setStatus(`Started run ${run_id}`);
    } catch (e) {
      setStatus(e.message);
    } finally {
      setBusy(false);
    }
  }, [task, cap, defaultCap]);

  const handleReset = useCallback(async () => {
    setBusy(true);
    setStatus("");
    try {
      await resetWorkspace();
      setStatus("Workspace reset to seed app");
    } catch (e) {
      setStatus(e.message);
    } finally {
      setBusy(false);
    }
  }, []);

  const workers = payload?.workers ?? [];
  const running = Boolean(payload?.running);

  return (
    <div className="min-h-screen p-3 font-mono text-sm text-slate-100 sm:p-6">
      <div className="mx-auto max-w-6xl">
        <Header
          task={task}
          onTaskChange={setTask}
          cap={cap}
          onCapChange={setCap}
          onRun={handleRun}
          onReset={handleReset}
          busy={busy}
          connected={connected}
          cost={payload?.cost}
          status={status}
          streamError={streamError}
          isMock={isMock}
          running={running}
        />

        <RouterBanner routing={payload?.routing} workers={workers} />

        <Timeline
          workers={workers}
          phase={payload?.phase}
          running={running}
          parallelOverlap={payload?.parallel_overlap}
        />

        <div className="mb-4 grid gap-4 lg:grid-cols-2">
          <AgentGrid workers={workers} />
          <CostPanel cost={payload?.cost} savings={payload?.savings} />
        </div>

        <ActivityFeed events={payload?.events} workers={workers} />

        {payload?.error && (
          <div className="mt-4 rounded-lg border border-red-800/60 bg-red-950/40 p-4 text-red-200">
            <p className="text-xs font-semibold uppercase">Error</p>
            <p className="mt-1 text-xs">{payload.error}</p>
          </div>
        )}

        {payload?.result && (
          <div className="mt-4 rounded-lg border border-emerald-800/50 bg-emerald-950/30 p-4">
            <p className="mb-1 text-xs font-semibold uppercase text-emerald-500">
              Result
            </p>
            <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap text-xs text-emerald-100 scrollbar-thin">
              {payload.result}
            </pre>
          </div>
        )}

        <CriteriaStrip criteria={payload?.criteria} cost={payload?.cost} />
      </div>
    </div>
  );
}
