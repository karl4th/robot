#include "SensorSupport.h"

const uint8_t ADDRESS = 0x0D;
const uint32_t MAGIC = 0x3147414DUL;
// Continuous, 50 Hz, +/-8 gauss, OSR 512.
const uint8_t CONTROL = 0x15;
struct Calibration {
  uint32_t magic;
  uint8_t version, flags;
  float bias[3], gain[3];
  uint16_t crc;
};
Calibration cal;
Frame frame;
Commands commands;
bool ready = false, collecting = false;
uint32_t sequence = 0, lastSample = 0, lastPoll = 0, retryAt = 0, startTime = 0;
uint16_t count = 0;
int16_t minimum[3], maximum[3], cloud[96][3];
uint8_t cloudCount = 0;
uint8_t lastCloudBin = 255;
const uint32_t CAPTURE_MS = 60000;
const uint16_t CLOUD_BIN_MS = 625; // 96 time bins span the entire capture.

void collectSample(const int16_t* raw, uint32_t now) {
  ++count;
  for (uint8_t i = 0; i < 3; ++i) {
    minimum[i] = min(minimum[i], raw[i]); maximum[i] = max(maximum[i], raw[i]);
  }
  uint32_t elapsed = now - startTime;
  if (elapsed >= CAPTURE_MS) return;
  uint8_t bin = elapsed / CLOUD_BIN_MS;
  // Retain one sample per time bin. Later motion cannot erase early coverage.
  if (bin == lastCloudBin || cloudCount >= 96) return;
  for (uint8_t i = 0; i < 3; ++i) cloud[cloudCount][i] = raw[i];
  ++cloudCount;
  lastCloudBin = bin;
}

