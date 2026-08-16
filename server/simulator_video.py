import asyncio
import cv2
import numpy as np
import websockets
import time
import argparse
import logging
import socket
import threading
import os
import glob

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] VideoSimulator: %(message)s")
logger = logging.getLogger("VideoSimulator")

# JPEG Quality sesuai hardware esp32cam.ino (jpeg_quality=20)
JPEG_QUALITY = 20

class VideoReader:
    """Membaca frame video di thread terpisah dan melakukan loop saat selesai."""
    def __init__(self, video_path, cam_id):
        self.video_path = video_path
        self.cam_id = cam_id
        self._frame = None
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

    def get_frame(self):
        with self._lock:
            return self._frame

    def _read_loop(self, resolution: tuple):
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            logger.error(f"[{self.cam_id}] Could not open video {self.video_path}.")
            return
            
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0 or np.isnan(fps):
            fps = 30.0
        frame_delay = 1.0 / fps
        logger.info(f"[{self.cam_id}] Video loaded: {os.path.basename(self.video_path)} (FPS: {fps:.2f})")

        try:
            while self._running:
                start_time = time.time()
                ret, frame = cap.read()
                
                if not ret:
                    # Loop the video jika mencapai akhir
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                    
                w, h = resolution
                resized = cv2.resize(frame, (w, h))
                with self._lock:
                    self._frame = resized
                    
                elapsed = time.time() - start_time
                sleep_time = frame_delay - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
        finally:
            cap.release()

    def start(self, resolution=(640, 480)):
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, args=(resolution,), daemon=True, name=f"Thread-{self.cam_id}")
        self._thread.start()
        logger.info(f"[{self.cam_id}] Video reader thread started.")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

async def run_camera(video_reader: VideoReader, server_url: str, esp32_id: str, fps: int):
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
                
                # Mulai thread video dengan resolusi default
                video_reader.stop()
                video_reader.start(state["resolution"])

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
                                    video_reader.stop()
                                    video_reader.start(state["resolution"])
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

                # Tunggu frame pertama
                for _ in range(50):
                    if video_reader.get_frame() is not None:
                        break
                    await asyncio.sleep(0.1)

                try:
                    while True:
                        if state["is_sleeping"]:
                            logger.info(f"[{esp32_id}] Standby. Simulating PIR wakeup in 10s...")
                            await asyncio.sleep(10)
                            state["is_sleeping"] = False
                            logger.info(f"[{esp32_id}] PIR WAKEUP - resuming stream.")
                            continue

                        raw_frame = video_reader.get_frame()
                        if raw_frame is not None:
                            ok, encoded = cv2.imencode(
                                ".jpg", raw_frame,
                                [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
                            )
                            if ok:
                                await websocket.send(encoded.tobytes())
                                frame_num += 1
                                if frame_num % 100 == 0:
                                    size_kb = len(encoded.tobytes()) / 1024
                                    logger.info(f"[{esp32_id}] Sent {frame_num} frames | {size_kb:.1f} KB/frame | res={state['resolution']}")

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


async def run_multi_simulator(base_url: str, video_dir: str, fps: int):
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

    # Cari semua file video di direktori
    video_files = []
    for ext in ["*.mp4", "*.avi", "*.mkv", "*.mov"]:
        video_files.extend(glob.glob(os.path.join(video_dir, ext)))
        
    if not video_files:
        logger.error(f"No video files found in {video_dir}")
        return

    logger.info(f"Starting Multi-Video Simulator: {len(video_files)} cameras -> {base_url}")
    logger.info(f"FPS: {fps} | JPEG Quality: {JPEG_QUALITY}")

    video_readers = []
    tasks = []

    for i, video_path in enumerate(sorted(video_files)):
        esp32_id = f"VideoCam_{i+1}"
        reader = VideoReader(video_path, esp32_id)
        video_readers.append(reader)
        tasks.append(asyncio.create_task(run_camera(reader, base_url, esp32_id, fps)))

    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down simulator...")
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for reader in video_readers:
            reader.stop()
        logger.info("Simulator stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Multi Video WebSocket Simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 simulator_video.py                                         # Auto-discover, scan ../sample
  python3 simulator_video.py --dir /path/to/my/videos                # Custom directory
  python3 simulator_video.py --url ws://192.168.1.10:8765            # Manual URL
        """
    )
    
    # Default ke folder sample
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_dir = os.path.join(base_dir, "sample")
    
    parser.add_argument("--url",  type=str, default="auto",       help="WebSocket URL or 'auto'")
    parser.add_argument("--dir",  type=str, default=default_dir,  help="Directory containing video samples")
    parser.add_argument("--fps",  type=int, default=10,           help="Target streaming FPS to server (default: 10)")

    args = parser.parse_args()
    
    if not os.path.exists(args.dir) or not os.path.isdir(args.dir):
        logger.error(f"Directory not found: {args.dir}")
        exit(1)
        
    try:
        asyncio.run(run_multi_simulator(args.url, args.dir, args.fps))
    except KeyboardInterrupt:
        print("\nMulti Video Simulator stopped.")
