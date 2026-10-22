const $ = id => document.getElementById(id);
const canvas = $('map'), ctx = canvas.getContext('2d');
let scan = {points:[],live:false}, range = 4, perspective = false, frozen = false, heading = 0;
let received = 0;
const fmt = n => n.toLocaleString('en-US');
function robot(x,y){
 ctx.save();ctx.translate(x,y);ctx.shadowColor='#25382330';ctx.shadowBlur=18;ctx.shadowOffsetY=8;
 ctx.fillStyle='#263b30';for(const a of [-1,1])for(const b of [-1,1]){ctx.beginPath();ctx.roundRect(a*38-8,b*23-12,16,24,5);ctx.fill();}
 ctx.shadowBlur=0;ctx.shadowOffsetY=0;
 const g=ctx.createLinearGradient(-26,-36,26,35);g.addColorStop(0,'#fce88c');g.addColorStop(1,'#dcb02d');ctx.fillStyle=g;ctx.strokeStyle='#c6a12f';ctx.lineWidth=1;ctx.beginPath();ctx.roundRect(-35,-35,70,70,11);ctx.fill();ctx.stroke();
 ctx.strokeStyle='#fff4bf';ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(-16,-26);ctx.lineTo(16,-26);ctx.stroke();ctx.fillStyle='#d3ab36';ctx.beginPath();ctx.roundRect(-18,17,36,11,4);ctx.fill();ctx.fillStyle='#263e32';ctx.beginPath();ctx.arc(0,-2,13,0,Math.PI*2);ctx.fill();ctx.fillStyle='#64816a';ctx.beginPath();ctx.arc(0,-3,7,0,Math.PI*2);ctx.fill();ctx.fillStyle='#f6e7a0';ctx.beginPath();ctx.arc(-2,-5,2,0,Math.PI*2);ctx.fill();ctx.restore();
}
function draw(){
 const rect=canvas.getBoundingClientRect(),w=rect.width,h=rect.height,dpr=window.devicePixelRatio||1;
 if(canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)){canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);}
 ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
 const cx=w/2,cy=h*.53,scale=Math.min(w,h)*.41/range,sy=perspective?.60:1;
 const project=(x,y)=>[cx+x*scale,cy-y*scale*sy];
 ctx.strokeStyle='#c6d3bc65';ctx.lineWidth=1;
 const extent=Math.ceil(Math.max(w,h)/scale);
 for(let n=-extent;n<=extent;n++){ctx.beginPath();ctx.moveTo(...project(n,-extent));ctx.lineTo(...project(n,extent));ctx.stroke();ctx.beginPath();ctx.moveTo(...project(-extent,n));ctx.lineTo(...project(extent,n));ctx.stroke();}
 for(let r=1;r<=range;r++){ctx.strokeStyle='#9eb38f55';ctx.setLineDash([3,5]);ctx.beginPath();ctx.ellipse(cx,cy,r*scale,r*scale*sy,0,0,Math.PI*2);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#97a78c';ctx.font='10px system-ui';ctx.fillText(r+' m',cx+7,cy-r*scale*sy-5);}
 const glow=ctx.createRadialGradient(cx,cy,10,cx,cy,Math.min(w,h)*.4);glow.addColorStop(0,'#f5f8ed88');glow.addColorStop(1,'#f5f8ed00');ctx.fillStyle=glow;ctx.fillRect(0,0,w,h);
 let nearest=null;
 const points=(scan.live||frozen)?scan.points:[];
 for(const p of points){const angle=(p[0]+heading)*Math.PI/180,dist=p[1]/1000;if(!nearest||dist<nearest.dist)nearest={dist,angle:p[0]};const [x,y]=project(Math.sin(angle)*dist,Math.cos(angle)*dist);ctx.fillStyle=p[2]>100?'#3c6d50':'#729777';ctx.globalAlpha=.45+Math.min(p[2]/255,.55);ctx.beginPath();ctx.arc(x,y,2,0,Math.PI*2);ctx.fill();}
 ctx.globalAlpha=1;
 ctx.strokeStyle='#91a080';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(cx,cy-61);ctx.lineTo(cx,cy-78);ctx.moveTo(cx-4,cy-73);ctx.lineTo(cx,cy-78);ctx.lineTo(cx+4,cy-73);ctx.stroke();ctx.fillStyle='#849579';ctx.font='9px system-ui';ctx.textAlign='center';ctx.fillText('FRONT',cx,cy-88);ctx.textAlign='left';robot(cx,cy);
 $('nearest').textContent=nearest?nearest.dist.toFixed(2):'—';$('bearing').textContent=nearest?`Raw return at ${((nearest.angle+heading+360)%360).toFixed(0)}° · unfiltered`:'Waiting for measurements';
}
function update(){
 $('status').textContent=scan.live?'SENSOR LIVE':'SENSOR OFFLINE';$('dot').classList.toggle('live',scan.live);
 $('hz').innerHTML=(scan.live?scan.hz.toFixed(2):'—')+'<small>Hz</small>';
 $('returns').textContent=fmt(scan.points.length);$('packets').textContent=fmt(scan.packets||0);$('crc').textContent=fmt(scan.crc_errors||0);$('age').textContent=scan.age_ms==null?'—':scan.age_ms+' ms';$('port').textContent=scan.port||'Detecting device…';
 $('notice').textContent=frozen?'VIEW FROZEN · Showing a captured scan':scan.live?'':scan.error||'Waiting for sensor data…';draw();
}
async function poll(){
 try{const response=await fetch('/api/scan',{signal:AbortSignal.timeout(2000)});if(!response.ok)throw Error('Server unavailable');const next=await response.json();received=Date.now();if(!frozen){scan=next;update();}else{$('status').textContent=next.live?'SENSOR LIVE · VIEW FROZEN':'SENSOR OFFLINE · VIEW FROZEN';$('dot').classList.toggle('live',next.live);}}
 catch(error){$('status').textContent='DISCONNECTED';$('dot').classList.remove('live');if(!frozen){scan={...scan,live:false,points:[],error:'Dashboard disconnected. Check the local server.'};update();}}
 setTimeout(poll,80);
}
$('in').onclick=()=>{range=Math.max(1,range-1);$('range').textContent=range+' m';draw();};
$('out').onclick=()=>{range=Math.min(12,range+1);$('range').textContent=range+' m';draw();};
function view(value){perspective=value;$('top').classList.toggle('active',!value);$('perspective').classList.toggle('active',value);draw();}
$('top').onclick=()=>view(false);$('perspective').onclick=()=>view(true);
$('heading').oninput=e=>{heading=Number(e.target.value);$('heading-value').textContent=heading+'°';draw();};
$('pause').onclick=()=>{frozen=!frozen;$('pause').textContent=frozen?'Resume live':'Freeze view';if(!frozen){scan={...scan,live:false,points:[]};}update();};
$('reset').onclick=()=>{range=4;heading=0;$('heading').value=0;$('heading-value').textContent='0°';$('range').textContent='4 m';view(false);};
new ResizeObserver(draw).observe(canvas);setInterval(()=>{$('clock').textContent=new Date().toLocaleTimeString('en-GB');if(!frozen&&Date.now()-received>2500&&scan.live){scan.live=false;scan.points=[];scan.error='Waiting for fresh sensor data';update();}},500);poll();

