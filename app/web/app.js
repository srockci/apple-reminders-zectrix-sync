// Zectrix Sync — Web UI Logic

// ── State ──────────────────────────────────────────
let apiKey     = '';
let devices    = [];
let syncConfig = { poll_interval: 300, daemon: false, db_path: './sync.db' };
let connected  = false;
let lastSync   = null;

// ── Tab Navigation ──────────────────────────────────
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.add('hidden'));
    tab.classList.add('active');
    document.getElementById('panel' + tab.dataset.tab.charAt(0).toUpperCase() + tab.dataset.tab.slice(1)).classList.remove('hidden');
  });
});

// ── Log ─────────────────────────────────────────────
function log(msg) {
  const pre = document.getElementById('logPre');
  const ts  = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  pre.textContent += `\n[${ts}] ${msg}`;
  pre.parentElement.scrollTop = pre.parentElement.scrollHeight;
}

function clearLog() { document.getElementById('logPre').textContent = ''; }

// ── Status ──────────────────────────────────────────
function setStatus(text, ok) {
  document.getElementById('txtStatus').textContent = text;
  const dot = document.getElementById('dotStatus');
  dot.className = 'status-dot' + (ok === true ? ' ok' : ok === false ? ' err' : '');
}

// ── Device List ─────────────────────────────────────
function renderDevices() {
  const box = document.getElementById('deviceList');
  if (!apiKey) {
    box.innerHTML = '<div class="hint">填入 API Key 后自动获取设备列表</div>';
    return;
  }
  if (!devices.length) {
    box.innerHTML = '<div class="hint">未找到已注册的设备</div>';
    return;
  }
  box.innerHTML = devices.map(d => {
    const sel = syncConfig.devices && syncConfig.devices.includes(d.deviceId);
    return `<div class="device-item${sel ? ' selected' : ''}" data-id="${d.deviceId}">
      <div class="device-checkbox">${sel ? '✓' : ''}</div>
      <div class="device-info">
        <div class="device-name">${d.deviceName || d.deviceId}</div>
        <div class="device-meta">${d.deviceId} &nbsp;|&nbsp; ${d.screenWidth}×${d.screenHeight}</div>
      </div>
    </div>`;
  }).join('');

  box.querySelectorAll('.device-item').forEach(el => {
    el.addEventListener('click', () => {
      const id = el.dataset.id;
      if (!syncConfig.devices) syncConfig.devices = [];
      const idx = syncConfig.devices.indexOf(id);
      if (idx >= 0) { syncConfig.devices.splice(idx, 1); el.classList.remove('selected'); el.querySelector('.device-checkbox').textContent = ''; }
      else { syncConfig.devices.push(id); el.classList.add('selected'); el.querySelector('.device-checkbox').textContent = '✓'; }
    });
  });
}

// ── API Test ────────────────────────────────────────
document.getElementById('btnTestApi').addEventListener('click', async () => {
  const key    = document.getElementById('inpApiKey').value.trim();
  const errEl = document.getElementById('hintApiError');
  errEl.textContent = '';
  if (!key) { errEl.textContent = '请输入 API Key'; return; }

  document.getElementById('btnTestApi').innerHTML = '<div class="spinner"></div>';
  log('测试 API 连接...');

  try {
    const res = await eel.test_api(key)();
    document.getElementById('btnTestApi').textContent = '测试';
    if (res.ok) {
      apiKey    = key;
      devices   = res.devices || [];
      connected = true;
      setStatus('已连接', true);
      log(`连接成功，找到 ${devices.length} 个设备`);
      syncConfig.devices = devices.map(d => d.deviceId);
      renderDevices();
    } else {
      errEl.textContent = res.error || 'API Key 无效';
      setStatus('连接失败', false);
      log('连接失败: ' + (res.error || '未知错误'));
    }
  } catch(e) {
    document.getElementById('btnTestApi').textContent = '测试';
    errEl.textContent = '连接失败: ' + e.message;
    setStatus('连接失败', false);
    log('异常: ' + e.message);
  }
});

// ── Sync Now ────────────────────────────────────────
document.getElementById('btnSyncNow').addEventListener('click', async () => {
  if (!connected) { log('请先在「设备」页面填写并测试 API Key'); return; }
  clearLog(); log('开始同步...');
  try {
    const res = await eel.run_sync()(apiKey, syncConfig);
    log(res.log || '同步完成');
    document.getElementById('txtAppleCount').textContent  = res.apple_count  ?? '—';
    document.getElementById('txtZectrixCount').textContent = res.zectrix_count ?? '—';
    const ts = new Date().toLocaleString('zh-CN', { hour12: false });
    document.getElementById('txtLastSync').textContent = ts;
    lastSync = ts;
  } catch(e) { log('同步异常: ' + e.message); }
});

// ── Dry Run ─────────────────────────────────────────
document.getElementById('btnDryRun').addEventListener('click', async () => {
  if (!connected) { log('请先在「设备」页面填写并测试 API Key'); return; }
  clearLog(); log('[DRY-RUN] 预览同步...');
  try {
    const res = await eel.run_sync()(apiKey, { ...syncConfig, dry_run: true });
    log(res.log || '预览完成');
  } catch(e) { log('预览异常: ' + e.message); }
});

// ── Save Settings ───────────────────────────────────
document.getElementById('btnSaveSettings').addEventListener('click', async () => {
  syncConfig.poll_interval = parseInt(document.getElementById('inpInterval').value) || 300;
  syncConfig.daemon       = document.getElementById('chkDaemon').checked;
  try {
    await eel.save_config()(apiKey, syncConfig);
    log('设置已保存');
  } catch(e) { log('保存失败: ' + e.message); }
});

// ── Close → minimize to background ──────────────────
document.getElementById('btnClose').addEventListener('click', () => {
  eel.minimize_window()();
});

// ── Load saved config on start ───────────────────────
(async () => {
  try {
    const cfg = await eel.load_config()();
    if (cfg && cfg.api_key) {
      document.getElementById('inpApiKey').value = cfg.api_key;
      apiKey = cfg.api_key;
      document.getElementById('inpInterval').value = cfg.poll_interval || 300;
      document.getElementById('chkDaemon').checked  = !!cfg.daemon;
      document.getElementById('inpDbPath').value    = cfg.db_path || './sync.db';
      // auto-populate device list
      connected = true;
      setStatus('已载入配置', true);
      log('已载入上次配置');
    }
  } catch(e) { /* config may not exist yet */ }
})();