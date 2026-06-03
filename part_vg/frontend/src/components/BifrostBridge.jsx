export default function BifrostBridge() {
  return (
    <div
      className="relative flex h-20 w-full items-end justify-center overflow-hidden rounded-xl border border-white/[0.05]"
      style={{
        background:
          "radial-gradient(ellipse 90% 70% at 50% 100%, rgba(57,255,20,0.2) 0%, transparent 65%)",
        boxShadow: "inset 0 -20px 40px rgba(57,255,20,0.06)",
      }}
    >
      <svg
        viewBox="0 0 280 120"
        className="h-full w-full max-w-[180px] animate-bridge-glow opacity-90"
        aria-hidden
      >
        <defs>
          <linearGradient id="archGrad" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#1b4322" stopOpacity="0.2" />
            <stop offset="35%" stopColor="#5dff4a" stopOpacity="1" />
            <stop offset="65%" stopColor="#39ff14" stopOpacity="1" />
            <stop offset="100%" stopColor="#1b4322" stopOpacity="0.2" />
          </linearGradient>
          <linearGradient id="deckGrad" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="#7dff5a" />
            <stop offset="50%" stopColor="#39ff14" />
            <stop offset="100%" stopColor="#1b4322" />
          </linearGradient>
          <filter id="archGlow" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <filter id="softGlow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="6" result="glow" />
            <feMerge>
              <feMergeNode in="glow" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <radialGradient id="pillarLight" cx="50%" cy="0%" r="80%">
            <stop offset="0%" stopColor="#7dff5a" stopOpacity="1" />
            <stop offset="100%" stopColor="#39ff14" stopOpacity="0" />
          </radialGradient>
        </defs>

        <ellipse
          cx="140"
          cy="108"
          rx="130"
          ry="12"
          fill="rgba(57,255,20,0.15)"
          filter="url(#softGlow)"
        />

        <path
          d="M 30 95 Q 140 12 250 95"
          fill="none"
          stroke="url(#archGrad)"
          strokeWidth="5"
          filter="url(#archGlow)"
        />
        <path
          d="M 50 88 Q 140 32 230 88"
          fill="none"
          stroke="rgba(93,255,74,0.45)"
          strokeWidth="2.5"
          filter="url(#softGlow)"
        />

        {[70, 110, 140, 170, 210].map((x, i) => (
          <line
            key={x}
            x1={x}
            y1={95 - Math.abs(140 - x) * 0.38}
            x2={x}
            y2={95}
            stroke="url(#pillarLight)"
            strokeWidth="2.5"
            opacity={0.45 + i * 0.12}
          />
        ))}

        <path
          d="M 45 78 L 235 78 L 228 94 L 52 94 Z"
          fill="url(#deckGrad)"
          opacity="0.9"
          filter="url(#archGlow)"
        />
        <path
          d="M 58 78 L 222 78"
          stroke="rgba(255,255,255,0.35)"
          strokeWidth="1.5"
        />

        <circle cx="140" cy="38" r="7" fill="#7dff5a" filter="url(#archGlow)">
          <animate
            attributeName="opacity"
            values="0.5;1;0.5"
            dur="2.5s"
            repeatCount="indefinite"
          />
        </circle>
        <circle cx="140" cy="38" r="14" fill="none" stroke="#39ff14" strokeWidth="1" opacity="0.25">
          <animate
            attributeName="r"
            values="10;18;10"
            dur="2.5s"
            repeatCount="indefinite"
          />
          <animate
            attributeName="opacity"
            values="0.15;0.35;0.15"
            dur="2.5s"
            repeatCount="indefinite"
          />
        </circle>
      </svg>
      <div className="pointer-events-none absolute inset-0 rounded-2xl bg-gradient-to-t from-midgard/90 via-midgard/20 to-transparent" />
    </div>
  );
}
