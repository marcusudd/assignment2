export function actionStyle(action) {
  const a = action || "";
  if (a.includes("BLOCKED") || /error/i.test(a)) {
    return { text: "text-red-300", bar: "bg-red-500" };
  }
  if (/creating|editing/i.test(a)) {
    return { text: "text-emerald-300", bar: "bg-emerald-500" };
  }
  if (/reading/i.test(a)) {
    return { text: "text-cyan-400/80", bar: "bg-cyan-600" };
  }
  if (/thinking/i.test(a)) {
    return { text: "text-amber-300", bar: "bg-amber-400" };
  }
  if (/\$ /.test(a)) {
    return { text: "text-fuchsia-300", bar: "bg-fuchsia-500" };
  }
  return { text: "text-slate-300", bar: "bg-slate-500" };
}

export function eventStyle(kind) {
  switch (kind) {
    case "blocked":
      return "border-red-800/60 bg-red-950/40 text-red-200";
    case "compaction":
      return "border-violet-800/60 bg-violet-950/40 text-violet-200";
    case "escalation":
      return "border-amber-800/60 bg-amber-950/40 text-amber-200";
    case "done":
      return "border-emerald-800/60 bg-emerald-950/40 text-emerald-200";
    default:
      return "border-slate-700/60 bg-slate-900/60 text-slate-300";
  }
}