let gps = {status:'offline',track:[]};
const gpsCanvas=$('gps-track'), gc=gpsCanvas.getContext('2d');
function gpsTrack(){
 const r=gpsCanvas.getBoundingClientRect(), w=r.width,h=r.height,dpr=devicePixelRatio||1;
 gpsCanvas.width=Math.round(w*dpr);gpsCanvas.height=Math.round(h*dpr);gc.setTransform(dpr,0,0,dpr,0,0);
 gc.clearRect(0,0,w,h);gc.strokeStyle='#cfdbc5';gc.lineWidth=1;
 for(let x=0;x<w;x+=30){gc.beginPath();gc.moveTo(x,0);gc.lineTo(x,h);gc.stroke();}
 for(let y=0;y<h;y+=30){gc.beginPath();gc.moveTo(0,y);gc.lineTo(w,y);gc.stroke();}
 gc.fillStyle='#829775';gc.font='10px system-ui';gc.fillText('N ↑',w-38,25);
 const track=gps.track||[];
 if(!track.length){gc.textAlign='center';gc.fillText('Track begins with a valid fix',w/2,h/2);gc.textAlign='left';$('gps-scale').textContent='Waiting for fix';return;}
 const [lat,lon]=track[0], rad=Math.PI/180;
 const xy=track.map(p=>[(((p[1]-lon+540)%360)-180)*111320*Math.cos(lat*rad),(p[0]-lat)*111320,p[2]]);
 const xs=xy.map(p=>p[0]),ys=xy.map(p=>p[1]);const xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys);
 const scale=Math.min((w-65)/Math.max(20,xmax-xmin),(h-80)/Math.max(20,ymax-ymin));
 const project=p=>[w/2+(p[0]-(xmin+xmax)/2)*scale,h/2-(p[1]-(ymin+ymax)/2)*scale];
 gc.strokeStyle='#6a8c66';gc.lineWidth=2;gc.beginPath();xy.forEach((p,i)=>{const q=project(p);if(!i||p[2]!==xy[i-1][2])gc.moveTo(...q);else gc.lineTo(...q);});gc.stroke();
 const start=project(xy[0]),end=project(xy.at(-1));gc.fillStyle='#91aa82';gc.beginPath();gc.arc(...start,3,0,Math.PI*2);gc.fill();gc.fillStyle=gps.status==='live'?'#d7b542':'#a2ac9b';gc.strokeStyle='#fff';gc.lineWidth=2;gc.beginPath();gc.arc(...end,6,0,Math.PI*2);gc.fill();gc.stroke();
 $('gps-scale').textContent=`${((w-65)/scale).toFixed(0)} m across · ${track.length} fixes${gps.status==='live'?'':' · historical'}`;
}
function gpsUpdate(){
 const live=gps.status==='live';const labels={live:'GPS FIX',no_fix:'NO FIX',offline:'OFFLINE',disabled:'NOT CONFIGURED'};
 const weak=live&&gps.hdop!=null&&gps.hdop>5;
 $('gps-status').textContent=weak?'WEAK GEOMETRY':labels[gps.status]||'OFFLINE';$('gps-status').classList.toggle('live',live&&!weak);
 const value=(v,d=1,s='')=>v==null?'—':v.toFixed(d)+s;
 $('gps-lat').textContent=live?value(gps.latitude,6,'°'):'—';$('gps-lon').textContent=live?value(gps.longitude,6,'°'):'—';
 $('gps-sats').textContent=gps.satellites??'—';$('gps-speed').textContent=value(gps.speed_kmh,1,' km/h');$('gps-hdop').textContent=value(gps.hdop);$('gps-alt').textContent=value(gps.altitude_m,1,' m');$('gps-course').textContent=value(gps.course_deg,0,'°');$('gps-age').textContent=gps.age_ms==null?'—':(gps.age_ms/1000).toFixed(1)+' s';$('gps-port').textContent=gps.port||'Set --gps-port to connect';
 const quality={1:'Autonomous fix',2:'Differential fix',4:'Fixed solution',5:'Float solution'};
 $('gps-note').textContent=live?`${quality[gps.quality]||'Valid fix'} · ${weak?'High HDOP: position and speed may drift.':'Live GPS independent of lidar freeze.'}`:gps.status==='no_fix'?'Receiver connected. Waiting for a valid satellite fix.':gps.error||'GPS connection lost. Historical track retained.';gpsTrack();
}
async function pollGPS(){
 try{const response=await fetch('/api/gps',{signal:AbortSignal.timeout(2000)});if(!response.ok)throw Error('GPS unavailable');gps=await response.json();}
 catch{gps={status:'offline',track:gps.track||[],port:gps.port,error:'GPS connection lost. Check the local server.'};}
 gpsUpdate();setTimeout(pollGPS,500);
}
new ResizeObserver(gpsTrack).observe(gpsCanvas);pollGPS();

