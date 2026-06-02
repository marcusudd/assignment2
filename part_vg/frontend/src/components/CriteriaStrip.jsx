import { useEffect, useRef, useState } from "react";

const ORDER = [
  "VG.1",
  "VG.2",
  "VG.3",
  "VG.4",
  "VG.5",
  "VG.6",
  "VG.7",
  "VG.8",
  "VG.9",
];

const STATIC = new Set(["VG.7", "VG.8"]);

const LABELS = {
  "VG.1": "Parallel sub-agents",
  "VG.2": "Context compaction",
  "VG.3": "Cost cap + warnings",
  "VG.4": "Harmful call guard",
  "VG.5": "Bash execution",
  "VG.6": "Section file edit",
  "VG.7": "Docker packaging",
  "VG.8": "Config + env secrets",
  "VG.9": "Tool vs yield",
};

export default function CriteriaStrip({ criteria, cost }) {
  const c = criteria ?? {};
  const prevRef = useRef({});
  const [popped, setPopped] = useState({});

  useEffect(() => {
    const next = {};
    for (const key of ORDER) {
      const on = Boolean(c[key]) || (key === "VG.3" && cost);
      const was = prevRef.current[key];
      if (on && !was && !STATIC.has(key)) {
        next[key] = true;
      }
      prevRef.current[key] = on;
    }
    if (Object.keys(next).length) {
      setPopped((p) => ({ ...p, ...next }));
      const t = window.setTimeout(() => {
        setPopped((p) => {
          const copy = { ...p };
          for (const k of Object.keys(next)) delete copy[k];
          return copy;
        });
      }, 600);
      return () => window.clearTimeout(t);
    }
    return undefined;
  }, [JSON.stringify(c), cost?.warning, cost?.stopped]);

  return (
    <footer className="mt-4 rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-3">
      <p className="mb-2 text-xs text-slate-500">
        Criteria — light up as they happen during the run
      </p>
      <div className="flex flex-wrap gap-2">
        {ORDER.map((key) => {
          const on = Boolean(c[key]);
          const live = on && !STATIC.has(key);
          const vg3Warn = key === "VG.3" && cost?.warning && !cost?.stopped;
          const showOn = on || (key === "VG.3" && cost);
          const pop = popped[key];

          return (
            <span
              key={key}
              title={LABELS[key]}
              className={`rounded-full px-2.5 py-1 text-xs font-semibold transition-all duration-300 ${
                pop ? "animate-criteria-pop" : ""
              } ${
                showOn
                  ? live || key === "VG.3"
                    ? "bg-emerald-900/80 text-emerald-200 ring-1 ring-emerald-600/50"
                    : "bg-slate-700/90 text-slate-300 ring-1 ring-slate-600/40"
                  : "bg-slate-800/60 text-slate-600"
              }`}
            >
              {key}
              {showOn ? " ✓" : ""}
              {vg3Warn ? " ●" : ""}
            </span>
          );
        })}
      </div>
    </footer>
  );
}
