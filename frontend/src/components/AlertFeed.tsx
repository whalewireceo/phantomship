import { useMemo, useState } from "react";
import type { Severity, Threat } from "../lib/types";

interface Props {
  threats: Threat[];
  selectedThreatId: string | null;
  onSelectThreat: (t: Threat) => void;
}

const ALL: Severity[] = ["critical", "high", "medium", "low"];

const DETECTOR_LABELS: Record<string, string> = {
  kinematic: "Kinematic",
  identity: "Identity",
  dark_activity: "Dark activity",
  loitering: "Loitering",
  ml_anomaly: "ML anomaly",
};

export function AlertFeed({ threats, selectedThreatId, onSelectThreat }: Props) {
  const [filter, setFilter] = useState<Severity | "all">("all");

  const filtered = useMemo(() => {
    return filter === "all" ? threats : threats.filter((t) => t.severity === filter);
  }, [threats, filter]);

  const counts = useMemo(() => {
    const m: Record<string, number> = { all: threats.length };
    for (const s of ALL) m[s] = threats.filter((t) => t.severity === s).length;
    return m;
  }, [threats]);

  return (
    <section className="panel flex flex-col h-full overflow-hidden">
      <div className="flex items-center justify-between px-3 pt-3 pb-2">
        <h2 className="panel-title">
          Live alerts <span className="panel-tag">{threats.length}</span>
        </h2>
      </div>

      <div className="px-3 pb-2 flex flex-wrap gap-1.5">
        <FilterPill
          label="All"
          active={filter === "all"}
          count={counts.all ?? 0}
          onClick={() => setFilter("all")}
        />
        {ALL.map((s) => (
          <FilterPill
            key={s}
            label={s.toUpperCase()}
            active={filter === s}
            count={counts[s] ?? 0}
            severity={s}
            onClick={() => setFilter(s)}
          />
        ))}
      </div>

      <div className="overflow-y-auto px-3 pb-3 space-y-2 flex-1">
        {filtered.length === 0 && (
          <div className="text-dim text-[12px] py-8 text-center">
            No threats match this filter.
          </div>
        )}
        {filtered.map((t) => (
          <AlertCard
            key={t.id}
            t={t}
            selected={t.id === selectedThreatId}
            onClick={() => onSelectThreat(t)}
          />
        ))}
      </div>
    </section>
  );
}

function FilterPill({
  label,
  active,
  count,
  severity,
  onClick,
}: {
  label: string;
  active: boolean;
  count: number;
  severity?: Severity;
  onClick: () => void;
}) {
  const tone = severity
    ? {
        critical: "border-danger/40 text-danger",
        high: "border-amber/40 text-amber",
        medium: "border-select/40 text-select",
        low: "border-line2 text-dim",
      }[severity]
    : "border-line2 text-dim";
  return (
    <button
      onClick={onClick}
      className={[
        "text-[10px] font-mono uppercase tracking-[0.08em] px-2 py-1 rounded-md",
        "border bg-surface transition-colors",
        active ? "bg-surface2 text-ink border-line2" : tone,
      ].join(" ")}
    >
      {label}
      <span className="ml-1.5 text-dim2">{count}</span>
    </button>
  );
}

function AlertCard({
  t,
  selected,
  onClick,
}: {
  t: Threat;
  selected: boolean;
  onClick: () => void;
}) {
  const sevClass = `sev-${t.severity}`;
  const detectedAt = new Date(t.detected_at);
  const time = detectedAt.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });

  return (
    <button
      onClick={onClick}
      className={[
        "w-full text-left rounded-md border p-2.5 bg-surface transition-all",
        "hover:bg-surface2 hover:border-line2",
        selected
          ? "border-sonar/50 bg-sonar/[0.06] shadow-glow"
          : t.severity === "critical"
            ? "border-danger/30"
            : t.severity === "high"
              ? "border-amber/30"
              : "border-line",
      ].join(" ")}
    >
      <div className="flex items-center gap-2">
        <span className={`sev-pill ${sevClass}`}>{t.severity.toUpperCase()}</span>
        <span className="text-[10px] font-mono text-dim2">
          {DETECTOR_LABELS[t.detector] ?? t.detector}
        </span>
        <span className="flex-1" />
        <span className="text-[10px] font-mono text-dim">{time}</span>
      </div>
      <div className="mt-1.5 text-[12px] font-medium text-ink leading-tight">
        {t.title}
      </div>
      <div className="mt-1 text-[11px] text-dim leading-snug line-clamp-2">
        {t.description}
      </div>
      <div className="mt-1.5 text-[10px] font-mono text-dim2">
        MMSI {t.mmsi} · {t.vessel_name}
      </div>
    </button>
  );
}
