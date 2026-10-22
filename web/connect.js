const $ = id => document.getElementById(id);
$('telemetry-link').href = `${location.protocol}//${location.hostname}:8765/`;
let session = sessionStorage.getItem('driveSession');

function message(text, error = false) {
  $('message').textContent = text;
  $('message').classList.toggle('error', error);
}

function ready(value) {
  $('connection').textContent = value ? 'Verified' : 'Disconnected';
  $('connection').classList.toggle('on', value);
  $('drive-link').classList.toggle('disabled', !value);
  $('drive-link').setAttribute('aria-disabled', String(!value));
}

function showChecks(checks) {
  for (const side of ['left', 'right']) {
    const check = checks?.[side];
    $(side + '-status').textContent = check?.response || 'Not checked';
    $(side + '-status').classList.toggle('ok', Boolean(check?.matched));
    $(side + '-port').textContent = check ? `${check.port} · expected ${check.expected}`
      : `Expected: ${side === 'left' ? 'LSTAT,OK' : 'RSTAT,OK'}`;
  }
}

async function request(path, body) {
  const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body), cache: 'no-store'});
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error || 'Request failed');
    error.checks = data.checks;
    throw error;
  }
  return data;
}

async function refreshPorts() {
  try {
    const response = await fetch('/api/state', {cache: 'no-store'});
    if (!response.ok) throw new Error('Could not read serial ports');
    const state = await response.json();
    for (const side of ['left', 'right']) {
      const select = $(side);
      const selected = select.value || state[side];
      select.replaceChildren();
      select.add(new Option('Select a port', ''));
      for (const port of state.ports) select.add(new Option(`${port.device} — ${port.description}`, port.device));
      if (state.ports.some(port => port.device === selected)) select.value = selected;
    }
  } catch (error) { message(error.message, true); }
}

$('connect').addEventListener('click', async () => {
  const left = $('left').value;
  const right = $('right').value;
  if (!left || !right || left === right) {
    message('Select two different motor ports.', true);
    return;
  }
  sessionStorage.removeItem('driveSession');
  session = null;
  ready(false);
  showChecks(null);
  $('connect').disabled = true;
  message('Opening ports and checking both board replies. This may take a few seconds.');
  try {
    const data = await request('/api/connect', {left, right, code: $('code').value,
      invert_left: $('invert-left').checked, invert_right: $('invert-right').checked});
    session = data.session;
    sessionStorage.setItem('driveSession', session);
    showChecks(data.checks);
    ready(true);
    message('Both boards identified correctly. Open the drive page when ready.');
  } catch (error) {
    showChecks(error.checks);
    message(error.message, true);
  } finally { $('connect').disabled = false; }
});

$('drive-link').addEventListener('click', event => {
  if (!session) event.preventDefault();
});
$('refresh').addEventListener('click', refreshPorts);

async function restoreSession() {
  if (!session) return;
  try {
    const data = await request('/api/session', {session});
    showChecks(data.checks);
    ready(true);
    message('Both boards remain connected.');
  } catch (_) {
    sessionStorage.removeItem('driveSession');
    session = null;
    ready(false);
  }
}

ready(false);
refreshPorts();
restoreSession();
