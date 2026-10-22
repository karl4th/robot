/*
 * ╔══════════════════════════════════════════════════════════════════╗
 * ║                      M A N I F E S T R O                         ║
 * ╠══════════════════════════════════════════════════════════════════╣
 * ║  Built by   Manifestro                                           ║
 * ║  Repo       github.com/karl4th/                                  ║
 * ║             liquid-neural-network-delivery-robot                 ║
 * ║─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ║
 * ║  License    MIT                    Year  2026                    ║
 * ╚══════════════════════════════════════════════════════════════════╝
 */

#include <SPI.h>
#include <mcp_can.h>

MCP_CAN CAN(10);

#define MAX_RPM       30000
#define CAN_ID        0x1801E600
#define FEEDBACK_ID   0x1801E001
#define SEND_INTERVAL 50
#define TIMEOUT_MS    200
#define BUF_SIZE      48

int16_t targetRPM = 0;
bool brakeActive  = false;
unsigned long lastSend    = 0;
unsigned long lastReceive = 0;

char buf[BUF_SIZE];
uint8_t bufLen = 0;

void sendCAN(int16_t rpm) {
  rpm = constrain(rpm, -MAX_RPM, MAX_RPM);
  uint8_t hi = (rpm >> 8) & 0xFF;
  uint8_t lo = rpm & 0xFF;
  uint8_t data[8];
  data[0] = brakeActive ? 0xC1 : 0xC3;
  data[1] = hi;
  data[2] = lo;
  data[3] = 100;
  data[4] = hi;
  data[5] = lo;
  data[6] = 100;
  data[7] = 0x00;
  CAN.sendMsgBuf(CAN_ID, 1, 8, data);
}

void parseCommand(const char* s) {
  if (strcmp(s, "STATUS") == 0) {
    Serial.println("LSTAT,OK");
    return;
  }

  char* endPtr;
  long rpmVal = strtol(s, &endPtr, 10);

  if (*endPtr != ',') return;

  long brakeVal = strtol(endPtr + 1, NULL, 10);

  targetRPM   = constrain(rpmVal, -MAX_RPM, MAX_RPM);
  brakeActive = (brakeVal == 1);
  lastReceive = millis();
}

void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      if (bufLen > 0) {
        buf[bufLen] = '\0';
        parseCommand(buf);
      }
      bufLen = 0;
    } else if (c != '\r' && bufLen < BUF_SIZE - 1) {
      buf[bufLen++] = c;
    }
  }
}

void readFeedback() {
  if (CAN.checkReceive() != CAN_MSGAVAIL) return;
  unsigned long rxId;
  uint8_t len, rxBuf[8];
  CAN.readMsgBuf(&rxId, &len, rxBuf);
  if ((rxId & 0x1FFFFFFF) == FEEDBACK_ID && len == 8) {
    int16_t rpm2 = (int16_t)((rxBuf[2] << 8) | rxBuf[3]);
    int16_t rpm1 = (int16_t)((rxBuf[4] << 8) | rxBuf[5]);
    float   volt = ((rxBuf[6] << 8) | rxBuf[7]) * 0.1f;
    Serial.print("LFB,");
    Serial.print(rpm1); Serial.print(",");
    Serial.print(rpm2); Serial.print(",");
    Serial.print(rxBuf[0]); Serial.print(",");
    Serial.print(rxBuf[1]); Serial.print(",");
    Serial.println(volt, 1);
  }
}

void setup() {
  Serial.begin(115200);
  SPI.begin();
  delay(500);

  int attempts = 0;
  while (CAN.begin(MCP_ANY, CAN_500KBPS, MCP_8MHZ) != CAN_OK) {
    Serial.println("# CAN init failed, retry...");
    delay(500);
    if (++attempts > 10) {
      Serial.println("# CAN DEAD");
      while (1);
    }
  }
  CAN.setMode(MCP_NORMAL);
  lastReceive = millis();
  Serial.println("# LEFT ready");
}

void loop() {
  readFeedback();
  readSerial();

  unsigned long now = millis();

  if (now - lastReceive > TIMEOUT_MS) {
    targetRPM   = 0;
    brakeActive = false;
  }

  if (now - lastSend >= SEND_INTERVAL) {
    lastSend = now;
    sendCAN(targetRPM);
  }
}
