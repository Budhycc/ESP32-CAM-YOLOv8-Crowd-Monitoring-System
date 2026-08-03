import asyncio
import json
import base64
import logging
import datetime
import websockets
from config import HOST, PORT, CAMERA_ID, ROOM_CAPACITY
from database import init_db, save_detection, get_recent_logs, get_latest_log
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

# Initialize YOLOv8 Object Detector
detector = None

async def broadcast_to_dashboards(data_payload: dict):
    """Broadcasts metadata and annotated frame to all connected Web Dashboard clients."""
    if not dashboard_clients:
        return

    message = json.dumps(data_payload)
    disconnected = set()

    for client in dashboard_clients:
        try:
            await client.send(message)
        except websockets.exceptions.ConnectionClosed:
            disconnected.add(client)
        except Exception as e:
            logger.error(f"Error broadcasting to client: {e}")
            disconnected.add(client)

    # Clean up disconnected clients
    for client in disconnected:
        dashboard_clients.discard(client)

async def handle_esp32_client(websocket):
    """Handles incoming JPEG frames from ESP32-CAM over WebSocket."""
    logger.info("ESP32-CAM connected to server.")
    frame_counter = 0

    try:
        async for message in websocket:
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
            # 1. Run YOLOv8 detection
            person_count, avg_conf, persons, annotated_jpeg = detector.process_frame(
                image_bytes, 
                draw_overlay=True
            )

            # 2. Perform Crowd Density Classification
            classification = classify_crowd(person_count, ROOM_CAPACITY)
            crowd_status = classification["status"]

            # Re-process frame with updated crowd status banner if needed
            # (or detector can use the status directly)

            # 3. Save detection record to SQLite database
            save_detection(
                kamera_id=CAMERA_ID,
                jumlah_orang=person_count,
                status_keramaian=crowd_status,
                confidence_rata2=avg_conf
            )

            # 4. Prepare data payload for Web Dashboard
            timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            annotated_b64 = base64.b64encode(annotated_jpeg).decode('utf-8') if annotated_jpeg else ""

            payload = {
                "type": "detection_update",
                "frame_id": frame_counter,
                "waktu": timestamp_str,
                "kamera_id": CAMERA_ID,
                "jumlah_orang": person_count,
                "kapasitas": ROOM_CAPACITY,
                "persentase": classification["persentase"],
                "status": crowd_status,
                "confidence_rata2": round(avg_conf, 2),
                "deteksi_detail": persons,
                "frame_b64": annotated_b64
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
        logger.info("ESP32-CAM streaming session ended.")

async def handle_dashboard_client(websocket):
    """Handles Web Dashboard client connection and real-time streaming."""
    logger.info("Web Dashboard client connected.")
    dashboard_clients.add(websocket)

    try:
        # Send latest detection log & history upon connection
        latest_log = get_latest_log()
        recent_history = get_recent_logs(limit=20)
        
        init_payload = {
            "type": "init_state",
            "kamera_id": CAMERA_ID,
            "kapasitas": ROOM_CAPACITY,
            "latest": latest_log,
            "history": recent_history
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
    req_path = getattr(websocket, 'path', path) or '/'
    logger.info(f"Incoming WebSocket connection on path: '{req_path}'")

    if req_path.startswith("/ws/dashboard"):
        await handle_dashboard_client(websocket)
    else:
        # Default or /ws/esp32 handles ESP32-CAM node
        await handle_esp32_client(websocket)

async def main():
    global detector

    # Initialize Database Schema
    logger.info("Step 1: Initializing Database...")
    init_db()

    # Load YOLOv8 Model
    logger.info("Step 2: Loading YOLOv8 Object Detection Model...")
    detector = ObjectDetector()

    # Start WebSocket Server
    logger.info(f"Step 3: Starting WebSocket Server on ws://{HOST}:{PORT}...")
    async with websockets.serve(connection_router, HOST, PORT):
        logger.info(f"Server is RUNNING and listening on ws://{HOST}:{PORT}")
        logger.info(f"- ESP32-CAM endpoint: ws://<SERVER_IP>:{PORT}/ws/esp32")
        logger.info(f"- Dashboard endpoint: ws://<SERVER_IP>:{PORT}/ws/dashboard")
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user (KeyboardInterrupt).")
