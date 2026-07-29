import React from "react";
import { GlassCard } from "./GlassCard";

export interface SensorFusionData {
  fused_threat_confidence: number;
  sensor_fusion_status: string;
  is_false_positive_bird: boolean;
  radar: {
    sensor_type: string;
    rcs_m2: number;
    doppler_speed_ms: number;
  };
  rf_scanner: {
    sensor_type: string;
    frequency: string;
    signal_strength_dbm: number;
  };
  optical_ai: {
    model: string;
    detected_class: string;
    confidence: number;
  };
  acoustic_array: {
    propeller_harmonic_hz: number;
    status: string;
  };
  kalman_trajectory: {
    predicted_lat: number;
    predicted_lon: number;
    deviation_meters: number;
    trajectory_anomaly: boolean;
  };
}

export function MultiSensorPanel({ data }: { data?: SensorFusionData }) {
  const radar = data?.radar ?? { sensor_type: "3D AESA Radar", rcs_m2: 0.052, doppler_speed_ms: 24.5 };
  const rf = data?.rf_scanner ?? { sensor_type: "RF Spectrum Analyzer", frequency: "2.4 GHz", signal_strength_dbm: -64.2 };
  const optical = data?.optical_ai ?? { model: "YOLOv11 Vision Transformer", detected_class: "QuadCopter_UAV", confidence: 0.94 };
  const acoustic = data?.acoustic_array ?? { propeller_harmonic_hz: 240.5, status: "Harmonics Matched" };
  const kalman = data?.kalman_trajectory ?? { predicted_lat: 28.6139, predicted_lon: 77.209, deviation_meters: 12.4, trajectory_anomaly: false };
  const confidence = data?.fused_threat_confidence ?? 88.5;

  return (
    <GlassCard className="p-6">
      <div className="flex items-center justify-between mb-6 border-b border-white/10 pb-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-sg-primary/10 border border-sg-primary/30 flex items-center justify-center">
            <span className="material-symbols-outlined text-sg-primary text-xl">radar</span>
          </div>
          <div>
            <h2 className="text-base font-bold font-mono tracking-wider text-sg-text uppercase">Multi-Sensor Defense Fusion Matrix</h2>
            <p className="text-xs font-mono text-sg-text-muted">3D AESA Radar + RF Scanner + YOLOv11 Camera + Acoustic + Kalman Filter</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right font-mono">
            <div className="text-[10px] text-sg-text-dim uppercase tracking-wider">Fusion Confidence</div>
            <div className="text-lg font-bold text-sg-primary">{confidence.toFixed(1)}%</div>
          </div>
          <span className={`px-3 py-1 rounded text-xs font-mono font-bold tracking-widest uppercase border ${confidence > 60 ? 'bg-red-500/20 text-red-400 border-red-500/30 shadow-[0_0_10px_rgba(239,68,68,0.3)]' : 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'}`}>
            {data?.sensor_fusion_status ?? "THREAT_CONFIRMED"}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-4">
        {/* Sensor 1: 3D AESA Radar */}
        <div className="bg-[#080f11] p-4 rounded-lg border border-white/5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between text-xs font-mono text-sg-primary mb-2">
              <span className="flex items-center gap-1.5"><span className="material-symbols-outlined text-sm">radar</span> RADAR</span>
              <span className="text-[10px] text-emerald-400">ACTIVE</span>
            </div>
            <div className="text-xs text-sg-text-muted font-mono mb-1">{radar.sensor_type}</div>
            <div className="text-sm font-bold font-mono text-sg-text">RCS: {radar.rcs_m2} m²</div>
            <div className="text-xs font-mono text-sg-text-dim mt-1">Doppler: {radar.doppler_speed_ms} m/s</div>
          </div>
          <div className="mt-3 text-[10px] font-mono text-sg-primary/80 border-t border-white/5 pt-2">Long-Range 3D Scan</div>
        </div>

        {/* Sensor 2: RF Spectrum Scanner */}
        <div className="bg-[#080f11] p-4 rounded-lg border border-white/5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between text-xs font-mono text-cyan-400 mb-2">
              <span className="flex items-center gap-1.5"><span className="material-symbols-outlined text-sm">cell_tower</span> RF SCANNER</span>
              <span className="text-[10px] text-cyan-300">{rf.frequency}</span>
            </div>
            <div className="text-xs text-sg-text-muted font-mono mb-1">{rf.sensor_type}</div>
            <div className="text-sm font-bold font-mono text-sg-text">Pwr: {rf.signal_strength_dbm} dBm</div>
            <div className="text-xs font-mono text-sg-text-dim mt-1">Band: C2 Comm Protocol</div>
          </div>
          <div className="mt-3 text-[10px] font-mono text-cyan-400/80 border-t border-white/5 pt-2">Pilot Triangulated</div>
        </div>

        {/* Sensor 3: Optical AI Camera (YOLOv11) */}
        <div className="bg-[#080f11] p-4 rounded-lg border border-white/5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between text-xs font-mono text-amber-400 mb-2">
              <span className="flex items-center gap-1.5"><span className="material-symbols-outlined text-sm">videocam</span> OPTICAL AI</span>
              <span className="text-[10px] text-amber-300">{(optical.confidence * 100).toFixed(0)}% CONF</span>
            </div>
            <div className="text-xs text-sg-text-muted font-mono mb-1">{optical.model}</div>
            <div className="text-sm font-bold font-mono text-amber-300 truncate">{optical.detected_class}</div>
            <div className="text-xs font-mono text-sg-text-dim mt-1">Bounding Box: Tracking</div>
          </div>
          <div className="mt-3 text-[10px] font-mono text-amber-400/80 border-t border-white/5 pt-2">Vision Classifier</div>
        </div>

        {/* Sensor 4: Acoustic Array */}
        <div className="bg-[#080f11] p-4 rounded-lg border border-white/5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between text-xs font-mono text-purple-400 mb-2">
              <span className="flex items-center gap-1.5"><span className="material-symbols-outlined text-sm">graphic_eq</span> ACOUSTIC</span>
              <span className="text-[10px] text-purple-300">PROP FREQ</span>
            </div>
            <div className="text-xs text-sg-text-muted font-mono mb-1">Microphone Array</div>
            <div className="text-sm font-bold font-mono text-sg-text">{acoustic.propeller_harmonic_hz} Hz</div>
            <div className="text-xs font-mono text-sg-text-dim mt-1">{acoustic.status}</div>
          </div>
          <div className="mt-3 text-[10px] font-mono text-purple-400/80 border-t border-white/5 pt-2">Audio Fingerprint</div>
        </div>

        {/* Sensor 5: Kalman Trajectory Filter */}
        <div className="bg-[#080f11] p-4 rounded-lg border border-white/5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between text-xs font-mono text-emerald-400 mb-2">
              <span className="flex items-center gap-1.5"><span className="material-symbols-outlined text-sm">route</span> KALMAN FILTER</span>
              <span className={`text-[10px] font-bold ${kalman.trajectory_anomaly ? 'text-red-400' : 'text-emerald-400'}`}>
                {kalman.trajectory_anomaly ? 'SPOOFED' : 'ESTIMATED'}
              </span>
            </div>
            <div className="text-xs text-sg-text-muted font-mono mb-1">2D/3D Trajectory Predictor</div>
            <div className="text-sm font-bold font-mono text-sg-text">Dev: {kalman.deviation_meters} m</div>
            <div className="text-xs font-mono text-sg-text-dim mt-1">Pred: {kalman.predicted_lat}, {kalman.predicted_lon}</div>
          </div>
          <div className="mt-3 text-[10px] font-mono text-emerald-400/80 border-t border-white/5 pt-2">State Vector Model</div>
        </div>
      </div>
    </GlassCard>
  );
}
