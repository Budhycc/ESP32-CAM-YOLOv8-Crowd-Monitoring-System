#include "WiFi.h"
#include "esp_camera.h"
#include <WebSocketsClient.h>

// ==========================================
// CONFIGURATION
// ==========================================
const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";

// WebSocket Server Configuration
const char* websocket_server = "192.168.1.100"; // Ganti dengan IP komputer/server Python
const uint16_t websocket_port = 8765;           // Ganti dengan Port server Python (sesuai config.py)
const char* websocket_path = "/ws/esp32";

// PIR Sensor Configuration
const int pirPin = 13; // Pin yang terhubung ke sensor PIR (sesuaikan jika berbeda)
bool motionDetected = false;
unsigned long lastCaptureTime = 0;
const int captureInterval = 500; // Interval ambil gambar saat ada gerakan (dalam ms)

// ==========================================
// CAMERA PINS (AI-THINKER ESP32-CAM)
// ==========================================
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

WebSocketsClient webSocket;

void webSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
  switch(type) {
    case WStype_DISCONNECTED:
      Serial.println("[WebSocket] Disconnected!");
      break;
    case WStype_CONNECTED:
      Serial.printf("[WebSocket] Connected to url: %s\n", payload);
      break;
    case WStype_TEXT:
      Serial.printf("[WebSocket] Received text: %s\n", payload);
      break;
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
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  // Sesuaikan resolusi, untuk koneksi lancar disarankan QVGA, VGA, atau SVGA
  if(psramFound()){
    config.frame_size = FRAMESIZE_VGA; // FRAMESIZE_VGA (640x480), FRAMESIZE_SVGA (800x600)
    config.jpeg_quality = 12;
    config.fb_count = 2;
  } else {
    config.frame_size = FRAMESIZE_VGA;
    config.jpeg_quality = 12;
    config.fb_count = 1;
  }

  // Inisialisasi Kamera
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x", err);
    return;
  }
  Serial.println("Camera Setup Successful.");
}

void setup() {
  Serial.begin(115200);
  Serial.println();

  // Setup PIR Sensor
  pinMode(pirPin, INPUT);
  Serial.println("PIR Sensor Initialized.");

  // Setup WiFi
  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("");
  Serial.print("WiFi connected, IP address: ");
  Serial.println(WiFi.localIP());

  // Setup Camera
  setupCamera();

  // Setup WebSocket Client
  webSocket.begin(websocket_server, websocket_port, websocket_path);
  webSocket.onEvent(webSocketEvent);
  webSocket.setReconnectInterval(5000);
}

void loop() {
  webSocket.loop();
  
  // Baca status sensor PIR
  int pirState = digitalRead(pirPin);
  
  if (pirState == HIGH) {
    if (!motionDetected) {
      Serial.println("Gerakan Terdeteksi! Memulai pengiriman frame...");
      motionDetected = true;
    }
    
    // Kirim gambar ke server setiap interval (e.g. 500ms) selama ada gerakan
    if (millis() - lastCaptureTime > captureInterval) {
      sendCameraFrame();
      lastCaptureTime = millis();
    }
  } else {
    if (motionDetected) {
      Serial.println("Gerakan Berhenti.");
      motionDetected = false;
    }
  }
}

void sendCameraFrame() {
  // Hanya mengirim jika websocket terhubung
  if (webSocket.isConnected()) {
    camera_fb_t * fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("Camera capture failed");
      return;
    }

    // Kirim frame JPEG ke server dalam bentuk binary
    webSocket.sendBIN(fb->buf, fb->len);
    Serial.printf("Frame terkirim: %u bytes\n", fb->len);
    
    esp_camera_fb_return(fb);
  }
}
