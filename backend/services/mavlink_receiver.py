import asyncio
import time
from pymavlink import mavutil
from sqlalchemy.orm import Session

from config import get_settings
from database import SessionLocal
from utils.logger import logger
from services.telemetry_service import telemetry_service
from services.ws_manager import ws_manager
import schemas

settings = get_settings()

class MavlinkReceiver:
    # Exponential backoff bounds, and how often a sustained outage is logged.
    MIN_RECONNECT_DELAY = 2
    MAX_RECONNECT_DELAY = 60
    LOG_EVERY_N_FAILURES = 20

    def __init__(self):
        self.running = False
        self.mav_connection = None
        self.reconnect_delay = self.MIN_RECONNECT_DELAY
        self.consecutive_failures = 0
        self.drone_id_prefix = "DRONE_MAV_"
        self.packet_sequence = 0
        self._task = None
        self.drone_states = {}
        
    def _connect(self):
        """
        Attempt a connection.

        Logging is deliberately quiet on repeat failures. A UDP endpoint with no
        transmitter fails on every attempt, and logging each one buries real
        events under thousands of identical lines. The first failure and then
        every LOG_EVERY_N_FAILURES are reported; the rest are counted silently.
        """
        connection_string = (
            f"{settings.MAVLINK_PROTOCOL}:{settings.MAVLINK_HOST}:{settings.MAVLINK_PORT}"
        )

        if self.consecutive_failures == 0:
            logger.info(f"Connecting to MAVLink at {connection_string}")

        try:
            self.mav_connection = mavutil.mavlink_connection(connection_string)
            self.mav_connection.wait_heartbeat(timeout=5)

            if self.consecutive_failures > 0:
                logger.info(
                    f"MAVLink recovered after {self.consecutive_failures} failed attempts "
                    f"(system {self.mav_connection.target_system})."
                )
            else:
                logger.info(
                    f"MAVLink connected (system {self.mav_connection.target_system}, "
                    f"component {self.mav_connection.target_component})."
                )

            self.consecutive_failures = 0
            self.reconnect_delay = self.MIN_RECONNECT_DELAY
            return True

        except Exception as e:
            self.consecutive_failures += 1

            if self.consecutive_failures == 1:
                logger.warning(f"MAVLink connection to {connection_string} failed: {e}")
            elif self.consecutive_failures % self.LOG_EVERY_N_FAILURES == 0:
                logger.warning(
                    f"MAVLink still unreachable at {connection_string} after "
                    f"{self.consecutive_failures} attempts "
                    f"(retrying every {self.reconnect_delay}s)."
                )

            # mavutil may leave a half-open socket behind on failure.
            if self.mav_connection is not None:
                try:
                    self.mav_connection.close()
                except Exception:
                    pass
            self.mav_connection = None
            return False

    async def start(self):
        if self.running:
            return

        if not settings.MAVLINK_ENABLED:
            logger.info("MAVLink receiver disabled (set MAVLINK_ENABLED=true to enable).")
            return

        if settings.MAVLINK_ORGANIZATION_ID is None:
            # Refuse rather than ingest telemetry that no tenant can read.
            logger.error(
                "MAVLINK_ENABLED is true but MAVLINK_ORGANIZATION_ID is not set. "
                "Receiver not started."
            )
            return

        self.running = True
        self._task = asyncio.create_task(self._listen_loop())
        logger.info(
            f"MAVLink receiver started (organization_id={settings.MAVLINK_ORGANIZATION_ID})."
        )

    async def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
        if self.mav_connection:
            self.mav_connection.close()
        logger.info("MAVLink Receiver stopped.")

    async def _listen_loop(self):
        while self.running:
            if not self.mav_connection:
                success = await asyncio.to_thread(self._connect)
                if not success:
                    # _connect handles reporting; sleeping silently here keeps a
                    # sustained outage from producing one log line per attempt.
                    await asyncio.sleep(self.reconnect_delay)
                    self.reconnect_delay = min(
                        self.reconnect_delay * 2, self.MAX_RECONNECT_DELAY
                    )
                    continue

            try:
                msg = self.mav_connection.recv_match(
                    type=['GLOBAL_POSITION_INT', 'SYS_STATUS', 'HEARTBEAT', 'GPS_RAW_INT'], 
                    blocking=False
                )
            except Exception as e:
                logger.error(f"Error reading MAVLink packet: {e}")
                self.mav_connection.close()
                self.mav_connection = None
                continue
                
            if msg is None:
                await asyncio.sleep(0.01)
                continue
                
            self._process_message(msg)

    def _process_message(self, msg):
        msg_type = msg.get_type()
        sys_id = msg.get_srcSystem()
        drone_id = f"{self.drone_id_prefix}{sys_id}"
        
        if drone_id not in self.drone_states:
            self.drone_states[drone_id] = {
                "battery": 100.0,
                "flight_mode": "UNKNOWN",
                "armed_status": False,
                "satellites": 0
            }
        
        state = self.drone_states[drone_id]
        
        if msg_type == "HEARTBEAT":
            # Determine armed status (MAV_MODE_FLAG_SAFETY_ARMED is 128)
            state["armed_status"] = (msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED) != 0
            # Custom mode represents flight mode
            state["flight_mode"] = str(msg.custom_mode)
            
        elif msg_type == "SYS_STATUS":
            # battery_remaining is -1 if invalid, else 0-100
            if msg.battery_remaining != -1:
                state["battery"] = float(msg.battery_remaining)
                
        elif msg_type == "GPS_RAW_INT":
            if msg.satellites_visible != 255:
                state["satellites"] = msg.satellites_visible
        
        elif msg_type == "GLOBAL_POSITION_INT":
            self.packet_sequence += 1
            
            lat = msg.lat / 1e7
            lon = msg.lon / 1e7
            alt = msg.relative_alt / 1000.0
            
            vx = msg.vx / 100.0
            vy = msg.vy / 100.0
            speed = ((vx**2) + (vy**2)) ** 0.5
            heading = msg.hdg / 100.0 if msg.hdg != 65535 else 0.0

            packet_data = {
                "drone_id": drone_id,
                "latitude": lat,
                "longitude": lon,
                "altitude": alt,
                "speed": speed,
                "heading": heading,
                "battery": state["battery"],
                "flight_mode": state["flight_mode"],
                "armed_status": state["armed_status"],
                "satellites": state["satellites"],
                "packet_sequence": self.packet_sequence
            }
            
            self._ingest_packet(packet_data)

    def _ingest_packet(self, packet_data: dict):
        try:
            # Validate via Pydantic
            packet = schemas.TelemetryPacket(**packet_data)
        except Exception as e:
            logger.error(f"Invalid packet received from MAVLink: {e}")
            return
            
        organization_id = settings.MAVLINK_ORGANIZATION_ID
        if organization_id is None:
            # start() refuses to run without this, so reaching here means the
            # setting changed underneath us.
            logger.error("MAVLINK_ORGANIZATION_ID is not set; dropping packet.")
            return

        db = SessionLocal()
        try:
            processed_data = telemetry_service.process_telemetry(
                packet, db, organization_id=organization_id
            )
            asyncio.create_task(ws_manager.broadcast(processed_data, organization_id))
        except Exception as e:
            logger.error(f"Failed to ingest MAVLink packet: {e}")
        finally:
            db.close()


mavlink_receiver = MavlinkReceiver()
