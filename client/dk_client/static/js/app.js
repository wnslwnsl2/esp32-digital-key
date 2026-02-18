/**
 * Digital Key Web UI — Auto-scan & connect
 */

let ws = null;
let clientId = null;
let connected = false;
let stepStartTimes = {};
let currentVehicleId = null;
let currentAccount = '';
let isOwner = false;

const STEP_IDS = ['connect', 'auth', 'device_auth', 'subscribe'];
const STEP_EL_KEYS = ['stepConnect', 'stepAuth', 'stepDeviceAuth', 'stepSubscribe'];
const STORAGE_KEY = 'dk_progress';

const el = {
  cardScanning: document.getElementById('card-scanning'),
  cardProgress: document.getElementById('card-progress'),
  cardLock: document.getElementById('card-lock'),
  cardStatus: document.getElementById('card-status'),
  scanText: document.getElementById('scan-text'),
  scanDetail: document.getElementById('scan-detail'),
  stepConnect: document.getElementById('step-connect'),
  stepAuth: document.getElementById('step-auth'),
  stepDeviceAuth: document.getElementById('step-device_auth'),
  stepSubscribe: document.getElementById('step-subscribe'),
  lockIndicator: document.getElementById('lock-indicator'),
  lockStateText: document.getElementById('lock-state-text'),
  statusAuth: document.getElementById('status-auth'),
  statusZone: document.getElementById('status-zone'),
  statusRssi: document.getElementById('status-rssi'),
  statusLock: document.getElementById('status-lock'),
  statusRegKeys: document.getElementById('status-reg-keys'),
  statusPendKeys: document.getElementById('status-pend-keys'),
  infoAccount: document.getElementById('info-account'),
  infoVehicle: document.getElementById('info-vehicle'),
  infoRole: document.getElementById('info-role'),
  logContainer: document.getElementById('log-container'),
};

// --- sessionStorage persistence ---

function saveProgress() {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(savedSteps));
}

// { connect: {status, detail, elapsed}, auth: {...}, ... }
let savedSteps = {};

function loadProgress() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw) savedSteps = JSON.parse(raw);
  } catch { savedSteps = {}; }
}

function clearProgress() {
  savedSteps = {};
  sessionStorage.removeItem(STORAGE_KEY);
}

function restoreProgressUI() {
  if (!Object.keys(savedSteps).length) return;
  STEP_IDS.forEach((id, i) => {
    const info = savedSteps[id];
    if (!info) return;
    const stepEl = el[STEP_EL_KEYS[i]];
    if (!stepEl) return;
    applyStepUI(stepEl, info.status, info.detail, info.elapsed);
  });
}

function applyStepUI(stepEl, status, detail, elapsed) {
  stepEl.className = `step ${status}`;

  const detailEl = stepEl.querySelector('.step-detail');
  if (detailEl) detailEl.textContent = detail || '';

  const timeEl = stepEl.querySelector('.step-time');
  if (timeEl) timeEl.textContent = elapsed || '';

  const iconEl = stepEl.querySelector('.step-icon');
  if (iconEl) {
    if (status === 'done') iconEl.innerHTML = '&#10003;';
    else if (status === 'failed') iconEl.innerHTML = '&#10007;';
    else if (status === 'skipped') iconEl.innerHTML = '&#8722;';
    else iconEl.innerHTML = '&#9679;';
  }
}

// --- Initialize ---

document.addEventListener('DOMContentLoaded', () => {
  loadProgress();
  initWebSocket();
});

// --- WebSocket ---

function initWebSocket() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => appendLog('INFO', 'Connected to server');
  ws.onmessage = (e) => handleMessage(JSON.parse(e.data));
  ws.onclose = (e) => {
    if (e.code === 4401) { window.location.href = '/login'; return; }
    appendLog('WARNING', 'Server disconnected, reconnecting...');
    clientId = null;
    setTimeout(initWebSocket, 3000);
  };
  ws.onerror = () => appendLog('ERROR', 'WebSocket error');
}

