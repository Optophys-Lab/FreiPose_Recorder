/*
 * Camera Trigger Sketch for Arduino Nano Every
 * Controls camera triggering via FreiPose Recorder serial protocol
 * Commands: S{fps} = start trigger, Q = stop, P = ping
 * Pin D2 output to camera optoisolated input (Line1)
 * Baud rate: 115200
 */

int camout = 2;
int fps = 30;
bool active = false;

void setup() {
  pinMode(camout, OUTPUT);
  Serial.begin(115200);
  delay(2000);  // wait 2 seconds for connecting software to be ready
  Serial.println("CAM_TRIGGER_READY");
}

void loop() {
  if (Serial.available()) {
    String input = Serial.readStringUntil('\n');
    input.trim();
    
    if (input.startsWith("S")) {
      fps = input.substring(1).toInt();  // extract fps from S30
      tone(camout, fps);
      active = true;
      Serial.println("running");
    } 
    else if (input == "Q") {
      noTone(camout);
      active = false;
      Serial.println("stopping");
    }
    else if (input == "P") {
      Serial.println("PONG_");  // respond to ping - underscore needed for FreiPose parser
    }
  }
}