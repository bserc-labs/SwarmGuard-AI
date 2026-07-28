import type { TelemetryPacket } from "@/services/api";

export interface DroneMapLocation extends Pick<TelemetryPacket, "drone_id" | "latitude" | "longitude" | "speed" | "altitude" | "battery"> {
  threat_status?: "Normal" | "Warning" | "Critical" | string;
  last_updated?: string;
}

export const demoDroneLocations: DroneMapLocation[] = [
  {
    drone_id: "DRONE-01",
    latitude: 18.5204,
    longitude: 73.8567,
    altitude: 128.5,
    speed: 11.3,
    battery: 84.2,
    threat_status: "Normal",
    last_updated: "2026-07-27T10:12:00Z",
  },
  {
    drone_id: "DRONE-02",
    latitude: 18.531,
    longitude: 73.8475,
    altitude: 142.1,
    speed: 9.4,
    battery: 61.8,
    threat_status: "Warning",
    last_updated: "2026-07-27T10:11:45Z",
  },
  {
    drone_id: "DRONE-03",
    latitude: 18.509,
    longitude: 73.875,
    altitude: 116.7,
    speed: 13.1,
    battery: 47.5,
    threat_status: "Normal",
    last_updated: "2026-07-27T10:11:20Z",
  },
  {
    drone_id: "DRONE-04",
    latitude: 18.5415,
    longitude: 73.8625,
    altitude: 97.3,
    speed: 7.8,
    battery: 23.4,
    threat_status: "Critical",
    last_updated: "2026-07-27T10:10:55Z",
  },
  {
    drone_id: "DRONE-05",
    latitude: 18.4978,
    longitude: 73.8402,
    altitude: 154.2,
    speed: 10.7,
    battery: 72.0,
    threat_status: "Normal",
    last_updated: "2026-07-27T10:10:30Z",
  },
];
