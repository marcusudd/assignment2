export function formatUsd(n) {
  if (n == null || Number.isNaN(n)) return "$0.00";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

export function shortModel(model) {
  if (!model) return "?";
  const part = model.split("/").pop() || model;
  return part.length > 22 ? `${part.slice(0, 20)}…` : part;
}

export function phaseLabel(phase) {
  const labels = {
    idle: "IDLE",
    routing: "ROUTING",
    fanout: "FAN-OUT",
    integration: "INTEGRATION",
    done: "DONE",
  };
  return labels[phase] || String(phase || "idle").toUpperCase();
}
