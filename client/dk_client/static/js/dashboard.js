/* Digital Key Server — Dashboard */

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (res.status === 401) {
    window.location.href = '/login';
    return null;
  }
  return res;
}

// --- Vehicles ---

async function loadVehicles() {
  const res = await api('GET', '/api/vehicles');
  if (!res) return;
  const vehicles = await res.json();
  renderVehicles(vehicles);
}

function renderVehicles(vehicles) {
  const container = document.getElementById('vehicles-container');
  if (!vehicles.length) {
    container.innerHTML = '<div class="empty-state">No vehicles registered</div>';
    return;
  }
  container.innerHTML = vehicles.map(v => `
    <div class="vehicle-card">
      <div class="vehicle-header">
        <div>
          <h3>${esc(v.name)}</h3>
          <span class="vehicle-addr">${esc(v.ble_address)}</span>
          <span class="vehicle-date">&middot; ${formatDate(v.created_at)}</span>
        </div>
        <div>
          <button class="btn-icon" title="Add key" onclick="showAddKey('${v.id}')">🔑</button>
          <button class="btn-icon" title="Delete vehicle" onclick="removeVehicle('${v.id}','${esc(v.name)}')">✕</button>
        </div>
      </div>
      ${renderKeys(v.id, v.keys)}
    </div>
  `).join('');
}

function renderKeys(vehicleId, keys) {
  if (!keys || !keys.length) {
    return '<div class="key-list"><div class="empty-state" style="padding:8px">No keys bound</div></div>';
  }
  return `<div class="key-list">${keys.map(k => `
    <div class="key-item">
      <div class="key-info">
        <span class="key-id">${esc(k.key_id)}</span>
        <span class="key-role ${k.role}">${k.role}</span>
        ${k.public_key ? `<span class="key-pubkey">${esc(k.public_key.substring(0, 16))}…</span>` : ''}
      </div>
      <button class="btn-icon" title="Unbind key" onclick="removeKey('${vehicleId}','${k.key_id}')">✕</button>
    </div>
  `).join('')}</div>`;
}

// --- Events ---

async function loadEvents() {
  const res = await api('GET', '/api/events?limit=50');
  if (!res) return;
  const events = await res.json();
  renderEvents(events);
}

function renderEvents(events) {
  const container = document.getElementById('events-container');
  if (!events.length) {
    container.innerHTML = '<div class="empty-state">No events yet</div>';
    return;
  }
  container.innerHTML = `
    <table class="event-table">
      <thead>
        <tr><th>Time</th><th>Vehicle</th><th>Key</th><th>Event</th><th>Detail</th></tr>
      </thead>
      <tbody>
        ${events.map(e => `
          <tr>
            <td class="event-time">${formatTime(e.ts)}</td>
            <td class="event-addr">${esc(e.vehicle || '—')}</td>
            <td class="key-id">${esc(e.key_id ? e.key_id.substring(0, 8) : '—')}</td>
            <td><span class="event-type ${e.event}">${esc(e.event)}</span></td>
            <td>${esc(e.detail || '')}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

// --- Actions ---

function showAddVehicle() {
  document.getElementById('vehicle-name').value = '';
  document.getElementById('vehicle-addr').value = '';
  document.getElementById('add-vehicle-modal').classList.add('active');
  document.getElementById('vehicle-name').focus();
}

async function addVehicle() {
  const name = document.getElementById('vehicle-name').value.trim();
  const ble_address = document.getElementById('vehicle-addr').value.trim();
  if (!name || !ble_address) return;
  await api('POST', '/api/vehicles', { name, ble_address });
  hideModal('add-vehicle-modal');
  loadVehicles();
}

async function removeVehicle(id, name) {
  if (!confirm(`Delete vehicle "${name}"?`)) return;
  await api('DELETE', `/api/vehicles/${id}`);
  loadVehicles();
}

async function showAddKey(vehicleId) {
  document.getElementById('key-vehicle-id').value = vehicleId;
  document.getElementById('key-id-manual').value = '';
  document.getElementById('key-pubkey').value = '';

  // Load local keys into select
  const sel = document.getElementById('key-id-select');
  sel.innerHTML = '<option value="">Select a local key...</option>';
  try {
    const res = await api('GET', '/api/local-keys');
    if (res) {
      const keys = await res.json();
      keys.forEach(k => {
        const opt = document.createElement('option');
        opt.value = k.key_id;
        opt.textContent = k.key_id;
        sel.appendChild(opt);
      });
    }
  } catch { /* ignore */ }

  document.getElementById('add-key-modal').classList.add('active');
}

async function addKey() {
  const vehicleId = document.getElementById('key-vehicle-id').value;
  const selected = document.getElementById('key-id-select').value;
  const manual = document.getElementById('key-id-manual').value.trim();
  const key_id = manual || selected;
  const public_key = document.getElementById('key-pubkey').value.trim();
  const role = document.getElementById('key-role').value;

  if (!key_id) return alert('Select or enter a Key ID');
  await api('POST', `/api/vehicles/${vehicleId}/keys`, { key_id, public_key, role });
  hideModal('add-key-modal');
  loadVehicles();
}

async function removeKey(vehicleId, keyId) {
  if (!confirm(`Unbind key "${keyId}"?`)) return;
  await api('DELETE', `/api/vehicles/${vehicleId}/keys/${keyId}`);
  loadVehicles();
}

function hideModal(id) {
  document.getElementById(id).classList.remove('active');
}

async function logout() {
  await api('POST', '/api/logout');
  window.location.href = '/login';
}

// --- Helpers ---

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleDateString();
}

function formatTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleString();
}

// --- Close modals on overlay click ---
document.querySelectorAll('.modal-overlay').forEach(el => {
  el.addEventListener('click', (e) => {
    if (e.target === el) el.classList.remove('active');
  });
});

// --- Init ---
loadVehicles();
loadEvents();
setInterval(loadEvents, 5000);
