import asyncio
import cv2
import numpy as np
import websockets
import time
import argparse
import logging
import socket
import threading

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] MultiSim: %(message)s")
logger = logging.getLogger("MultiSim")

# ==========================================
# JPEG QUALITY: Harus sesuai dengan hardware ESP32-CAM
# Di ESP32-CAM: angka lebih besar = kualitas lebih rendah = file lebih kecil
# Quality 20 = ~10-15KB per frame (sama dengan setting di esp32cam.ino)
# ==========================================
JPEG_QUALITY = 20

# ==========================================
# FRAME PRODUCER - Webcam / Synthetic
# Dijalankan di thread terpisah agar tidak block async event loop
# ==========================================

class FrameProducer:
    """Thread-safe frame producer untuk webcam atau synthetic mode."""

    def __init__(self, mode: str, fps: int):
        self.mode = mode
        self.fps = fps
        self._frame = None
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._frame_num = 0

    def get_frame(self):
        """Ambil frame terbaru (thread-safe)."""
        with self._lock:
            return self._frame

    def _create_synthetic_frame(self, person_count: int = 3):
        """Membuat frame sintetis dengan figur manusia dummy."""
        h, w = 480, 640
        frame = np.full((h, w, 3), (240, 240, 240), dtype=np.uint8)
        cv2.putText(frame, "MULTI-CAM SIMULATOR", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (50, 50, 50), 2)
        cv2.line(frame, (0, 50), (w, 50), (100, 100, 100), 2)

        for i in range(person_count):
            cx = 100 + (i * 120) % (w - 100)
            cy = 200 + ((i * 50) % 150)
            cv2.circle(frame, (cx, cy), 25, (50, 50, 200), -1)
            cv2.rectangle(frame, (cx - 20, cy + 25), (cx + 20, cy + 120), (200, 50, 50), -1)
            # FIX BUG: putText sebelumnya di luar loop sehingga hanya label person terakhir yang muncul
            cv2.putText(frame, f"Person {i+1}", (cx - 30, cy - 35), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

        ts = time.strftime("%H:%M:%S")
        cv2.putText(frame, ts, (w - 120, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (80, 80, 80), 1)
        return frame

    def _producer_thread(self):
        """Loop yang berjalan di thread background - TIDAK ada asyncio di sini."""
        cap = None
        delay = 1.0 / self.fps if self.fps > 0 else 0.033

        if self.mode == "webcam":
            logger.info("Opening webcam device (index 0)...")
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                logger.warning("Could not open webcam. Falling back to synthetic mode.")
                self.mode = "synthetic"
            else:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Ambil frame terbaru selalu

        try:
            while self._running:
                self._frame_num += 1
                t_start = time.monotonic()

                if self.mode == "webcam" and cap and cap.isOpened():
                    ret, frame = cap.read()
                    if ret:
                        with self._lock:
                            self._frame = frame
                    else:
                        logger.warning("Webcam read failed, retrying...")
                else:
                    test_counts = [2, 6, 15, 25]
                    count_idx = (self._frame_num // 30) % len(test_counts)
                    frame = self._create_synthetic_frame(test_counts[count_idx])
                    with self._lock:
                        self._frame = frame

                elapsed = time.monotonic() - t_start
                sleep_time = delay - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

        finally:
            if cap:
                cap.release()
            logger.info("Frame producer thread stopped.")

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._producer_thread, daemon=True, name="FrameProducer")
        self._thread.start()
        logger.info(f"Frame producer started (mode={self.mode}, fps={self.fps})")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)


# ==========================================
# CAMERA CLIENT - Satu instance per kamera virtual
# ==========================================

async def run_camera(producer: FrameProducer, server_url: str, esp32_id: str, fps: int):
    """
    Koneksikan satu kamera virtual ke server, kirim frame, dan tangani perintah server.
    Setiap kamera punya state sendiri (tidak berbagi global variable dengan kamera lain).
    """
    full_url = f"{server_url}/ws/esp32/{esp32_id}"
    delay_default = 1.0 / fps if fps > 0 else 0.01

    while True:  # Loop reconnect otomatis
        try:
            async with websockets.connect(
                full_url,
                ping_interval=20,
                ping_timeout=10,
                max_size=5 * 1024 * 1024
            ) as websocket:
                logger.info(f"[{esp32_id}] Connected to {full_url}")
                frame_num = 0

                state = {
                    "is_sleeping": False,
                    "delay": delay_default,
                    "resolution": (640, 480),
                }

                async def receiver():
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
                                    state["resolution"] = res_map[res]
                                    logger.info(f"[{esp32_id}] Resolution -> {res} {res_map[res]}")
                            elif message.startswith("SET_FPS:"):
                                try:
                                    f_val = int(message.split(":")[1].strip())
                                    state["delay"] = (1.0 / f_val) if f_val > 0 else 0.01
                                    label = f"{f_val} FPS" if f_val > 0 else "Dynamic/Max"
                                    logger.info(f"[{esp32_id}] FPS -> {label}")
                                except (ValueError, ZeroDivisionError):
                                    pass
                            elif message == "SLEEP":
                                logger.info(f"[{esp32_id}] SLEEP command received. Entering standby.")
                                state["is_sleeping"] = True
                    except (websockets.exceptions.ConnectionClosed, asyncio.CancelledError):
                        pass
                    except Exception as e:
                        logger.debug(f"[{esp32_id}] Receiver error: {e}")

                recv_task = asyncio.create_task(receiver())

                try:
                    while True:
                        if state["is_sleeping"]:
                            logger.info(f"[{esp32_id}] Standby. Simulating PIR wakeup in 10s...")
                            await asyncio.sleep(10)
                            state["is_sleeping"] = False
                            logger.info(f"[{esp32_id}] PIR WAKEUP - resuming stream.")
                            continue

                        frame = producer.get_frame()
                        if frame is not None:
                            w, h = state["resolution"]
                            resized = cv2.resize(frame, (w, h))
                            ok, encoded = cv2.imencode(
                                ".jpg", resized,
                                [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
                            )
                            if ok:
                                await websocket.send(encoded.tobytes())
                                frame_num += 1
                                if frame_num % 100 == 0:
                                    size_kb = len(encoded.tobytes()) / 1024
                                    logger.info(f"[{esp32_id}] Sent {frame_num} frames | {size_kb:.1f} KB/frame")

                        await asyncio.sleep(state["delay"])

                finally:
                    recv_task.cancel()
                    try:
                        await recv_task
                    except asyncio.CancelledError:
                        pass

        except (ConnectionRefusedError, OSError) as e:
            logger.error(f"[{esp32_id}] Connection refused: {e}. Retrying in 5s...")
            await asyncio.sleep(5)
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"[{esp32_id}] Connection closed by server. Reconnecting in 3s...")
            await asyncio.sleep(3)
        except asyncio.CancelledError:
            logger.info(f"[{esp32_id}] Camera task cancelled.")
            break
        except Exception as e:
            logger.error(f"[{esp32_id}] Unexpected error: {e}. Retrying in 5s...")
            await asyncio.sleep(5)


# ==========================================
# MAIN ORCHESTRATOR
# ==========================================

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
                logger.info(f"Auto-discovered server at {base_url}")
        except socket.timeout:
            logger.error("Auto-discovery timed out. Use --url ws://<IP>:8765 manually.")
            return
        finally:
            sock.close()

    if base_url.lower() == "auto":
        return

    logger.info(f"Starting Multi-Camera Simulator: {count} cameras -> {base_url}")
    logger.info(f"Mode: {mode} | FPS: {fps} | JPEG Quality: {JPEG_QUALITY}")

    producer = FrameProducer(mode=mode, fps=fps)
    producer.start()

    # Tunggu frame pertama tersedia
    logger.info("Waiting for first frame from producer...")
    for _ in range(50):
        if producer.get_frame() is not None:
            break
        await asyncio.sleep(0.1)
    else:
        logger.warning("No frame after 5s, proceeding anyway.")

    tasks = [
        asyncio.create_task(run_camera(producer, base_url, f"MultiCam_{i}", fps))
        for i in range(1, count + 1)
    ]

    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down simulator...")
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        producer.stop()
        logger.info("Simulator stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Multi ESP32-CAM WebSocket Simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 simulator_multi.py                               # Auto-discover, 3 cameras, webcam
  python3 simulator_multi.py --mode synthetic              # Synthetic frames
  python3 simulator_multi.py --url ws://192.168.1.10:8765 --count 5
  python3 simulator_multi.py --fps 10 --mode synthetic
        """
    )
    parser.add_argument("--url",   type=str, default="auto",      help="WebSocket URL or 'auto'")
    parser.add_argument("--count", type=int, default=3,            help="Number of cameras (default: 3)")
    parser.add_argument("--mode",  type=str, choices=["synthetic", "webcam"], default="webcam", help="Frame source")
    parser.add_argument("--fps",   type=int, default=10,           help="Target FPS per camera (default: 10)")

    args = parser.parse_args()

    try:
        asyncio.run(run_multi_simulator(args.url, args.count, args.mode, args.fps))
    except KeyboardInterrupt:
        print("\nMulti Simulator stopped.")
