#include <cassert>
#include "../mpu6050_calibration/mpu6050_calibration.ino"
uint32_t fakeTime = 0;
FakeSerial Serial;
FakeWire Wire;
FakeEEPROM EEPROM;

void fill(int16_t ax, int16_t ay, int16_t az, int16_t gx=100, int16_t gy=-200, int16_t gz=50) {
  capture.clear();
  int16_t values[6] = {ax,ay,az,gx,gy,gz};
  for (int i=0; i<200; ++i) capture.push(values);
}
int main() {
  defaults(); ready = true;
  fill(0,0,16384); captureMode=0; finishCapture();
  assert(cal.flags==2 && cal.gyroBias[1]==-200);
  Calibration before=cal;
  fill(0,0,16384); capture.m2[3]=10000000; captureMode=0; finishCapture();
  assert(!memcmp(&before,&cal,sizeof(cal)));
  for (int face=0;face<6;++face) {
    int16_t a[3]={100,-200,300}; a[face/2] += face%2 ? -16000 : 16000;
    fill(a[0],a[1],a[2]); captureMode=face+1; finishCapture();
  }
  assert(cal.flags==6 && faceMask==0);
  assert(fabs(cal.accelBias[0]-100)<.01 && fabs(cal.accelGain[0]-1.024)<.0001);
  before=cal;
  fill(0,0,16384); captureMode=1; finishCapture(); // Wrong face.
  assert(faceMask==0 && !memcmp(&before,&cal,sizeof(cal)));
  assert(saveRecord(cal,MAGIC)); defaults(); assert(loadRecord(cal,MAGIC) && sane());
  EEPROM.data[12]^=1; assert(!loadRecord(cal,MAGIC));
  assert(crcBytes((const uint8_t*)"123456789",9)==0x29B1);
  Serial.output.clear(); frame.begin(F("MAG1")); frame.unsignedField(1); frame.end();
  std::string body="MAG1,1"; uint16_t crc=crcBytes((const uint8_t*)body.c_str(),body.size());
  assert(Serial.output.find("MAG1,1*")==0 && crc!=0);
  // Distinguish acceleration noise, gyro noise and mean-bias rejection.
  for (int kind=0; kind<3; ++kind) {
    fill(0,0,16384); faceMask=3; captureMode=3; Serial.output.clear();
    if (kind==0) capture.m2[0]=200.0f*200*199;
    if (kind==1) capture.m2[3]=50.0f*50*199;
    if (kind==2) capture.mean[3]=1400;
    before=cal; finishCapture();
    const char* reason=kind==0 ? "CAL_ACCEL_NOISE" : kind==1 ? "CAL_GYRO_NOISE" : "CAL_GYRO_BIAS";
    assert(Serial.output.find(reason)!=std::string::npos);
    assert(Serial.output.find("AXIS=X,VALUE=")!=std::string::npos);
    assert(faceMask==3 && !memcmp(&before,&cal,sizeof(cal)));
  }
  assert(!configure()); // I2C failure never reports ready.
  // A fast turn between faces must not look like an I2C/data timeout.
  ready=true; faceMask=1; captureMode=-1; before=cal;
  int16_t raw[7]={16384,0,0,0,32767,0,0};
  Serial.output.clear();
  assert(!acceptRange(raw));
  assert(ready && faceMask==1 && captureMode==-1);
  assert(Serial.output.empty() && !memcmp(&before,&cal,sizeof(cal)));
  raw[4]=-32768;
  assert(!acceptRange(raw) && faceMask==1 && ready);
  captureMode=2;
  assert(!acceptRange(raw) && captureMode==-1 && faceMask==1 && ready);
  assert(Serial.output.find("IMU_SATURATION,CAPTURE_ABORTED")!=std::string::npos);
  raw[4]=0;
  assert(acceptRange(raw));
  fail(F("IMU_STATUS_READ_FAILED"));
  assert(!ready && faceMask==0);
  assert(Serial.output.find("IMU_STATUS_READ_FAILED,CAL_ABORTED")!=std::string::npos);
}
