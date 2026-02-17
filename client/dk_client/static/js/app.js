/**
 * Digital Key Web UI
 */

// State
let ws = null;
let clientId = null;
let connected = false;
let devices = [];
let stepStartTimes = {};

// DOM Elements
const elements = {
  deviceSelect: document.getElementById('device-select'),
  btnScan: document.getElementById('btn-scan'),
  btnConnect: document.getElementById('btn-connect'),
  connectProgress: document.getElementById('connect-progress'),
  stepConnect: document.getElementById('step-connect'),
  stepProvision: document.getElementById('step-provision'),
  stepAuth: document.getElementById('step-auth'),
  stepSubscribe: document.getElementById('step-subscribe'),
  lockIndicator: document.getElementById('lock-indicator'),
  lockStateText: document.getElementById('lock-state-text'),
  statusAuth: document.getElementById('status-auth'),
  statusZone: document.getElementById('status-zone'),
  statusRssi: document.getElementById('status-rssi'),
  statusLock: document.getElementById('status-lock'),
  statusRegKeys: document.getElementById('status-reg-keys'),
  statusPendKeys: document.getElementById('status-pend-keys'),
  keyIdInput: document.getElementById('key-id-input'),
  btnApprove: document.getElementById('btn-approve'),
  btnDelete: document.getElementById('btn-delete'),
  logContainer: document.getElementById('log-container'),
};

// Initialize
document.addEventListener('DOMContentLoaded', () => {
  initWebSocket();
  initEventListeners();
  appendLog('INFO', 'Digital Key Web UI started');
});

// WebSocket
function initWebSocket() {
  ws = new WebSocket(`ws://${location.host}/ws`);

  ws.onopen = () => {
    appendLog('INFO', 'WebSocket connected');
  };

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    handleMessage(msg);
  };

  ws.onclose = () => {
    appendLog('WARNING', 'WebSocket disconnected, reconnecting...');
    clientId = null;
    setTimeout(initWebSocket, 3000);
  };

  ws.onerror = () => {
    appendLog('ERROR', 'WebSocket error');
  };
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
      if (msg.data.devices && msg.data.devices.length > 0) {
        updateDeviceList(msg.data.devices);
      }
      if (msg.data.scanning) {
        setScanState(true);
      }
      appendLog('INFO', `Client ID: ${clientId}`);
      break;

    case 'status':
      updateStatus(msg.data);
      break;

    case 'log':
      appendLog(msg.data.level, msg.data.message);
      break;

    case 'scan_result':
      updateDeviceList(msg.data, true);
      break;

    case 'connect_progress':
      updateProgress(msg.data);
      break;

    case 'auth_result':
      // Auth is shown via progress steps, no separate handling needed
      break;

    case 'scan_state':
      setScanState(msg.data.scanning);
      break;

    case 'command_result':
      if (!msg.data.success) {
        appendLog('ERROR', `Command failed: ${msg.data.action} - ${msg.data.error || ''}`);
      }
      break;

    case 'error':
      appendLog('ERROR', msg.data.message);
      break;
  }
}

// Event Listeners
function initEventListeners() {
  elements.btnScan.addEventListener('click', scanDevices);
  elements.btnConnect.addEventListener('click', toggleConnection);

  elements.deviceSelect.addEventListener('change', () => {
    elements.btnConnect.disabled = !elements.deviceSelect.value;
  });

  elements.btnApprove.addEventListener('click', () => {
    const keyId = elements.keyIdInput.value.trim();
    if (keyId) {
      sendWs('approve', { key_id: keyId });
    } else {
      appendLog('ERROR', 'Key ID is required');
    }
  });

  elements.btnDelete.addEventListener('click', () => {
    const keyId = elements.keyIdInput.value.trim();
    if (keyId) {
      sendWs('delete', { key_id: keyId });
    } else {
      appendLog('ERROR', 'Key ID is required');
    }
  });
}

// Scan
function scanDevices() {
  sendWs('scan');
}

function setScanState(scanning) {
  elements.btnScan.disabled = scanning;
  elements.btnScan.textContent = scanning ? 'Scanning...' : 'Scan';
}

// Connect / Disconnect
function toggleConnection() {
  if (connected) {
    sendWs('disconnect');
    elements.connectProgress.style.display = 'none';
  } else {
    const address = elements.deviceSelect.value;
    if (!address) return;

    // Show progress, reset steps
    elements.connectProgress.style.display = 'flex';
    stepStartTimes = {};
    ['stepConnect', 'stepProvision', 'stepAuth', 'stepSubscribe'].forEach(id => {
      const el = elements[id];
      el.className = 'step';
      el.querySelector('.step-detail').textContent = '';
      el.querySelector('.step-time').textContent = '';
    });

    elements.btnConnect.disabled = true;
    elements.btnScan.disabled = true;
    sendWs('connect', { address });
  }
}

