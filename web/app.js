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