void defaults() {
  memset(&cal, 0, sizeof(cal));
  for (uint8_t i = 0; i < 3; ++i) cal.gain[i] = 1;
}
bool sane() {
  if (cal.flags & ~2) return false;
  for (uint8_t i = 0; i < 3; ++i)
    if (!isfinite(cal.bias[i]) || fabsf(cal.bias[i]) > 20000 ||
        !isfinite(cal.gain[i]) || cal.gain[i] < .5 || cal.gain[i] > 2) return false;
  return true;
}
void status() {
  Serial.print(F("#STATUS,MAG1,CONFIG=")); Serial.print(ready);
  Serial.print(F(",CAL_FLAGS=")); Serial.print(cal.flags);
  Serial.print(F(",ACTIVE=")); Serial.print(collecting);
  Serial.print(F(",COUNT=")); Serial.println(count);
  for (uint8_t i = 0; i < 3; ++i) {
    Serial.print(F("#COEFF,")); Serial.print(i);
    Serial.print(','); Serial.print(cal.bias[i], 6);
    Serial.print(','); Serial.println(cal.gain[i], 6);
  }
}
bool configure() {
  uint8_t id;
  if (!readRegs(ADDRESS, 0x0D, &id, 1) || id != 0xFF) return false;
  if (!writeReg(ADDRESS, 0x0A, 0x80)) return false;
  delay(20);
  if (!writeReg(ADDRESS, 0x0B, 1) || !writeReg(ADDRESS, 0x0A, 0) || !writeReg(ADDRESS, 0x09, CONTROL)) return false;
  delay(20);
  return verifyReg(ADDRESS, 0x0B, 1) && verifyReg(ADDRESS, 0x09, CONTROL) && verifyReg(ADDRESS, 0x0A, 0);
}
void fail() {
  ready = false; retryAt = millis(); collecting = false;
  Serial.println(F("#ERR,MAG_IO_OR_DATA_TIMEOUT,CAL_ABORTED"));
}
void startCalibration() {
  if (!ready) { Serial.println(F("#ERR,NOT_READY")); return; }
  collecting = true; startTime = millis(); count = 0; cloudCount = 0; lastCloudBin = 255;
  for (uint8_t i = 0; i < 3; ++i) { minimum[i] = 32767; maximum[i] = -32768; }
  Serial.println(F("#CAL,ROTATE_ALL_AXES_60S,MINIMUM_60S"));
}
void finishCalibration() {
  collecting = false;
  if (millis() - startTime < CAPTURE_MS || count < 1000 || cloudCount < 96) {
    Serial.println(F("#ERR,CAL_TOO_SHORT")); return;
  }
  Calibration candidate = cal;
  float radius[3], average = 0;
  for (uint8_t i = 0; i < 3; ++i) {
    radius[i] = ((float)maximum[i] - minimum[i]) / 2;
    if (radius[i] < 200 || radius[i] > 15000) { Serial.println(F("#ERR,CAL_AXIS_COVERAGE")); return; }
    candidate.bias[i] = ((float)maximum[i] + minimum[i]) / 2;
    if (fabsf(candidate.bias[i]) > 20000) { Serial.println(F("#ERR,CAL_FIELD_BIAS")); return; }
    average += radius[i] / 3;
  }
  for (uint8_t i = 0; i < 3; ++i) {
    candidate.gain[i] = average / radius[i];
    if (candidate.gain[i] < .5 || candidate.gain[i] > 2) { Serial.println(F("#ERR,CAL_DISTORTION")); return; }
  }
  uint8_t octants = 0;
  float residual = 0;
  for (uint8_t n = 0; n < cloudCount; ++n) {
    float norm = 0; uint8_t octant = 0;
    for (uint8_t i = 0; i < 3; ++i) {
      float v = (cloud[n][i] - candidate.bias[i]) / radius[i];
      if (v > 0) octant |= 1 << i;
      norm += v * v;
    }
    octants |= 1 << octant;
    float error = sqrtf(norm) - 1;
    residual += error * error;
  }
  float rms = sqrtf(residual / cloudCount);
  uint8_t covered = 0;
  for (uint8_t i = 0; i < 8; ++i) if (octants & (1 << i)) ++covered;
  if (octants != 255 || rms > .15) {
    Serial.print(octants != 255 ? F("#ERR,CAL_COVERAGE") : F("#ERR,CAL_RESIDUAL"));
    Serial.print(F(",OCTANTS=")); Serial.print(covered); Serial.print(F("/8,MASK=")); Serial.print(octants);
    Serial.print(F(",RMS=")); Serial.print(rms, 4); Serial.println(F(",LIMIT=0.1500"));
    return;
  }
  candidate.flags = 2; cal = candidate;
  Serial.print(F("#CAL,MAG_ACCEPTED_RAM,RMS=")); Serial.print(rms, 4);
  Serial.println(F(",SAVE_REQUIRED"));
}
void command(const char* text) {
  if (!strcmp(text, "HELP")) Serial.println(F("#HELP,STATUS|CAL START|CAL STOP|ABORT|SAVE|RESET"));
  else if (!strcmp(text, "STATUS")) status();
  else if (!strcmp(text, "ABORT")) { collecting = false; Serial.println(F("#CAL,ABORTED")); }
  else if (!strcmp(text, "CAL STOP") && collecting) finishCalibration();
  else if (collecting) Serial.println(F("#ERR,CAL_BUSY"));
  else if (!strcmp(text, "CAL START")) startCalibration();
  else if (!strcmp(text, "SAVE")) Serial.println(sane() && saveRecord(cal, MAGIC) ? F("#OK,SAVED") : F("#ERR,SAVE"));
  else if (!strcmp(text, "RESET")) { defaults(); Serial.println(F("#OK,DEFAULTS_RAM,SAVE_REQUIRED")); }
  else Serial.println(F("#ERR,UNKNOWN_COMMAND"));
}
void setup() {
  Serial.begin(115200); beginBus();
  if (!loadRecord(cal, MAGIC) || !sane()) { defaults(); Serial.println(F("#BOOT,DEFAULT_CAL")); }
  else Serial.println(F("#BOOT,EEPROM_CAL_LOADED"));
  Serial.println(F("#BOOT,MAG1,50HZ,RANGE_8G,CRC16"));
  ready = configure(); retryAt = lastSample = millis(); status();
}
void loop() {
  commands.poll(command);
  uint32_t now = millis();
  if (!ready) {
    if (now - retryAt >= 2000) { retryAt = now; ready = configure(); lastSample = millis(); if (!ready) Serial.println(F("#ERR,MAG_INIT")); }
    return;
  }
  if (collecting && now - startTime >= CAPTURE_MS) finishCalibration();
  static uint32_t configCheck = 0;
  if (now - configCheck >= 1000) {
    configCheck = now;
    if (!(verifyReg(ADDRESS, 0x0B, 1) && verifyReg(ADDRESS, 0x09, CONTROL))) { fail(); return; }
  }
  if (now - lastPoll < 2) return;
  lastPoll = now;
  uint8_t statusByte, bytes[6];
  if (!readRegs(ADDRESS, 0x06, &statusByte, 1)) { fail(); return; }
  if (statusByte & 2) {
    // Drain invalid data to clear overflow, but never publish it.
    if (!readRegs(ADDRESS, 0, bytes, 6)) { fail(); return; }
    collecting = false;
    if (now - lastSample > 500) fail();
    else Serial.println(F("#ERR,MAG_OVERFLOW,CAL_ABORTED"));
    return;
  }
  if (!(statusByte & 1)) { if (now - lastSample > 500) fail(); return; }
  if (!readRegs(ADDRESS, 0, bytes, 6)) { fail(); return; }
  int16_t raw[3];
  for (uint8_t i = 0; i < 3; ++i) {
    raw[i] = (int16_t)((uint16_t)bytes[i*2] | ((uint16_t)bytes[i*2+1] << 8));
    if (raw[i] == -32768 || raw[i] == 32767) { fail(); return; }
  }
  lastSample = now;
  if (collecting) collectSample(raw, now);
  frame.begin(F("MAG1")); frame.unsignedField(sequence++); frame.unsignedField(now);
  frame.field(1 | cal.flags | (collecting ? 8 : 0) | ((statusByte & 4) ? 16 : 0));
  for (uint8_t i = 0; i < 3; ++i) frame.field(raw[i]);
  for (uint8_t i = 0; i < 3; ++i) frame.field(lroundf((raw[i] - cal.bias[i]) * cal.gain[i] * (100000.0f / 3000)));
  frame.end();
}
