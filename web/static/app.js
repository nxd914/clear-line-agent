const LS_KEY = 'vequil_api_key';
const LS_WORKSPACE_KEY = 'vequil_workspace_key';

const $ = id => document.getElementById(id);
const currency = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });

let currentWorkspaceId = '';
let currentWorkspaceSlug = 'all';
let allEvents = [];
let allAnomalies = [];
let allWorkspaces = [];

function storedKey() {
  return localStorage.getItem(LS_KEY) || '';
}

function workspaceKey() {
  return localStorage.getItem(LS_WORKSPACE_KEY) || '';
}

function fmtMoney(value) {
  const amount = Number(value || 0);
  return currency.format(amount);
}

function fmtDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function setStatus(state, label) {
  const pill = $('status-pill');
  pill.className = `status-pill ${state}`;
  pill.textContent = label;
}

function showAuth() {
  $('app').style.display = 'none';
  $('auth-gate').style.display = 'flex';
}

function showApp() {
  $('auth-gate').style.display = 'none';
  $('app').style.display = 'flex';
  hydrateActivation();
  loadOverview();
}

async function submitKey() {
  const key = $('api-key-input').value.trim();
  if (!key) return;

  $('auth-error').style.display = 'none';
  $('auth-submit').disabled = true;
  $('auth-submit').textContent = 'Verifying…';

  try {
    const res = await fetch('/api/health', {
      headers: { 'X-API-Key': key }
    });
    if (!res.ok) throw new Error('Unauthorized');
    localStorage.setItem(LS_KEY, key);
    showApp();
  } catch {
    $('auth-error').style.display = 'block';
  } finally {
    $('auth-submit').disabled = false;
    $('auth-submit').textContent = 'Unlock Console';
  }
}

async function apiFetch(path, params = {}) {
  const url = new URL(path, window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== '' && value !== null && value !== undefined) {
      url.searchParams.set(key, String(value));
    }
  });

  const res = await fetch(url, {
    headers: storedKey() ? { 'X-API-Key': storedKey() } : {}
  });
  if (res.status === 401) {
    showAuth();
    throw new Error('Unauthorized');
  }
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    throw new Error(payload.detail || payload.error || `Server error ${res.status}`);
  }
  return res.json();
}

function setActivationState(connected) {
  const badge = $('activation-state');
  badge.textContent = connected ? 'Connected' : 'Not Connected';
  badge.className = connected ? 'panel-badge' : 'panel-badge danger';
}

function setActivationMessage(message, isError = false) {
  const node = $('activation-msg');
  node.textContent = message;
  node.style.color = isError ? '#dc2626' : '';
}

function hydrateActivation() {
  const key = workspaceKey();
  $('workspace-key').value = key;
  setActivationState(Boolean(key));
}

async function createWorkspace() {
  const name = $('workspace-name').value.trim();
  const slug = $('workspace-slug').value.trim().toLowerCase();
  if (!name || !slug) {
    setActivationMessage('Workspace name and slug are required.', true);
    return;
  }

  try {
    const res = await fetch('/api/workspaces', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(storedKey() ? { 'X-API-Key': storedKey() } : {})
      },
      body: JSON.stringify({ name, slug })
    });
    const payload = await res.json();
    if (!res.ok) throw new Error(payload.detail || payload.error || 'Failed to create workspace');

    localStorage.setItem(LS_WORKSPACE_KEY, payload.workspace.ingest_api_key);
    $('workspace-key').value = payload.workspace.ingest_api_key;
    $('workspace-name').value = payload.workspace.name;
    $('workspace-slug').value = payload.workspace.slug;
    setActivationState(true);
    setActivationMessage(`Workspace ${payload.workspace.name} is ready. Send one test event to validate ingest.`);
    await loadOverview();
  } catch (err) {
    setActivationMessage(err.message || 'Workspace creation failed.', true);
  }
}

