import asyncio
import json
import base64
import logging
import datetime
import threading
import http.server
import socketserver
import os
import socket
import time
import websockets
from config import HOST, PORT, DEFAULT_CAPACITY
from database import init_db, save_detection, get_recent_logs, get_latest_log, get_all_rooms, get_room_capacity, upsert_room, delete_room, get_room_by_esp32, rename_room
from classifier import classify_crowd
from detector import ObjectDetector

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ServerMain")

# Global Connected Dashboard Clients Set
# Global Connected Dashboard Clients Set
dashboard_clients = set()
active_esps = set()
active_rooms_cache = []

# Initialize YOLOv8 Object Detector
detector = None

def start_http_server():
    """Runs a local HTTP server for the Web Dashboard in a background thread."""
    web_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../dashboard'))
    try:
        os.chdir(web_dir)
    except FileNotFoundError:
        logger.error(f"Dashboard directory not found at {web_dir}")
        return
        
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            pass # Suppress HTTP logs to keep terminal clean
            
    try:
        # Allow port reuse just in case
        socketserver.TCPServer.allow_reuse_address = True
        httpd = socketserver.TCPServer(("", 8000), QuietHandler)
        httpd.serve_forever()
    except Exception as e:
        logger.error(f"HTTP Server failed to start: {e}")

async def broadcast_to_dashboards(data_payload: dict):
    """Broadcasts metadata and annotated frame to all connected Web Dashboard clients."""
    if not dashboard_clients:
        return

    message = json.dumps(data_payload)
    disconnected = set()

    async def send_to_client(client):
        try:
            # Add a timeout so a slow client doesn't block the broadcast
            await asyncio.wait_for(client.send(message), timeout=1.0)
        except (websockets.exceptions.ConnectionClosed, asyncio.TimeoutError):
            disconnected.add(client)
        except Exception as e:
            logger.error(f"Error broadcasting to client: {e}")
            disconnected.add(client)

    # Run all sends concurrently
    if dashboard_clients:
        await asyncio.gather(*(send_to_client(client) for client in list(dashboard_clients)))

    # Clean up disconnected or slow clients
    for client in disconnected:
        try:
            await client.close()
        except:
            pass
        dashboard_clients.discard(client)

async def handle_esp32_client(websocket, esp32_id):
    """Handles incoming JPEG frames from ESP32-CAM over WebSocket."""
    global active_rooms_cache
    logger.info(f"ESP32-CAM (Hardware ID: {esp32_id}) connected to server.")
    frame_counter = 0
    
    active_esps.add(esp32_id)
    await broadcast_to_dashboards({
        "type": "active_esps_update",
        "active_esps": list(active_esps)
    })

    try:
        async for message in websocket:
            room_info = next((r for r in active_rooms_cache if r.get('esp32_id') == esp32_id), None)
            if room_info:
                current_camera_id = room_info['room_id']
                current_capacity = room_info['capacity']
            else:
                current_camera_id = f"Unassigned ({esp32_id})"
                current_capacity = DEFAULT_CAPACITY

            frame_counter += 1
            
            # ESP32-CAM sends binary JPEG data
            if isinstance(message, bytes):
                image_bytes = message
            else:
                # If frame is sent as base64 string
                try:
                    image_bytes = base64.b64decode(message)
                except Exception:
                    logger.warning("Received invalid text data from ESP32-CAM, expected binary JPEG or base64.")
                    continue

            # First perform preliminary classification to get crowd status for frame header
            # 1. Run YOLOv8 detection in a separate thread to prevent blocking the asyncio event loop
            loop = asyncio.get_running_loop()
            person_count, avg_conf, persons, annotated_jpeg, latency_ms = await loop.run_in_executor(
                None,
                lambda: detector.process_frame(image_bytes, draw_overlay=True)
            )

            # 2. Perform Crowd Density Classification
            classification = classify_crowd(person_count, current_capacity)
            crowd_status = classification["status"]

            # Re-process frame with updated crowd status banner if needed
            # (or detector can use the status directly)

            # 3. Save detection record to SQLite database
            await loop.run_in_executor(
                None,
                lambda: save_detection(
                    kamera_id=current_camera_id,
                    jumlah_orang=person_count,
                    status_keramaian=crowd_status,
                    confidence_rata2=avg_conf
                )
            )

            # 4. Prepare data payload for Web Dashboard
            timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            annotated_b64 = base64.b64encode(annotated_jpeg).decode('utf-8') if annotated_jpeg else ""

            payload = {
                "type": "detection_update",
                "frame_id": frame_counter,
                "waktu": timestamp_str,
                "kamera_id": current_camera_id,
                "jumlah_orang": person_count,
                "kapasitas": current_capacity,
                "persentase": classification["persentase"],
                "status": crowd_status,
                "confidence_rata2": round(avg_conf, 2),
                "deteksi_detail": persons,
                "frame_b64": annotated_b64,
                "latensi": round(latency_ms, 1)
            }

            # 5. Broadcast real-time update to all active Web Dashboards
            await broadcast_to_dashboards(payload)

    except websockets.exceptions.ConnectionClosedError:
        logger.info("ESP32-CAM connection closed unexpectedly.")
    except websockets.exceptions.ConnectionClosedOK:
        logger.info("ESP32-CAM disconnected gracefully.")
    except Exception as e:
        logger.error(f"Error handling ESP32-CAM stream: {e}", exc_info=True)
    finally:
        active_esps.discard(esp32_id)
        await broadcast_to_dashboards({
            "type": "active_esps_update",
            "active_esps": list(active_esps)
        })
        logger.info("ESP32-CAM streaming session ended.")

