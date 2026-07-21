import type { Stats } from "../lib/types";

interface Props {
  stats: Stats | null;
}

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return [h, m, s].map((v) => v.toString().padStart(2, "0")).join(":");
}

export function Header({ stats }: Props) {
  const mode = stats?.mode ?? "—";
  const uptime = stats ? formatUptime(stats.uptime_seconds) : "00:00:00";
  const tick = stats?.tick ?? 0;

  return (
    <header className="flex items-center gap-4 px-5 py-3 border-b border-line bg-deep relative z-20">
      {/* Wordmark */}
      <div className="flex items-center gap-3">
        <svg
          width="22"
          height="22"
          viewBox="0 0 32 32"
          aria-hidden="true"
          className="text-sonar"
        >
          <circle
            cx="16"
            cy="16"
            r="11"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.3"
            opacity="0.6"
          />
          <circle
            cx="16"
            cy="16"
            r="6"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.3"
          />
          <circle cx="16" cy="16" r="1.6" fill="currentColor" />
          <line
            x1="16"
            y1="2"
            x2="16"
            y2="30"
            stroke="currentColor"
            strokeWidth="0.6"
            opacity="0.5"
          />
          <line
            x1="2"
            y1="16"
            x2="30"
            y2="16"
            stroke="currentColor"
            strokeWidth="0.6"
            opacity="0.5"
          />
        </svg>
        <div className="display text-[15px] font-medium tracking-[0.18em] text-ink">
          PHANTOM<span className="text-sonar">SHIP</span>
        </div>
      </div>

      <div className="hidden md:block label">Maritime Anomaly Console</div>

      <div className="flex-1" />

      {/* Status group */}
      <div className="flex items-center gap-5">
        <StatusChip
          label="Mode"
          value={mode.toUpperCase()}
          dot={mode === "live" ? "var(--c-sonar)" : "var(--c-amber-light)"}
        />
        <Divider />
        <StatusChip label="Uptime" value={uptime} mono />
        <Divider />
        <StatusChip label="Tick" value={String(tick)} mono />
      </div>
    </header>
  );
}

function StatusChip({
  label,
  value,
  mono = false,
  dot,
}: {
  label: string;
  value: string;
  mono?: boolean;
  dot?: string;
}) {
  return (
    <div className="flex items-center gap-2">
      {dot && (
        <span
          className="inline-block w-1.5 h-1.5 rounded-full animate-pulse-slow"
          style={{ background: dot ?? "#00e5c0" }}
        />
      )}
      <span className="label">{label}</span>
      <span className={`text-[12px] text-ink ${mono ? "mono" : ""}`}>{value}</span>
    </div>
  );
}

function Divider() {
  return <span className="h-3 w-px bg-line2" aria-hidden="true" />;
}
