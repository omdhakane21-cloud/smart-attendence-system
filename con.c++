#include <WiFi.h>
#include <HTTPClient.h>
#include <SPI.h>
#include <MFRC522.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <time.h>

// ---------------- PIN CONFIGURATION ----------------

#define SS_PIN     5
#define RST_PIN    4

#define OLED_SDA   21
#define OLED_SCL   22

#define SCREEN_WIDTH  128
#define SCREEN_HEIGHT 64

// ---------------- WIFI CONFIGURATION ----------------

const char* WIFI_SSID = "YOUR_WIFI_NAME";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// Replace with your computer's LAN IP while testing locally.
// Example: http://192.168.1.10:8000
const char* SERVER_URL = "http://192.168.1.10:8000";

// ---------------- HARDWARE OBJECTS ----------------

MFRC522 rfid(SS_PIN, RST_PIN);

Adafruit_SSD1306 display(
  SCREEN_WIDTH,
  SCREEN_HEIGHT,
  &Wire,
  -1
);

// ---------------- SESSION CONFIGURATION ----------------

// Set this to the session ID obtained from your backend.
int sessionID = 1;

// ---------------- DISPLAY FUNCTION ----------------

void showMessage(String line1, String line2 = "", String line3 = "") {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);

  display.setCursor(0, 0);
  display.println(line1);

  display.println(line2);
  display.println(line3);

  display.display();
}

// ---------------- RFID UID ----------------

String getCardUID() {
  String uid = "";

  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) {
      uid += "0";
    }

    uid += String(rfid.uid.uidByte[i], HEX);
  }

  uid.toUpperCase();
  return uid;
}

// ---------------- SEND ATTENDANCE ----------------

void sendAttendance(String uid) {
  if (WiFi.status() != WL_CONNECTED) {
    showMessage("WiFi disconnected", "Attendance not sent");
    return;
  }

  HTTPClient http;

  String url = String(SERVER_URL) + "/attendance/scan";

  http.begin(url);
  http.addHeader("Content-Type", "application/json");

  // Send the session ID and RFID UID to the backend.
  String payload =
    "{\"uid\":\"" + uid +
    "\",\"session_id\":" + String(sessionID) + "}";

  int responseCode = http.POST(payload);

  if (responseCode > 0) {
    String response = http.getString();

    Serial.println(response);

    if (response.indexOf("\"status\":\"marked\"") >= 0) {
      showMessage("Attendance Marked", "UID: " + uid);
    }
    else if (response.indexOf("\"status\":\"already_marked\"") >= 0) {
      showMessage("Already Marked", "UID: " + uid);
    }
    else if (response.indexOf("\"status\":\"session_closed\"") >= 0) {
      showMessage("Session Closed", "Contact teacher");
    }
    else if (response.indexOf("\"status\":\"unknown_card\"") >= 0) {
      showMessage("Unknown Card", "Not registered");
    }
    else {
      showMessage("Server Response", response.substring(0, 20));
    }
  }
  else {
    showMessage("Server Error", "Code: " + String(responseCode));
    Serial.println(http.errorToString(responseCode));
  }

  http.end();
}

// ---------------- SETUP ----------------

void setup() {
  Serial.begin(115200);

  Wire.begin(OLED_SDA, OLED_SCL);

  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("OLED initialization failed");
    while (true) {
      delay(1000);
    }
  }

  showMessage("Smart Attendance", "Starting...");

  SPI.begin(18, 19, 23, SS_PIN);
  rfid.PCD_Init();

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  showMessage("Connecting WiFi");

  unsigned long startTime = millis();

  while (WiFi.status() != WL_CONNECTED &&
         millis() - startTime < 20000) {
    delay(500);
    Serial.print(".");
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi connected");
    Serial.println(WiFi.localIP());

    showMessage("WiFi Connected", "Scan your card");
  } else {
    showMessage("WiFi Failed", "Check credentials");
  }

  // Indian Standard Time.
  configTime(
    19800,
    0,
    "pool.ntp.org",
    "time.google.com"
  );
}

// ---------------- MAIN LOOP ----------------

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.reconnect();
  }

  if (!rfid.PICC_IsNewCardPresent()) {
    delay(50);
    return;
  }

  if (!rfid.PICC_ReadCardSerial()) {
    delay(50);
    return;
  }

  String uid = getCardUID();

  Serial.print("Card UID: ");
  Serial.println(uid);

  showMessage("Card Detected", uid, "Checking...");

  sendAttendance(uid);

  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();

  // Prevent an immediate repeated read of the same card.
  delay(1500);
}