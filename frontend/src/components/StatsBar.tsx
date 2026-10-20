import type { Stats } from "../lib/types";

interface Props {
  stats: Stats | null;
}

export function StatsBar({ stats }: Props) {
  const cells = [
    { k: "Vessels", v: stats?.vessels_tracked ?? 0 },
    {
      k: "Threats",
      v: stats?.threats_active ?? 0,
      tone: (stats?.threats_active ?? 0) > 0 ? "text-danger" : "text-ink",
    },
    {
      k: "Critical",
      v: stats?.threats_by_severity?.critical ?? 0,
      tone: "text-danger",
    },
    {
      k: "High",
      v: stats?.threats_by_severity?.high ?? 0,
      tone: "text-amber",
    },
    {
      k: "Watch zones",
      v: stats?.critical_zones ?? 0,
      tone: "text-sonar",
    },
    {
      k: "ML baseline",
      v: !stats?.ml
        ? "—"
        : stats.ml.state === "active"
          ? "ACTIVE"
          : `LEARNING ${Math.min(100, Math.round((100 * stats.ml.baseline_samples) / Math.max(1, stats.ml.min_samples)))}%`,
      tone: stats?.ml?.state === "active" ? "text-sonar" : "text-amber",
    },
  ];

  return (
    <div className="grid grid-cols-6 border-t border-line bg-deep">
      {cells.map((c, i) => (
        <div
          key={c.k}
          className={`px-4 py-2.5 ${i < cells.length - 1 ? "border-r border-line" : ""}`}
        >
          <div className="label">{c.k}</div>
          <div className={`mono text-[17px] mt-0.5 ${c.tone ?? "text-ink"}`}>{c.v}</div>
        </div>
      ))}
    </div>
  );
}
