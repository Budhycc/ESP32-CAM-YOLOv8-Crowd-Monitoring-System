import asyncio
import cv2
import numpy as np
import websockets
import time
import argparse
import logging
import socket

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] MultiSim: %(message)s")
logger = logging.getLogger("MultiSim")

latest_frame = None

def create_synthetic_frame(person_count: int = 3):
    """Generates a synthetic frame with specified number of dummy human figures."""
    h, w = 480, 640
    frame = np.full((h, w, 3), (240, 240, 240), dtype=np.uint8)

    cv2.putText(frame, "MULTI-CAM SIMULATOR", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (50, 50, 50), 2)
    cv2.line(frame, (0, 50), (w, 50), (100, 100, 100), 2)

    for i in range(person_count):
        cx = 100 + (i * 120) % (w - 100)
        cy = 200 + ((i * 50) % 150)
        cv2.circle(frame, (cx, cy), 25, (50, 50, 200), -1)
        cv2.rectangle(frame, (cx - 20, cy + 25), (cx + 20, cy + 120), (200, 50, 50), -1)
    cv2.putText(frame, f"Person {i+1}", (cx - 30, cy - 35), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

    return frame

async def frame_producer(mode: str, fps: int):
    """Reads from webcam or synthetic generator and updates the global latest_frame."""
    global latest_frame
    cap = None
    if mode == "webcam":
        logger.info("Opening webcam device (index 0)...")
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            logger.warning("Could not open webcam. Falling back to synthetic image mode.")
            mode = "synthetic"

    delay = 1.0 / fps
    frame_num = 0

    try:
        while True:
            frame_num += 1
            if mode == "webcam" and cap and cap.isOpened():
                # For cv2.read() in async, it might block the event loop slightly,
                # but for simulator purposes at low FPS this is generally acceptable.
                ret, frame = cap.read()
                if not ret:
                    logger.error("Failed to read webcam frame.")
                    await asyncio.sleep(delay)
                    continue
                latest_frame = frame
            else:
                test_counts = [2, 6, 15, 25]
                count_idx = (frame_num // 30) % len(test_counts)
                num_people = test_counts[count_idx]
                latest_frame = create_synthetic_frame(num_people)

            await asyncio.sleep(delay)
    except asyncio.CancelledError:
        pass
    finally:
        if cap:
            cap.release()

async def run_camera(server_url: str, esp32_id: str, fps: int):
    """Connects a single camera to the server and sends the latest_frame."""
    global latest_frame
    current_resolution = (640, 480)
    
    full_url = f"{server_url}/ws/esp32/{esp32_id}"
    
    try:
        async with websockets.connect(full_url) as websocket:
            logger.info(f"[{esp32_id}] Connected to server!")
            frame_num = 0
            
            state = {"is_sleeping": False, "delay": 1.0 / fps if fps > 0 else 0.01}
            
            async def receiver():
                nonlocal current_resolution
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
                                logger.info(f"[{esp32_id}] Resolution changed to {res} {current_resolution}")
                            elif message.startswith("SET_FPS:"):
                                try:
                                    f_val = int(message.split(":")[1].strip())
                                    if f_val <= 0:
                                        state["delay"] = 0.01
                                        logger.info(f"[{esp32_id}] FPS changed to Dynamic / Max")
                                    else:
                                        state["delay"] = 1.0 / f_val
                                        logger.info(f"[{esp32_id}] FPS changed to {f_val} FPS")
                                except Exception:
                                    pass
                            elif message == "SLEEP":
                                logger.info(f"[{esp32_id}] Received SLEEP command. Entering STANDBY mode.")
                                state["is_sleeping"] = True
                except Exception:
                    pass

            asyncio.create_task(receiver())
            
            while True:
                if state["is_sleeping"]:
                    logger.info(f"[{esp32_id}] Sleeping. Waking up in 10 seconds (Simulating PIR motion)...")
                    await asyncio.sleep(10)
                    state["is_sleeping"] = False
                    logger.info(f"[{esp32_id}] Simulated PIR WAKEUP! Resuming stream.")
                    continue

                if latest_frame is not None:
                    resized = cv2.resize(latest_frame, current_resolution)
                    _, encoded = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, 75])
                    await websocket.send(encoded.tobytes())
                    frame_num += 1
                    if frame_num % 50 == 0:
                        logger.info(f"[{esp32_id}] Sent {frame_num} frames")
                await asyncio.sleep(state["delay"])
                
    except ConnectionRefusedError:
        logger.error(f"[{esp32_id}] Connection refused at {full_url}")
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"[{esp32_id}] Connection closed by server.")
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"[{esp32_id}] Error: {e}")

async def run_multi_simulator(base_url: str, count: int, mode: str, fps: int):
    if base_url.lower() == "auto":
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
                base_url = f"ws://{addr[0]}:{port}"
                logger.info(f"Auto-discovered base server at {base_url}")
        except socket.timeout:
            logger.error("Auto-discovery timed out. Please specify --url manually.")
            return
        finally:
            sock.close()

    if base_url.lower() == "auto":
        return

    logger.info(f"Starting Multi-Camera Simulator with {count} cameras at {base_url}")

    tasks = []
    # 1. Start the frame producer (webcam / synthetic)
    tasks.append(asyncio.create_task(frame_producer(mode, fps)))
    
    # 2. Start the individual camera clients
    for i in range(1, count + 1):
        camera_id = f"MultiCam_{i}"
        tasks.append(asyncio.create_task(run_camera(base_url, camera_id, fps)))

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        for task in tasks:
            task.cancel()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi ESP32-CAM WebSocket Simulator")
    parser.add_argument("--url", type=str, default="auto", help="Base WebSocket URL (e.g., ws://localhost:8765) or 'auto'")
    parser.add_argument("--count", type=int, default=3, help="Number of cameras to simulate")
    parser.add_argument("--mode", type=str, choices=["synthetic", "webcam"], default="webcam", help="Stream source mode")
    parser.add_argument("--fps", type=int, default=25, help="Frames per second")

    args = parser.parse_args()
    
    try:
        asyncio.run(run_multi_simulator(args.url, args.count, args.mode, args.fps))
    except KeyboardInterrupt:
        print("\nMulti Simulator stopped.")
