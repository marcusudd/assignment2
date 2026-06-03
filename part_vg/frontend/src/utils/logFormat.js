export function formatLogTs(ts) {
  if (ts == null || Number.isNaN(ts)) return "";
  return `+${Number(ts).toFixed(1)}s`;
}

export function realmLabel(realm) {
  if (realm === "midgard") return "Midgard";
  if (realm === "asgard") return "Asgard";
  if (realm === "bifrost") return "Router";
  return null;
}

export function sortEventsByTs(events) {
  return [...(events ?? [])].sort((a, b) => (a.ts ?? 0) - (b.ts ?? 0));
}
