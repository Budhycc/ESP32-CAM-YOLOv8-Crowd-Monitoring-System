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
from database import init_db, save_detection, get_recent_logs, get_latest_log, get_all_rooms, get_room_capacity, upsert_room, delete_room, get_room_by_esp32, rename_room, update_room_ui_settings
from classifier import classify_crowd
from detector import ObjectDetector

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ServerMain")

# Global Connected Dashboard Clients Set
dashboard_clients = set()
active_esps = set()
esp32_websockets = {}
# Room cache sebagai dict {esp32_id: room_info} untuk lookup O(1) per frame
# vs list dengan linear search O(n) sebelumnya
active_rooms_cache = {}  # keyed by esp32_id

# Initialize YOLOv8 Object Detector
detector = None

# Global Flag for CLAHE Activation (Skenario S5)
# Removed globals in favor of per-room settings

def _build_rooms_cache(rooms_list: list) -> dict:
    """Konversi list rooms dari DB menjadi dict {esp32_id: room_info} untuk O(1) lookup."""
    return {r['esp32_id']: r for r in rooms_list if r.get('esp32_id')}

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
    last_person_time = time.time()
    last_frame_time = time.time()
    
    active_esps.add(esp32_id)
    esp32_websockets[esp32_id] = websocket
    
    # Apply saved resolution & FPS from database immediately (Default FPS = 0 for Dynamic/Max speed)
    room_info = active_rooms_cache.get(esp32_id)
    target_fps = room_info.get('fps', 0) if (room_info and room_info.get('fps') is not None) else 0
    try:
        await websocket.send(f"SET_FPS:{target_fps}")
        logger.info(f"Sent initial FPS setting ({target_fps}) to {esp32_id}")
    except Exception as e:
        logger.error(f"Failed to send initial FPS to {esp32_id}: {e}")

    if room_info and room_info.get('resolution') and room_info.get('resolution') != 'VGA':
        try:
            await websocket.send(f"SET_RESOLUTION:{room_info['resolution']}")
        except Exception as e:
            logger.error(f"Failed to send initial resolution to {esp32_id}: {e}")

    await broadcast_to_dashboards({
        "type": "active_esps_update",
        "active_esps": list(active_esps)
    })

    # Decoupled Non-Blocking Frame Processing Pipeline (Zero Latency & No Backpressure)
    latest_frame = None
    frame_event = asyncio.Event()
    is_active = True
    # Throttle timers per kamera
    last_save_time = 0.0       # DB write throttle: max 1x/detik
    last_broadcast_time = 0.0  # Dashboard frame throttle: max 5 FPS (0.2s interval)

    async def frame_processor():
        nonlocal latest_frame, frame_counter, last_person_time, last_frame_time
        nonlocal last_save_time, last_broadcast_time
        loop = asyncio.get_running_loop()
        
        while is_active:
            await frame_event.wait()
            frame_event.clear()
            
            if latest_frame is None:
                continue
                
            raw_msg = latest_frame
            latest_frame = None
            
            now = time.time()
            if now - last_frame_time > 5.0:
                # Kamera baru bangun dari mode sleep
                last_person_time = now
            last_frame_time = now

            # O(1) lookup via dict (vs O(n) linear search sebelumnya)
            room_info = active_rooms_cache.get(esp32_id)
            if room_info:
                current_camera_id = room_info['room_id']
                current_capacity = room_info['capacity']
                use_clahe = bool(room_info.get('use_clahe', 0))
                use_frame_avg = bool(room_info.get('use_frame_avg', 0))
                use_adaptive_conf = bool(room_info.get('use_adaptive_conf', 0))
            else:
                current_camera_id = f"Unassigned ({esp32_id})"
                current_capacity = DEFAULT_CAPACITY
                use_clahe = False
                use_frame_avg = False
                use_adaptive_conf = False

            frame_counter += 1
            
            # ESP32-CAM sends binary JPEG data
            if isinstance(raw_msg, bytes):
                image_bytes = raw_msg
            else:
                # If frame is sent as base64 string
                try:
                    image_bytes = base64.b64decode(raw_msg)
                except Exception:
                    logger.warning("Received invalid text data from ESP32-CAM, expected binary JPEG or base64.")
                    continue

            # Run YOLOv8 detection in executor thread
            # Gunakan executor dedicated milik detector (ThreadPoolExecutor max_workers=4)
            person_count, avg_conf, persons, annotated_jpeg, latency_ms = await loop.run_in_executor(
                detector.executor,
                lambda: detector.process_frame(
                    image_bytes, 
                    draw_overlay=True, 
                    use_clahe=use_clahe,
                    camera_id=esp32_id,
                    use_frame_averaging=use_frame_avg,
                    use_adaptive_confidence=use_adaptive_conf
                )
            )

            # Perform Crowd Density Classification
            classification = classify_crowd(person_count, current_capacity)
            crowd_status = classification["status"]

            # Smart-Streaming Logic
            if person_count > 0:
                last_person_time = now
                
            if person_count == 0 and (now - last_person_time > 15.0):
                logger.info(f"Kamera {current_camera_id} tidak melihat orang selama 15 detik. Mengirim perintah SLEEP.")
                try:
                    await websocket.send("SLEEP")
                    await broadcast_to_dashboards({
                        "type": "camera_sleep",
                        "kamera_id": current_camera_id
                    })
                except Exception as e:
                    logger.error(f"Gagal mengirim SLEEP: {e}")
                last_person_time = now # reset timer agar tidak spam

            # Save detection record to SQLite database
            # THROTTLE: max 1 write/detik per kamera agar tidak storm disk I/O
            # (sebelumnya bisa 25+ write/detik di mode max FPS)
            if now - last_save_time >= 1.0:
                last_save_time = now
                # Capture nilai untuk lambda closure (hindari late-binding bug)
                _camera_id = current_camera_id
                _person_count = person_count
                _crowd_status = crowd_status
                _avg_conf = avg_conf
                await loop.run_in_executor(
                    None,
                    lambda: save_detection(
                        kamera_id=_camera_id,
                        jumlah_orang=_person_count,
                        status_keramaian=_crowd_status,
                        confidence_rata2=_avg_conf
                    )
                )

            # Prepare data payload for Web Dashboard
            timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # THROTTLE frame_b64 ke dashboard: max 5 FPS (interval 0.2 detik)
            # Metadata (count, status) tetap dikirim setiap frame; hanya gambar yang di-throttle
            should_send_frame = (now - last_broadcast_time) >= 0.2
            if should_send_frame:
                last_broadcast_time = now
                annotated_b64 = base64.b64encode(annotated_jpeg).decode('utf-8') if annotated_jpeg else ""
            else:
                annotated_b64 = ""  # Kosong = dashboard gunakan frame terakhir yang ada

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

            # Broadcast real-time update ke semua Web Dashboard yang aktif
            await broadcast_to_dashboards(payload)

    processor_task = asyncio.create_task(frame_processor())

    try:
        async for message in websocket:
            latest_frame = message
            frame_event.set()

    except websockets.exceptions.ConnectionClosedError:
        logger.info("ESP32-CAM connection closed unexpectedly.")
    except websockets.exceptions.ConnectionClosedOK:
        logger.info("ESP32-CAM disconnected gracefully.")
    except Exception as e:
        logger.error(f"Error handling ESP32-CAM stream: {e}", exc_info=True)
    finally:
        is_active = False
        frame_event.set()
        processor_task.cancel()
        active_esps.discard(esp32_id)
        esp32_websockets.pop(esp32_id, None)
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
            rooms_list = get_all_rooms()
            active_rooms_cache = _build_rooms_cache(rooms_list)
        else:
            rooms_list = list(active_rooms_cache.values())
            
        init_payload = {
            "type": "init_state",
            "rooms": rooms_list,  # Dashboard tetap terima list untuk kompatibilitas frontend
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
                elif req.get("action") == "update_mitigation":
                    room_id = req.get("room_id")
                    if room_id:
                        room = next((r for r in active_rooms_cache.values() if r.get('room_id') == room_id), None)
                        if room:
                            update_room_ui_settings(
                                room_id,
                                use_clahe=req.get("clahe"),
                                use_frame_avg=req.get("frame_avg"),
                                use_adaptive_conf=req.get("adaptive_conf")
                            )
                            rooms_list = get_all_rooms()
                            active_rooms_cache = _build_rooms_cache(rooms_list)
                            logger.info(f"Room '{room_id}' mitigation settings updated.")
                elif req.get("action") == "add_room":
                    room_id = req.get("room_id")
                    old_room_id = req.get("old_room_id")
                    capacity = int(req.get("capacity", DEFAULT_CAPACITY))
                    esp32_id = req.get("esp32_id")
                    if room_id:
                        if old_room_id and old_room_id != room_id:
                            rename_room(old_room_id, room_id)
                        upsert_room(room_id, capacity, esp32_id)
                        rooms_list = get_all_rooms()
                        active_rooms_cache = _build_rooms_cache(rooms_list)
                        await broadcast_to_dashboards({
                            "type": "room_config_update",
                            "rooms": rooms_list
                        })
                elif req.get("action") == "delete_room":
                    room_id = req.get("room_id")
                    if room_id:
                        delete_room(room_id)
                        rooms_list = get_all_rooms()
                        active_rooms_cache = _build_rooms_cache(rooms_list)
                        await broadcast_to_dashboards({
                            "type": "room_config_update",
                            "rooms": rooms_list
                        })
                elif req.get("action") == "set_resolution":
                    esp32_id = req.get("esp32_id")
                    res = req.get("resolution")
                    room_id = req.get("room_id")
                    
                    if room_id:
                        # Cari room by room_id di dict values
                        room = next((r for r in active_rooms_cache.values() if r.get('room_id') == room_id), None)
                        if room:
                            update_room_ui_settings(room_id, res, room.get('show_bbox', 1))
                            rooms_list = get_all_rooms()
                            active_rooms_cache = _build_rooms_cache(rooms_list)

                    if esp32_id and esp32_id in esp32_websockets:
                        try:
                            await esp32_websockets[esp32_id].send(f"SET_RESOLUTION:{res}")
                            logger.info(f"Sent resolution {res} to {esp32_id}")
                        except Exception as e:
                            logger.error(f"Failed to send resolution: {e}")
                            
                elif req.get("action") == "set_fps":
                    esp32_id = req.get("esp32_id")
                    fps_val = req.get("fps", 2)
                    room_id = req.get("room_id")
                    
                    if room_id:
                        room = next((r for r in active_rooms_cache.values() if r.get('room_id') == room_id), None)
                        if room:
                            update_room_ui_settings(room_id, fps=fps_val)
                            rooms_list = get_all_rooms()
                            active_rooms_cache = _build_rooms_cache(rooms_list)

                    if esp32_id and esp32_id in esp32_websockets:
                        try:
                            await esp32_websockets[esp32_id].send(f"SET_FPS:{fps_val}")
                            logger.info(f"Sent target FPS {fps_val} to {esp32_id}")
                        except Exception as e:
                            logger.error(f"Failed to send FPS: {e}")
                            
                    await broadcast_to_dashboards({
                        "type": "room_config_update",
                        "rooms": list(active_rooms_cache.values())
                    })
                elif req.get("action") == "update_bbox":
                    room_id = req.get("room_id")
                    show_bbox = req.get("show_bbox")
                    if room_id:
                        room = next((r for r in active_rooms_cache.values() if r.get('room_id') == room_id), None)
                        if room:
                            update_room_ui_settings(room_id, show_bbox=show_bbox)
                            rooms_list = get_all_rooms()
                            active_rooms_cache = _build_rooms_cache(rooms_list)
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
    rooms_list = get_all_rooms()
    active_rooms_cache = _build_rooms_cache(rooms_list)
    logger.info(f"Loaded {len(active_rooms_cache)} rooms into cache (dict, O(1) lookup).")

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
