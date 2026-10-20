import { useEffect, useMemo, useRef } from "react";
import Globe from "react-globe.gl";
import * as THREE from "three";
import type { Threat, Vessel, Zone } from "../lib/types";

interface Props {
  vessels: Vessel[];
  threats: Threat[];
  zones: Zone[];
  selectedMmsi: string | null;
  onSelectVessel: (mmsi: string | null) => void;
}

// ------------------------------------------------------------------------- //
// Color grading by threat score
// ------------------------------------------------------------------------- //
const SONAR = "#00e5c0";
const SELECT = "#7c9cff";
const AMBER = "#ffb020";
const DANGER = "#ff3b5c";

function vesselColor(v: Vessel): string {
  const s = v.threat_score;
  if (s >= 0.9) return DANGER;
  if (s >= 0.7) return AMBER;
  if (s >= 0.4) return SELECT;
  return SONAR;
}

function vesselAltitude(v: Vessel): number {
  // Lift threat-scored vessels slightly above the globe surface so they
  // visually pop and aren't occluded by the equator graticule.
  return 0.005 + v.threat_score * 0.018;
}

// Shared Three.js resources. The globe rebuilds vessel meshes every poll, and
// creating a new geometry and material per ship per poll (thousands of
// them every 2.5 s with a live feed) leaked GPU memory and stalled the page.
const VESSEL_GEOMETRY = (() => {
  const g = new THREE.ConeGeometry(0.55, 1.3, 4);
  g.rotateX(Math.PI / 2);
  return g;
})();
const HALO_GEOMETRY = new THREE.RingGeometry(1.0, 1.4, 24);
const vesselMaterials = new Map<string, THREE.MeshBasicMaterial>();
const haloMaterials = new Map<string, THREE.MeshBasicMaterial>();

function vesselMaterial(color: string): THREE.MeshBasicMaterial {
  let m = vesselMaterials.get(color);
  if (!m) {
    m = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.95 });
    vesselMaterials.set(color, m);
  }
  return m;
}

function haloMaterial(color: string): THREE.MeshBasicMaterial {
  let m = haloMaterials.get(color);
  if (!m) {
    m = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.45, side: THREE.DoubleSide });
    haloMaterials.set(color, m);
  }
  return m;
}

// ------------------------------------------------------------------------- //
// Polygon helpers — react-globe.gl expects GeoJSON-like rings
// ------------------------------------------------------------------------- //
interface ZoneFeature {
  zone: Zone;
  // Loose GeoJSON shape — the library's type widens this; we narrow at the
  // accessor site.
  geometry: { type: "Polygon"; coordinates: number[][][] };
}

function zonesToFeatures(zones: Zone[]): ZoneFeature[] {
  return zones.map((z) => ({
    zone: z,
    geometry: {
      type: "Polygon",
      coordinates: [z.polygon.map(([lon, lat]) => [lon, lat])],
    },
  }));
}

function zoneSideColor(z: Zone): string {
  return z.category === "cable" ? "rgba(255, 59, 92, 0.20)" : "rgba(0, 229, 192, 0.18)";
}
function zoneCapColor(z: Zone): string {
  return z.category === "cable" ? "rgba(255, 59, 92, 0.10)" : "rgba(0, 229, 192, 0.08)";
}
function zoneStrokeColor(z: Zone): string {
  return z.category === "cable" ? DANGER : SONAR;
}

// ------------------------------------------------------------------------- //
// Threat arcs — render impossible-jump teleportation events as red arcs
// ------------------------------------------------------------------------- //
interface ArcData {
  startLat: number;
  startLng: number;
  endLat: number;
  endLng: number;
  color: string;
}