function sendWs(type, data = {}) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type, data }));
  }
}

function handleMessage(msg) {
  switch (msg.type) {
    case 'init':
      clientId = msg.data.client_id;
      displayInfo(msg.data);
      appendLog('INFO', 'Ready');
      break;

    case 'auto_scan':
      handleAutoScan(msg.data);
      break;

    case 'connect_progress':
      updateProgress(msg.data);
      break;

    case 'status':
      updateStatus(msg.data);
      break;

    case 'log':
      appendLog(msg.data.level, msg.data.message);
      break;

    case 'auth_result':
      break;

    case 'command_result':
      if (!msg.data.success) {
        appendLog('ERROR', `${msg.data.action} failed: ${msg.data.error || ''}`);
      }
      break;

    case 'error':
      appendLog('ERROR', msg.data.message);
      break;
  }
}

// --- Account & Vehicle Info ---

function displayInfo(data) {
  currentAccount = data.account || '';
  el.infoAccount.textContent = currentAccount || '-';

  const vehicles = data.vehicles || [];
  if (vehicles.length === 0) {
    el.infoVehicle.textContent = 'None';
    el.infoRole.textContent = '-';
    currentVehicleId = null;
    isOwner = false;
    return;
  }

  // Show first vehicle with user's key
  const v = vehicles[0];
  currentVehicleId = v.id;
  el.infoVehicle.textContent = v.name || v.ble_address || '-';

  // Find user's role in this vehicle
  const keys = v.keys || [];
  const myKey = keys.find(k => k.account === currentAccount);
  const role = myKey ? myKey.role : '-';
  el.infoRole.textContent = role;
  isOwner = (role === 'owner');

  // Show share button only for owners
  document.getElementById('share-row').style.display = isOwner ? '' : 'none';
}

// --- Auto-scan ---

function handleAutoScan(data) {
  switch (data.state) {
    case 'scanning':
      showCard('scanning');
      clearProgress();
      el.scanText.textContent = data.vehicles.length === 1
        ? `Searching for ${data.vehicles[0]}...`
        : `Searching for ${data.vehicles.length} vehicles...`;
      el.scanDetail.textContent = '';
      break;

    case 'found':
      showCard('progress');
      resetProgressSteps();
      break;

    case 'not_found':
      el.scanDetail.textContent = data.scan_count > 0
        ? `${data.scan_count} BLE device(s) nearby`
        : 'No BLE devices nearby';
      break;

    case 'scan_error':
      el.scanDetail.textContent = data.error;
      break;

    case 'no_vehicles':
      el.scanText.textContent = 'No vehicles registered';
      el.scanDetail.textContent = 'Add a vehicle in dk-server dashboard';
      break;
  }
}

// --- Card visibility ---

function showCard(state) {
  el.cardScanning.style.display = (state === 'scanning') ? '' : 'none';
  el.cardProgress.style.display = (state === 'progress' || state === 'connected') ? '' : 'none';
  el.cardLock.style.display = (state === 'connected') ? '' : 'none';
  el.cardStatus.style.display = (state === 'connected') ? '' : 'none';
}

function resetProgressSteps() {
  stepStartTimes = {};
  STEP_EL_KEYS.forEach(id => {
    const step = el[id];
    if (!step) return;
    step.className = 'step';
    step.querySelector('.step-detail').textContent = '';
    step.querySelector('.step-time').textContent = '';
    step.querySelector('.step-icon').innerHTML = '&#9679;';
  });
}

// --- Connect Progress ---

function updateProgress(data) {
  const stepEl = document.getElementById(`step-${data.step}`);
  if (!stepEl) return;

  if (data.step === 'connect' && data.status === 'in_progress') {
    showCard('progress');
    resetProgressSteps();
  }

  // Compute elapsed
  let elapsed = '';
  if (data.status === 'in_progress') {
    stepStartTimes[data.step] = Date.now();
  } else if (stepStartTimes[data.step]) {
    elapsed = formatElapsed(Date.now() - stepStartTimes[data.step]);
  }

  applyStepUI(stepEl, data.status, data.detail, elapsed);

  // Persist
  savedSteps[data.step] = {
    status: data.status,
    detail: data.detail || '',
    elapsed,
  };
  saveProgress();
}

