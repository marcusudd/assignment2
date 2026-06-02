import { eventStyle } from "../utils/actionStyle.js";

const KIND_TAG = {
  blocked: "VG.4",
  compaction: "VG.2",
  escalation: "⚡",
  done: "✓",
};

export default function ActivityFeed({ events, workers }) {
  const items = (events ?? []).slice(-24).reverse();
  const workerMap = Object.fromEntries((workers ?? []).map((w) => [w.id, w]));

  return (
    <section className="rounded-xl border border-slate-700/80 bg-slate-900/40 p-4">
      <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
        Activity feed
      </h2>
      <ul className="scrollbar-thin max-h-52 space-y-1.5 overflow-y-auto text-xs">
        {!items.length ? (
          <li className="text-slate-500">Waiting for tool events…</li>
        ) : (
          items.map((ev, i) => {
            const w = workerMap[ev.worker];
            const icon = w?.is_local ? "🏠" : "☁️";
            const tag = KIND_TAG[ev.kind];
            return (
              <li
                key={`${ev.worker}-${i}-${ev.text.slice(0, 24)}`}
                className={`animate-feed-in rounded border px-2 py-1.5 ${eventStyle(ev.kind)}`}
                style={{ animationDelay: `${Math.min(i, 8) * 40}ms` }}
              >
                {tag && (
                  <span className="mr-1 font-bold opacity-90">{tag}</span>
                )}
                <span className="opacity-70">{icon}</span>{" "}
                <span className="font-medium text-slate-500">{ev.worker}</span>
                <span className="text-slate-600"> · </span>
                <span className="break-all">{ev.text}</span>
              </li>
            );
          })
        )}
      </ul>
    </section>
  );
}