async function sendSampleActivity() {
  const wsKey = $('workspace-key').value.trim() || workspaceKey();
  if (!wsKey) {
    setActivationMessage('Create a workspace first to get a key.', true);
    return;
  }

  const event = {
    source: 'openclaw',
    event_type: 'tool_call',
    event_status: 'success',
    event_at: new Date().toISOString(),
    agent_id: 'main-agent',
    session_id: 'main-session',
    tool_name: 'bash',
    cost_usd: 0.01,
    metadata: {
      action_id: `evt-${Date.now()}`,
      project: 'vequil',
      environment: 'dashboard'
    }
  };

  try {
    const res = await fetch('/api/ingest', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Workspace-Key': wsKey
      },
      body: JSON.stringify(event)
    });
    const payload = await res.json();
    if (!res.ok) throw new Error(payload.detail || payload.error || 'Failed to ingest test event');
    setActivationState(true);
    setActivationMessage(`Test event accepted as #${payload.event_id}. The console is now live.`);
    await loadOverview();
  } catch (err) {
    setActivationMessage(err.message || 'Test event failed.', true);
  }
}

function metricCard(title, value, color = '') {
  const card = document.createElement('div');
  card.className = 'metric';
  card.innerHTML = `
    <div class="metric-title">${title}</div>
    <div class="metric-value ${color}">${value}</div>
  `;
  return card;
}

function renderMetrics(metrics) {
  const container = $('metrics');
  container.innerHTML = '';
  container.append(
    metricCard('Total Events', metrics.total_events.toLocaleString()),
    metricCard('Anomalies', metrics.anomaly_events.toLocaleString(), metrics.anomaly_events ? 'danger' : 'success'),
    metricCard('Resolved', metrics.resolved_events.toLocaleString(), metrics.resolved_events ? 'success' : ''),
    metricCard('Success Rate', `${metrics.success_rate}%`, metrics.success_rate >= 95 ? 'success' : 'blue'),
    metricCard('Spend', fmtMoney(metrics.total_cost_usd), metrics.total_cost_usd > 0 ? 'blue' : ''),
    metricCard('Active Agents', metrics.active_agents.toLocaleString()),
    metricCard('Sources', metrics.active_sources.toLocaleString()),
    metricCard('Workspaces', metrics.active_workspaces.toLocaleString())
  );
}

function renderList(targetId, rows, emptyText, renderRow) {
  const container = $(targetId);
  container.innerHTML = '';
  if (!rows.length) {
    const empty = document.createElement('div');
    empty.className = 'muted';
    empty.textContent = emptyText;
    container.append(empty);
    return;
  }
  const list = document.createElement('div');
  list.className = 'summary-list';
  rows.forEach(row => list.append(renderRow(row)));
  container.append(list);
}

function summaryItem(name, meta, amount) {
  const item = document.createElement('div');
  item.className = 'summary-item';
  item.innerHTML = `
    <div>
      <div class="summary-item-name">${name}</div>
      <div class="summary-meta">${meta}</div>
    </div>
    <div class="summary-amount">${amount}</div>
  `;
  return item;
}

function renderWorkspaces(rows) {
  $('workspace-count').textContent = `${rows.length} total`;
  renderList(
    'workspace-summary',
    rows,
    'No workspaces yet.',
    row => summaryItem(
      row.name,
      `${row.event_count} events · ${row.anomaly_count} anomalies · ${row.last_event_at ? fmtDate(row.last_event_at) : 'No activity yet'}`,
      fmtMoney(row.total_cost_usd)
    )
  );
}

function renderRuntimes(rows) {
  $('runtime-count').textContent = `${rows.length} sources`;
  renderList(
    'runtime-summary',
    rows,
    'No runtime activity yet.',
    row => summaryItem(
      row.source,
      `${row.event_count} events · ${row.anomaly_count} anomalies · ${row.agent_count} agents`,
      fmtMoney(row.total_cost_usd)
    )
  );
}

function flagClass(label) {
  const text = (label || '').toLowerCase();
  if (text.includes('loop')) return 'duplicate';
  if (text.includes('blocked') || text.includes('denied')) return 'missing-auth';
  if (text.includes('cost')) return 'high-value';
  if (text.includes('time') || text.includes('warn')) return 'unsettled';
  return 'variance';
}