// --- Status ---

function updateStatus(data) {
  if (data.connected !== undefined) {
    connected = data.connected;
    if (connected) {
      showCard('connected');
      restoreProgressUI();
    } else {
      showCard('scanning');
    }
  }

  if (data.auth_state !== undefined) el.statusAuth.textContent = data.auth_state;
  if (data.zone !== undefined) el.statusZone.textContent = data.zone;
  if (data.rssi !== undefined) el.statusRssi.textContent = `${data.rssi} dBm`;

  if (data.lock_state !== undefined) {
    el.statusLock.textContent = data.lock_state;
    el.lockStateText.textContent = data.lock_state;
    el.lockIndicator.className = data.lock_state_raw === 1
      ? 'lock-indicator unlocked' : 'lock-indicator locked';
  }

  if (data.registered_keys !== undefined) el.statusRegKeys.textContent = data.registered_keys;
  if (data.pending_keys !== undefined) el.statusPendKeys.textContent = data.pending_keys;
}

// --- Log ---

function appendLog(level, message) {
  const line = document.createElement('div');
  line.className = `log-line ${level.toLowerCase()}`;
  line.textContent = `[${formatTime(new Date())}] ${level}: ${message}`;
  el.logContainer.appendChild(line);
  el.logContainer.scrollTop = el.logContainer.scrollHeight;

  while (el.logContainer.children.length > 100) {
    el.logContainer.removeChild(el.logContainer.firstChild);
  }
}

// --- Logout ---

async function logout() {
  sendWs('disconnect');
  try { await fetch('/api/logout', { method: 'POST' }); } catch { /* ignore */ }
  clearProgress();
  sessionStorage.removeItem('dk_user');
  window.location.href = '/login';
}

// --- Share ---

async function showShareModal() {
  if (!currentVehicleId) return;
  const modal = document.getElementById('share-modal');
  const sel = document.getElementById('share-account');
  sel.innerHTML = '<option value="">Loading...</option>';
  modal.classList.add('active');

  try {
    const res = await fetch('/api/accounts');
    const accounts = await res.json();
    sel.innerHTML = accounts
      .filter(a => a.name !== currentAccount)
      .map(a => `<option value="${esc(a.name)}">${esc(a.name)}</option>`)
      .join('');
    if (!sel.innerHTML) sel.innerHTML = '<option value="">No other accounts</option>';
  } catch {
    sel.innerHTML = '<option value="">Failed to load</option>';
  }
}

function hideShareModal() {
  document.getElementById('share-modal').classList.remove('active');
}

function toggleShareExpiry() {
  const role = document.getElementById('share-role').value;
  document.getElementById('share-expiry-group').style.display = role === 'guest' ? '' : 'none';
}

async function submitShare() {
  const account = document.getElementById('share-account').value;
  const role = document.getElementById('share-role').value;
  const expires_at = document.getElementById('share-expires').value || '';

  if (!account) return alert('Select an account');
  if (!currentVehicleId) return;

  try {
    const res = await fetch('/api/share', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ vehicle_id: currentVehicleId, account, role, expires_at }),
    });
    const data = await res.json();
    if (res.ok) {
      appendLog('INFO', `Shared vehicle with ${account} (${role})`);
      hideShareModal();
    } else {
      alert(data.error || 'Share failed');
    }
  } catch (e) {
    alert('Share failed: ' + e.message);
  }
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// Close modal on overlay click
document.querySelectorAll('.modal-overlay').forEach(el => {
  el.addEventListener('click', (e) => {
    if (e.target === el) el.classList.remove('active');
  });
});

// --- Formatters ---

function formatElapsed(ms) {
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

function formatTime(date) {
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  });
}
