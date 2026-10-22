(() => {
  const el = id => document.getElementById(id);
  const video = el('camera-video');
  let stream = null;

  function status(label, live, detail) {
    el('camera-status').textContent = label;
    el('camera-status').classList.toggle('live', live);
    el('camera-summary').textContent = live ? 'Live' : label === 'OFF' ? 'Off' : 'Unavailable';
    el('camera-led').classList.toggle('live', live);
    el('camera-message').textContent = detail;
    el('camera-placeholder').hidden = live;
    el('camera-start').disabled = live;
    el('camera-stop').disabled = !live;
  }

  async function listCameras() {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    const selected = el('camera-select').value;
    const devices = (await navigator.mediaDevices.enumerateDevices()).filter(item => item.kind === 'videoinput');
    el('camera-select').replaceChildren(new Option('Default camera', ''));
    devices.forEach((device, index) => el('camera-select').add(new Option(device.label || `Camera ${index + 1}`, device.deviceId)));
    if (devices.some(device => device.deviceId === selected)) el('camera-select').value = selected;
  }

  function stop() {
    if (stream) stream.getTracks().forEach(track => track.stop());
    stream = null;
    video.srcObject = null;
    status('OFF', false, 'Preview stopped. No video is uploaded.');
  }

  el('camera-start').addEventListener('click', async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      status('UNAVAILABLE', false, 'Camera preview requires localhost or HTTPS in a supported browser.');
      return;
    }
    try {
      const deviceId = el('camera-select').value;
      stream = await navigator.mediaDevices.getUserMedia({video: deviceId ? {deviceId: {exact: deviceId}} : true, audio: false});
      video.srcObject = stream;
      await video.play();
      await listCameras();
      status('LIVE', true, 'Preview stays in this browser. No video is uploaded.');
      stream.getVideoTracks()[0]?.addEventListener('ended', stop, {once: true});
    } catch (error) {
      stop();
      status('UNAVAILABLE', false, `Could not start camera: ${error.message}`);
    }
  });
  el('camera-stop').addEventListener('click', stop);
  window.addEventListener('pagehide', stop);
  listCameras().catch(() => {});
})();