let imu={status:'offline',sample:null};
const tiltCanvas=$('imu-tilt'),tc=tiltCanvas.getContext('2d');
function drawTilt(){
 const r=tiltCanvas.getBoundingClientRect(),w=r.width,h=r.height,dpr=devicePixelRatio||1;
 tiltCanvas.width=Math.round(w*dpr);tiltCanvas.height=Math.round(h*dpr);tc.setTransform(dpr,0,0,dpr,0,0);
 const s=imu.sample,valid=imu.status==='live'&&s&&s.roll_deg!=null&&s.pitch_deg!=null;
 tc.clearRect(0,0,w,h);tc.save();tc.translate(w/2,h/2+5);const radius=Math.min(w*.38,h*.34);
 tc.beginPath();tc.arc(0,0,radius,0,2*Math.PI);tc.clip();tc.fillStyle='#e1e9d8';tc.fillRect(-radius,-radius,2*radius,2*radius);
 if(valid){tc.rotate(-s.roll_deg*Math.PI/180);tc.translate(0,s.pitch_deg*radius/90);tc.fillStyle='#c2d2b4';tc.fillRect(-radius*3,0,radius*6,radius*6);tc.strokeStyle='#76916a';tc.lineWidth=2;tc.beginPath();tc.moveTo(-radius*3,0);tc.lineTo(radius*3,0);tc.stroke();tc.strokeStyle='#8fa381';tc.lineWidth=1;for(let i=-3;i<=3;i++){if(!i)continue;tc.beginPath();tc.moveTo(-12,i*radius/4);tc.lineTo(12,i*radius/4);tc.stroke();}}
 tc.restore();tc.strokeStyle='#a4b596';tc.lineWidth=1;tc.beginPath();tc.arc(w/2,h/2+5,radius,0,Math.PI*2);tc.stroke();tc.strokeStyle=valid?'#b89832':'#9eaa94';tc.lineWidth=3;tc.beginPath();tc.moveTo(w/2-32,h/2+5);tc.lineTo(w/2-9,h/2+5);tc.lineTo(w/2,h/2+12);tc.lineTo(w/2+9,h/2+5);tc.lineTo(w/2+32,h/2+5);tc.stroke();tc.fillStyle='#829575';tc.font='10px system-ui';tc.textAlign='center';tc.fillText(valid?'GRAVITY REFERENCE':'TILT UNAVAILABLE',w/2,h-15);
}
function imuUpdate(){
 const s=imu.status==='live'?imu.sample:null;const value=(v,n=2,unit='')=>v==null?'—':v.toFixed(n)+unit;
 $('imu-status').textContent=s?(s.flags&8?'CALIBRATING':'IMU LIVE'):imu.status==='disabled'?'NOT CONFIGURED':'OFFLINE';$('imu-status').classList.toggle('live',!!s);
 $('imu-roll').textContent=value(s?.roll_deg,1,'°');$('imu-pitch').textContent=value(s?.pitch_deg,1,'°');
 ['x','y','z'].forEach((axis,i)=>{$('imu-a'+axis).textContent=value(s?.accel_g[i],3);$('imu-g'+axis).textContent=value(s?.gyro_dps[i],2);});
 $('imu-hz').textContent=value(imu.hz,1,' Hz');$('imu-temp').textContent=value(s?.temperature_c,1,' °C');$('imu-norm').textContent=value(s?.accel_norm_g,3,' g');$('imu-age').textContent=value(imu.age_ms,0,' ms');
 $('imu-port').textContent=imu.port?`${imu.port} · ${imu.baud||'detecting'} baud`:'Set --imu-port to connect';
 $('imu-note').textContent=s?(s.format==='v1'?`CRC verified · Device-configured ±2 g / ±250 °/s · Gyro correction ${s.flags&2?'applied':'absent'} · Accel correction ${s.flags&4?'applied':'absent'}.`:`${s.format==='legacy'?'Legacy stream · temperature not transmitted':'CSV stream'} · Assumed ±${imu.accel_range} g / ±${imu.gyro_range} °/s · Uncalibrated.`):imu.error||'Waiting for fresh IMU data…';
 $('imu-raw').textContent=s?`Acceleration: ${s.accel_raw.join(', ')}\nGyroscope: ${s.gyro_raw.join(', ')}\nTemperature: ${s.temp_raw??'not transmitted'}\nSamples: ${imu.samples} · Rejected lines: ${imu.rejected}${s.format==='v1'?`\nSequence: ${s.sequence} · Device time: ${s.device_ms} ms`:''}`:'No current sample';drawTilt();
}
async function pollIMU(){
 try{const response=await fetch('/api/imu',{signal:AbortSignal.timeout(1000)});if(!response.ok)throw Error('IMU unavailable');imu=await response.json();}
 catch{imu={status:'offline',sample:null,error:'IMU connection lost. Check the local server.'};}
 imuUpdate();setTimeout(pollIMU,100);
}
new ResizeObserver(drawTilt).observe(tiltCanvas);pollIMU();

