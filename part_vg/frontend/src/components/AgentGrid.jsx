import AgentCard from "./AgentCard.jsx";

export default function AgentGrid({ workers }) {
  const list = workers ?? [];
  if (!list.length) return null;

  return (
    <section>
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
        Agents
      </h2>
      <div className="grid gap-3 sm:grid-cols-2">
        {list.map((w) => (
          <AgentCard key={w.id} worker={w} />
        ))}
      </div>
    </section>
  );
}