// Connect Progress
function updateProgress(data) {
  const stepEl = document.getElementById(`step-${data.step}`);
  if (!stepEl) return;

  stepEl.className = `step ${data.status}`;

  // Detail text
  const detailEl = stepEl.querySelector('.step-detail');
  if (detailEl && data.detail) {
    detailEl.textContent = data.detail;
  }

  // Elapsed time tracking
  const timeEl = stepEl.querySelector('.step-time');
  if (data.status === 'in_progress') {
    stepStartTimes[data.step] = Date.now();
    if (timeEl) timeEl.textContent = '';
  } else if (stepStartTimes[data.step] && timeEl) {
    const elapsed = Date.now() - stepStartTimes[data.step];
    timeEl.textContent = formatElapsed(elapsed);
  }

  // Icon update
  const iconEl = stepEl.querySelector('.step-icon');
  if (iconEl) {
    if (data.status === 'done') iconEl.innerHTML = '&#10003;';       // checkmark
    else if (data.status === 'failed') iconEl.innerHTML = '&#10007;'; // cross
    else if (data.status === 'skipped') iconEl.innerHTML = '&#8722;'; // minus
    else if (data.status === 'in_progress') iconEl.innerHTML = '&#9679;'; // dot
  }

  // Re-enable buttons when flow completes or fails
  if (data.step === 'subscribe' && data.status === 'done') {
    elements.btnConnect.disabled = false;
    elements.btnConnect.textContent = 'Disconnect';
  } else if (data.status === 'failed' && data.step === 'connect') {
    elements.btnConnect.disabled = false;
    elements.btnScan.disabled = false;
  }
}

function formatElapsed(ms) {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

// UI Updates
function setConnectionStatus(status) {
  connected = status === 'connected';
  elements.btnConnect.textContent = connected ? 'Disconnect' : 'Connect';
  elements.btnScan.disabled = connected;
  elements.btnConnect.disabled = false;

  if (!connected) {
    elements.connectProgress.style.display = 'none';
  }

  updateControlButtons();
}

function updateControlButtons() {
  elements.btnApprove.disabled = !connected;
  elements.btnDelete.disabled = !connected;
}

function updateStatus(data) {
  if (data.connected !== undefined) {
    setConnectionStatus(data.connected ? 'connected' : 'disconnected');
  }

  if (data.auth_state !== undefined) {
    elements.statusAuth.textContent = data.auth_state;
  }

  if (data.zone !== undefined) {
    elements.statusZone.textContent = data.zone;
  }

  if (data.rssi !== undefined) {
    elements.statusRssi.textContent = `${data.rssi} dBm`;
  }

  if (data.lock_state !== undefined) {
    elements.statusLock.textContent = data.lock_state;
    elements.lockStateText.textContent = data.lock_state;

    if (data.lock_state_raw === 1) {
      elements.lockIndicator.className = 'lock-indicator unlocked';
    } else {
      elements.lockIndicator.className = 'lock-indicator locked';
    }
  }

  if (data.registered_keys !== undefined) {
    elements.statusRegKeys.textContent = data.registered_keys;
  }

  if (data.pending_keys !== undefined) {
    elements.statusPendKeys.textContent = data.pending_keys;
  }
}

function updateDeviceList(deviceList, showLog = false) {
  devices = deviceList;

  if (deviceList.length > 0) {
    elements.deviceSelect.innerHTML = '';
    deviceList.forEach(device => {
      const option = document.createElement('option');
      option.value = device.address;
      option.textContent = `${device.name} (${device.rssi} dBm)`;
      elements.deviceSelect.appendChild(option);
    });
    elements.deviceSelect.selectedIndex = 0;
    elements.deviceSelect.disabled = false;
    elements.btnConnect.disabled = false;
  } else {
    elements.deviceSelect.innerHTML = '<option value="">Select a device</option>';
    elements.deviceSelect.disabled = true;
  }

  if (showLog) {
    appendLog('INFO', `${deviceList.length} device(s) found`);
  }
}

function appendLog(level, message) {
  const line = document.createElement('div');
  line.className = `log-line ${level.toLowerCase()}`;
  line.textContent = `[${formatTime(new Date())}] ${level}: ${message}`;
  elements.logContainer.appendChild(line);
  elements.logContainer.scrollTop = elements.logContainer.scrollHeight;

  while (elements.logContainer.children.length > 100) {
    elements.logContainer.removeChild(elements.logContainer.firstChild);
  }
}

function formatTime(date) {
  if (typeof date === 'string') {
    date = new Date(date);
  }
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}
