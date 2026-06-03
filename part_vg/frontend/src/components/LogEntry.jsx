import { AlertTriangle, GitBranch, Shrink, XCircle } from "lucide-react";
import { formatLogTs, realmLabel } from "../utils/logFormat.js";

export function logEntryVariant(kind, text = "") {
  if (kind === "blocked" || /BLOCKED/i.test(text)) return "blocked";
  if (
    kind === "error" ||
    /\bERROR\b/.test(text) ||
    /Circuit breaker|output truncated|malformed JSON/i.test(text)
  ) {
    return "error";
  }
  if (kind === "compaction") return "compaction";
  if (kind === "escalation" || /⚡/.test(text)) return "routing";
  if (kind === "routing" || kind === "lane") return "routing";
  return "action";
}

function entryClass(variant) {
  if (variant === "blocked") return "log-entry log-entry-blocked";
  if (variant === "error") return "log-entry log-entry-error";
  if (variant === "compaction") return "log-entry log-entry-compaction";
  if (variant === "routing") return "log-entry log-entry-routing";
  return "log-entry log-entry-action";
}

export default function LogEntry({ worker, text, kind, ts, realm, showWorker = true }) {
  const variant = logEntryVariant(kind, text);
  const Icon =
    variant === "blocked"
      ? AlertTriangle
      : variant === "error"
        ? XCircle
        : variant === "compaction"
          ? Shrink
          : variant === "routing"
            ? GitBranch
            : null;
  const iconColor =
    variant === "blocked"
      ? "text-red-400"
      : variant === "compaction"
        ? "text-bifrost"
        : variant === "routing"
          ? "text-sky-300"
          : "text-orange-400";
  const realmTag = realmLabel(realm);
  const timeLabel = formatLogTs(ts);

  return (
    <li className={entryClass(variant)}>
      {Icon && (
        <Icon
          className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${iconColor}`}
          strokeWidth={2.25}
        />
      )}
      <span className="min-w-0 flex-1">
        <span className="mb-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
          {timeLabel && (
            <span className="font-mono text-[10px] tabular-nums text-bifrost/55">
              {timeLabel}
            </span>
          )}
          {realmTag && (
            <span
              className={`rounded px-1 py-px text-[9px] font-semibold uppercase tracking-wide ${
                realm === "midgard"
                  ? "bg-bifrost/15 text-bifrost"
                  : realm === "asgard"
                    ? "bg-sky-500/15 text-sky-300"
                    : "bg-white/10 text-white/50"
              }`}
            >
              {realmTag}
            </span>
          )}
          {showWorker && worker && (
            <span className="text-[10px] font-semibold uppercase tracking-wide text-white/40">
              [{worker}]
            </span>
          )}
        </span>
        <span className="block">{text}</span>
      </span>
    </li>
  );
}
