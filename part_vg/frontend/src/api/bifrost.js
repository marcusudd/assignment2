const API = "/api";

export async function fetchConfig() {
  const res = await fetch(`${API}/config`);
  if (!res.ok) {
    throw new Error(`config failed: ${res.status}`);
  }
  return res.json();
}

export async function runTask(task, cap) {
  const body = { task };
  if (cap != null && cap !== "") {
    body.cap = Number(cap);
  }
  const res = await fetch(`${API}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `run failed: ${res.status}`);
  }
  return res.json();
}

export async function resetWorkspace() {
  const res = await fetch(`${API}/reset`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `reset failed: ${res.status}`);
  }
  return res.json();
}

/**
 * Subscribe to live SSE snapshots. Returns a cleanup function.
 */
export function subscribeEvents(onMessage, onError) {
  const source = new EventSource(`${API}/events`);

  source.onmessage = (event) => {
    try {
      onMessage(JSON.parse(event.data));
    } catch (e) {
      onError?.(e);
    }
  };

  source.onerror = () => {
    onError?.(new Error("SSE connection lost"));
    source.close();
  };

  return () => source.close();
}
