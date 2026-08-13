import asyncio
import cv2
import numpy as np
import websockets
import time
import argparse
import logging
import socket

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] Simulator: %(message)s")
logger = logging.getLogger("ESP32Simulator")

current_resolution = (640, 480)

def create_synthetic_frame(person_count: int = 3, resolution=(640, 480)):
    """Generates a synthetic frame with specified number of dummy human figures for testing."""
    w, h = resolution
    frame = np.full((h, w, 3), (240, 240, 240), dtype=np.uint8)

    # Draw room background
    cv2.putText(frame, "SIMULATED ESP32-CAM FEED", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (50, 50, 50), 2)
    cv2.line(frame, (0, 50), (w, 50), (100, 100, 100), 2)

    # Draw dummy person shapes
    for i in range(person_count):
        cx = 100 + (i * 120) % (w - 100)
        cy = 200 + ((i * 50) % 150)

        # Draw head
        cv2.circle(frame, (cx, cy), 25, (50, 50, 200), -1)
        # Draw body
        cv2.rectangle(frame, (cx - 20, cy + 25), (cx + 20, cy + 120), (200, 50, 50), -1)
        # Draw label
        cv2.putText(frame, f"Person {i+1}", (cx - 30, cy - 35), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

    # Encode to JPEG
    _, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return encoded.tobytes()

async def run_simulator(server_url: str, esp32_id: str, mode: str, fps: int = 5):
    """Connects to WebSocket server and streams simulated JPEG frames."""
    if server_url.lower() == "auto":
        logger.info("Listening for UDP Auto-Discovery on port 9876 (timeout 15s)...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", 9876))
        sock.settimeout(15.0)
        try:
            data, addr = sock.recvfrom(1024)
            msg = data.decode('utf-8')
            if msg.startswith("YOLOV8_SERVER_ANNOUNCE:"):
                port = msg.split(":")[1]
                server_url = f"ws://{addr[0]}:{port}/ws/esp32/{esp32_id}"
                logger.info(f"Auto-discovered server at {server_url}")
        except socket.timeout:
            logger.error("Auto-discovery timed out. Please specify --url manually.")
            return
        finally:
            sock.close()
    
    logger.info(f"Connecting to ESP32-CAM server at: {server_url}")

    cap = None
    if mode == "webcam":
        logger.info("Opening webcam device (index 0)...")
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            logger.warning("Could not open webcam. Falling back to synthetic image mode.")
            mode = "synthetic"

    state = {"is_sleeping": False, "delay": 1.0 / fps}

    try:
        async with websockets.connect(server_url) as websocket:
            logger.info("Connected successfully! Starting stream...")
            frame_num = 0

            async def receiver():
                global current_resolution
                try:
                    async for message in websocket:
                        if isinstance(message, str):
                            if message.startswith("SET_RESOLUTION:"):
                                res = message.split(":")[1].strip()
                                if res == "QVGA": current_resolution = (320, 240)
                                elif res == "VGA": current_resolution = (640, 480)
                                elif res == "SVGA": current_resolution = (800, 600)
                                elif res == "XGA": current_resolution = (1024, 768)
                                elif res == "HD": current_resolution = (1280, 720)
                                logger.info(f"Simulator resolution changed to {res} {current_resolution}")
                            elif message.startswith("SET_FPS:"):
                                try:
                                    f_val = int(message.split(":")[1].strip())
                                    if f_val <= 0:
                                        state["delay"] = 0.01
                                        logger.info("Simulator FPS changed to Dynamic / Max")
                                    else:
                                        state["delay"] = 1.0 / f_val
                                        logger.info(f"Simulator FPS changed to {f_val} FPS (delay={state['delay']:.3f}s)")
                                except Exception:
                                    pass
                            elif message == "SLEEP":
                                logger.info("Received SLEEP command. Simulator entering STANDBY mode.")
                                state["is_sleeping"] = True
                except Exception:
                    pass

            asyncio.create_task(receiver())

            while True:
                if state["is_sleeping"]:
                    logger.info("Simulator is sleeping. Waking up in 10 seconds (Simulating PIR motion)...")
                    await asyncio.sleep(10)
                    state["is_sleeping"] = False
                    logger.info("Simulated PIR WAKEUP! Resuming stream.")
                    continue

                frame_num += 1

                if mode == "webcam" and cap and cap.isOpened():
                    ret, frame = cap.read()
                    if not ret:
                        logger.error("Failed to read webcam frame.")
                        break
                    frame = cv2.resize(frame, current_resolution)
                    _, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                    jpeg_bytes = encoded.tobytes()
                else:
                    # Synthetic mode: cycle between 1, 5, 12, 25 people every 20 frames to test classification
                    test_counts = [2, 6, 15, 25]
                    count_idx = (frame_num // 30) % len(test_counts)
                    num_people = test_counts[count_idx]
                    jpeg_bytes = create_synthetic_frame(num_people, current_resolution)

                # Send binary JPEG frame over WebSocket
                await websocket.send(jpeg_bytes)
                logger.info(f"Sent frame #{frame_num} ({len(jpeg_bytes)} bytes)")

                await asyncio.sleep(state["delay"])

    except ConnectionRefusedError:
        logger.error(f"Could not connect to server at {server_url}. Is main.py running?")
    except websockets.exceptions.ConnectionClosed:
        logger.info("Connection closed by server.")
    except Exception as e:
        logger.error(f"Simulator error: {e}")
    finally:
        if cap:
            cap.release()
        logger.info("Simulator stopped.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ESP32-CAM WebSocket Simulator")
    parser.add_argument("--url", type=str, default="auto", help="Server WebSocket URL or 'auto' for UDP discovery")
    parser.add_argument("--id", type=str, default="Sim_Camera", help="Hardware ID for this simulator (used in auto-discovery)")
    parser.add_argument("--mode", type=str, choices=["synthetic", "webcam"], default="synthetic", help="Stream source mode")
    parser.add_argument("--fps", type=int, default=25, help="Frames per second")

    args = parser.parse_args()
    asyncio.run(run_simulator(args.url, args.id, args.mode, args.fps))
