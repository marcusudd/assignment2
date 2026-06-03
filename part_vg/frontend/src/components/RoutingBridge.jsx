export default function RoutingBridge({ active = true, compact = false }) {
  const h = compact ? 72 : 88;
  const vw = compact ? 200 : 240;

  return (
    <div
      className={`relative flex flex-1 items-center justify-center ${
        compact ? "min-h-[72px]" : "min-h-[88px]"
      }`}
    >
      <svg
        viewBox={`0 0 ${vw} ${h}`}
        className={`w-full max-w-[200px] ${active ? "animate-bridge-glow" : "opacity-40"}`}
        aria-hidden
      >
        <defs>
          <linearGradient id="routingArchGrad" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#1b4322" stopOpacity={active ? 0.3 : 0.15} />
            <stop offset="35%" stopColor="#5dff4a" stopOpacity={active ? 1 : 0.35} />
            <stop offset="65%" stopColor="#39ff14" stopOpacity={active ? 1 : 0.35} />
            <stop offset="100%" stopColor="#1b4322" stopOpacity={active ? 0.3 : 0.15} />
          </linearGradient>
          <linearGradient id="routingDeckGrad" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="#7dff5a" stopOpacity={active ? 1 : 0.4} />
            <stop offset="50%" stopColor="#39ff14" stopOpacity={active ? 0.9 : 0.35} />
            <stop offset="100%" stopColor="#1b4322" />
          </linearGradient>
          <filter id="routingArchGlow" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <ellipse
          cx={vw / 2}
          cy={h - 8}
          rx={vw / 2 - 12}
          ry="8"
          fill={active ? "rgba(57,255,20,0.12)" : "rgba(27,67,34,0.2)"}
        />

        <path
          d={`M 16 ${h - 18} Q ${vw / 2} 14 ${vw - 16} ${h - 18}`}
          fill="none"
          stroke="url(#routingArchGrad)"
          strokeWidth="4"
          filter={active ? "url(#routingArchGlow)" : undefined}
        />
        <path
          d={`M 28 ${h - 24} Q ${vw / 2} 28 ${vw - 28} ${h - 24}`}
          fill="none"
          stroke={active ? "rgba(93,255,74,0.4)" : "rgba(27,67,34,0.4)"}
          strokeWidth="1.5"
        />

        <path
          d={`M 24 ${h - 32} L ${vw - 24} ${h - 32} L ${vw - 30} ${h - 14} L 30 ${h - 14} Z`}
          fill="url(#routingDeckGrad)"
          opacity={active ? 0.85 : 0.45}
          filter={active ? "url(#routingArchGlow)" : undefined}
        />
        <path
          d={`M 36 ${h - 32} L ${vw - 36} ${h - 32}`}
          stroke="rgba(255,255,255,0.25)"
          strokeWidth="1"
        />

        {active && (
          <circle cx={vw / 2} cy={h / 2 - 8} r="4" fill="#7dff5a" filter="url(#routingArchGlow)">
            <animate attributeName="opacity" values="0.6;1;0.6" dur="2.5s" repeatCount="indefinite" />
          </circle>
        )}
      </svg>
    </div>
  );
}