function teleportArcsFromThreats(threats: Threat[]): ArcData[] {
  const arcs: ArcData[] = [];
  for (const t of threats) {
    if (t.detector !== "kinematic") continue;
    const ev = t.evidence as Record<string, unknown>;
    const fromLat = ev["from_lat"];
    const fromLon = ev["from_lon"];
    const toLat = ev["to_lat"];
    const toLon = ev["to_lon"];
    if (
      typeof fromLat === "number" &&
      typeof fromLon === "number" &&
      typeof toLat === "number" &&
      typeof toLon === "number"
    ) {
      arcs.push({
        startLat: fromLat,
        startLng: fromLon,
        endLat: toLat,
        endLng: toLon,
        color: DANGER,
      });
    }
  }
  return arcs.slice(0, 40); // cap for perf
}

// ------------------------------------------------------------------------- //
// Globe component
// ------------------------------------------------------------------------- //
export function GlobeView({
  vessels,
  threats,
  zones,
  selectedMmsi,
  onSelectVessel,
}: Props) {
  const ref = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Initial camera + gentle auto-rotate
  useEffect(() => {
    const g = ref.current;
    if (!g) return;
    g.pointOfView({ lat: 25, lng: 15, altitude: 2.4 }, 0);
    const controls = g.controls();
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.18;
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 200;
    controls.maxDistance = 600;
  }, []);

  // Stop auto-rotate when the user selects a vessel
  useEffect(() => {
    const g = ref.current;
    if (!g) return;
    const controls = g.controls();
    controls.autoRotate = !selectedMmsi;
  }, [selectedMmsi]);

  // Resize handling — globe uses canvas, we measure the container
  const size = useResizeObserver(containerRef);

  const features = useMemo(() => zonesToFeatures(zones), [zones]);
  const arcs = useMemo(() => teleportArcsFromThreats(threats), [threats]);

  // ----- Custom 3D vessel geometry: small directional triangle ----- //
  const objectThreeObject = useMemo(
    () => (v: any) => {
      const vessel = v as Vessel;
      const color = vesselColor(vessel);
      const mesh = new THREE.Mesh(VESSEL_GEOMETRY, vesselMaterial(color));
      mesh.rotation.z = -(vessel.course * Math.PI) / 180;
      // Critical-threat halo ring
      if (vessel.threat_score >= 0.9) {
        const ring = new THREE.Mesh(HALO_GEOMETRY, haloMaterial(color));
        ring.rotation.x = Math.PI / 2;
        mesh.add(ring);
      }
      return mesh;
    },
    []
  );

  const labelForVessel = (v: any) => {
    const vessel = v as Vessel;
    const sev =
      vessel.threat_score >= 0.9
        ? "CRITICAL"
        : vessel.threat_score >= 0.7
          ? "HIGH"
          : vessel.threat_score >= 0.4
            ? "WATCH"
            : "NOMINAL";
    return `
      <div style="
        font-family:'IBM Plex Mono',ui-monospace,monospace;
        font-size:11px;line-height:1.4;
        background:rgba(10,16,30,0.94);border:1px solid #1f2940;
        padding:7px 9px;border-radius:6px;color:#e5e9f0;
        white-space:nowrap;
      ">
        <div style="font-family:'IBM Plex Sans';font-size:12px;font-weight:500;letter-spacing:0.04em;">
          ${escapeHtml(vessel.name)}
        </div>
        <div style="font-size:10px;color:#8794ad;margin-top:2px;letter-spacing:0.06em;">
          MMSI ${escapeHtml(vessel.mmsi)} · ${escapeHtml(vessel.flag)} · ${escapeHtml(vessel.type.toUpperCase())}
        </div>
        <div style="display:flex;gap:10px;margin-top:5px;font-size:10px;color:#8794ad;">
          <span>SOG ${vessel.speed_available === false ? "n/a" : vessel.speed.toFixed(1) + " kn"}</span>
          <span>COG ${vessel.course_available === false ? "n/a" : vessel.course.toFixed(0) + "°"}</span>
        </div>
        <div style="margin-top:5px;font-size:9.5px;letter-spacing:0.08em;
          color:${vesselColor(vessel)};">${sev}</div>
      </div>
    `;
  };

  return (
    <div ref={containerRef} className="absolute inset-0">
      <Globe
        ref={ref}
        width={size.w}
        height={size.h}
        // Deep-space backdrop
        backgroundColor="rgba(6,9,18,1)"
        // Globe surface — a dark night render keeps the cyan accents loud
        globeImageUrl="//unpkg.com/three-globe/example/img/earth-night.jpg"
        bumpImageUrl="//unpkg.com/three-globe/example/img/earth-topology.png"
        atmosphereColor="#00e5c0"
        atmosphereAltitude={0.16}
        showGraticules
        // Vessels
        objectsData={vessels}
        objectLat={(d: any) => (d as Vessel).lat}
        objectLng={(d: any) => (d as Vessel).lon}
        objectAltitude={(d: any) => vesselAltitude(d as Vessel)}
        objectThreeObject={objectThreeObject}
        objectLabel={labelForVessel}
        onObjectClick={(d: any) => onSelectVessel((d as Vessel).mmsi)}
        // Critical zones — polygons
        polygonsData={features as any}
        polygonGeoJsonGeometry={((f: any) => (f as ZoneFeature).geometry) as any}
        polygonAltitude={0.006}
        polygonCapColor={(f: any) => zoneCapColor((f as ZoneFeature).zone)}
        polygonSideColor={(f: any) => zoneSideColor((f as ZoneFeature).zone)}
        polygonStrokeColor={(f: any) => zoneStrokeColor((f as ZoneFeature).zone)}
        polygonLabel={(f: any) => {
          const z = (f as ZoneFeature).zone;
          return `
            <div style="
              font-family:'IBM Plex Sans';font-size:11px;
              background:rgba(10,16,30,0.94);border:1px solid #1f2940;
              padding:7px 9px;border-radius:6px;color:#e5e9f0;
            ">
              <div style="font-weight:500;letter-spacing:0.04em;">${escapeHtml(z.name)}</div>
              <div style="font-size:10px;color:#8794ad;margin-top:2px;
                letter-spacing:0.06em;text-transform:uppercase;">
                ${escapeHtml(z.category)}
              </div>
            </div>
          `;
        }}
        // Teleportation arcs
        arcsData={arcs}
        arcStartLat={(d: any) => (d as ArcData).startLat}
        arcStartLng={(d: any) => (d as ArcData).startLng}
        arcEndLat={(d: any) => (d as ArcData).endLat}
        arcEndLng={(d: any) => (d as ArcData).endLng}
        arcColor={(d: any) => (d as ArcData).color}
        arcStroke={0.4}
        arcAltitudeAutoScale={0.4}
        arcDashLength={0.35}
        arcDashGap={0.7}
        arcDashAnimateTime={3500}
      />
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Helpers
// --------------------------------------------------------------------------- //
function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function useResizeObserver(ref: React.RefObject<HTMLDivElement>): { w: number; h: number } {
  const sizeRef = useRef({ w: 0, h: 0 });
  const [, force] = useThrottledForce(120);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        sizeRef.current = { w: Math.floor(width), h: Math.floor(height) };
        force();
      }
    });
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, [ref, force]);
  return sizeRef.current;
}

function useThrottledForce(ms: number): [number, () => void] {
  const lastRef = useRef(0);
  const tRef = useRef<number | null>(null);
  const [n, setN] = useStateLocal(0);
  const tick = () => {
    const now = Date.now();
    if (now - lastRef.current >= ms) {
      lastRef.current = now;
      setN((x: number) => x + 1);
    } else if (tRef.current === null) {
      tRef.current = window.setTimeout(() => {
        tRef.current = null;
        lastRef.current = Date.now();
        setN((x: number) => x + 1);
      }, ms);
    }
  };
  return [n, tick];
}

// Tiny local state shim so this file doesn't import useState twice from different
// React versions in dev. (Keeps bundler happy under StrictMode double-invocation.)
import { useState as useStateLocal } from "react";
