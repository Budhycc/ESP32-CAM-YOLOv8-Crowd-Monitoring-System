#define PIR_PIN 13

void setup() {
  Serial.begin(115200);

  pinMode(PIR_PIN, INPUT);

  Serial.println("Testing PIR ESP32-CAM");
  Serial.println("Tunggu sensor stabil...");
  delay(3000);

  Serial.println("PIR siap!");
}

void loop() {
  int pirState = digitalRead(PIR_PIN);

  if (pirState == HIGH) {
    Serial.println("GERAKAN TERDETEKSI!");
  } else {
    Serial.println("Tidak ada gerakan");
  }

  delay(500);
}