async def handle_dashboard_client(websocket):
    """Handles Web Dashboard client connection and real-time streaming."""
    global active_rooms_cache
    logger.info("Web Dashboard client connected.")
    dashboard_clients.add(websocket)

    try:
        # Send latest detection log & history upon connection
        latest_log = get_latest_log()
        recent_history = get_recent_logs(limit=20)
        
        if not active_rooms_cache:
            active_rooms_cache = get_all_rooms()
            
        init_payload = {
            "type": "init_state",
            "rooms": active_rooms_cache,
            "device": getattr(detector, 'device', 'UNKNOWN'),
            "latest": latest_log,
            "history": recent_history,
            "active_esps": list(active_esps)
        }
        await websocket.send(json.dumps(init_payload))

        # Listen for dashboard commands (e.g., history requests, ping/pong)
        async for message in websocket:
            try:
                req = json.loads(message)
                if req.get("action") == "get_history":
                    limit = req.get("limit", 50)
                    history = get_recent_logs(limit=limit)
                    await websocket.send(json.dumps({
                        "type": "history_response",
                        "history": history
                    }))
                elif req.get("action") == "add_room":
                    room_id = req.get("room_id")
                    old_room_id = req.get("old_room_id")
                    capacity = int(req.get("capacity", DEFAULT_CAPACITY))
                    esp32_id = req.get("esp32_id")
                    if room_id:
                        if old_room_id and old_room_id != room_id:
                            rename_room(old_room_id, room_id)
                        upsert_room(room_id, capacity, esp32_id)
                        active_rooms_cache = get_all_rooms()
                        await broadcast_to_dashboards({
                            "type": "room_config_update",
                            "rooms": active_rooms_cache
                        })
                elif req.get("action") == "delete_room":
                    room_id = req.get("room_id")
                    if room_id:
                        delete_room(room_id)
                        active_rooms_cache = get_all_rooms()
                        await broadcast_to_dashboards({
                            "type": "room_config_update",
                            "rooms": active_rooms_cache
                        })
            except Exception as e:
                logger.error(f"Error parsing dashboard client request: {e}")

    except websockets.exceptions.ConnectionClosed:
        logger.info("Web Dashboard client disconnected.")
    finally:
        dashboard_clients.discard(websocket)

async def connection_router(websocket, path=None):
    """
    Routes WebSocket connections based on request URI path.
    - '/ws/esp32' or root '/' -> ESP32-CAM stream producer
    - '/ws/dashboard' -> Web Dashboard stream consumer
    """
    try:
        req_path = websocket.request.path
    except AttributeError:
        req_path = getattr(websocket, 'path', path) or '/'
        
    logger.info(f"Incoming WebSocket connection on path: '{req_path}'")

    if req_path.startswith("/ws/dashboard"):
        await handle_dashboard_client(websocket)
    else:
        # Default or /ws/esp32 handles ESP32-CAM node
        parts = req_path.split("/")
        esp32_id = parts[-1] if len(parts) > 3 else "Unknown"
        await handle_esp32_client(websocket, esp32_id)

async def main():
    global detector

    # Initialize Database Schema
    logger.info("Step 1: Initializing Database...")
    init_db()
    
    global active_rooms_cache
    active_rooms_cache = get_all_rooms()

    # Load YOLOv8 Model
    logger.info("Step 2: Loading YOLOv8 Object Detection Model...")
    detector = ObjectDetector()

    # Start WebSocket Server
    logger.info(f"Step 3: Starting WebSocket Server on ws://{HOST}:{PORT}...")
    
    # Start Web Dashboard Server (Localhost HTTP)
    logger.info(f"Step 4: Starting Web Dashboard Server at http://localhost:8000...")
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()

    # Start UDP Announcer for ESP32 Auto-Discovery
    def udp_announcer():
        UDP_PORT = 9876
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        message = f"YOLOV8_SERVER_ANNOUNCE:{PORT}".encode('utf-8')
        logger.info(f"Step 5: Starting UDP Auto-Discovery Broadcaster on port {UDP_PORT}...")
        while True:
            try:
                sock.sendto(message, ('<broadcast>', UDP_PORT))
                time.sleep(2)
            except Exception as e:
                logger.error(f"UDP Announce error: {e}")
                time.sleep(5)
                
    udp_thread = threading.Thread(target=udp_announcer, daemon=True)
    udp_thread.start()

    async with websockets.serve(connection_router, HOST, PORT):
        logger.info(f"Server is RUNNING and listening on ws://{HOST}:{PORT}")
        logger.info(f"- ESP32-CAM endpoint: ws://<SERVER_IP>:{PORT}/ws/esp32/<camera_id>")
        logger.info(f"- Dashboard endpoint: ws://<SERVER_IP>:{PORT}/ws/dashboard")
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user (KeyboardInterrupt).")
