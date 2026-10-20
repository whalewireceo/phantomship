import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { Threat, Vessel } from "../lib/types";

interface Props {
  vessel: Vessel | null;
  threat: Threat | null;
  aiEnabled: boolean;
  onClear: () => void;
}

export function VesselPanel({ vessel, threat, aiEnabled, onClear }: Props) {
  if (!vessel && !threat) return <EmptyState />;

  return (
    <div className="panel flex flex-col h-full overflow-hidden">
      <div className="px-3 pt-3 pb-2 flex items-center justify-between">
        <h2 className="panel-title">Vessel intel</h2>
        <button
          onClick={onClear}
          className="text-[10px] font-mono uppercase tracking-[0.08em] text-dim hover:text-ink transition-colors"
        >
          Clear
        </button>
      </div>

      <div className="overflow-y-auto px-3 pb-3 flex-1 space-y-3">
        {vessel && <VesselCard v={vessel} />}
        {threat && <ThreatCard t={threat} />}
        {threat && <AnalystReport threat={threat} aiEnabled={aiEnabled} />}
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="panel h-full flex flex-col items-center justify-center px-6 text-center">
      <svg width="42" height="42" viewBox="0 0 32 32" className="text-dim2 mb-3">
        <circle cx="16" cy="16" r="11" fill="none" stroke="currentColor" strokeWidth="1" opacity="0.5" />
        <circle cx="16" cy="16" r="6" fill="none" stroke="currentColor" strokeWidth="1" opacity="0.7" />
        <circle cx="16" cy="16" r="1.4" fill="currentColor" />
      </svg>
      <div className="text-[12px] text-ink mb-1">No vessel selected</div>
      <div className="text-[11px] text-dim leading-snug">
        Click a vessel on the globe or an alert in the feed to inspect.
      </div>
    </div>
  );
}

function VesselCard({ v }: { v: Vessel }) {
  const threatLabel =
    v.threat_score >= 0.9
      ? { text: "CRITICAL", cls: "text-danger" }
      : v.threat_score >= 0.7
        ? { text: "HIGH", cls: "text-amber" }
        : v.threat_score >= 0.4
          ? { text: "WATCH", cls: "text-select" }
          : { text: "NOMINAL", cls: "text-sonar" };
  return (
    <div className="panel bg-surface border-line p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-[13px] font-medium text-ink leading-tight">{v.name}</div>
          <div className="text-[10px] font-mono text-dim mt-0.5">
            MMSI {v.mmsi} · {v.flag.toUpperCase()} FLAG
          </div>
        </div>
        <div className={`text-[10px] font-mono tracking-[0.08em] ${threatLabel.cls}`}>
          {threatLabel.text}
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
        <KV k="Class" v={v.type.toUpperCase()} />
        <KV k="LOA" v={v.length_m > 0 ? `${v.length_m} m` : "unknown"} />
        <KV k="Speed" v={v.speed_available === false ? "not reported" : `${v.speed.toFixed(1)} kn`} />
        <KV k="Course" v={v.course_available === false ? "not reported" : `${v.course.toFixed(0)}°`} />
        <KV k="Position" v={`${v.lat.toFixed(3)}, ${v.lon.toFixed(3)}`} className="col-span-2" />
        <KV k="Destination" v={v.destination} className="col-span-2" />
      </div>
    </div>
  );
}