function renderAnomalies(rows) {
  const tbody = $('anomaly-queue');
  tbody.innerHTML = '';
  $('finding-count').textContent = `${rows.length} open`;
  $('no-anomalies').style.display = rows.length ? 'none' : 'block';

  rows.forEach(row => {
    const tr = document.createElement('tr');
    const resolutionCell = document.createElement('td');
    const resolutionWrap = document.createElement('div');
    resolutionWrap.className = 'resolve-cell';

    if (row.resolved_note) {
      resolutionWrap.innerHTML = `
        <div class="res-status">Resolved</div>
        <div class="res-note">${row.resolved_note}</div>
      `;
    } else {
      const btn = document.createElement('button');
      btn.className = 'resolve-btn';
      btn.textContent = 'Resolve';
      btn.onclick = () => reviewEvent(row);
      resolutionWrap.append(btn);
    }
    resolutionCell.append(resolutionWrap);

    const anomalyBadge = `<span class="flag-badge ${flagClass(row.anomaly_label)}">${row.anomaly_label || '—'}</span>`;
    tr.innerHTML = `
      <td>${fmtDate(row.event_at)}</td>
      <td>${row.workspace_name}</td>
      <td>${row.source}</td>
      <td>${row.agent_id}</td>
      <td>${row.tool_name || '—'}</td>
      <td>${anomalyBadge}</td>
      <td>${row.event_status}</td>
    `;
    tr.append(resolutionCell);
    tbody.append(tr);
  });
}

