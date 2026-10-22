const $ = id => document.getElementById(id);
let session = null;
let pointer = null;
let position = {x: 0, y: 0};
let sending = false;
let sequence = 0;
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

async function refreshPorts() {
  try {
    const state = await (await fetch('/api/state', {cache: 'no-store'})).json();
    for (const side of ['left', 'right']) {
      const select = $(side);
      const selected = select.value || state[side];
      select.replaceChildren();
      select.add(new Option('Select a port', ''));
      for (const port of state.ports) select.add(new Option(`${port.device} — ${port.description}`, port.device));
      if (state.ports.some(port => port.device === selected)) select.value = selected;
    }
    if (state.error) message(state.error, true);
    if (session && !state.connected) lostConnection('Motor connection lost. Reconnect the ports.');
  } catch (error) { message(error.message, true); }
}

function resetStick() {
  position = {x: 0, y: 0};
  $('stick').style.left = '50%';
  $('stick').style.top = '50%';
  $('left-rpm').textContent = '0';
  $('right-rpm').textContent = '0';
}

function lostConnection(text) {
  session = null;
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
  if (!session || pointer === null || sending) return;
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

$('connect').addEventListener('click', async () => {
  await stop();
  if (!$('left').value || !$('right').value || $('left').value === $('right').value) {
    message('Select two different motor ports.', true); return;
  }
  $('connect').disabled = true;
  message('Opening motor ports...');
  try {
    const data = await request('/api/connect', {
      left: $('left').value, right: $('right').value, code: $('code').value,
      invert_left: $('invert-left').checked, invert_right: $('invert-right').checked
    });
    session = data.session;
    sequence = 0;
    setConnected(true);
    message('Connected. Hold the joystick to drive.');
  } catch (error) { lostConnection(error.message); }
  finally { $('connect').disabled = false; }
});

$('refresh').addEventListener('click', refreshPorts);
$('stop').addEventListener('click', stop);
pad.addEventListener('pointerdown', event => {
  if (!session || pointer !== null) return;
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
setInterval(refreshPorts, 2000);
setConnected(false);
refreshPorts();
