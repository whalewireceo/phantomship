export function Legend() {
  return (
    <div className="absolute bottom-4 left-4 z-10 panel bg-deep/95 backdrop-blur-sm px-3 py-2.5 select-none pointer-events-none">
      <div className="label mb-1.5">Threat key</div>
      <div className="space-y-1">
        <Row color="#00e5c0" label="Nominal" />
        <Row color="#7c9cff" label="Watch · ML anomaly" />
        <Row color="#ffb020" label="High" />
        <Row color="#ff3b5c" label="Critical" pulse />
      </div>
      <div className="mt-2 pt-2 border-t border-line">
        <div className="label mb-1">Zones</div>
        <div className="flex items-center gap-2 text-[10.5px] text-ink">
          <span className="inline-block w-3 h-2 border border-sonar bg-sonar/10 rounded-sm" />
          <span>Chokepoint</span>
        </div>
        <div className="flex items-center gap-2 text-[10.5px] text-ink mt-1">
          <span className="inline-block w-3 h-2 border border-danger bg-danger/10 rounded-sm" />
          <span>Cable corridor</span>
        </div>
      </div>
    </div>
  );
}

function Row({ color, label, pulse }: { color: string; label: string; pulse?: boolean }) {
  return (
    <div className="flex items-center gap-2 text-[10.5px] text-ink">
      <span
        className={`inline-block w-2 h-2 rounded-full ${pulse ? "animate-pulse-slow" : ""}`}
        style={{ background: color, boxShadow: `0 0 8px ${color}55` }}
      />
      <span>{label}</span>
    </div>
  );
}
