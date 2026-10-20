// API types — mirror the backend `to_public()` payloads exactly.

export type Severity = "low" | "medium" | "high" | "critical";

export type DetectorType =
  | "kinematic"
  | "identity"
  | "dark_activity"
  | "loitering"
  | "ml_anomaly";

export interface Vessel {
  mmsi: string;
  name: string;
  type: string;
  flag: string;
  length_m: number;
  destination: string;
  lat: number;
  lon: number;
  speed: number;
  course: number;
  heading: number;
  speed_available?: boolean;
  course_available?: boolean;
  nav_status?: number | null;
  is_dark: boolean;
  threat_score: number;
  timestamp: string;
}

export interface Threat {
  id: string;
  mmsi: string;
  vessel_name: string;
  detector: DetectorType;
  severity: Severity;
  title: string;
  description: string;
  evidence: Record<string, unknown>;
  lat: number;
  lon: number;
  detected_at: string;
  last_seen_at?: string;
  occurrences?: number;
  ai_assessment: string | null;
  ai_engine?: string | null;
}

export interface Zone {
  id: string;
  name: string;
  category: "cable" | "chokepoint" | "sanctioned_port" | "eez" | string;
  description: string;
  polygon: [number, number][]; // [lon, lat][]
  center: [number, number];
}

export interface Stats {
  mode: string;
  uptime_seconds: number;
  tick: number;
  vessels_tracked: number;
  vessels_dark: number;
  threats_active: number;
  threats_by_severity: Record<Severity, number>;
  threats_by_detector: Record<string, number>;
  critical_zones: number;
  scan_ms?: number;
  findings_written?: number;
  ai_enabled?: boolean;
  ml?: {
    state: "learning" | "active";
    baseline_samples: number;
    baseline_vessels: number;
    min_samples: number;
    min_vessels: number;
    fits: number;
  } | null;
  data_quality?: Record<string, number>;
  feed?: {
    connected: boolean;
    messages: number;
    last_message_at: string | null;
    last_error: string | null;
    connects: number;
  };
}

export interface ThreatDetail {
  threat: Threat;
  vessel: Vessel | null;
  track: { lat: number; lon: number; speed: number; course: number; timestamp: string }[];
}

export interface AnalysisResponse {
  assessment: string;
  engine?: string | null;
  cached: boolean;
}
