import { useEffect, useMemo, useState } from "react";
import { AlertFeed } from "./components/AlertFeed";
import { GlobeView } from "./components/Globe";
import { Header } from "./components/Header";
import { Legend } from "./components/Legend";
import { StatsBar } from "./components/StatsBar";
import { VesselPanel } from "./components/VesselPanel";
import { usePoll } from "./hooks/usePoll";
import { api } from "./lib/api";
import type { Threat, Vessel, Zone } from "./lib/types";

export default function App() {
  const stats = usePoll(api.stats, 3000);
  const vesselsResp = usePoll(api.vessels, 2500);
  const threatsResp = usePoll(api.threats, 2500);
  const zonesResp = usePoll(api.zones, 60_000);

  const vessels: Vessel[] = vesselsResp.data?.vessels ?? [];
  const threats: Threat[] = threatsResp.data?.threats ?? [];
  const zones: Zone[] = zonesResp.data?.zones ?? [];

  const [selectedMmsi, setSelectedMmsi] = useState<string | null>(null);
  const [selectedThreatId, setSelectedThreatId] = useState<string | null>(null);

  // Selecting a threat also selects its vessel
  const onSelectThreat = (t: Threat) => {
    setSelectedThreatId(t.id);
    setSelectedMmsi(t.mmsi);
  };
  // Selecting a vessel finds its highest-severity threat (if any)
  const onSelectVessel = (mmsi: string | null) => {
    setSelectedMmsi(mmsi);
    if (mmsi) {
      const hit = threats.find((t) => t.mmsi === mmsi);
      setSelectedThreatId(hit?.id ?? null);
    } else {
      setSelectedThreatId(null);
    }
  };
  const onClear = () => {
    setSelectedMmsi(null);
    setSelectedThreatId(null);
  };

  const selectedVessel = useMemo(
    () => vessels.find((v) => v.mmsi === selectedMmsi) ?? null,
    [vessels, selectedMmsi]
  );
  const selectedThreat = useMemo(
    () => threats.find((t) => t.id === selectedThreatId) ?? null,
    [threats, selectedThreatId]
  );

  // Connection status banner if everything is broken
  const allFailing =
    stats.error && vesselsResp.error && threatsResp.error;

  // Keyboard escape to clear selection
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClear();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="h-full w-full flex flex-col bg-abyss text-ink">
      <Header stats={stats.data} />

      {allFailing && <ConnectionBanner />}

      <div className="flex-1 grid grid-cols-[300px_1fr_320px] gap-2.5 p-2.5 overflow-hidden grid-bg">
        <AlertFeed
          threats={threats}
          selectedThreatId={selectedThreatId}
          onSelectThreat={onSelectThreat}
        />

        <div className="panel relative overflow-hidden scan-overlay">
          <GlobeView
            vessels={vessels}
            threats={threats}
            zones={zones}
            selectedMmsi={selectedMmsi}
            onSelectVessel={onSelectVessel}
          />
          <Legend />
          {(vesselsResp.loading || zonesResp.loading) && !vessels.length && (
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
              <div className="text-sonar text-[11px] font-mono tracking-[0.16em] animate-pulse">
                ESTABLISHING FEED…
              </div>
            </div>
          )}
        </div>

        <VesselPanel
          vessel={selectedVessel}
          threat={selectedThreat}
          onClear={onClear}
        />
      </div>

      <StatsBar stats={stats.data} />
    </div>
  );
}

function ConnectionBanner() {
  return (
    <div className="bg-danger/10 border-b border-danger/30 px-4 py-2 text-[11px] text-danger font-mono">
      Cannot reach the PhantomShip backend. Verify it is running on port 8000.
    </div>
  );
}
