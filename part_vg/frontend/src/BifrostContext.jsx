import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  compactSession,
  fetchConfig,
  resetWorkspace,
  runTask,
} from "./api/bifrost.js";
import { useEventStream } from "./hooks/useEventStream.js";

const BifrostContext = createContext(null);

// Haiku = the cloud model Bifrost actually uses → "vs all-Haiku, no Bifrost" is the
// honest local-offload metric. Opus is available for the premium comparison.
export const DEFAULT_COMPARISON_MODEL = "anthropic/claude-haiku-4-5";

const FALLBACK_COMPARISON_MODELS = [
  "anthropic/claude-opus-4-8",
  "anthropic/claude-sonnet-4-6",
  "anthropic/claude-haiku-4-5",
  "openai/gpt-5.5",
  "openai/gpt-5",
  "openai/gpt-5-mini",
  "google/gemini-2.5-pro",
  "google/gemini-2.5-flash",
  "google/gemini-2.5-flash-lite",
];

export function isLocalModel(modelId, config) {
  if (!modelId) return false;
  if (config?.locals?.some((l) => l.model === modelId)) return true;
  return false;
}

export function isCompactCommand(text) {
  return /^\/compact\b/i.test((text || "").trim());
}

export function BifrostProvider({ children }) {
  const { payload, connected, streamError, isMock } = useEventStream();
  const [config, setConfig] = useState(null);
  const [configError, setConfigError] = useState(null);
  const [selectedModel, setSelectedModel] = useState("");
  const [localEnabled, setLocalEnabled] = useState(true);
  const [cloudEnabled, setCloudEnabled] = useState(true);
  const [task, setTask] = useState("");
  const [currentTask, setCurrentTask] = useState("");
  const [cap, setCap] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [comparisonModel, setComparisonModel] = useState(DEFAULT_COMPARISON_MODEL);

  useEffect(() => {
    if (isMock) return;
    fetchConfig()
      .then((cfg) => {
        setConfig(cfg);
        setConfigError(null);
        setCap((prev) => prev || String(cfg.cost_cap_usd ?? "0.20"));
        const firstLocal = cfg.locals?.[0]?.model;
        const cloudModel = cfg.cloud?.model;
        setSelectedModel((prev) => prev || firstLocal || cloudModel || "");
      })
      .catch((e) => setConfigError(e.message));
  }, [isMock]);

  useEffect(() => {
    if (!payload?.workers?.length) return;
    const running = payload.workers.find((w) => w.status === "running");
    if (running?.model) setSelectedModel(running.model);
  }, [payload?.workers]);

  useEffect(() => {
    if (payload?.task) setCurrentTask(payload.task);
  }, [payload?.task]);

  const localModels = useMemo(() => {
    if (config?.locals?.length) {
      return config.locals.map((l) => ({ id: l.model, label: l.model, group: l.name }));
    }
    return (payload?.workers ?? [])
      .filter((w) => w.is_local)
      .map((w) => ({ id: w.model, label: w.model, group: w.backend }));
  }, [config, payload?.workers]);

  const cloudModels = useMemo(() => {
    if (config?.cloud) {
      return [{ id: config.cloud.model, label: config.cloud.model, group: config.cloud.name }];
    }
    const seen = new Set();
    return (payload?.workers ?? [])
      .filter((w) => {
        if (w.is_local || seen.has(w.model)) return false;
        seen.add(w.model);
        return true;
      })
      .map((w) => ({ id: w.model, label: w.model, group: w.backend }));
  }, [config, payload?.workers]);

  const comparisonModels = useMemo(() => {
    if (config?.comparison_models?.length) return config.comparison_models;
    const fromSavings = [...new Set((payload?.savings ?? []).map((s) => s.model))];
    if (fromSavings.length) return fromSavings;
    return FALLBACK_COMPARISON_MODELS;
  }, [config?.comparison_models, payload?.savings]);

  const hasLocalsLoaded =
    config?.locals?.some((l) => l.loaded) ||
    (payload?.workers ?? []).some((w) => w.is_local);
  const hasLocals = (config?.locals?.length ?? 0) > 0 || localModels.length > 0;
  const hasCloud = Boolean(config?.cloud) || (payload?.workers ?? []).some((w) => !w.is_local);
  const cloudKeyConfigured = isMock || Boolean(config?.cloud);

  const running = Boolean(payload?.running);

  const requestCompact = useCallback(async () => {
    if (isMock) {
      setStatus("Mock mode — compact unavailable");
      return;
    }
    if (!running) {
      setStatus("Compact only works during an active run");
      return;
    }
    try {
      await compactSession();
      setStatus("Compaction requested — fires when a session has enough history");
    } catch (e) {
      setStatus(e.message);
    }
  }, [isMock, running]);

  const handleRun = useCallback(async () => {
    const text = task.trim();
    if (!text) {
      setStatus("Enter a task first");
      return;
    }
    if (isCompactCommand(text)) {
      setTask("");
      setBusy(true);
      try {
        await requestCompact();
      } finally {
        setBusy(false);
      }
      return;
    }
    if (!localEnabled && !cloudEnabled) {
      setStatus("Enable at least one realm (Midgard or Asgard)");
      return;
    }
    if (isMock) {
      setStatus("Mock mode — start backend on :8000 for live runs");
      return;
    }
    setBusy(true);
    setStatus("");
    try {
      const { run_id } = await runTask(text, cap, {
        allowLocal: localEnabled,
        allowCloud: cloudEnabled,
      });
      setCurrentTask(text);
      setTask("");
      setStatus(`Started run ${run_id}`);
    } catch (e) {
      setStatus(e.message);
    } finally {
      setBusy(false);
    }
  }, [task, cap, isMock, localEnabled, cloudEnabled, requestCompact]);

  const handleReset = useCallback(async () => {
    if (isMock) {
      setStatus("Mock mode — reset unavailable");
      return;
    }
    setBusy(true);
    setStatus("");
    try {
      await resetWorkspace();
      setStatus("Workspace cleared");
      setTask("");
      setCurrentTask("");
    } catch (e) {
      setStatus(e.message);
    } finally {
      setBusy(false);
    }
  }, [isMock]);

  const handleCompact = requestCompact;

  const value = useMemo(
    () => ({
      payload,
      connected,
      streamError,
      isMock,
      config,
      configError,
      selectedModel,
      setSelectedModel,
      localEnabled,
      setLocalEnabled,
      cloudEnabled,
      setCloudEnabled,
      localModels,
      cloudModels,
      hasLocals,
      hasLocalsLoaded,
      hasCloud,
      cloudKeyConfigured,
      comparisonModel,
      setComparisonModel,
      comparisonModels,
      task,
      setTask,
      currentTask,
      cap,
      setCap,
      status,
      busy,
      handleRun,
      handleReset,
      handleCompact,
      running,
    }),
    [
      payload,
      connected,
      streamError,
      isMock,
      config,
      configError,
      selectedModel,
      localEnabled,
      cloudEnabled,
      localModels,
      cloudModels,
      hasLocals,
      hasLocalsLoaded,
      hasCloud,
      cloudKeyConfigured,
      comparisonModel,
      comparisonModels,
      task,
      currentTask,
      cap,
      status,
      busy,
      handleRun,
      handleReset,
      handleCompact,
      running,
    ],
  );

  return (
    <BifrostContext.Provider value={value}>{children}</BifrostContext.Provider>
  );
}

export function useBifrost() {
  const ctx = useContext(BifrostContext);
  if (!ctx) {
    throw new Error("useBifrost must be used within BifrostProvider");
  }
  return ctx;
}
