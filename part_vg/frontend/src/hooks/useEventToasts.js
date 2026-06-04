import { useCallback, useEffect, useRef, useState } from "react";
import { logEntryVariant } from "../components/LogEntry.jsx";

const TOAST_TTL_MS = 4000;
const MAX_TOASTS = 2;

export function useEventToasts(events, costStopped, phase, runId) {
  const [toasts, setToasts] = useState([]);
  const seenRef = useRef({
    runId: null,
    eventCount: 0,
    compactionCount: 0,
    costStopped: false,
    phase: null,
  });

  const pushToast = useCallback((variant, message) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    setToasts((prev) => [...prev.slice(-(MAX_TOASTS - 1)), { id, variant, message }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, TOAST_TTL_MS);
  }, []);

  useEffect(() => {
    if (runId !== seenRef.current.runId) {
      seenRef.current = {
        runId,
        eventCount: 0,
        compactionCount: 0,
        costStopped: false,
        phase: null,
      };
      setToasts([]);
    }
  }, [runId]);

  useEffect(() => {
    const list = events ?? [];
    const prevCount = seenRef.current.eventCount;
    if (list.length > prevCount) {
      for (let i = prevCount; i < list.length; i++) {
        const ev = list[i];
        if (logEntryVariant(ev.kind, ev.text) === "blocked") {
          const text = (ev.text || "Command blocked").replace(/\s+/g, " ").trim();
          pushToast("blocked", text.length > 72 ? `${text.slice(0, 69)}…` : text);
        }
      }
      const compactionTotal = list.filter((e) => e.kind === "compaction").length;
      if (compactionTotal > seenRef.current.compactionCount) {
        pushToast("compaction", "Context compacted");
      }
      seenRef.current.compactionCount = compactionTotal;
      seenRef.current.eventCount = list.length;
    }

    if (costStopped && !seenRef.current.costStopped) {
      pushToast("blocked", "Budget cap reached");
      seenRef.current.costStopped = true;
    }

    if (phase === "done" && seenRef.current.phase !== "done") {
      pushToast("done", "Run complete");
    }
    seenRef.current.phase = phase;
  }, [events, costStopped, phase, pushToast]);

  return toasts;
}
