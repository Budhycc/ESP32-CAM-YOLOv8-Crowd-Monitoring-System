#include "WiFi.h"
#include "esp_camera.h"
#include <WebSocketsClient.h>
#include <WiFiManager.h>
#include <WiFiUdp.h>
#include <Preferences.h>
// ==========================================
// CONFIGURATION
// ==========================================

// WebSocket Server Configuration
String esp32_id = ""; // Akan diisi otomatis dengan MAC Address di setup()
String websocket_server = ""; // Akan diisi otomatis via UDP Auto-Discovery
const uint16_t websocket_port =
    8765; // Ganti dengan Port server Python (sesuai config.py)
String websocket_path_str;

// PIR Sensor Configuration
const int pirPin =
    13; // Pin yang terhubung ke sensor PIR (sesuaikan jika berbeda)
bool motionDetected = false;
bool isStreaming = false;
unsigned long lastCaptureTime = 0;
int captureInterval =
    0; // Default: 0 = Dinamis (Tanpa Delay / Max FPS)

// BOOT Button Configuration (Reset WiFi)
const bool enableBootReset =
    false; // Set true jika ingin mengaktifkan reset WiFi via tombol BOOT
const int bootButtonPin = 0; // Pin tombol BOOT (GPIO 0)
unsigned long bootPressStartTime = 0;
bool bootButtonPressed = false;
int lastHoldSecond = 0;

// ==========================================
// CAMERA PINS (AI-THINKER ESP32-CAM)
// ==========================================
#define PWDN_GPIO_NUM 32
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM 0
#define SIOD_GPIO_NUM 26
#define SIOC_GPIO_NUM 27
#define Y9_GPIO_NUM 35
#define Y8_GPIO_NUM 34
#define Y7_GPIO_NUM 39
#define Y6_GPIO_NUM 36
#define Y5_GPIO_NUM 21
#define Y4_GPIO_NUM 19
#define Y3_GPIO_NUM 18
#define Y2_GPIO_NUM 5
#define VSYNC_GPIO_NUM 25
#define HREF_GPIO_NUM 23
#define PCLK_GPIO_NUM 22

WebSocketsClient webSocket;
WiFiUDP udp;
Preferences preferences;

void setResolution(String resStr) {
  sensor_t *s = esp_camera_sensor_get();
  if (!s) {
    Serial.println("Sensor not found");
    return;
  }

  resStr.toUpperCase();
  if (resStr == "QVGA") {
    s->set_framesize(s, FRAMESIZE_QVGA);
    Serial.println("Resolution set to QVGA (320x240)");
  } else if (resStr == "VGA") {
    s->set_framesize(s, FRAMESIZE_VGA);
    Serial.println("Resolution set to VGA (640x480)");
  } else if (resStr == "SVGA") {
    s->set_framesize(s, FRAMESIZE_SVGA);
    Serial.println("Resolution set to SVGA (800x600)");
  } else if (resStr == "XGA") {
    s->set_framesize(s, FRAMESIZE_XGA);
    Serial.println("Resolution set to XGA (1024x768)");
  } else if (resStr == "HD") {
    s->set_framesize(s, FRAMESIZE_HD);
    Serial.println("Resolution set to HD (1280x720)");
  } else {
    Serial.println("Unknown resolution format");
  }
}

