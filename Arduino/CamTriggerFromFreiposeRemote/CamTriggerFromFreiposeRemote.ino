/*
 * CamTriggerFromFreiposeRemote
 * Arduino Nano Every — Camera trigger for FreiPose Recorder
 *
 * Commands received over serial (115200 baud, newline-terminated):
 *   S<fps>   Start trigger at <fps> Hz  (e.g. "S30\n")
 *   Q        Stop trigger               (e.g. "Q\n")
 *   P        Ping                       (e.g. "P\n")
 *
 * Responses:
 *   CAM_TRIGGER_READY    on startup
 *   TRIG_START_<fps>     when trigger starts (FreiPose checks for PONG_ on P)
 *   TRIG_STOP            when trigger stops (by command or watchdog)
 *   WATCHDOG_STOP        when stopped by watchdog (no comms for WATCHDOG_MS)
 *   PONG_                response to P ping
 *
 * Watchdog: if trigger is active and no serial command is received within
 * WATCHDOG_MS milliseconds, trigger stops automatically.
 * This prevents runaway triggering when FreiPose crashes without sending Q.
 *
 * Hardware:
 *   Pin D2 → optoisolator → camera Line1 (GPIO input)
 *   tone() generates a 50% duty cycle square wave at the requested Hz.
 *   Cameras trigger on the rising edge.
 */

const int    CAM_PIN       = 2;
const long   WATCHDOG_MS   = 10000;   // stop trigger if no comms for 10 s
const int    BAUD           = 115200;

int          fps            = 30;
bool         active         = false;
unsigned long last_serial_ms = 0;

// Serial input buffer
String inputBuf = "";


void setup() {
  pinMode(CAM_PIN, OUTPUT);
  digitalWrite(CAM_PIN, LOW);
  Serial.begin(BAUD);
  delay(2000);   // wait for connecting software to open port
  Serial.println("CAM_TRIGGER_READY");
  last_serial_ms = millis();
}


void loop() {

  // ── Read serial input ──────────────────────────────────────────────────────
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (inputBuf.length() > 0) {
        handleCommand(inputBuf);
        inputBuf = "";
        last_serial_ms = millis();   // reset watchdog on any command
      }
    } else {
      inputBuf += c;
    }
  }

  // ── Watchdog ───────────────────────────────────────────────────────────────
  if (active && (millis() - last_serial_ms > WATCHDOG_MS)) {
    noTone(CAM_PIN);
    digitalWrite(CAM_PIN, LOW);
    active = false;
    Serial.println("WATCHDOG_STOP");
  }
}


void handleCommand(String cmd) {
  cmd.trim();

  if (cmd.startsWith("S")) {
    // Start trigger at given fps
    int requested = cmd.substring(1).toInt();
    if (requested > 0 && requested <= 200) {
      fps = requested;
      noTone(CAM_PIN);              // stop any previous tone first
      tone(CAM_PIN, fps);
      active = true;
      Serial.print("TRIG_START_");
      Serial.println(fps);
    } else {
      Serial.println("ERR_INVALID_FPS");
    }

  } else if (cmd == "Q") {
    // Stop trigger
    noTone(CAM_PIN);
    digitalWrite(CAM_PIN, LOW);
    active = false;
    Serial.println("TRIG_STOP");

  } else if (cmd == "P") {
    // Ping — underscore suffix needed for FreiPose serial parser
    Serial.println("PONG_");

  } else if (cmd == "STATUS") {
    // Optional: human-readable status for debugging
    Serial.print("STATUS_");
    Serial.print(active ? "RUNNING" : "IDLE");
    Serial.print("_FPS_");
    Serial.println(fps);
  }
}
