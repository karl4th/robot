(() => {
  const names = ['lidar', 'gps', 'imu', 'mag'];
  const el = id => document.getElementById(id);

  function message(value, error = false) {
    el('sensor-message').textContent = value;
    el('sensor-message').classList.toggle('error', error);
  }

  async function refresh(preserve = false) {
    try {
      const response = await fetch('/api/sensors', {cache: 'no-store'});
      if (!response.ok) throw new Error('Could not read sensor ports');
      const data = await response.json();
      for (const name of names) {
        const select = el(`sensor-${name}`);
        const selected = preserve ? select.value : data.selected[name];
        select.replaceChildren(new Option('Not connected', ''));
        for (const port of data.ports.filter(item => item.device.startsWith('/dev/cu.usb') ||
          item.device.startsWith('/dev/ttyUSB') || item.device.startsWith('/dev/ttyACM'))) {
          select.add(new Option(`${port.device} — ${port.description}`, port.device));
        }
        if (data.ports.some(port => port.device === selected)) select.value = selected;
      }
      message('Sensor port list is current.');
    } catch (error) { message(error.message, true); }
  }

  el('sensor-refresh').addEventListener('click', () => refresh(true));
  el('sensor-apply').addEventListener('click', async () => {
    const ports = Object.fromEntries(names.map(name => [name, el(`sensor-${name}`).value || null]));
    const selected = Object.values(ports).filter(Boolean);
    if (new Set(selected).size !== selected.length) return message('Choose a different USB port for each sensor.', true);
    el('sensor-apply').disabled = true;
    message('Stopping old readers and opening selected ports…');
    try {
      const response = await fetch('/api/sensors', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, cache: 'no-store',
        body: JSON.stringify({code: el('motor-code').value, ports})
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not apply sensor ports');
      message('Sensor ports applied. Live status will update above.');
      await refresh();
    } catch (error) { message(error.message, true); }
    finally { el('sensor-apply').disabled = false; }
  });
  refresh();
})();