void webSocketEvent(WStype_t type, uint8_t *payload, size_t length) {
  switch (type) {
  case WStype_DISCONNECTED:
    Serial.println("[WebSocket] Disconnected!");
    break;
  case WStype_CONNECTED:
    Serial.printf("[WebSocket] Connected to url: %s\n", payload);
    break;
  case WStype_TEXT: {
    Serial.printf("[WebSocket] Received text: %s\n", payload);
    String msg = String((char *)payload);
    if (msg.startsWith("SET_RESOLUTION:")) {
      String resStr = msg.substring(15);
      resStr.trim();
      setResolution(resStr);
    } else if (msg.startsWith("SET_FPS:")) {
      String fpsStr = msg.substring(8);
      fpsStr.trim();
      int fpsVal = fpsStr.toInt();
      if (fpsVal <= 0) {
        captureInterval = 0; // Mode Dinamis / Maksimal (Tanpa Delay)
        Serial.println("[WebSocket] FPS set to Dynamic / Max (captureInterval = 0 ms)");
      } else {
        captureInterval = 1000 / fpsVal;
        Serial.printf("[WebSocket] FPS set to %d (captureInterval = %d ms)\n", fpsVal, captureInterval);
      }
    } else if (msg == "SLEEP") {
      Serial.println(
          "Perintah SLEEP dari server diterima. Menghentikan streaming.");
      isStreaming = false;
    } else if (msg.startsWith("SET_ADV_CONFIG:")) {
      int nxclk, njpeg, nfb, nbri, ncon, nsat, nvflip;
      if (sscanf(msg.c_str(), "SET_ADV_CONFIG:%d,%d,%d,%d,%d,%d,%d", &nxclk, &njpeg, &nfb, &nbri, &ncon, &nsat, &nvflip) == 7) {
        bool needsRestart = false;
        if (preferences.getInt("xclk", 20000000) != nxclk || preferences.getInt("fb_count", 2) != nfb) {
          needsRestart = true;
        }
        preferences.putInt("xclk", nxclk);
        preferences.putInt("jpeg_quality", njpeg);
        preferences.putInt("fb_count", nfb);
        preferences.putInt("brightness", nbri);
        preferences.putInt("contrast", ncon);
        preferences.putInt("saturation", nsat);
        preferences.putInt("vflip", nvflip);
        
        sensor_t *s = esp_camera_sensor_get();
        if (s) {
          s->set_quality(s, njpeg);
          s->set_brightness(s, nbri);
          s->set_contrast(s, ncon);
          s->set_saturation(s, nsat);
          s->set_vflip(s, nvflip);
        }
        if (needsRestart) {
          Serial.println("Core config synced from server. Restarting ESP32...");
          delay(500);
          ESP.restart();
        }
      }
    } else if (msg.startsWith("SET_QUALITY:")) {
      int val = msg.substring(12).toInt();
      preferences.putInt("jpeg_quality", val);
      sensor_t *s = esp_camera_sensor_get();
      if (s) s->set_quality(s, val);
    } else if (msg.startsWith("SET_BRIGHTNESS:")) {
      int val = msg.substring(15).toInt();
      preferences.putInt("brightness", val);
      sensor_t *s = esp_camera_sensor_get();
      if (s) s->set_brightness(s, val);
    } else if (msg.startsWith("SET_CONTRAST:")) {
      int val = msg.substring(13).toInt();
      preferences.putInt("contrast", val);
      sensor_t *s = esp_camera_sensor_get();
      if (s) s->set_contrast(s, val);
    } else if (msg.startsWith("SET_SATURATION:")) {
      int val = msg.substring(15).toInt();
      preferences.putInt("saturation", val);
      sensor_t *s = esp_camera_sensor_get();
      if (s) s->set_saturation(s, val);
    } else if (msg.startsWith("SET_VFLIP:")) {
      int val = msg.substring(10).toInt();
      preferences.putInt("vflip", val);
      sensor_t *s = esp_camera_sensor_get();
      if (s) s->set_vflip(s, val);
    } else if (msg.startsWith("SET_CORE_CONFIG:")) {
      int nxclk, nfb;
      if (sscanf(msg.c_str(), "SET_CORE_CONFIG:%d,%d", &nxclk, &nfb) == 2) {
        preferences.putInt("xclk", nxclk);
        preferences.putInt("fb_count", nfb);
        Serial.println("Core config updated. Restarting ESP32...");
        delay(500);
        ESP.restart();
      }
    }
    break;
  }
  case WStype_BIN:
    Serial.printf("[WebSocket] Received binary length: %u\n", length);
    break;
  case WStype_ERROR:
  case WStype_FRAGMENT_TEXT_START:
  case WStype_FRAGMENT_BIN_START:
  case WStype_FRAGMENT:
  case WStype_FRAGMENT_FIN:
    break;
  }
}

void setupCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  int pref_xclk = preferences.getInt("xclk", 20000000);
  int pref_jpeg = preferences.getInt("jpeg_quality", 20);
  int pref_fb = preferences.getInt("fb_count", 2);

  config.xclk_freq_hz = pref_xclk;
  // CATATAN: 24MHz secara teori lebih cepat, tapi tidak stabil di banyak board AI Thinker
  config.pixel_format = PIXFORMAT_JPEG;

  // Sesuaikan resolusi, untuk koneksi lancar disarankan QVGA, VGA, atau SVGA
  // CATATAN PENTING: Di ESP32-CAM, jpeg_quality TERBALIK dari konvensi umum:
  //   Angka LEBIH KECIL = kualitas LEBIH TINGGI = file LEBIH BESAR (lambat)
  //   Angka LEBIH BESAR = kualitas LEBIH RENDAH = file LEBIH KECIL (cepat transfer)
  //   Optimal untuk streaming: 20-25 (balance kecepatan & cukup jelas untuk YOLOv8)
  if (psramFound()) {
    config.frame_size = FRAMESIZE_VGA;
    config.jpeg_quality = pref_jpeg;
    config.fb_count = pref_fb;      // 2 DMA buffer: stabil & aman untuk semua board AI Thinker
    config.grab_mode = CAMERA_GRAB_LATEST; // Selalu ambil frame terbaru (Low Latency)
  } else {
    config.frame_size = FRAMESIZE_QVGA; // Non-PSRAM fallback ke QVGA agar lancar
    config.jpeg_quality = pref_jpeg;
    config.fb_count = 1;
    config.grab_mode = CAMERA_GRAB_LATEST;
  }

  // Inisialisasi Kamera
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x", err);
    return;
  }

  // ==========================================
  // SENSOR OV2640 TUNING (AI Thinker)
  // ==========================================
  // Hanya gunakan setting yang dijamin ada di semua versi library esp32-camera
  sensor_t *s = esp_camera_sensor_get();
  if (s) {
    int pref_bri = preferences.getInt("brightness", 1);
    int pref_con = preferences.getInt("contrast", 1);
    int pref_sat = preferences.getInt("saturation", -1);
    int pref_vflip = preferences.getInt("vflip", 0);
    
    s->set_brightness(s, pref_bri);
    s->set_contrast(s, pref_con);
    s->set_saturation(s, pref_sat);
    s->set_aec2(s, true);         // Advanced AEC: auto exposure lebih adaptif
    s->set_awb_gain(s, true);     // Auto White Balance Gain aktif
    s->set_lenc(s, true);         // Lens correction: koreksi distorsi lensa AI Thinker
    s->set_vflip(s, pref_vflip);
    Serial.println("OV2640 sensor tuning applied from NVS.");
    delay(300); // Beri waktu sensor stabilisasi sebelum mulai capture
  }

  Serial.println("Camera Setup Successful.");
}

void setup() {
  Serial.begin(115200);
  Serial.println();

  // Setup PIR Sensor
  pinMode(pirPin, INPUT);
  Serial.println("PIR Sensor Initialized.");

  // Initialize NVS Preferences
  preferences.begin("cam_config", false);
  Serial.println("NVS Preferences loaded.");

  // Setup BOOT Button (jika diaktifkan)
  if (enableBootReset) {
    pinMode(bootButtonPin, INPUT_PULLUP);
    Serial.println("BOOT Button Initialized (Hold 5s to reset WiFi).");
  } else {
    Serial.println(
        "BOOT Button reset feature is DISABLED (enableBootReset = false).");
  }

  // Setup WiFiManager
  WiFiManager wm;
  Serial.println("Connecting to WiFi or starting AP: ESP32-CAM-SETUP");
  bool res = wm.autoConnect("ESP32-CAM-SETUP");
  if (!res) {
    Serial.println("Failed to connect or timeout");
    ESP.restart();
  }
  Serial.print("WiFi connected, IP address: ");
  Serial.println(WiFi.localIP());

  // Generate ESP32 ID from MAC Address
  uint8_t mac[6];
  WiFi.macAddress(mac);
  char macStr[18];
  sprintf(macStr, "ESP-%02X%02X%02X", mac[3], mac[4], mac[5]);
  esp32_id = String(macStr);
  Serial.print("Generated Hardware ID: ");
  Serial.println(esp32_id);

  // Setup Camera
  setupCamera();

  // Start UDP Listener for Server Auto-Discovery
  udp.begin(9876);
  Serial.println("Listening for Server Announce on UDP port 9876...");
}

