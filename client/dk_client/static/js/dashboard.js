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
          <button class="btn-icon" title="Share" onclick="showShare('${v.id}')">👥</button>
          <button class="btn-icon" title="Delete vehicle" onclick="removeVehicle('${v.id}','${esc(v.name)}')">✕</button>
        </div>
      </div>
      ${renderKeys(v.id, v.keys)}
    </div>
  `).join('');
}

function renderKeys(vehicleId, keys) {
  if (!keys || !keys.length) {
    return '<div class="key-list"><div class="empty-state" style="padding:8px">No keys</div></div>';
  }
  return `<div class="key-list">${keys.map(k => `
    <div class="key-item">
      <div class="key-info">
        <span class="key-id">${esc(k.key_id)}</span>
        <span class="key-role ${k.role}">${k.role}</span>
        ${k.account ? `<span class="key-account">${esc(k.account)}</span>` : ''}
        ${k.expires_at ? `<span class="key-expires">exp: ${formatTime(k.expires_at)}</span>` : ''}
      </div>
      <button class="btn-icon" title="Remove key" onclick="removeKey('${vehicleId}','${k.key_id}')">✕</button>
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

// --- Accounts ---
let accountList = [];

async function loadAccounts() {
  const res = await api('GET', '/api/accounts');
  if (!res) return;
  const accounts = await res.json();
  accountList = accounts;
  const container = document.getElementById('accounts-container');
  if (!accounts.length) {
    container.innerHTML = '<div class="empty-state">No accounts</div>';
    return;
  }
  container.innerHTML = accounts.map(a => `
    <div class="key-item">
      <div class="key-info">
        <span class="key-id">${esc(a.name || '(unnamed)')}</span>
      </div>
      <button class="btn-icon" title="Delete account" onclick="removeAccount('${esc(a.name)}')">✕</button>
    </div>
  `).join('');
}

function showAddAccount() {
  document.getElementById('account-name-input').value = '';
  document.getElementById('account-pin-input').value = '';
  document.getElementById('add-account-modal').classList.add('active');
  document.getElementById('account-name-input').focus();
}

async function addAccount() {
  const name = document.getElementById('account-name-input').value.trim();
  const pin = document.getElementById('account-pin-input').value;
  if (!name || !pin) return alert('Name and PIN required');
  await api('POST', '/api/accounts', { name, pin });
  hideModal('add-account-modal');
  loadAccounts();
}

async function removeAccount(name) {
  if (!confirm(`Delete account "${name}"?`)) return;
  await api('DELETE', `/api/accounts/${encodeURIComponent(name)}`);
  loadAccounts();
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

// --- Key management ---

function _populateAccountSelect(selectId) {
  const sel = document.getElementById(selectId);
  sel.innerHTML = accountList.map(a =>
    `<option value="${esc(a.name)}">${esc(a.name)}</option>`
  ).join('');
}

function toggleExpiry() {
  const role = document.getElementById('key-role').value;
  document.getElementById('key-expiry-group').style.display = role === 'guest' ? '' : 'none';
}

function toggleShareExpiry() {
  const role = document.getElementById('share-role').value;
  document.getElementById('share-expiry-group').style.display = role === 'guest' ? '' : 'none';
}

function showAddKey(vehicleId) {
  document.getElementById('key-vehicle-id').value = vehicleId;
  document.getElementById('key-role').value = 'owner';
  document.getElementById('key-expires').value = '';
  toggleExpiry();
  _populateAccountSelect('key-account');
  document.getElementById('add-key-modal').classList.add('active');
}

async function addKey() {
  const vehicleId = document.getElementById('key-vehicle-id').value;
  const account = document.getElementById('key-account').value;
  const role = document.getElementById('key-role').value;
  const expires_at = document.getElementById('key-expires').value || '';

  if (!account) return alert('Select an account');
  await api('POST', `/api/vehicles/${vehicleId}/keys`, { account, role, expires_at });
  hideModal('add-key-modal');
  loadVehicles();
}

async function removeKey(vehicleId, keyId) {
  if (!confirm(`Remove key "${keyId}"?`)) return;
  await api('DELETE', `/api/vehicles/${vehicleId}/keys/${keyId}`);
  loadVehicles();
}

// --- Share ---

function showShare(vehicleId) {
  document.getElementById('share-vehicle-id').value = vehicleId;
  document.getElementById('share-role').value = 'family';
  document.getElementById('share-expires').value = '';
  toggleShareExpiry();
  _populateAccountSelect('share-account');
  document.getElementById('share-modal').classList.add('active');
}

async function shareVehicle() {
  const vehicleId = document.getElementById('share-vehicle-id').value;
  const account = document.getElementById('share-account').value;
  const role = document.getElementById('share-role').value;
  const expires_at = document.getElementById('share-expires').value || '';

  if (!account) return alert('Select an account');
  await api('POST', `/api/vehicles/${vehicleId}/share`, { account, role, expires_at });
  hideModal('share-modal');
  loadVehicles();
}

// --- Modal helpers ---

function hideModal(id) {
  document.getElementById(id).classList.remove('active');
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
async function init() {
  await loadAccounts();
  await loadVehicles();
  loadEvents();
  setInterval(loadEvents, 5000);
}
init();
