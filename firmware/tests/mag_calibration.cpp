#include <cassert>
#include "../qmc5883l_calibration/qmc5883l_calibration.ino"
uint32_t fakeTime = 0;
FakeSerial Serial;
FakeWire Wire;
FakeEEPROM EEPROM;
void fixture() {
  count=2000; cloudCount=96; startTime=0; fakeTime=60000; collecting=true;
  const int bias[3]={300,-200,100}, radius[3]={1000,1200,800};
  for(int i=0;i<3;++i) { minimum[i]=bias[i]-radius[i]; maximum[i]=bias[i]+radius[i]; }
  for(int n=0;n<96;++n) for(int i=0;i<3;++i)
    cloud[n][i]=bias[i]+lroundf(((n%8)&(1<<i)?1:-1)*radius[i]/sqrtf(3));
}
int main() {
  defaults(); fixture(); finishCalibration();
  assert(cal.flags==2 && fabs(cal.bias[0]-300)<.01 && fabs(cal.gain[2]-1.25)<.001);
  Calibration before=cal;
  fixture(); count=50; finishCalibration(); assert(!memcmp(&before,&cal,sizeof(cal)));
  fixture(); for(int n=0;n<96;++n) cloud[n][0]=900;
  finishCalibration(); assert(!memcmp(&before,&cal,sizeof(cal)));
  fixture(); maximum[2]=minimum[2]+20;
  finishCalibration(); assert(!memcmp(&before,&cal,sizeof(cal)));
  fixture(); for(int n=0;n<96;++n) for(int i=0;i<3;++i) cloud[n][i]*=2;
  finishCalibration(); assert(!memcmp(&before,&cal,sizeof(cal)));
  assert(saveRecord(cal,MAGIC)); assert(loadRecord(cal,MAGIC) && sane());
  EEPROM.data[0]=0; assert(!loadRecord(cal,MAGIC));
  assert(!configure());
  // Late samples must not evict directions captured in the first half.
  ready=true;fakeTime=0;startCalibration();
  for (uint32_t t=0;t<60000;t+=20) {
    int16_t raw[3]={(int16_t)(t/625),100,200};
    collectSample(raw,t);
  }
  assert(count==3000 && cloudCount==96);
  for (int i=0;i<96;++i) assert(cloud[i][0]==i);
  // Reject an incomplete time span, preserving the existing calibration.
  before=cal;fakeTime=30000;Serial.output.clear();finishCalibration();
  assert(Serial.output.find("CAL_TOO_SHORT")!=std::string::npos);
  assert(!memcmp(&before,&cal,sizeof(cal)));
  // Coverage diagnostics and residual diagnostics are independently visible.
  fixture(); for(int n=0;n<96;++n) cloud[n][0]=900;
  Serial.output.clear();finishCalibration();
  assert(Serial.output.find("#ERR,CAL_COVERAGE,OCTANTS=4/8")!=std::string::npos);
  fixture();for(int n=0;n<96;++n)for(int i=0;i<3;++i)
    cloud[n][i]=(int16_t)((minimum[i]+maximum[i])/2 + (cloud[n][i]-(minimum[i]+maximum[i])/2)*1.5f);
  Serial.output.clear();finishCalibration();
  assert(Serial.output.find("#ERR,CAL_RESIDUAL,OCTANTS=8/8")!=std::string::npos);
  assert(!memcmp(&before,&cal,sizeof(cal)));
  // Start of another run clears only acquisition state, not saved corrections.
  fakeTime=70000;startCalibration();assert(cloudCount==0 && lastCloudBin==255);
  assert(!memcmp(&before,&cal,sizeof(cal)));
}
