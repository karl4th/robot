#pragma once
#include <stdint.h>
#include <cstring>
class FakeEEPROM {
public:
  uint8_t data[1024] = {};
  template<typename T> void get(int at, T& value) { memcpy(&value, data + at, sizeof(T)); }
  void update(int at, uint8_t value) { data[at] = value; }
};
extern FakeEEPROM EEPROM;
