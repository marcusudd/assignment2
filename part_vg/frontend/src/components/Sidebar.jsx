import { Cloud, Key, Server } from "lucide-react";
import { useBifrost } from "../BifrostContext.jsx";
import BifrostBridge from "./BifrostBridge.jsx";

function PulseIndicator({ active, color = "green", small = false }) {
  const size = small ? "h-2 w-2" : "h-3 w-3";
  return (
    <span className={`relative flex shrink-0 ${size}`}>
      {active && !small && (
        <span
          className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-40 ${
            color === "green" ? "bg-bifrost" : "bg-red-500"
          }`}
        />
      )}
      <span
        className={`relative inline-flex rounded-full ${size} ${
          active
            ? color === "green"
              ? "bg-bifrost shadow-neon-soft"
              : "bg-red-500 shadow-[0_0_12px_rgba(239,68,68,0.5)]"
            : "bg-red-500/80"
        }`}
      />
    </span>
  );
}

function LocalConnectionsCard({ locals, connected }) {
  const anyLoaded = locals.some((l) => l.loaded);
  return (
    <div className="glass-card px-4 py-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-sm font-medium text-slate-200">Local backends</p>
        <PulseIndicator active={connected && anyLoaded} />
      </div>
      <p className="mb-2 text-[10px] text-slate-500">LM Studio / Ollama</p>
      {locals.length === 0 ? (
        <p className="text-xs text-red-400/90">No local slots configured</p>
      ) : (
        <ul className="space-y-2">
          {locals.map((l) => (
            <li
              key={`${l.name}-${l.model}`}
              className="flex items-start justify-between gap-2 rounded-lg border border-white/[0.04] bg-black/20 px-2 py-1.5"
            >
              <div className="min-w-0 flex-1">
                <p className="text-[10px] font-medium text-slate-400">{l.name}</p>
                <p className="truncate font-mono text-[11px] text-slate-300">
                  {l.model}
                </p>
              </div>
              <span
                className={`shrink-0 text-[9px] font-medium uppercase tracking-wide ${
                  l.loaded ? "text-bifrost" : "text-red-400/80"
                }`}
              >
                {l.loaded ? "loaded" : "not loaded"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CloudConnectionCard({ cloud, active }) {
  return (
    <div className="glass-card flex items-center justify-between px-4 py-3">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-slate-200">Cloud API</p>
        <p
          className={`truncate font-mono text-xs ${
            active ? "text-bifrost/80" : "text-red-400/90"
          }`}
        >
          {cloud?.model ?? "offline"}
        </p>
        <p className="text-[10px] text-slate-500">{cloud?.name ?? "OpenRouter"}</p>
      </div>
      <PulseIndicator active={active} />
    </div>
  );
}

function ApiKeyRow({ provider, masked, active }) {
  return (
    <div className="glass-card flex items-center gap-3 px-4 py-3">
      <div
        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${
          active ? "bg-bifrost/10 shadow-neon-soft" : "bg-white/[0.03]"
        }`}
      >
        <Key
          className={`h-4 w-4 ${active ? "text-bifrost" : "text-slate-500"}`}
        />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-slate-300">{provider}</p>
        <p className="truncate font-mono text-xs tracking-wide text-slate-500">
          {masked}
        </p>
      </div>
      <PulseIndicator active={active} />
    </div>
  );
}

function PillToggle({ enabled, onChange, label }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm text-slate-300">{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        onClick={() => onChange(!enabled)}
        className="pill-switch-track"
        data-on={enabled}
      >
        <span className="pill-switch-thumb" />
      </button>
    </div>
  );
}

function ModelCard({ model, selected, onSelect }) {
  return (
    <button
      type="button"
      onClick={() => onSelect(model.id)}
      className={`w-full rounded-xl px-3 py-2.5 text-left transition-all duration-300 ${
        selected
          ? "model-card-active border border-bifrost/30 bg-gradient-to-br from-bifrost/10 to-asgard/80"
          : "glass-card border-transparent"
      }`}
    >
      <p
        className={`text-sm font-medium ${
          selected ? "text-bifrost" : "text-slate-400"
        }`}
      >
        {model.label}
      </p>
      <p className="text-xs text-slate-500">{model.group}</p>
    </button>
  );
}

