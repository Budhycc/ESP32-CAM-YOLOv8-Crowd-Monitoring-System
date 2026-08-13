import asyncio
import cv2
import numpy as np
import websockets
import time
import argparse
import logging
import socket
import threading

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] Simulator: %(message)s")
logger = logging.getLogger("ESP32Simulator")

# JPEG Quality sesuai hardware esp32cam.ino (jpeg_quality=20)
JPEG_QUALITY = 20


def create_synthetic_frame(person_count: int = 3, resolution=(640, 480)):
    """Membuat frame sintetis dengan figur manusia dummy."""
    w, h = resolution
    frame = np.full((h, w, 3), (240, 240, 240), dtype=np.uint8)

    cv2.putText(frame, "SIMULATED ESP32-CAM FEED", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (50, 50, 50), 2)
    cv2.line(frame, (0, 50), (w, 50), (100, 100, 100), 2)

    for i in range(person_count):
        cx = 100 + (i * 120) % (w - 100)
        cy = 200 + ((i * 50) % 150)
        cv2.circle(frame, (cx, cy), 25, (50, 50, 200), -1)
        cv2.rectangle(frame, (cx - 20, cy + 25), (cx + 20, cy + 120), (200, 50, 50), -1)
        cv2.putText(frame, f"Person {i+1}", (cx - 30, cy - 35), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

    ts = time.strftime("%H:%M:%S")
    cv2.putText(frame, ts, (w - 120, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (80, 80, 80), 1)

    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    return encoded.tobytes() if ok else b""


class WebcamReader:
    """
    Membaca frame webcam di thread terpisah agar tidak block async event loop.
    Thread blocking cv2.VideoCapture.read() tidak boleh dipanggil langsung dari coroutine.
    """

    def __init__(self):
        self._frame = None
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

    def get_frame(self):
        with self._lock:
            return self._frame

    def _read_loop(self, resolution: tuple):
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Selalu ambil frame terbaru
        if not cap.isOpened():
            logger.error("Could not open webcam.")
            return
        try:
            while self._running:
                ret, frame = cap.read()
                if ret:
                    w, h = resolution
                    resized = cv2.resize(frame, (w, h))
                    with self._lock:
                        self._frame = resized
                else:
                    time.sleep(0.05)
        finally:
            cap.release()

    def start(self, resolution=(640, 480)):
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, args=(resolution,), daemon=True)
        self._thread.start()
        logger.info("Webcam reader thread started.")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)


