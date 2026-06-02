import { useCallback, useEffect, useRef, useState } from "react";

/** Fallback client clock when SSE mock mode has no server `end` updates. */
export function useTimelineClock(active, useClientClock) {
  const [now, setNow] = useState(() => performance.now());
  const epochRef = useRef(null);

  useEffect(() => {
    if (!active || !useClientClock) {
      epochRef.current = null;
      return undefined;
    }
    if (epochRef.current == null) {
      epochRef.current = performance.now();
    }
    const id = window.setInterval(() => setNow(performance.now()), 200);
    return () => window.clearInterval(id);
  }, [active, useClientClock]);

  const elapsedSec =
    active && useClientClock && epochRef.current != null
      ? (now - epochRef.current) / 1000
      : 0;

  const resetEpoch = useCallback(() => {
    epochRef.current = performance.now();
  }, []);

  return { elapsedSec, resetEpoch };
}

export function effectiveEnd(worker, elapsedSec, minStart, useClientClock) {
  if (worker.end != null) return worker.end;
  if (!useClientClock) return worker.start ?? 0;
  if (worker.start == null) return 0;
  if (worker.status === "running" || worker.status === "pending") {
    const live = minStart + elapsedSec;
    return Math.max(worker.start + 0.3, live);
  }
  return worker.start;
}
