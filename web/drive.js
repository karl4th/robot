const $ = id => document.getElementById(id);
let session = sessionStorage.getItem('driveSession');
let pointer = null;
let position = {x: 0, y: 0};
let sending = false;
let sequence = 0;
let verified = false;
const pad = $('pad');

function message(text, error = false) {
  $('message').textContent = text;
  $('message').classList.toggle('error', error);
}

async function request(path, body) {
  const response = await fetch(path, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body), cache: 'no-store'
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}

function setConnected(value) {
  $('connection').textContent = value ? 'Connected' : 'Disconnected';
  $('connection').classList.toggle('on', value);
  $('stop').disabled = !value;
  pad.classList.toggle('disabled', !value);
}

async function checkSession() {
  if (!session) return;
  const activeSession = session;
  try {
    const state = await request('/api/session', {session: activeSession});
    if (session !== activeSession) return;
    $('left-board').textContent = state.left;
    $('right-board').textContent = state.right;
    $('left-reply').textContent = state.checks.left.response;
    $('right-reply').textContent = state.checks.right.response;
    verified = true;
    setConnected(true);
    message(`Both boards verified. Speed limit: ${state.max_rpm} RPM.`);
  } catch (error) { if (session === activeSession) lostConnection(error.message); }
}

function resetStick() {
  position = {x: 0, y: 0};
  $('stick').style.left = '50%';
  $('stick').style.top = '50%';
  $('left-rpm').textContent = '0';
  $('right-rpm').textContent = '0';
}

function lostConnection(text) {
  sessionStorage.removeItem('driveSession');
  session = null;
  verified = false;
  pointer = null;
  resetStick();
  setConnected(false);
  message(text, true);
}

async function stop() {
  pointer = null;
  resetStick();
  if (!session) return;
  const activeSession = session;
  try { await request('/api/stop', {session: activeSession, sequence: ++sequence}); }
  catch (error) { if (session === activeSession) lostConnection(error.message); }
}

async function sendPosition() {
  if (!session || !verified || pointer === null || sending) return;
  sending = true;
  const activeSession = session;
  try {
    const activePointer = pointer;
    const data = await request('/api/drive', {session: activeSession, ...position, sequence: ++sequence});
    if (session === activeSession && pointer === activePointer && pointer !== null) {
      $('left-rpm').textContent = data.target[0];
      $('right-rpm').textContent = data.target[1];
    }
  } catch (error) { if (session === activeSession) lostConnection(error.message); }
  finally { sending = false; }
}

function move(event) {
  const bounds = pad.getBoundingClientRect();
  const radius = bounds.width / 2;
  let x = (event.clientX - bounds.left - radius) / radius;
  let y = (radius - (event.clientY - bounds.top)) / radius;
  const length = Math.hypot(x, y);
  if (length > 1) { x /= length; y /= length; }
  position = {x, y};
  $('stick').style.left = `${50 + x * 38}%`;
  $('stick').style.top = `${50 - y * 38}%`;
  sendPosition();
}

$('stop').addEventListener('click', stop);
pad.addEventListener('pointerdown', event => {
  if (!session || !verified || pointer !== null) return;
  pointer = event.pointerId;
  pad.setPointerCapture(pointer);
  move(event);
});
pad.addEventListener('pointermove', event => { if (event.pointerId === pointer) move(event); });
for (const name of ['pointerup', 'pointercancel', 'lostpointercapture']) {
  pad.addEventListener(name, event => { if (event.pointerId === pointer) stop(); });
}
window.addEventListener('blur', stop);
document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
window.addEventListener('pagehide', () => {
  if (session) fetch('/api/stop', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({session, sequence: ++sequence}), keepalive: true
  }).catch(() => {});
});
setInterval(sendPosition, 80);
setInterval(checkSession, 2000);
setConnected(false);
if (session) checkSession();
else { message('Connect and verify the motor boards first.', true); }
