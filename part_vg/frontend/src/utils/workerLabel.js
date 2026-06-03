const LANE_ID_RE = /^(midgard|asgard)\.(.+)$/;

/** Display label for a worker row from SSE (fallback if backend omits label). */
export function workerDisplayLabel(w) {
  if (w.label) return w.label;
  const m = w.id?.match(LANE_ID_RE);
  if (m) {
    const realm = m[1] === "midgard" ? "Midgard" : "Asgard";
    const slug = m[2];
    if (slug === "primary") return `${realm} · primary`;
    if (slug === "integration") return "Integration";
    return `${realm} · ${slug}`;
  }
  if (w.id === "integration") return "Integration";
  if (w.owned_files?.length) {
    const parts = w.owned_files[0].split("/").filter(Boolean);
    const short =
      parts.length >= 2 ? `${parts[parts.length - 2]}/${parts[parts.length - 1]}` : parts[0];
    const realm = w.is_local ? "Midgard" : "Asgard";
    return `${realm} · ${short}`;
  }
  const task = (w.task_summary || "").trim();
  if (task) {
    const short = task.length > 28 ? `${task.slice(0, 25)}…` : task;
    return `${w.role || "worker"} · ${short}`;
  }
  return w.id;
}

export function workerShortId(w) {
  const label = workerDisplayLabel(w);
  if (label.length <= 14) return label;
  return `${label.slice(0, 12)}…`;
}
