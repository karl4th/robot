#pragma once
#include <Arduino.h>
#include <Wire.h>
#include <EEPROM.h>
#include <math.h>
#include <stddef.h>

#if !defined(__AVR_ATmega328P__)
#error "This sketch targets ATmega328P boards."
#endif

inline uint16_t crcByte(uint16_t crc, uint8_t value) {
  crc ^= (uint16_t)value << 8;
  for (uint8_t i = 0; i < 8; ++i)
    crc = (crc & 0x8000) ? (crc << 1) ^ 0x1021 : crc << 1;
  return crc;
}
inline uint16_t crcBytes(const uint8_t* data, size_t size) {
  uint16_t crc = 0xFFFF;
  while (size--) crc = crcByte(crc, *data++);
  return crc;
}

class Frame : public Print {
  uint16_t crc;
public:
  size_t write(uint8_t value) override {
    crc = crcByte(crc, value);
    return Serial.write(value);
  }
  void begin(const __FlashStringHelper* tag) { crc = 0xFFFF; print(tag); }
  void field(long value) { print(','); print(value); }
  void unsignedField(uint32_t value) { print(','); print(value); }
  void end() {
    Serial.write('*');
    const char hex[] = "0123456789ABCDEF";
    for (int8_t shift = 12; shift >= 0; shift -= 4) Serial.write(hex[(crc >> shift) & 15]);
    Serial.println();
  }
};

inline bool writeReg(uint8_t address, uint8_t reg, uint8_t value) {
  Wire.clearWireTimeoutFlag();
  Wire.beginTransmission(address); Wire.write(reg); Wire.write(value);
  uint8_t result = Wire.endTransmission(true);
  return result == 0 && !Wire.getWireTimeoutFlag();
}
inline bool readRegs(uint8_t address, uint8_t reg, uint8_t* data, uint8_t count) {
  Wire.clearWireTimeoutFlag();
  Wire.beginTransmission(address); Wire.write(reg);
  if (Wire.endTransmission(false) != 0 || Wire.getWireTimeoutFlag()) return false;
  uint8_t received = Wire.requestFrom(address, count, (uint8_t)true);
  if (received != count || Wire.getWireTimeoutFlag()) {
    while (Wire.available()) Wire.read();
    return false;
  }
  for (uint8_t i = 0; i < count; ++i) data[i] = Wire.read();
  return true;
}
inline bool verifyReg(uint8_t address, uint8_t reg, uint8_t expected) {
  uint8_t value;
  return readRegs(address, reg, &value, 1) && value == expected;
}
inline void beginBus() {
  Wire.begin(); Wire.setClock(100000); Wire.setWireTimeout(25000, true);
}

// The record is invalidated before writing. Interrupted writes load defaults.
// Calibration is not automatically written during acquisition.
template <typename T> bool loadRecord(T& record, uint32_t magic) {
  EEPROM.get(0, record);
  return record.magic == magic && record.version == 1 &&
    record.crc == crcBytes((const uint8_t*)&record, offsetof(T, crc));
}
template <typename T> bool saveRecord(T& record, uint32_t magic) {
  record.magic = magic; record.version = 1;
  record.crc = crcBytes((const uint8_t*)&record, offsetof(T, crc));
  EEPROM.update(0, 0);
  const uint8_t* bytes = (const uint8_t*)&record;
  for (size_t i = 1; i < sizeof(T); ++i) EEPROM.update(i, bytes[i]);
  EEPROM.update(0, bytes[0]);
  T check;
  return loadRecord(check, magic) && memcmp(&record, &check, sizeof(T)) == 0;
}

class Commands {
  char line[40];
  uint8_t length = 0;
  bool overflow = false;
public:
  void poll(void (*handler)(const char*)) {
    // Bound each pass so command flooding cannot starve acquisition.
    for (uint8_t budget = 0; budget < 48 && Serial.available(); ++budget) {
      char c = Serial.read();
      if (c == '\r' || c == '\n') {
        if (overflow) Serial.println(F("#ERR,COMMAND_TOO_LONG"));
        else if (length) { line[length] = 0; handler(line); }
        length = 0; overflow = false;
      } else if (!overflow) {
        if (length < sizeof(line) - 1) line[length++] = c;
        else overflow = true;
      }
    }
  }
};

struct Moments {
  uint16_t n;
  float mean[6], m2[6];
  void clear() { memset(this, 0, sizeof(*this)); }
  void push(const int16_t* values) {
    ++n;
    for (uint8_t i = 0; i < 6; ++i) {
      float delta = values[i] - mean[i];
      mean[i] += delta / n;
      m2[i] += delta * (values[i] - mean[i]);
    }
  }
  float deviation(uint8_t i) const { return n > 1 ? sqrtf(m2[i] / (n - 1)) : 0; }
};