function renderEvents(rows) {
  const tbody = $('events-table');
  tbody.innerHTML = '';
  $('event-count').textContent = `${rows.length} shown`;
  $('no-events').style.display = rows.length ? 'none' : 'block';

  rows.forEach(row => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${fmtDate(row.event_at)}</td>
      <td>${row.workspace_name}</td>
      <td>${row.source}</td>
      <td>${row.agent_id}</td>
      <td>${row.event_type}</td>
      <td>${row.tool_name || '—'}</td>
      <td>${row.event_status}</td>
      <td>${fmtMoney(row.cost_usd)}</td>
    `;
    tbody.append(tr);
  });
}

function populateWorkspaceFilter(rows, selectedWorkspace) {
  const select = $('workspace-filter');
  const previous = currentWorkspaceId;
  select.innerHTML = '<option value="">All workspaces</option>';
  rows.forEach(row => {
    const option = document.createElement('option');
    option.value = String(row.id);
    option.textContent = row.name;
    select.append(option);
  });

  const nextValue = selectedWorkspace ? String(selectedWorkspace.id) : previous;
  if ([...select.options].some(option => option.value === nextValue)) {
    select.value = nextValue;
  } else {
    select.value = '';
  }

  currentWorkspaceId = select.value;
  const match = rows.find(row => String(row.id) === select.value);
  currentWorkspaceSlug = match ? match.slug : 'all';
}

async function loadOverview() {
  $('loading-state').style.display = 'flex';
  $('error-state').style.display = 'none';
  $('dashboard-content').style.opacity = '0.35';
  setStatus('running', 'Refreshing');

  try {
    const payload = await apiFetch('/api/overview', currentWorkspaceId ? { workspace_id: currentWorkspaceId } : {});

    allEvents = payload.recent_events || [];
    allAnomalies = payload.recent_anomalies || [];
    allWorkspaces = payload.workspaces || [];

    populateWorkspaceFilter(payload.workspaces || [], payload.selected_workspace);
    renderMetrics(payload.metrics);
    renderWorkspaces(payload.workspaces || []);
    renderRuntimes(payload.runtimes || []);
    renderAnomalies(allAnomalies);
    renderEvents(allEvents);

    $('generated-at').textContent = payload.metrics.last_event_at
      ? `Last event ${fmtDate(payload.metrics.last_event_at)}`
      : 'No live events yet';

    setActivationState(Boolean(workspaceKey()) || payload.metrics.total_events > 0);
    setStatus('done', 'Live');
  } catch (err) {
    $('error-msg').textContent = err.message || 'Failed to load console.';
    $('error-state').style.display = 'flex';
    setStatus('error', 'Error');
  } finally {
    $('loading-state').style.display = 'none';
    $('dashboard-content').style.opacity = '1';
  }
}

async function reviewEvent(row) {
  const note = window.prompt(`Resolution note for event #${row.event_id}`, 'Reviewed by operator.');
  if (note === null) return;
  try {
    const res = await fetch('/api/resolve', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(storedKey() ? { 'X-API-Key': storedKey() } : {})
      },
      body: JSON.stringify({ event_id: row.event_id, resolution: note })
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(payload.detail || payload.error || 'Failed to resolve event');
    await loadOverview();
  } catch (err) {
    window.alert(err.message || 'Failed to resolve event');
  }
}

function applyAnomalyFilter(query) {
  const q = query.trim().toLowerCase();
  if (!q) {
    renderAnomalies(allAnomalies);
    return;
  }
  const filtered = allAnomalies.filter(row =>
    [row.workspace_name, row.source, row.agent_id, row.tool_name, row.anomaly_label, row.event_status]
      .some(value => String(value || '').toLowerCase().includes(q))
  );
  renderAnomalies(filtered);
}

function applyEventsFilter(query) {
  const q = query.trim().toLowerCase();
  if (!q) {
    renderEvents(allEvents);
    return;
  }
  const filtered = allEvents.filter(row =>
    [row.workspace_name, row.source, row.agent_id, row.tool_name, row.event_type, row.event_status]
      .some(value => String(value || '').toLowerCase().includes(q))
  );
  renderEvents(filtered);
}

async function copyPublicLink() {
  const path = `/report/${currentWorkspaceSlug || 'all'}`;
  await navigator.clipboard.writeText(`${window.location.origin}${path}`);
}

function showReportCard() {
  const totalEvents = allEvents.length;
  const anomalies = allAnomalies.length;
  const topAgent = allEvents[0]?.agent_id || 'No active agent';
  const topAnomaly = allAnomalies[0]?.anomaly_label || 'No anomalies detected';

  $('report-card-preview').innerHTML = `
    <div class="inner-card">
      <div class="ic-header">
        <div class="ic-title">Weekly Agent Report</div>
        <div class="ic-badge">${currentWorkspaceSlug === 'all' ? 'ALL WORKSPACES' : currentWorkspaceSlug.toUpperCase()}</div>
      </div>
      <div class="ic-stats">
        <div class="ics-item">
          <span class="label">Activity</span>
          <div class="val">${totalEvents.toLocaleString()} events</div>
          <div class="sub">Captured by Vequil</div>
        </div>
        <div class="ics-item">
          <span class="label">Anomaly Risk</span>
          <div class="val">${anomalies.toLocaleString()} flagged</div>
          <div class="sub">${topAnomaly}</div>
        </div>
        <div class="ics-item">
          <span class="label">Most Active Agent</span>
          <div class="val">${topAgent}</div>
          <div class="sub">Most recent high-volume runtime</div>
        </div>
      </div>
      <div class="ic-stamp">VEQUIL VERIFIED</div>
    </div>
  `;
  $('report-modal').style.display = 'flex';
}

$('auth-submit').addEventListener('click', submitKey);
$('api-key-input').addEventListener('keydown', event => {
  if (event.key === 'Enter') submitKey();
});
$('logout-btn').addEventListener('click', () => {
  localStorage.removeItem(LS_KEY);
  showAuth();
});
$('create-workspace-btn').addEventListener('click', createWorkspace);
$('sample-activity-btn').addEventListener('click', sendSampleActivity);
$('copy-key-btn').addEventListener('click', async () => {
  const value = $('workspace-key').value.trim();
  if (!value) {
    setActivationMessage('No workspace key to copy yet.', true);
    return;
  }
  await navigator.clipboard.writeText(value);
  setActivationMessage('Workspace key copied.');
});
$('refresh-btn').addEventListener('click', loadOverview);
$('retry-btn').addEventListener('click', loadOverview);
$('workspace-filter').addEventListener('change', event => {
  currentWorkspaceId = event.target.value;
  const match = allWorkspaces.find(row => String(row.id) === currentWorkspaceId);
  currentWorkspaceSlug = match ? match.slug : 'all';
  loadOverview();
});
$('queue-filter').addEventListener('input', event => applyAnomalyFilter(event.target.value));
$('events-filter').addEventListener('input', event => applyEventsFilter(event.target.value));
$('copy-report-link').addEventListener('click', copyPublicLink);
$('copy-report-link-modal').addEventListener('click', copyPublicLink);
$('nav-report').addEventListener('click', event => {
  event.preventDefault();
  showReportCard();
});
$('close-modal').addEventListener('click', () => {
  $('report-modal').style.display = 'none';
});
window.addEventListener('click', event => {
  if (event.target === $('report-modal')) {
    $('report-modal').style.display = 'none';
  }
});

if (storedKey()) {
  showApp();
} else {
  showAuth();
}