export default function Sidebar() {
  const {
    connected,
    streamError,
    isMock,
    configError,
    selectedModel,
    setSelectedModel,
    localEnabled,
    setLocalEnabled,
    cloudEnabled,
    setCloudEnabled,
    localModels,
    cloudModels,
    hasCloud,
    cloudKeyConfigured,
    config,
  } = useBifrost();

  const configLocals = config?.locals ?? [];
  const cloudActive = hasCloud && connected && cloudKeyConfigured;

  const realmHint = [
    localEnabled ? "Midgard on" : "Midgard off",
    cloudEnabled ? "Asgard on" : "Asgard off",
  ].join(" · ");

  return (
    <aside className="glass-panel panel-schematic flex h-full min-h-0 flex-col overflow-hidden">
      <div className="relative z-10 flex min-h-0 flex-1 flex-col overflow-y-auto p-4 scrollbar-thin">
        <header className="mb-3">
          <div className="flex items-center gap-2">
            <PulseIndicator active={connected} small />
            <Server className="h-4 w-4 text-bifrost/90" />
            <h1 className="flex-1 text-base font-semibold tracking-tight text-slate-100">
              Realm Operations
            </h1>
            {isMock && (
              <span className="text-[10px] text-slate-500">mock</span>
            )}
          </div>
          {streamError && !connected && (
            <p className="mt-1 text-[10px] text-red-400/90">{streamError}</p>
          )}
          {configError && (
            <p className="mt-1 text-xs text-red-400">{configError}</p>
          )}
        </header>

        <div className="mb-4">
          <BifrostBridge />
        </div>

        <section className="mb-5">
          <h2 className="mb-3 text-xs font-medium uppercase tracking-widest text-slate-500">
            Connections
          </h2>
          <div className="space-y-2">
            <LocalConnectionsCard locals={configLocals} connected={connected} />
            <CloudConnectionCard cloud={config?.cloud} active={cloudActive} />
          </div>
        </section>

        <section className="mb-5">
          <h2 className="mb-3 text-xs font-medium uppercase tracking-widest text-slate-500">
            API Keys
          </h2>
          <div className="space-y-2">
            <ApiKeyRow
              provider="OpenRouter (cloud)"
              masked={cloudKeyConfigured ? "configured via .env" : "Not configured"}
              active={cloudKeyConfigured}
            />
          </div>
        </section>

        <section className="mb-5">
          <h2 className="mb-3 text-xs font-medium uppercase tracking-widest text-slate-500">
            Realm Toggles
          </h2>
          <div className="glass-card space-y-4 p-4">
            <PillToggle
              enabled={localEnabled}
              onChange={setLocalEnabled}
              label="Midgard (Local)"
            />
            <PillToggle
              enabled={cloudEnabled}
              onChange={setCloudEnabled}
              label="Asgard (Cloud)"
            />
            <p className="text-[10px] leading-relaxed text-slate-500">
              Next run: {realmHint}. Workers follow toggles; router may still use
              cloud for planning.
            </p>
          </div>
        </section>

        <section className="flex-1 pb-2">
          <h2 className="mb-3 flex items-center gap-1.5 text-xs font-medium uppercase tracking-widest text-slate-500">
            <Cloud className="h-3.5 w-3.5" />
            Active Models
          </h2>
          {localModels.length > 0 && (
            <>
              <p className="mb-2 text-xs text-slate-500">Local</p>
              <div className="mb-3 space-y-2">
                {localModels.map((model) => (
                  <ModelCard
                    key={model.id}
                    model={model}
                    selected={selectedModel === model.id}
                    onSelect={setSelectedModel}
                  />
                ))}
              </div>
            </>
          )}
          {cloudModels.length > 0 && (
            <>
              <p className="mb-2 text-xs text-slate-500">Cloud</p>
              <div className="space-y-2">
                {cloudModels.map((model) => (
                  <ModelCard
                    key={model.id}
                    model={model}
                    selected={selectedModel === model.id}
                    onSelect={setSelectedModel}
                  />
                ))}
              </div>
            </>
          )}
          {localModels.length === 0 && cloudModels.length === 0 && (
            <p className="text-xs text-slate-600">Load config from backend…</p>
          )}
        </section>
      </div>
    </aside>
  );
}
