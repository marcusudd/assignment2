import { AlertTriangle, Shrink, XCircle } from "lucide-react";

export function logEntryVariant(kind, text = "") {
  if (kind === "blocked" || /BLOCKED/i.test(text)) return "blocked";
  if (kind === "error" || /\bERROR\b/.test(text)) return "error";
  if (kind === "compaction") return "compaction";
  return "action";
}

function entryClass(variant) {
  if (variant === "blocked") return "log-entry log-entry-blocked";
  if (variant === "error") return "log-entry log-entry-error";
  if (variant === "compaction") return "log-entry log-entry-compaction";
  return "log-entry log-entry-action";
}

export default function LogEntry({ worker, text, kind }) {
  const variant = logEntryVariant(kind, text);
  const Icon =
    variant === "blocked"
      ? AlertTriangle
      : variant === "error"
        ? XCircle
        : variant === "compaction"
          ? Shrink
          : null;
  const iconColor =
    variant === "blocked"
      ? "text-red-400"
      : variant === "compaction"
        ? "text-bifrost"
        : "text-orange-400";

  return (
    <li className={entryClass(variant)}>
      {Icon && (
        <Icon
          className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${iconColor}`}
          strokeWidth={2.25}
        />
      )}
      <span className="min-w-0 flex-1">
        {worker && (
          <span className="mr-1.5 text-[10px] font-semibold uppercase tracking-wide text-white/40">
            [{worker}]
          </span>
        )}
        {text}
      </span>
    </li>
  );
}