void checkResetWiFi() {
  // Check for Serial commands to reset WiFi (selalu aktif)
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    if (command == "RESET_WIFI") {
      Serial.println("Resetting WiFi configuration...");
      WiFiManager wm;
      wm.resetSettings();
      Serial.println("WiFi configuration reset. Restarting...");
      delay(1000);
      ESP.restart();
    }
  }

  // Check for BOOT button hold (5 seconds to reset WiFi) - hanya jika
  // enableBootReset diaktifkan
  if (enableBootReset) {
    if (digitalRead(bootButtonPin) == LOW) {
      if (!bootButtonPressed) {
        bootButtonPressed = true;
        bootPressStartTime = millis();
        lastHoldSecond = 0;
      } else {
        unsigned long elapsed = millis() - bootPressStartTime;
        int currentSecond = elapsed / 1000;
        if (currentSecond > lastHoldSecond && currentSecond <= 5) {
          lastHoldSecond = currentSecond;
          Serial.printf("Tombol BOOT ditekan... %d/5 detik\n", currentSecond);
        }
        if (elapsed >= 5000) {
          Serial.println("\n[RESET] Tombol BOOT ditahan 5 detik! Mereset "
                         "konfigurasi WiFi...");
          WiFiManager wm;
          wm.resetSettings();
          Serial.println(
              "Konfigurasi WiFi berhasil di-reset. Restarting ESP32...");
          delay(1000);
          ESP.restart();
        }
      }
    } else {
      if (bootButtonPressed) {
        bootButtonPressed = false;
        lastHoldSecond = 0;
      }
    }
  }
}

void loop() {
  // Selalu periksa tombol BOOT & perintah Serial di setiap iterasi loop
  checkResetWiFi();

  // Jika IP Server belum didapatkan via UDP, lakukan pencarian non-blocking
  if (websocket_server == "") {
    int packetSize = udp.parsePacket();
    if (packetSize) {
      char packetBuffer[255];
      int len = udp.read(packetBuffer, 255);
      if (len > 0) {
        packetBuffer[len] = 0;
      }
      String msg = String(packetBuffer);
      if (msg.startsWith("YOLOV8_SERVER_ANNOUNCE:")) {
        websocket_server = udp.remoteIP().toString();
        Serial.print("Found Server at IP: ");
        Serial.println(websocket_server);

        // Setup WebSocket Client setelah IP ditemukan
        websocket_path_str = String("/ws/esp32/") + esp32_id;
        webSocket.begin(websocket_server.c_str(), websocket_port,
                        websocket_path_str.c_str());
        webSocket.onEvent(webSocketEvent);
        webSocket.setReconnectInterval(5000);
      }
    }
    delay(10);
    return;
  }

  webSocket.loop();

  // Baca status sensor PIR
  int pirState = digitalRead(pirPin);

  if (pirState == HIGH) {
    if (!motionDetected) {
      Serial.println("Gerakan di pintu terdeteksi! Membangunkan kamera...");
      motionDetected = true;
      isStreaming = true; // Nyalakan streaming
    }
  } else {
    if (motionDetected) {
      // Hanya mereset flag gerakan lokal, streaming tetap jalan sampai server
      // suruh SLEEP
      motionDetected = false;
    }
  }

  // Kirim gambar ke server setiap interval (e.g. 500ms) selama status streaming
  // aktif
  if (isStreaming) {
    if (captureInterval == 0 || millis() - lastCaptureTime > captureInterval) {
      sendCameraFrame();
      lastCaptureTime = millis();
      // Yield minimal agar watchdog timer tidak reset & buffer WebSocket tidak overflow
      // di mode max FPS (captureInterval == 0)
      if (captureInterval == 0) delay(1);
    }
  }
}

void sendCameraFrame() {
  // Hanya mengirim jika websocket terhubung
  if (webSocket.isConnected()) {
    // CATATAN: webSocket.loop() sudah dipanggil di loop() utama,
    // tidak perlu duplikat di sini (mengurangi overhead processing)
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("Camera capture failed");
      return;
    }

    // Kirim frame JPEG ke server dalam bentuk binary
    webSocket.sendBIN(fb->buf, fb->len);
    // Serial.printf("Frame terkirim: %u bytes\n", fb->len); // Uncomment untuk debug ukuran frame

    esp_camera_fb_return(fb);
  }
}