let compassAngle=null;
let mag={status:'offline',sample:null};
const magCanvas=$('mag-dial'),mc=magCanvas.getContext('2d');
function drawMag(){
 const rect=magCanvas.getBoundingClientRect(),w=rect.width,h=rect.height,dpr=devicePixelRatio||1;
 magCanvas.width=Math.round(w*dpr);magCanvas.height=Math.round(h*dpr);mc.setTransform(dpr,0,0,dpr,0,0);
 mc.clearRect(0,0,w,h);const x=w/2,y=h/2+8,r=Math.min(w*.34,h*.33);mc.strokeStyle='#b0c09f';mc.lineWidth=1;mc.beginPath();mc.arc(x,y,r,0,Math.PI*2);mc.stroke();
 for(let d=0;d<360;d+=15){const a=d*Math.PI/180,inner=r-(d%90===0?10:5);mc.beginPath();mc.moveTo(x+Math.sin(a)*inner,y-Math.cos(a)*inner);mc.lineTo(x+Math.sin(a)*r,y-Math.cos(a)*r);mc.stroke();}
 mc.fillStyle='#78906b';mc.font='10px system-ui';mc.textAlign='center';mc.fillText('N',x,y-r-10);mc.fillText('E',x+r+18,y+3);mc.fillText('S',x,y+r+16);mc.fillText('W',x-r-18,y+3);
 const angle=compassAngle;
 if(angle!=null){mc.save();mc.translate(x,y);mc.rotate(angle*Math.PI/180);mc.fillStyle='#d7b542';mc.beginPath();mc.moveTo(0,-r+14);mc.lineTo(-8,9);mc.lineTo(0,3);mc.lineTo(8,9);mc.closePath();mc.fill();mc.restore();}
 mc.fillStyle='#617b55';mc.beginPath();mc.arc(x,y,4,0,Math.PI*2);mc.fill();
}
function magUpdate(){
 const s=mag.status==='live'?mag.sample:null,v=(x,n=1,u='')=>x==null?'—':x.toFixed(n)+u;
 $('mag-status').textContent=s?(s.flags&8?'CALIBRATING':mag.calibrated?'CORRECTION APPLIED':'UNCALIBRATED'):mag.status==='disabled'?'NOT CONFIGURED':'OFFLINE';
 $('mag-norm').textContent=v(s?.norm_ut,1,' µT');
 ['x','y','z'].forEach((a,i)=>{$('mag-r'+a).textContent=s?s.raw[i]:'—';$('mag-'+a).textContent=v(s?.field_ut[i],2);});
 $('mag-hz').textContent=v(mag.hz,1,' Hz');$('mag-age').textContent=v(mag.age_ms,0,' ms');$('mag-count').textContent=mag.samples??'—';$('mag-rejected').textContent=mag.rejected??'—';$('mag-port').textContent=mag.port?`${mag.port} · ${mag.baud||'detecting'} baud`:'Set --mag-port to connect';
 $('mag-note').textContent=s?`${s.format==='v1'?'CRC verified · Device-configured':s.format==='legacy'?'Legacy stream · Assumed':'CSV stream · Assumed'} ±${mag.field_range} G.${s.clipped?' Range limit reached; angle hidden.':s.unchanged_s>2?' Values unchanged; acquisition freshness unknown.':s.angle_deg==null?' No horizontal field; angle unavailable.':' Field telemetry in sensor axes; robot heading uses both sensors.'}`:mag.error||'Waiting for fresh serial data…';drawMag();
}
async function pollMag(){
 try{const response=await fetch('/api/mag',{signal:AbortSignal.timeout(1000)});if(!response.ok)throw Error('Magnetometer unavailable');mag=await response.json();}
 catch{mag={status:'offline',sample:null,error:'Magnetometer connection lost. Check the local server.'};}
 magUpdate();setTimeout(pollMag,100);
}
new ResizeObserver(drawMag).observe(magCanvas);pollMag();

