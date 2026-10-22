(() => {
  const holder = document.querySelector('.gps-track-wrap');
  const fallback = document.getElementById('map-fallback');
  const mapNode = document.getElementById('gps-map');
  if (!window.L) {
    fallback.textContent = 'Map library unavailable. Local track shown below.';
    return;
  }

  let map = null;
  let marker = null;
  let route = null;
  let follow = true;
  let lastKey = '';

  function createMap(latitude, longitude) {
    map = L.map(mapNode, {zoomControl: true}).setView([latitude, longitude], 17);
    const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'
    }).addTo(map);
    tiles.on('load', () => {
      holder.classList.add('map-ready');
      fallback.hidden = true;
    });
    tiles.on('tileerror', () => {
      holder.classList.remove('map-ready');
      fallback.hidden = false;
      fallback.textContent = 'Map tiles unavailable. Local track shown below.';
    });
    map.on('dragstart zoomstart', () => { follow = false; });
    marker = L.circleMarker([latitude, longitude], {
      radius: 9, color: '#fff', weight: 3, fillColor: '#d6a62d', fillOpacity: 1
    }).addTo(map);
    route = L.polyline([], {color: '#345c46', weight: 4, opacity: .85}).addTo(map);
    const followControl = L.control({position: 'topright'});
    followControl.onAdd = () => {
      const button = L.DomUtil.create('button', 'map-follow');
      button.type = 'button';
      button.textContent = 'Follow GPS';
      button.title = 'Center on the latest GPS fix';
      L.DomEvent.disableClickPropagation(button);
      button.addEventListener('click', () => {
        follow = true;
        map.setView(marker.getLatLng(), Math.max(16, map.getZoom()));
      });
      return button;
    };
    followControl.addTo(map);
    new ResizeObserver(() => map.invalidateSize()).observe(mapNode);
  }

  window.updateGpsMap = gps => {
    if (gps.status !== 'live' || !Number.isFinite(gps.latitude) || !Number.isFinite(gps.longitude)) return;
    if (!map) createMap(gps.latitude, gps.longitude);
    const point = [gps.latitude, gps.longitude];
    marker.setLatLng(point);
    const track = (gps.track || []).filter(p => Number.isFinite(p[0]) && Number.isFinite(p[1]));
    const key = `${track.length}:${track.at(-1)?.join(',')}`;
    if (key !== lastKey) {
      route.setLatLngs(track.map(p => [p[0], p[1]]));
      lastKey = key;
    }
    if (follow && map.distance(map.getCenter(), point) > 30) {
      map.panTo(point, {animate: false});
    }
  };
})();
