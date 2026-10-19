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
