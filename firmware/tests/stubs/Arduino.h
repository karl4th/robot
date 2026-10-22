#pragma once
#include <stdint.h>
#include <stddef.h>
#include <cstring>
#include <string>
#include <sstream>
#include <iomanip>
#include <algorithm>
using std::min;
using std::max;
class __FlashStringHelper;
#define F(s) reinterpret_cast<const __FlashStringHelper*>(s)
extern uint32_t fakeTime;
inline uint32_t millis() { return fakeTime; }
inline void delay(uint32_t value) { fakeTime += value; }
class Print {
public:
  virtual ~Print() = default;
  virtual size_t write(uint8_t value) = 0;
  void print(char value) { write(value); }
  void print(const char* value) { while (*value) write(*value++); }
  void print(const __FlashStringHelper* value) { print(reinterpret_cast<const char*>(value)); }
  template<typename T> void print(T value) { std::ostringstream s; s << +value; print(s.str().c_str()); }
  void print(float value, int digits) { std::ostringstream s; s << std::fixed << std::setprecision(digits) << value; print(s.str().c_str()); }
  void println() { print('\n'); }
  template<typename T> void println(T value) { print(value); println(); }
  void println(float value, int digits) { print(value, digits); println(); }
};
class FakeSerial : public Print {
public:
  std::string output;
  size_t write(uint8_t value) override { output += char(value); return 1; }
  void begin(long) {}
  int available() { return 0; }
  int read() { return -1; }
};
extern FakeSerial Serial;