let calState=null,calSensor='imu',calSending=false,calLocalError='';
const calDialog=$('cal-dialog');
document.querySelectorAll('[data-cal]').forEach(button=>button.onclick=()=>{calSensor=button.dataset.cal;calLocalError='';calDialog.showModal();renderCalibration();});
$('cal-close').onclick=()=>calDialog.close();
function renderCalibration(){
 if(!calDialog.open)return;
 const c=calState?.[calSensor],isIMU=calSensor==='imu';
 $('cal-title').textContent=isIMU?'Calibrate MPU6050':'Calibrate QMC5883L';
 const labels=isIMU?['Gyro','+X','−X','+Y','−Y','+Z','−Z','Save']:['Rotate','Save'];
 const index=isIMU?(c?.step||0):(c?.phase==='accepted'||c?.phase==='saved'?1:0);
 $('cal-steps').replaceChildren(...labels.map((label,i)=>{const e=document.createElement('span');e.textContent=label;e.className=i<index||c?.phase==='saved'?'done':i===index?'current':'';return e;}));
 let title,description,icon;
 if(!c?.available){title='Calibration firmware required';description='Upload the calibration sketch, close Serial Monitor, and wait for live IMU1 or MAG1 data. The panel connects automatically.';icon='↥';}
 else if(c.phase==='saved'){title='Saved. Ready to continue.';description='The board confirmed EEPROM storage. Live measurements already use the accepted corrections.';icon='✓';}
 else if(c.phase==='accepted'){title='Save calibration';description='All required captures were accepted. Save the coefficients so they survive a board restart.';icon='✓';}
 else if(isIMU&&index>0&&index<7){const face=['+X','−X','+Y','−Y','+Z','−Z'][index-1];title=`Place ${face} upward`;description=`Point the sensor’s ${face} direction straight up. Use the axis markings on the module. Click Capture, then keep still for about six seconds.`;icon=face+' ↑';}
 else if(isIMU){title='Keep the sensor still';description='Let the sensor warm up on a stable surface. After Capture, leave it untouched for two seconds of settling and four seconds of measurements.';icon='◎';}
 else{title='Rotate around all three axes';description='For 60 seconds, slowly turn the sensor in every direction, including upside down. Keep rotating throughout; a flat circle is not enough. Stay away from temporary magnets and metal objects.';icon='↻';}
 $('cal-icon').textContent=icon;$('cal-instruction').textContent=title;$('cal-description').textContent=description;
 $('cal-message').textContent=c?.message||'Connecting to calibration service…';$('cal-error').textContent=calLocalError;
 const running=c?.phase==='running';$('cal-progress').hidden=!running;$('cal-progress').value=running?Math.min(99,c.elapsed/c.duration*100):0;
 $('cal-time').textContent=running?`${Math.floor(c.elapsed)} s elapsed · estimated ${c.duration} s · waiting for board acceptance`:'';
 const primary=$('cal-primary');primary.textContent=c?.phase==='saved'?'Done':c?.phase==='accepted'?'Save & continue':c?.phase==='ready'?'Capture this step':c?.pending?'Waiting for board…':'Start calibration';
 primary.disabled=calSending||!c?.available||!!c?.pending||!!c?.device_busy;
 $('cal-abort').disabled=calSending||!c?.available||c?.phase==='saved'||(c?.phase==='idle'&&!c?.device_busy);
}
async function calibrationAction(action){
 if(!calState||calSending)return;
 calSending=true;calLocalError='';renderCalibration();
 try{const response=await fetch('/api/calibration',{method:'POST',headers:{'Content-Type':'application/json','X-Control-Token':calState.token},body:JSON.stringify({sensor:calSensor,action,session:calState[calSensor].session}),signal:AbortSignal.timeout(3000)});const body=await response.json();if(!response.ok)throw Error(body.error||'Command rejected');
 const refresh=await fetch('/api/calibration',{signal:AbortSignal.timeout(2000)});if(refresh.ok)calState=await refresh.json();}
 catch(error){calLocalError=error.message;}
 finally{calSending=false;renderCalibration();}
}
$('cal-primary').onclick=()=>{const c=calState?.[calSensor];if(!c)return;if(c.phase==='saved'){calDialog.close();return;}calibrationAction(c.phase==='accepted'?'save':calSensor==='imu'&&c.phase==='ready'?'capture':'begin');};
$('cal-abort').onclick=()=>calibrationAction('abort');
async function pollCalibration(){
 try{const response=await fetch('/api/calibration',{signal:AbortSignal.timeout(1500)});if(!response.ok)throw Error();calState=await response.json();}
 catch{calState=null;}
 renderCalibration();setTimeout(pollCalibration,300);
}
pollCalibration();

