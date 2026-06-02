import { useEffect, useRef, useState } from "react";
import { subscribeEvents } from "../api/bifrost.js";
import mockPayload from "../fixtures/mock-payload.json";

const RECONNECT_MS = 1500;
const MOCK_TICK_MS = 400;
const IS_MOCK = import.meta.env.VITE_MOCK_SSE === "1";

export function useEventStream() {
  const [payload, setPayload] = useState(IS_MOCK ? mockPayload : null);
  const [connected, setConnected] = useState(IS_MOCK);
  const [streamError, setStreamError] = useState(null);
  const timerRef = useRef(null);

  useEffect(() => {
    if (IS_MOCK) {
      const id = window.setInterval(() => {
        setPayload((prev) => {
          const workers = (prev?.workers ?? []).map((w) => ({
            ...w,
            end: w.end != null ? w.end + 0.25 : w.end,
          }));
          return { ...prev, workers };
        });
      }, MOCK_TICK_MS);
      return () => window.clearInterval(id);
    }

    let stopped = false;
    let stop = () => {};

    function connect() {
      stop = subscribeEvents(
        (data) => {
          if (stopped) return;
          setPayload(data);
          setStreamError(null);
          setConnected(true);
        },
        () => {
          if (stopped) return;
          setConnected(false);
          setStreamError("Reconnecting…");
          timerRef.current = window.setTimeout(connect, RECONNECT_MS);
        },
      );
    }

    connect();

    return () => {
      stopped = true;
      if (timerRef.current) window.clearTimeout(timerRef.current);
      stop();
      setConnected(false);
    };
  }, []);

  return { payload, connected, streamError, isMock: IS_MOCK };
}
