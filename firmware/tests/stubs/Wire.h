#pragma once
#include <stdint.h>
class FakeWire {
public:
  void begin() {}
  void setClock(long) {}
  void setWireTimeout(long, bool) {}
  void clearWireTimeoutFlag() {}
  bool getWireTimeoutFlag() { return false; }
  void beginTransmission(uint8_t) {}
  void write(uint8_t) {}
  uint8_t endTransmission(bool) { return 4; }
  uint8_t requestFrom(uint8_t, uint8_t, uint8_t) { return 0; }
  int available() { return 0; }
  int read() { return -1; }
};
extern FakeWire Wire;