// Mount confirmation is local to this browser; no unverified heading is shown.
const mount=$('compass-mounted'), northMode=$('compass-mode'), declination=$('compass-declination');
let compassState=null;
try {const saved=JSON.parse(localStorage.getItem('rover-compass-v1')||'{}');
 mount.checked=saved.mounted===true;northMode.value=saved.mode==='true'?'true':'magnetic';
 if(Number.isFinite(saved.declination))declination.value=saved.declination;
} catch {}
function renderCompass(){
 const trueNorth=northMode.value==='true',value=declination.value.trim(),d=Number(value);
 declination.disabled=!trueNorth;
 let reason=!mount.checked?'Confirm mounting: both sensors +X forward, +Y left, +Z up.':
 trueNorth&&(!value||!Number.isFinite(d)||Math.abs(d)>180)?'Enter local magnetic declination for true north.':
 !compassState?.valid?(compassState?.reason||'Waiting for compass data'):'';
 compassAngle=reason?null:(compassState.heading_deg+(trueNorth?d:0)+360)%360;
 $('compass-reference').textContent=trueNorth?'True heading':'Magnetic heading';
 const names=['N','NE','E','SE','S','SW','W','NW'];
 $('mag-angle').textContent=compassAngle===null?'—':`${compassAngle.toFixed(1)}° ${names[Math.round(compassAngle/45)%8]}`;
 $('compass-note').textContent=reason||`Robot forward direction · ${trueNorth?'True':'Magnetic'} north · Tilt compensated`;
 drawMag();
}
for(const el of [mount,northMode,declination])el.addEventListener('change',()=>{
 try{localStorage.setItem('rover-compass-v1',JSON.stringify({mounted:mount.checked,mode:northMode.value,declination:declination.value.trim()?Number(declination.value):null}));}catch{}
 renderCompass();
});
async function pollCompass(){
 try{const response=await fetch('/api/compass',{signal:AbortSignal.timeout(1000)});if(!response.ok)throw Error();compassState=await response.json();}
 catch{compassState={valid:false,reason:'Compass connection lost'};}
 renderCompass();setTimeout(pollCompass,100);
}
pollCompass();
document.getElementById('drive-link').href = `${location.protocol}//${location.hostname}:8766/`;
