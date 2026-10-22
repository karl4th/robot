(() => {
  const el = id => document.getElementById(id);
  const pad = el('motor-pad');
  let session = sessionStorage.getItem('driveSession');
  let pointer = null;
  let position = {x: 0, y: 0};
  let sequence = 0;
  let sending = false;
  let verified = false;

  async function request(path, body) {
    const response = await fetch(path, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body), cache: 'no-store'
    });
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(data.error || 'Request failed');
      error.checks = data.checks;
      throw error;
    }
    return data;
  }

  function message(value, error = false) {
    el('motor-message').textContent = value;
    el('motor-message').classList.toggle('error', error);
  }

  function connected(value) {
    const wasVerified = verified;
    verified = value;
    if (value && !wasVerified) el('motor-settings').open = false;
    if (!value) el('motor-settings').open = true;
    el('drive-connection').textContent = value ? 'Boards verified' : 'Disconnected';
    el('drive-connection').classList.toggle('live', value);
    el('drive-summary').textContent = value ? 'Ready' : 'Disconnected';
    el('drive-led').classList.toggle('live', value);
    el('drive').classList.toggle('ready', value);
    pad.classList.toggle('disabled', !value);
    el('motor-stop').disabled = !value;
  }

  function checks(values) {
    for (const side of ['left', 'right']) {
      const check = values?.[side];
      el(`motor-${side}-status`).textContent = check?.response || 'Not checked';
      el(`motor-${side}-status`).classList.toggle('ok', Boolean(check?.matched));
      el(`motor-${side}-port`).textContent = check
        ? `${check.port} · expected ${check.expected}`
        : `Expected ${side === 'left' ? 'LSTAT,OK' : 'RSTAT,OK'}`;
    }
  }

  async function refreshPorts() {
    try {
      const response = await fetch('/api/state', {cache: 'no-store'});
      if (!response.ok) throw new Error('Could not read serial ports');
      const state = await response.json();
      for (const side of ['left', 'right']) {
        const select = el(`motor-${side}`);
        const selected = select.value || state[side];
        select.replaceChildren(new Option('Select a port', ''));
        for (const port of state.ports) {
          select.add(new Option(`${port.device} — ${port.description}`, port.device));
        }
        if (state.ports.some(port => port.device === selected)) select.value = selected;
      }
      if (!session && state.connected) message('Boards are connected in another browser session. Recheck ports to take control.');
    } catch (error) { message(error.message, true); }
  }

  async function checkSession() {
    if (!session) return;
    const current = session;
    try {
      const state = await request('/api/session', {session: current});
      if (session !== current) return;
      checks(state.checks);
      connected(true);
      message(`Both boards verified. Speed limit: ${state.max_rpm} RPM.`);
    } catch (error) { if (session === current) lose(error.message); }
  }

  function resetStick() {
    position = {x: 0, y: 0};
    el('motor-stick').style.left = '50%';
    el('motor-stick').style.top = '50%';
    el('motor-left-rpm').textContent = '0';
    el('motor-right-rpm').textContent = '0';
  }

  function lose(reason) {
    sessionStorage.removeItem('driveSession');
    session = null;
    pointer = null;
    resetStick();
    connected(false);
    message(reason, true);
  }

  async function stop() {
    pointer = null;
    resetStick();
    if (!session) return;
    const current = session;
    try { await request('/api/stop', {session: current, sequence: ++sequence}); }
    catch (error) { if (session === current) lose(error.message); }
  }

  async function sendPosition() {
    if (!session || !verified || pointer === null || sending) return;
    sending = true;
    const current = session;
    const activePointer = pointer;
    try {
      const data = await request('/api/drive', {session: current, ...position, sequence: ++sequence});
      if (session === current && pointer === activePointer && pointer !== null) {
        el('motor-left-rpm').textContent = data.target[0];
        el('motor-right-rpm').textContent = data.target[1];
      }
    } catch (error) { if (session === current) lose(error.message); }
    finally { sending = false; }
  }

  function axis(value, width) {
    return Math.abs(value) <= width ? 0 : Math.sign(value) * (Math.abs(value) - width) / (1 - width);
  }

  function move(event) {
    const bounds = pad.getBoundingClientRect();
    const radius = bounds.width / 2;
    let x = (event.clientX - bounds.left - radius) / radius;
    let y = (radius - (event.clientY - bounds.top)) / radius;
    const length = Math.hypot(x, y);
    if (length > 1) { x /= length; y /= length; }
    position = {x, y};
    el('motor-stick').style.left = `${50 + axis(x, 0.15) * 38}%`;
    el('motor-stick').style.top = `${50 - axis(y, 0.08) * 38}%`;
    sendPosition();
  }

  el('motor-connect').addEventListener('click', async () => {
    const left = el('motor-left').value;
    const right = el('motor-right').value;
    if (!left || !right || left === right) return message('Choose two different motor ports.', true);
    await stop();
    sessionStorage.removeItem('driveSession');
    session = null;
    connected(false);
    checks(null);
    el('motor-connect').disabled = true;
    message('Checking both board identities…');
    try {
      const data = await request('/api/connect', {
        left, right, code: el('motor-code').value,
        invert_left: el('motor-invert-left').checked,
        invert_right: el('motor-invert-right').checked
      });
      session = data.session;
      sequence = 0;
      sessionStorage.setItem('driveSession', session);
      checks(data.checks);
      connected(true);
      message('Both boards verified. Joystick ready.');
    } catch (error) { checks(error.checks); message(error.message, true); }
    finally { el('motor-connect').disabled = false; }
  });

  el('motor-refresh').addEventListener('click', refreshPorts);
  el('motor-stop').addEventListener('click', stop);
  pad.addEventListener('pointerdown', event => {
    if (!verified || pointer !== null) return;
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
  connected(false);
  refreshPorts();
  checkSession();
})();
