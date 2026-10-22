#include "SensorSupport.h"

// Change to 0x69 only when AD0 is high.
const uint8_t ADDRESS = 0x68;
const uint32_t MAGIC = 0x314D5549UL;
struct Calibration {
  uint32_t magic;
  uint8_t version, flags;
  float gyroBias[3], accelBias[3], accelGain[3];
  uint16_t crc;
};
Calibration cal;
Frame frame;
Commands commands;
Moments capture;
bool ready = false;
uint32_t sequence = 0, lastSample = 0, retryAt = 0, lastPoll = 0, captureStart = 0;
int8_t captureMode = -1; // -1 idle, 0 gyro, 1..6 accelerometer faces.
uint8_t faceMask = 0;
float faces[6][3];

void defaults() {
  memset(&cal, 0, sizeof(cal));
  for (uint8_t i = 0; i < 3; ++i) cal.accelGain[i] = 1;
}
bool sane() {
  if (cal.flags & ~6) return false;
  for (uint8_t i = 0; i < 3; ++i)
    if (!isfinite(cal.gyroBias[i]) || fabsf(cal.gyroBias[i]) > 1310 ||
        !isfinite(cal.accelBias[i]) || fabsf(cal.accelBias[i]) > 4000 ||
        !isfinite(cal.accelGain[i]) || cal.accelGain[i] < .7 || cal.accelGain[i] > 1.3) return false;
  return true;
}
void status() {
  Serial.print(F("#STATUS,IMU1,CONFIG=")); Serial.print(ready);
  Serial.print(F(",CAL_FLAGS=")); Serial.print(cal.flags);
  Serial.print(F(",FACE_MASK=")); Serial.print(faceMask);
  Serial.print(F(",ACTIVE=")); Serial.println(captureMode);
  for (uint8_t i = 0; i < 3; ++i) {
    Serial.print(F("#COEFF,")); Serial.print(i);
    Serial.print(','); Serial.print(cal.gyroBias[i], 6);
    Serial.print(','); Serial.print(cal.accelBias[i], 6);
    Serial.print(','); Serial.println(cal.accelGain[i], 6);
  }
}
bool configure() {
  uint8_t id;
  if (!readRegs(ADDRESS, 0x75, &id, 1) || id != 0x68) return false;
  if (!writeReg(ADDRESS, 0x6B, 0x80)) return false;
  delay(100);
  // PLL X gyro, all axes enabled, 44/42 Hz low-pass, 50 Hz output.
  if (!writeReg(ADDRESS, 0x6B, 0x01) || !writeReg(ADDRESS, 0x6C, 0) ||
      !writeReg(ADDRESS, 0x1A, 0x03) || !writeReg(ADDRESS, 0x19, 19) ||
      !writeReg(ADDRESS, 0x1B, 0) || !writeReg(ADDRESS, 0x1C, 0) ||
      !writeReg(ADDRESS, 0x38, 1)) return false;
  delay(100);
  return verifyReg(ADDRESS, 0x6B, 1) && verifyReg(ADDRESS, 0x6C, 0) &&
    verifyReg(ADDRESS, 0x1A, 3) && verifyReg(ADDRESS, 0x19, 19) &&
    verifyReg(ADDRESS, 0x1B, 0) && verifyReg(ADDRESS, 0x1C, 0) && verifyReg(ADDRESS, 0x38, 1);
}
void fail(const __FlashStringHelper* reason) {
  ready = false; retryAt = millis(); captureMode = -1; faceMask = 0;
  Serial.print(F("#ERR,")); Serial.print(reason); Serial.println(F(",CAL_ABORTED"));
}
// Saturation is a fresh measurement, not a bus failure. Repositioning may
// exceed the gyro range; never discard accepted faces while capture is idle.
bool acceptRange(const int16_t* raw) {
  for (uint8_t i = 0; i < 7; ++i) {
    if (raw[i] != -32768 && raw[i] != 32767) continue;
    if (captureMode >= 0) {
      captureMode = -1;
      Serial.println(F("#ERR,IMU_SATURATION,CAPTURE_ABORTED"));
    }
    return false;
  }
  return true;
}
void startCapture(int8_t mode) {
  if (!ready || captureMode >= 0) { Serial.println(F("#ERR,NOT_READY_OR_BUSY")); return; }
  capture.clear(); captureMode = mode; captureStart = millis();
  Serial.println(F("#CAL,SETTLE_2S_THEN_HOLD_STILL_4S"));
}
void rejectCapture(const __FlashStringHelper* reason, uint8_t axis, float value, float limit) {
  Serial.print(F("#ERR,")); Serial.print(reason);
  Serial.print(F(",AXIS=")); Serial.print("XYZ"[axis]);
  Serial.print(F(",VALUE=")); Serial.print(value, 2);
  Serial.print(F(",LIMIT=")); Serial.println(limit, 2);
}
void finishCapture() {
  int8_t mode = captureMode; captureMode = -1;
  float norm = 0;
  for (uint8_t i = 0; i < 3; ++i) {
    norm += capture.mean[i] * capture.mean[i];
    if (capture.deviation(i) > 180) {
      rejectCapture(F("CAL_ACCEL_NOISE"), i, capture.deviation(i), 180); return;
    }
    if (capture.deviation(i + 3) > 40) {
      rejectCapture(F("CAL_GYRO_NOISE"), i, capture.deviation(i + 3), 40); return;
    }
    if (fabsf(capture.mean[i + 3]) > 1310) {
      rejectCapture(F("CAL_GYRO_BIAS"), i, fabsf(capture.mean[i + 3]), 1310); return;
    }
  }
  norm = sqrtf(norm) / 16384;
  if (norm < .8 || norm > 1.2) { Serial.println(F("#ERR,CAL_GRAVITY_RANGE")); return; }
  if (mode == 0) {
    for (uint8_t i = 0; i < 3; ++i) cal.gyroBias[i] = capture.mean[i + 3];
    cal.flags |= 2;
    Serial.println(F("#CAL,GYRO_ACCEPTED_RAM,SAVE_REQUIRED")); return;
  }
  uint8_t face = mode - 1, axis = face / 2;
  float sign = face % 2 == 0 ? 1 : -1;
  for (uint8_t i = 0; i < 3; ++i) {
    float g = capture.mean[i] / 16384;
    if ((i == axis && (g * sign < .8 || g * sign > 1.2)) ||
        (i != axis && fabsf(g) > .15)) {
      Serial.println(F("#ERR,FACE_ORIENTATION")); return;
    }
  }
  for (uint8_t i = 0; i < 3; ++i) faces[face][i] = capture.mean[i];
  faceMask |= 1 << face;
  Serial.print(F("#CAL,FACE_ACCEPTED,MASK=")); Serial.println(faceMask);
  if (faceMask != 63) return;
  Calibration candidate = cal;
  for (uint8_t i = 0; i < 3; ++i) {
    float high = faces[i * 2][i], low = faces[i * 2 + 1][i];
    float bias = (high + low) / 2, gain = 32768.0f / (high - low);
    if (!isfinite(gain) || gain < .7 || gain > 1.3 || fabsf(bias) > 4000) {
      Serial.println(F("#ERR,ACCEL_FIT_RANGE")); faceMask = 0; return;
    }
    candidate.accelBias[i] = bias; candidate.accelGain[i] = gain;
  }
  candidate.flags |= 4; cal = candidate; faceMask = 0;
  Serial.println(F("#CAL,ACCEL_ACCEPTED_RAM,SAVE_REQUIRED"));
}
void command(const char* text) {
  if (!strcmp(text, "HELP")) {
    Serial.println(F("#HELP,STATUS|CAL GYRO|CAL ACCEL RESET|CAL ACCEL +X|-X|+Y|-Y|+Z|-Z|ABORT|SAVE|RESET"));
  } else if (!strcmp(text, "STATUS")) status();
  else if (!strcmp(text, "ABORT")) { captureMode = -1; faceMask = 0; Serial.println(F("#CAL,ABORTED")); }
  else if (captureMode >= 0) Serial.println(F("#ERR,CAL_BUSY"));
  else if (!strcmp(text, "CAL GYRO")) startCapture(0);
  else if (!strcmp(text, "CAL ACCEL RESET")) { faceMask = 0; Serial.println(F("#CAL,FACES_CLEARED")); }
  else if (!strncmp(text, "CAL ACCEL ", 10) && strlen(text) == 12) {
    const char* axes = "XYZ"; const char* axis = strchr(axes, text[11]);
    if (!axis || (text[10] != '+' && text[10] != '-')) { Serial.println(F("#ERR,COMMAND")); return; }
    startCapture(1 + (axis - axes) * 2 + (text[10] == '-'));
  } else if (!strcmp(text, "SAVE")) {
    Serial.println(sane() && saveRecord(cal, MAGIC) ? F("#OK,SAVED") : F("#ERR,SAVE"));
  } else if (!strcmp(text, "RESET")) { defaults(); faceMask = 0; Serial.println(F("#OK,DEFAULTS_RAM,SAVE_REQUIRED")); }
  else Serial.println(F("#ERR,UNKNOWN_COMMAND"));
}
void setup() {
  Serial.begin(115200); beginBus();
  if (!loadRecord(cal, MAGIC) || !sane()) { defaults(); Serial.println(F("#BOOT,DEFAULT_CAL")); }
  else Serial.println(F("#BOOT,EEPROM_CAL_LOADED"));
  Serial.println(F("#BOOT,IMU1,50HZ,ACCEL_2G,GYRO_250DPS,CRC16"));
  ready = configure(); lastSample = retryAt = millis(); status();
}
void loop() {
  commands.poll(command);
  uint32_t now = millis();
  if (!ready) {
    if (now - retryAt >= 2000) { retryAt = now; ready = configure(); lastSample = millis(); if (!ready) Serial.println(F("#ERR,IMU_INIT")); }
    return;
  }
  if (captureMode >= 0 && now - captureStart > 10000) { captureMode = -1; Serial.println(F("#ERR,CAL_TIMEOUT")); }
  static uint32_t configCheck = 0;
  if (now - configCheck >= 1000) {
    configCheck = now;
    if (!(verifyReg(ADDRESS, 0x6B, 1) && verifyReg(ADDRESS, 0x1A, 3) && verifyReg(ADDRESS, 0x19, 19) && verifyReg(ADDRESS, 0x1B, 0) && verifyReg(ADDRESS, 0x1C, 0))) { fail(F("IMU_CONFIG_CHECK_FAILED")); return; }
  }
  if (now - lastPoll < 2) return;
  lastPoll = now;
  uint8_t statusByte, bytes[14];
  if (!readRegs(ADDRESS, 0x3A, &statusByte, 1)) { fail(F("IMU_STATUS_READ_FAILED")); return; }
  if (!(statusByte & 1)) { if (now - lastSample > 500) fail(F("IMU_DATA_READY_TIMEOUT")); return; }
  if (!readRegs(ADDRESS, 0x3B, bytes, 14)) { fail(F("IMU_SAMPLE_READ_FAILED")); return; }
  int16_t raw[7];
  for (uint8_t i = 0; i < 7; ++i) raw[i] = (int16_t)(((uint16_t)bytes[i*2] << 8) | bytes[i*2+1]);
  lastSample = now;
  if (!acceptRange(raw)) return;
  if (captureMode >= 0 && now - captureStart >= 2000) {
    int16_t values[6] = {raw[0],raw[1],raw[2],raw[4],raw[5],raw[6]};
    capture.push(values); if (capture.n >= 200) finishCapture();
  }
  frame.begin(F("IMU1")); frame.unsignedField(sequence++); frame.unsignedField(now);
  frame.field(1 | cal.flags | (captureMode >= 0 ? 8 : 0));
  for (uint8_t i = 0; i < 7; ++i) frame.field(raw[i]);
  for (uint8_t i = 0; i < 3; ++i) frame.field(lroundf((raw[i] - cal.accelBias[i]) * cal.accelGain[i] * (1000.0f / 16384)));
  for (uint8_t i = 0; i < 3; ++i) frame.field(lroundf((raw[i+4] - cal.gyroBias[i]) * (1000.0f / 131)));
  frame.end();
}