function ThreatCard({ t }: { t: Threat }) {
  return (
    <div
      className={`panel bg-surface p-3 ${
        t.severity === "critical"
          ? "border-danger/40"
          : t.severity === "high"
            ? "border-amber/40"
            : "border-line"
      }`}
    >
      <div className="flex items-center gap-2">
        <span className={`sev-pill sev-${t.severity}`}>{t.severity.toUpperCase()}</span>
        <span className="text-[10px] font-mono text-dim2 uppercase tracking-[0.08em]">
          {t.detector.replace("_", " ")}
        </span>
      </div>
      <div className="mt-2 text-[12px] font-medium text-ink">{t.title}</div>
      <div className="mt-1 text-[11px] text-dim leading-relaxed">{t.description}</div>

      {Object.keys(t.evidence).length > 0 && (
        <details className="mt-2 text-[10px] font-mono group">
          <summary className="text-dim cursor-pointer hover:text-ink select-none">
            Evidence ▾
          </summary>
          <pre className="mt-1 p-2 bg-abyss border border-line rounded text-[10px] text-dim leading-relaxed overflow-x-auto">
            {JSON.stringify(t.evidence, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}

function AnalystReport({ threat, aiEnabled }: { threat: Threat; aiEnabled: boolean }) {
  const [assessment, setAssessment] = useState<string | null>(threat.ai_assessment);
  const [engine, setEngine] = useState<string | null>(threat.ai_engine ?? null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset when threat changes
  useEffect(() => {
    setAssessment(threat.ai_assessment);
    setEngine(threat.ai_engine ?? null);
    setError(null);
  }, [threat.id, threat.ai_assessment, threat.ai_engine]);

  const fetchAssessment = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api.analysis(threat.id);
      setAssessment(r.assessment);
      setEngine(r.engine ?? null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="panel bg-surface border-line p-3">
      <div className="flex items-center justify-between gap-2 mb-2">
        <h3 className="panel-title !mb-0">
          AI analyst{" "}
          {(engine ?? (aiEnabled ? "claude" : "rule_based")) === "claude" ? (
            <span className="panel-tag text-sonar border border-sonar/40 bg-transparent">CLAUDE</span>
          ) : (
            <span className="panel-tag text-dim border border-line2 bg-transparent">RULE BASED</span>
          )}
        </h3>
        {!assessment && (
          <button
            onClick={fetchAssessment}
            disabled={loading}
            className="btn btn-primary !px-2.5 !py-1 !text-[10px]"
          >
            {loading ? "Analyzing…" : "Run analysis"}
          </button>
        )}
      </div>

      {error && (
        <div className="text-[11px] text-danger">Failed to run analysis: {error}</div>
      )}

      {!assessment && !loading && !error && (
        <div className="text-[11px] text-dim leading-snug">
          Generate a maritime cyber threat assessment for this detection event.
          {aiEnabled
            ? " Uses Claude."
            : " No Anthropic API key is configured, so this uses the rule based assessment."}
        </div>
      )}

      {loading && <ShimmerLines />}

      {assessment && (
        <div className="text-[11.5px] text-ink leading-relaxed whitespace-pre-line animate-fade-in">
          {renderAssessment(assessment)}
        </div>
      )}
    </div>
  );
}

function renderAssessment(text: string): React.ReactNode {
  // Lightly format ALL-CAPS section labels at the start of paragraphs
  return text.split(/\n\n+/).map((para, i) => {
    const m = para.match(/^([A-Z][A-Z\s]{2,18}):\s*(.*)$/s);
    if (m) {
      return (
        <p key={i} className="mb-2 last:mb-0">
          <span className="font-medium text-sonar mr-1.5 tracking-[0.04em]">{m[1]}.</span>
          <span className="text-ink">{m[2]}</span>
        </p>
      );
    }
    return (
      <p key={i} className="mb-2 last:mb-0">
        {para}
      </p>
    );
  });
}

function ShimmerLines() {
  return (
    <div className="space-y-1.5">
      {[100, 92, 84].map((w, i) => (
        <div
          key={i}
          className="h-3 rounded bg-gradient-to-r from-surface2 via-line2 to-surface2 animate-pulse"
          style={{ width: `${w}%` }}
        />
      ))}
    </div>
  );
}

function KV({ k, v, className = "" }: { k: string; v: string; className?: string }) {
  return (
    <div className={`flex flex-col gap-0.5 ${className}`}>
      <span className="label">{k}</span>
      <span className="value">{v}</span>
    </div>
  );
}