async def run_simulator(server_url: str, esp32_id: str, mode: str, fps: int = 10):
    """Koneksikan ke server WebSocket dan stream JPEG frames. Auto-reconnect jika putus."""

    # UDP Auto-Discovery
    if server_url.lower() == "auto":
        logger.info("Listening for UDP Auto-Discovery on port 9876 (timeout 15s)...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", 9876))
        sock.settimeout(15.0)
        base_url = None
        try:
            data, addr = sock.recvfrom(1024)
            msg = data.decode('utf-8')
            if msg.startswith("YOLOV8_SERVER_ANNOUNCE:"):
                port = msg.split(":")[1]
                base_url = f"ws://{addr[0]}:{port}"
                logger.info(f"Auto-discovered server at {base_url}")
        except socket.timeout:
            logger.error("Auto-discovery timed out. Use --url ws://<IP>:8765 manually.")
            return
        finally:
            sock.close()
        if not base_url:
            return
        server_url = f"{base_url}/ws/esp32/{esp32_id}"
    elif not server_url.startswith("ws://") and not server_url.startswith("wss://"):
        logger.error("Invalid URL. Use ws://<IP>:<PORT>/ws/esp32/<ID> format.")
        return

    logger.info(f"Connecting to: {server_url}")
    logger.info(f"Mode: {mode} | FPS: {fps} | JPEG Quality: {JPEG_QUALITY}")

    # Siapkan webcam reader di thread terpisah (jika mode webcam)
    webcam = None
    if mode == "webcam":
        webcam = WebcamReader()
        webcam.start()
        # Tunggu frame pertama
        for _ in range(30):
            if webcam.get_frame() is not None:
                break
            await asyncio.sleep(0.1)
        if webcam.get_frame() is None:
            logger.warning("Webcam not available. Falling back to synthetic mode.")
            webcam.stop()
            webcam = None
            mode = "synthetic"

    try:
        while True:  # Loop reconnect otomatis
            try:
                async with websockets.connect(
                    server_url,
                    ping_interval=20,
                    ping_timeout=10,
                    max_size=5 * 1024 * 1024
                ) as websocket:
                    logger.info("Connected! Starting stream...")
                    frame_num = 0
                    current_resolution = (640, 480)

                    state = {
                        "is_sleeping": False,
                        "delay": 1.0 / fps if fps > 0 else 0.01,
                    }

                    async def receiver():
                        nonlocal current_resolution
                        try:
                            async for message in websocket:
                                if not isinstance(message, str):
                                    continue
                                if message.startswith("SET_RESOLUTION:"):
                                    res = message.split(":")[1].strip().upper()
                                    res_map = {
                                        "QVGA": (320, 240),
                                        "VGA":  (640, 480),
                                        "SVGA": (800, 600),
                                        "XGA":  (1024, 768),
                                        "HD":   (1280, 720),
                                    }
                                    if res in res_map:
                                        current_resolution = res_map[res]
                                        logger.info(f"Resolution -> {res} {current_resolution}")
                                        if webcam:
                                            webcam.stop()
                                            webcam.start(current_resolution)
                                elif message.startswith("SET_FPS:"):
                                    try:
                                        f_val = int(message.split(":")[1].strip())
                                        state["delay"] = (1.0 / f_val) if f_val > 0 else 0.01
                                        label = f"{f_val} FPS" if f_val > 0 else "Dynamic/Max"
                                        logger.info(f"FPS -> {label}")
                                    except (ValueError, ZeroDivisionError):
                                        pass
                                elif message == "SLEEP":
                                    logger.info("SLEEP received. Entering standby mode.")
                                    state["is_sleeping"] = True
                        except (websockets.exceptions.ConnectionClosed, asyncio.CancelledError):
                            pass
                        except Exception as e:
                            logger.debug(f"Receiver error: {e}")

                    recv_task = asyncio.create_task(receiver())

                    try:
                        while True:
                            if state["is_sleeping"]:
                                logger.info("Standby. Simulating PIR wakeup in 10s...")
                                await asyncio.sleep(10)
                                state["is_sleeping"] = False
                                logger.info("PIR WAKEUP - resuming stream.")
                                continue

                            frame_num += 1

                            if webcam:
                                # Webcam: baca dari thread buffer (non-blocking)
                                raw_frame = webcam.get_frame()
                                if raw_frame is not None:
                                    w, h = current_resolution
                                    resized = cv2.resize(raw_frame, (w, h))
                                    ok, encoded = cv2.imencode(
                                        ".jpg", resized,
                                        [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
                                    )
                                    jpeg_bytes = encoded.tobytes() if ok else b""
                                else:
                                    await asyncio.sleep(0.05)
                                    continue
                            else:
                                # Synthetic: cycle jumlah orang
                                test_counts = [2, 6, 15, 25]
                                count_idx = (frame_num // 30) % len(test_counts)
                                jpeg_bytes = create_synthetic_frame(test_counts[count_idx], current_resolution)

                            if jpeg_bytes:
                                await websocket.send(jpeg_bytes)
                                if frame_num % 50 == 0:
                                    size_kb = len(jpeg_bytes) / 1024
                                    logger.info(f"Frame #{frame_num} | {size_kb:.1f} KB | res={current_resolution}")

                            await asyncio.sleep(state["delay"])

                    finally:
                        recv_task.cancel()
                        try:
                            await recv_task
                        except asyncio.CancelledError:
                            pass

            except (ConnectionRefusedError, OSError) as e:
                logger.error(f"Connection refused: {e}. Retrying in 5s...")
                await asyncio.sleep(5)
            except websockets.exceptions.ConnectionClosed:
                logger.info("Connection closed by server. Reconnecting in 3s...")
                await asyncio.sleep(3)
            except asyncio.CancelledError:
                break

    finally:
        if webcam:
            webcam.stop()
        logger.info("Simulator stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ESP32-CAM WebSocket Simulator (Single Camera)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 simulator.py                                    # Auto-discover, synthetic mode
  python3 simulator.py --mode webcam                     # Use webcam
  python3 simulator.py --url ws://192.168.1.10:8765/ws/esp32/Sim_1 --fps 10
        """
    )
    parser.add_argument("--url",  type=str, default="auto",       help="WebSocket URL or 'auto'")
    parser.add_argument("--id",   type=str, default="Sim_Camera", help="Camera hardware ID")
    parser.add_argument("--mode", type=str, choices=["synthetic", "webcam"], default="synthetic")
    parser.add_argument("--fps",  type=int, default=10,            help="Target FPS (default: 10)")

    args = parser.parse_args()
    try:
        asyncio.run(run_simulator(args.url, args.id, args.mode, args.fps))
    except KeyboardInterrupt:
        print("\nSimulator stopped.")
