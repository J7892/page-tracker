// Application State
let monitors = [];
let smtpSettings = {};
let activeTab = 'monitors';
let selectedMonitor = null;
let selectedVersion = null;
let currentDiffMode = 'split'; // 'split', 'unified', 'raw'

// GitHub Integration Credentials (cached in LocalStorage)
let githubConfig = {
  repo: localStorage.getItem('gh_repo') || '',
  branch: localStorage.getItem('gh_branch') || 'main',
  token: localStorage.getItem('gh_token') || ''
};

// Determine if we are hosted statically (e.g. GitHub Pages) or on a different local port
const isStatic = window.location.hostname.endsWith('github.io') || 
                 window.location.protocol === 'file:' || 
                 !window.location.port || 
                 window.location.port !== '5001';

function getBaseUrl() {
  const path = window.location.pathname;
  if (path.endsWith('.html')) {
    return path.substring(0, path.lastIndexOf('/') + 1);
  }
  return path.endsWith('/') ? path : path + '/';
}

// Application Initialization
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initApp);
} else {
  initApp();
}

function initApp() {
  // Update GitHub Form UI from cache
  document.getElementById('gh_repo').value = githubConfig.repo;
  document.getElementById('gh_branch').value = githubConfig.branch;
  document.getElementById('gh_token').value = githubConfig.token;
  
  if (isGitHubMode()) {
    document.getElementById('btn-gh-disconnect').style.display = 'block';
    updateModeIndicator(true);
  } else {
    updateModeIndicator(false);
  }

  // Load monitors
  refreshMonitorsList();
  
  // Load Settings
  loadSettings();
}

function isGitHubMode() {
  return githubConfig.token && githubConfig.repo;
}

function updateModeIndicator(isGithub) {
  const badge = document.getElementById('mode-badge');
  const infoBlock = document.getElementById('github-info-block');
  const anchor = document.getElementById('github-repo-anchor');
  
  if (isGithub) {
    badge.innerHTML = '<span class="status-dot orange"></span> GitHub Mode';
    badge.className = 'mode-indicator';
    infoBlock.style.display = 'block';
    anchor.innerText = `🐙 ${githubConfig.repo}`;
    anchor.href = `https://github.com/${githubConfig.repo}`;
  } else {
    badge.innerHTML = '<span class="status-dot green"></span> Server Mode';
    badge.className = 'mode-indicator';
    infoBlock.style.display = 'none';
  }
}

// Tab Switching Navigation
function switchTab(tabId) {
  activeTab = tabId;
  document.querySelectorAll('.nav-item').forEach(btn => btn.classList.remove('active'));
  document.querySelectorAll('.app-panel').forEach(panel => panel.classList.remove('active'));
  
  if (tabId === 'monitors') {
    document.getElementById('nav-monitors').classList.add('active');
    document.getElementById('panel-monitors').classList.add('active');
    document.getElementById('page-title').innerText = 'Monitored Webpages';
    document.getElementById('page-subtitle').innerText = 'Track visual changes and receive alerts';
    refreshMonitorsList();
  } else if (tabId === 'settings') {
    document.getElementById('nav-settings').classList.add('active');
    document.getElementById('panel-settings').classList.add('active');
    document.getElementById('page-title').innerText = 'System Configurations';
    document.getElementById('page-subtitle').innerText = 'Configure SMTP alerts and GitHub integrations';
    loadSettings();
  }
}

// REST API and GitHub API Request Wrapper
async function apiRequest(endpoint, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  const isConfigRoute = endpoint.startsWith('/api/monitors');
  
  if (isStatic) {
    if (method === 'GET') {
      if (endpoint === '/api/monitors') {
        const res = await fetch(getBaseUrl() + 'data/monitors.json', { cache: 'no-store' });
        if (!res.ok) return [];
        return await res.json();
      }
      if (endpoint.startsWith('/api/history/')) {
        const monitorId = endpoint.split('/').pop();
        const res = await fetch(getBaseUrl() + `data/archive/${monitorId}/history.json`, { cache: 'no-store' });
        if (!res.ok) return [];
        return await res.json();
      }
      if (endpoint === '/api/settings') {
        return {
          smtp_host: '',
          smtp_port: 587,
          smtp_user: '',
          smtp_secure: true,
          email_from: '',
          email_to: '',
          has_password: false,
          env_overridden: true
        };
      }
    } else {
      // POST or DELETE
      if (isGitHubMode()) {
        if (isConfigRoute) {
          return handleGithubApiRequest(endpoint, options);
        }
      } else {
        alert("To add, edit, or delete monitors when hosted on GitHub Pages, you must first configure your GitHub Personal Access Token in the Settings panel.");
        throw new Error("GitHub credentials required.");
      }
    }
  }

  // Server Mode (Standard Local Flask Server APIs)
  if (isGitHubMode() && isConfigRoute) {
    return handleGithubApiRequest(endpoint, options);
  }
  
  try {
    const response = await fetch(endpoint, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(options.headers || {})
      }
    });
    if (!response.ok) {
      // Read response as text first, to handle HTML 404s gracefully
      const text = await response.text();
      let errorMsg = `HTTP error ${response.status}`;
      try {
        const err = JSON.parse(text);
        errorMsg = err.error || errorMsg;
      } catch (e) {}
      throw new Error(errorMsg);
    }
    return await response.json();
  } catch (error) {
    console.error(`API Error on ${endpoint}:`, error);
    showToast(`Error: ${error.message}`, true);
    throw error;
  }
}

// GitHub API Client implementation for Serverless Storage
async function handleGithubApiRequest(endpoint, options = {}) {
  const repo = githubConfig.repo;
  const branch = githubConfig.branch;
  const token = githubConfig.token;
  const path = 'data/monitors.json';
  const url = `https://api.github.com/repos/${repo}/contents/${path}?ref=${branch}`;
  
  const headers = {
    'Authorization': `Bearer ${token}`,
    'Accept': 'application/vnd.github.v3+json',
    'Content-Type': 'application/json'
  };

  try {
    // 1. Fetch file meta (to get SHA and current content)
    let sha = null;
    let currentContent = [];
    
    const fileRes = await fetch(url, { headers, cache: 'no-store' });
    if (fileRes.status === 200) {
      const fileData = await fileRes.json();
      sha = fileData.sha;
      const contentRaw = atob(fileData.content.replace(/\n/g, ''));
      currentContent = JSON.parse(contentRaw);
    } else if (fileRes.status !== 404) {
      throw new Error(`GitHub API returned status ${fileRes.status}`);
    }

    // 2. Perform GET
    if (endpoint === '/api/monitors' && (!options.method || options.method === 'GET')) {
      return currentContent;
    }

    // 3. Perform POST (Add/Edit)
    if (endpoint === '/api/monitors' && options.method === 'POST') {
      const body = JSON.parse(options.body);
      let monitor = null;
      let isEdit = false;
      
      if (body.id) {
        // Edit existing
        isEdit = true;
        currentContent = currentContent.map(m => {
          if (m.id === body.id) {
            monitor = { ...m, ...body };
            return monitor;
          }
          return m;
        });
      } else {
        // Create new
        const id = body.name.toLowerCase().replace(/[^a-z0-9\-]/g, '-').replace(/-+/g, '-').trim();
        monitor = {
          id: `${id}-${Date.now().toString().slice(-4)}`,
          ...body,
          last_checked: null,
          last_changed: null,
          status: 'pending',
          last_error: null
        };
        currentContent.push(monitor);
      }

      // Commit changes to GitHub
      const commitUrl = `https://api.github.com/repos/${repo}/contents/${path}`;
      const commitBody = {
        message: isEdit ? `Update monitor: ${monitor.name}` : `Add monitor: ${monitor.name}`,
        content: btoa(unescape(encodeURIComponent(JSON.stringify(currentContent, null, 2)))),
        branch: branch,
        sha: sha
      };

      const commitRes = await fetch(commitUrl, {
        method: 'PUT',
        headers,
        body: JSON.stringify(commitBody)
      });

      if (!commitRes.ok) {
        const err = await commitRes.json();
        throw new Error(`GitHub commit failed: ${err.message}`);
      }

      showToast(`Monitor ${isEdit ? 'updated' : 'added'} inside GitHub repository!`);
      return { success: true, monitor, monitors: currentContent };
    }

    // 4. Perform DELETE
    if (endpoint.startsWith('/api/monitors/') && options.method === 'DELETE') {
      const monitorId = endpoint.split('/').pop();
      const updatedContent = currentContent.filter(m => m.id !== monitorId);
      
      const commitUrl = `https://api.github.com/repos/${repo}/contents/${path}`;
      const commitBody = {
        message: `Delete monitor: ${monitorId}`,
        content: btoa(unescape(encodeURIComponent(JSON.stringify(updatedContent, null, 2)))),
        branch: branch,
        sha: sha
      };

      const commitRes = await fetch(commitUrl, {
        method: 'PUT',
        headers,
        body: JSON.stringify(commitBody)
      });

      if (!commitRes.ok) {
        const err = await commitRes.json();
        throw new Error(`GitHub commit failed: ${err.message}`);
      }

      showToast("Monitor deleted from GitHub repository.");
      return { success: true, monitors: updatedContent };
    }
  } catch (error) {
    console.error("GitHub API Request Failure:", error);
    showToast(`GitHub API Error: ${error.message}`, true);
    throw error;
  }
}

// Fetch historical raw files from GitHub archive
async function fetchHistoryFromGithub(monitorId) {
  const repo = githubConfig.repo;
  const branch = githubConfig.branch;
  const token = githubConfig.token;
  const path = `data/archive/${monitorId}/history.json`;
  const url = `https://api.github.com/repos/${repo}/contents/${path}?ref=${branch}`;

  const headers = {
    'Authorization': `Bearer ${token}`,
    'Accept': 'application/vnd.github.v3+raw'
  };

  try {
    const res = await fetch(url, { headers, cache: 'no-store' });
    if (res.status === 404) return [];
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.error(`Error loading history from GitHub for ${monitorId}:`, err);
    return [];
  }
}

// Fetch content of specific archive file
async function fetchFileContent(monitorId, filename) {
  if (isGitHubMode()) {
    const repo = githubConfig.repo;
    const branch = githubConfig.branch;
    const token = githubConfig.token;
    const path = `data/archive/${monitorId}/${filename}`;
    const url = `https://api.github.com/repos/${repo}/contents/${path}?ref=${branch}`;
    
    try {
      const res = await fetch(url, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Accept': 'application/vnd.github.v3+raw'
        },
        cache: 'no-store'
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.text();
    } catch (err) {
      console.error("Failed to load archive content from GitHub:", err);
      return "";
    }
  } else if (isStatic) {
    // Hosted statically: fetch relative path directly from site files
    try {
      const res = await fetch(getBaseUrl() + `data/archive/${monitorId}/${filename}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.text();
    } catch (err) {
      console.error("Failed to load archive content from static file:", err);
      return "";
    }
  } else {
    // In server mode, we get the diff containing text via local API
    try {
      const data = await apiRequest(`/api/diff/${monitorId}/${selectedVersion.timestamp}`);
      return data.current_text;
    } catch (err) {
      console.error(err);
      return null;
    }
  }
}

// Load Monitors Configurations
async function refreshMonitorsList() {
  const listContainer = document.getElementById('monitors-list');
  
  try {
    monitors = await apiRequest('/api/monitors');
    
    // Update Stats Row
    document.getElementById('stat-total').innerText = monitors.length;
    document.getElementById('stat-active').innerText = monitors.filter(m => m.active).length;
    
    // Count trackers showing changes
    const changesCount = monitors.filter(m => m.last_changed && m.last_checked && m.last_changed === m.last_checked).length;
    document.getElementById('stat-changes').innerText = changesCount;
    
    if (monitors.length === 0) {
      listContainer.innerHTML = `
        <div class="empty-state">
          <span style="font-size: 48px; margin-bottom: 12px;">🔍</span>
          <h3>No Webpages Monitored Yet</h3>
          <p class="text-muted">Add your first target URL to begin checking for content changes.</p>
          <button class="btn btn-primary" onclick="openMonitorModal()" style="margin-top: 16px;">Add Monitor</button>
        </div>
      `;
      return;
    }
    
    listContainer.innerHTML = '';
    
    monitors.forEach(monitor => {
      // Setup status badges and formatting
      let statusBadge = `<span class="badge badge-secondary">Pending</span>`;
      let cardBorderClass = '';
      
      if (monitor.status === 'success') {
        const hasChange = monitor.last_changed && monitor.last_checked && monitor.last_changed === monitor.last_checked;
        if (hasChange) {
          statusBadge = `<span class="badge badge-warning">Change Found</span>`;
        } else {
          statusBadge = `<span class="badge badge-success">No Changes</span>`;
        }
      } else if (monitor.status === 'failed') {
        statusBadge = `<span class="badge badge-danger" title="${monitor.last_error || 'Error'}">Error</span>`;
      }
      
      const lastCheck = monitor.last_checked ? formatRelativeTime(monitor.last_checked) : 'Never';
      const lastChange = monitor.last_changed ? formatRelativeTime(monitor.last_changed) : 'Never';
      
      const card = document.createElement('div');
      card.className = `monitor-card`;
      card.innerHTML = `
        <div class="card-body" onclick="openHistoryDrawer('${monitor.id}')">
          <div class="card-title-row">
            <h3 class="card-title">${monitor.name}</h3>
            ${statusBadge}
          </div>
          <div class="card-url" title="${monitor.url}">${monitor.url}</div>
          
          <div class="card-meta-grid">
            <div class="meta-item">
              <span class="meta-label">Last Checked</span>
              <span class="meta-value">${lastCheck}</span>
            </div>
            <div class="meta-item">
              <span class="meta-label">Last Change</span>
              <span class="meta-value">${lastChange}</span>
            </div>
            <div class="meta-item">
              <span class="meta-label">Schedule</span>
              <span class="meta-value">${monitor.check_interval_mins} mins</span>
            </div>
            <div class="meta-item">
              <span class="meta-label">Sensitivity</span>
              <span class="meta-value" style="text-transform: capitalize;">${monitor.sensitivity}</span>
            </div>
          </div>
        </div>
        
        <div class="card-actions">
          <div class="action-left">
            <label class="switch" title="Toggle Monitoring Activity">
              <input type="checkbox" ${monitor.active ? 'checked' : ''} onchange="toggleMonitorActive('${monitor.id}', this.checked)">
              <span class="slider"></span>
            </label>
            <span class="small-text text-muted">${monitor.active ? 'Active' : 'Paused'}</span>
          </div>
          
          <div class="action-buttons">
            <button class="btn-icon" title="Trigger Scan Now" onclick="triggerSingleCheck('${monitor.id}', event)">🔄</button>
            <button class="btn-icon" title="Edit Monitor Config" onclick="openMonitorModal('${monitor.id}', event)">✏️</button>
            <button class="btn-icon delete" title="Delete Monitor" onclick="deleteMonitor('${monitor.id}', event)">🗑️</button>
          </div>
        </div>
      `;
      listContainer.appendChild(card);
    });
    
  } catch (error) {
    listContainer.innerHTML = `
      <div class="empty-state">
        <span style="font-size: 48px; margin-bottom: 12px; color: var(--color-danger);">⚠️</span>
        <h3>Failed to Load Monitors</h3>
        <p class="text-muted">${error.message}</p>
        <button class="btn btn-secondary" onclick="refreshMonitorsList()" style="margin-top: 16px;">Try Again</button>
      </div>
    `;
  }
}

// Single Monitor Actions
async function toggleMonitorActive(monitorId, isActive) {
  const monitor = monitors.find(m => m.id === monitorId);
  if (!monitor) return;
  
  const updatedMonitor = { ...monitor, active: isActive };
  
  try {
    await apiRequest('/api/monitors', {
      method: 'POST',
      body: JSON.stringify(updatedMonitor)
    });
    showToast(`Monitor ${isActive ? 'activated' : 'paused'}.`);
    refreshMonitorsList();
  } catch (err) {
    console.error(err);
  }
}

async function triggerSingleCheck(monitorId, event) {
  event.stopPropagation();
  showToast("Scanning target webpage...");
  
  if (isGitHubMode()) {
    showToast("Manual checks cannot be triggered via GitHub pages dashboard directly. Trigger the workflow in your GitHub Repository or wait for the scheduler.", true);
    return;
  }
  
  try {
    await apiRequest('/api/check', {
      method: 'POST',
      body: JSON.stringify({ id: monitorId })
    });
    showToast("Scan complete.");
    refreshMonitorsList();
  } catch (err) {
    console.error(err);
  }
}

async function triggerAllChecks() {
  showToast("Scanning all active trackers...");
  
  if (isGitHubMode()) {
    showToast("Manual checks cannot be triggered via GitHub pages dashboard directly. Trigger the workflow in your GitHub Repository or wait for the scheduler.", true);
    return;
  }
  
  try {
    await apiRequest('/api/check', {
      method: 'POST',
      body: JSON.stringify({})
    });
    showToast("All webpage scans complete.");
    refreshMonitorsList();
  } catch (err) {
    console.error(err);
  }
}

async function deleteMonitor(monitorId, event) {
  event.stopPropagation();
  if (!confirm("Are you sure you want to delete this monitor? Configuration will be lost.")) return;
  
  try {
    await apiRequest(`/api/monitors/${monitorId}`, { method: 'DELETE' });
    refreshMonitorsList();
  } catch (err) {
    console.error(err);
  }
}

// Add/Edit Modal controls
function openMonitorModal(monitorId = null, event = null) {
  if (event) event.stopPropagation();
  
  const modal = document.getElementById('monitor-modal');
  const title = document.getElementById('modal-title');
  const form = document.getElementById('form-monitor');
  
  form.reset();
  document.getElementById('monitor_id').value = '';
  document.getElementById('tester-output-container').style.display = 'none';
  document.getElementById('selectors-accordion').style.display = 'none';
  document.getElementById('selectors-accordion-icon').innerText = '▼';
  document.querySelector('.accordion-section').classList.remove('open');
  
  if (monitorId) {
    title.innerText = 'Edit Monitor';
    const monitor = monitors.find(m => m.id === monitorId);
    if (monitor) {
      document.getElementById('monitor_id').value = monitor.id;
      document.getElementById('monitor_name').value = monitor.name;
      document.getElementById('monitor_url').value = monitor.url;
      document.getElementById('check_interval_mins').value = monitor.check_interval_mins;
      document.getElementById('sensitivity').value = monitor.sensitivity;
      document.getElementById('min_char_diff').value = monitor.min_char_diff;
      document.getElementById('monitor_active').checked = monitor.active;
      document.getElementById('include_selectors').value = monitor.include_selectors || '';
      document.getElementById('ignore_selectors').value = monitor.ignore_selectors || '';
    }
  } else {
    title.innerText = 'Add Monitor';
  }
  
  modal.classList.add('active');
}

function closeMonitorModal() {
  document.getElementById('monitor-modal').classList.remove('active');
}

async function submitMonitorForm(event) {
  event.preventDefault();
  
  const monitorId = document.getElementById('monitor_id').value;
  const monitorData = {
    name: document.getElementById('monitor_name').value,
    url: document.getElementById('monitor_url').value,
    check_interval_mins: parseInt(document.getElementById('check_interval_mins').value),
    sensitivity: document.getElementById('sensitivity').value,
    min_char_diff: parseInt(document.getElementById('min_char_diff').value || 0),
    active: document.getElementById('monitor_active').checked,
    include_selectors: document.getElementById('include_selectors').value,
    ignore_selectors: document.getElementById('ignore_selectors').value
  };
  
  if (monitorId) {
    monitorData.id = monitorId;
  }
  
  try {
    await apiRequest('/api/monitors', {
      method: 'POST',
      body: JSON.stringify(monitorData)
    });
    closeMonitorModal();
    refreshMonitorsList();
  } catch (err) {
    console.error(err);
  }
}

// Selector Tester Execution
async function runSelectorTest() {
  const url = document.getElementById('monitor_url').value;
  if (!url) {
    alert("Please enter a URL first to run the text extraction test.");
    return;
  }
  
  if (isGitHubMode()) {
    alert("HTML selector testing requires the backend server running locally. It cannot fetch websites directly in the browser due to CORS security policies.");
    return;
  }

  const include_selectors = document.getElementById('include_selectors').value;
  const ignore_selectors = document.getElementById('ignore_selectors').value;
  
  const loader = document.getElementById('tester-loader');
  const outputContainer = document.getElementById('tester-output-container');
  const output = document.getElementById('tester-output');
  
  loader.style.display = 'block';
  outputContainer.style.display = 'none';
  
  try {
    const data = await apiRequest('/api/test-selectors', {
      method: 'POST',
      body: JSON.stringify({ url, include_selectors, ignore_selectors })
    });
    
    loader.style.display = 'none';
    outputContainer.style.display = 'block';
    
    document.getElementById('test-badge-chars').innerText = `${data.char_count} chars`;
    document.getElementById('test-badge-words').innerText = `${data.word_count} words`;
    document.getElementById('test-badge-lines').innerText = `${data.line_count} lines`;
    
    output.innerText = data.preview || '[Empty Output - Nothing matches selectors or body]';
    if (data.truncated) {
      output.innerText += "\n\n... (Output truncated to first 100 lines) ...";
    }
  } catch (err) {
    loader.style.display = 'none';
    alert(`Testing failed: ${err.message}`);
  }
}

// SMTP Settings
async function loadSettings() {
  if (isGitHubMode()) {
    // Populate form fields with stub/env settings if available
    document.getElementById('smtp_host').disabled = true;
    document.getElementById('smtp_port').disabled = true;
    document.getElementById('smtp_user').disabled = true;
    document.getElementById('smtp_pass').disabled = true;
    document.getElementById('email_from').disabled = true;
    document.getElementById('email_to').disabled = true;
    document.getElementById('smtp_secure').disabled = true;
    
    const fields = ['smtp_host', 'smtp_port', 'smtp_user', 'email_from', 'email_to'];
    fields.forEach(f => {
      const el = document.getElementById(f);
      el.value = '';
      el.placeholder = 'Read from GitHub Secrets';
    });
    return;
  }
  
  try {
    smtpSettings = await apiRequest('/api/settings');
    
    document.getElementById('smtp_host').value = smtpSettings.smtp_host || '';
    document.getElementById('smtp_port').value = smtpSettings.smtp_port || 587;
    document.getElementById('smtp_user').value = smtpSettings.smtp_user || '';
    document.getElementById('smtp_pass').value = '';
    document.getElementById('smtp_pass').placeholder = smtpSettings.has_password ? '••••••••••••••••' : '';
    document.getElementById('email_from').value = smtpSettings.email_from || '';
    document.getElementById('email_to').value = smtpSettings.email_to || '';
    document.getElementById('smtp_secure').checked = smtpSettings.smtp_secure;
    
    // Warn if env overrides config
    if (smtpSettings.env_overridden) {
      showToast("Config loaded. Note: Environment variables are currently overriding config files.");
    }
  } catch (err) {
    console.error(err);
  }
}

async function saveSettings(event) {
  event.preventDefault();
  
  const settingsData = {
    smtp_host: document.getElementById('smtp_host').value,
    smtp_port: parseInt(document.getElementById('smtp_port').value),
    smtp_user: document.getElementById('smtp_user').value,
    smtp_pass: document.getElementById('smtp_pass').value,
    email_from: document.getElementById('email_from').value,
    email_to: document.getElementById('email_to').value,
    smtp_secure: document.getElementById('smtp_secure').checked
  };
  
  try {
    await apiRequest('/api/settings', {
      method: 'POST',
      body: JSON.stringify(settingsData)
    });
    showToast("SMTP settings saved.");
    loadSettings();
  } catch (err) {
    console.error(err);
  }
}

async function testEmailConnection() {
  showToast("Sending verification test email...");
  
  const settingsData = {
    smtp_host: document.getElementById('smtp_host').value,
    smtp_port: parseInt(document.getElementById('smtp_port').value),
    smtp_user: document.getElementById('smtp_user').value,
    smtp_pass: document.getElementById('smtp_pass').value,
    email_from: document.getElementById('email_from').value,
    email_to: document.getElementById('email_to').value,
    smtp_secure: document.getElementById('smtp_secure').checked
  };
  
  try {
    await apiRequest('/api/test-email', {
      method: 'POST',
      body: JSON.stringify(settingsData)
    });
    showToast("Test notification sent successfully!");
  } catch (err) {
    alert(`SMTP Test Failed: ${err.message}`);
  }
}

// GitHub Mode Setup
function saveGithubSettings(event) {
  event.preventDefault();
  
  const repo = document.getElementById('gh_repo').value.trim();
  const branch = document.getElementById('gh_branch').value.trim() || 'main';
  const token = document.getElementById('gh_token').value.trim();
  
  if (!repo || !token) {
    alert("Please fill in both the Repository (username/repo) and Personal Access Token fields to activate GitHub Mode.");
    return;
  }
  
  localStorage.setItem('gh_repo', repo);
  localStorage.setItem('gh_branch', branch);
  localStorage.setItem('gh_token', token);
  
  githubConfig = { repo, branch, token };
  
  document.getElementById('btn-gh-disconnect').style.display = 'block';
  updateModeIndicator(true);
  showToast("GitHub Mode Activated!");
  
  // Refresh page list from GitHub contents
  refreshMonitorsList();
}

function disconnectGitHub() {
  localStorage.removeItem('gh_repo');
  localStorage.removeItem('gh_branch');
  localStorage.removeItem('gh_token');
  
  githubConfig = { repo: '', branch: 'main', token: '' };
  
  document.getElementById('gh_repo').value = '';
  document.getElementById('gh_branch').value = '';
  document.getElementById('gh_token').value = '';
  
  document.getElementById('btn-gh-disconnect').style.display = 'none';
  updateModeIndicator(false);
  showToast("GitHub Mode Disconnected. Returning to Local Server Mode.");
  
  // Enable setting inputs
  const ids = ['smtp_host', 'smtp_port', 'smtp_user', 'smtp_pass', 'email_from', 'email_to', 'smtp_secure'];
  ids.forEach(id => document.getElementById(id).disabled = false);
  
  refreshMonitorsList();
  loadSettings();
}

// Timeline Drawer and Visual Diff Renderer
async function openHistoryDrawer(monitorId) {
  selectedMonitor = monitors.find(m => m.id === monitorId);
  if (!selectedMonitor) return;
  
  document.getElementById('drawer-site-name').innerText = selectedMonitor.name;
  document.getElementById('drawer-site-url').innerText = selectedMonitor.url;
  document.getElementById('drawer-site-url').href = selectedMonitor.url;
  
  // Clear diff view and timeline
  document.getElementById('history-timeline-list').innerHTML = '<div class="spinner spinner-sm"></div> Loading timeline...';
  document.getElementById('diff-view-content').innerHTML = `
    <div class="diff-empty-state">
      <span>👈 Select a version from the timeline to view changes</span>
    </div>
  `;
  document.getElementById('diff-meta-stats').style.display = 'none';
  
  document.getElementById('history-drawer-overlay').classList.add('active');
  document.getElementById('history-drawer').classList.add('active');
  
  // Load timeline items
  let history = [];
  if (isGitHubMode()) {
    history = await fetchHistoryFromGithub(monitorId);
  } else {
    try {
      history = await apiRequest(`/api/history/${monitorId}`);
    } catch (err) {
      console.error(err);
    }
  }
  
  renderTimeline(history);
}

function closeHistoryDrawer() {
  document.getElementById('history-drawer-overlay').classList.remove('active');
  document.getElementById('history-drawer').classList.remove('active');
  selectedMonitor = null;
  selectedVersion = null;
}

function renderTimeline(history) {
  const list = document.getElementById('history-timeline-list');
  list.innerHTML = '';
  
  if (history.length === 0) {
    list.innerHTML = '<div class="text-muted small-text">No archive snapshots captured yet.</div>';
    return;
  }
  
  // Sort reverse chronological
  const sorted = [...history].reverse();
  
  sorted.forEach((version, idx) => {
    const isInitial = idx === sorted.length - 1;
    const date = new Date(version.timestamp);
    const dateStr = date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
    
    const item = document.createElement('div');
    item.className = `timeline-item ${isInitial ? 'initial' : ''}`;
    item.id = `ts-item-${version.timestamp.replace(/[^a-zA-Z0-9]/g, '')}`;
    item.innerHTML = `
      <div class="timeline-time">${dateStr}</div>
      <div class="timeline-desc" title="${version.changes_summary}">${version.changes_summary}</div>
    `;
    item.onclick = () => selectTimelineVersion(version, history);
    list.appendChild(item);
  });
}

async function selectTimelineVersion(version, history) {
  selectedVersion = version;
  
  // Highlight timeline item
  document.querySelectorAll('.timeline-item').forEach(el => el.classList.remove('active'));
  const itemId = `ts-item-${version.timestamp.replace(/[^a-zA-Z0-9]/g, '')}`;
  const el = document.getElementById(itemId);
  if (el) el.classList.add('active');
  
  // Display Loader in Diff Content area
  const diffContent = document.getElementById('diff-view-content');
  diffContent.innerHTML = '<div class="empty-state"><div class="spinner"></div><p>Generating difference metrics...</p></div>';
  
  try {
    let diffData = null;
    
    if (isGitHubMode() || isStatic) {
      // Fetch the raw files directly and compute the diff in client JS
      const currentText = await fetchFileContent(selectedMonitor.id, version.filename);
      
      let previousText = "";
      const idx = history.findIndex(h => h.timestamp === version.timestamp);
      if (idx > 0) {
        const prevVersion = history[idx - 1];
        previousText = await fetchFileContent(selectedMonitor.id, prevVersion.filename);
      }
      
      // Compute diff in client JS
      const oldLines = previousText.split(/\r?\n/);
      const newLines = currentText.split(/\r?\n/);
      const diffLines = computeLcsDiff(oldLines, newLines);
      
      diffData = {
        timestamp: version.timestamp,
        summary: version.changes_summary,
        ratio: version.ratio || 1.0,
        added: version.added || 0,
        removed: version.removed || 0,
        diff: diffLines,
        current_text: currentText,
        previous_text: previousText
      };
    } else {
      // In Server Mode, fetch precomputed diff from Python FastAPI/Flask server
      diffData = await apiRequest(`/api/diff/${selectedMonitor.id}/${version.timestamp}`);
    }
    
    // Save current diff details on DOM element to allow mode switching
    diffContent.dataset.currentDiff = JSON.stringify(diffData);
    
    // Render Stats
    document.getElementById('diff-stat-added').innerText = `+${diffData.added} added`;
    document.getElementById('diff-stat-removed').innerText = `-${diffData.removed} removed`;
    document.getElementById('diff-similarity-text').innerText = `Similarity: ${(diffData.ratio).toFixed(4)}`;
    document.getElementById('diff-meta-stats').style.display = 'flex';
    
    renderDiffVisuals(diffData);
    
  } catch (err) {
    diffContent.innerHTML = `<div class="empty-state text-danger">⚠️ Error loading diff: ${err.message}</div>`;
  }
}

// Client Side LCS (Longest Common Subsequence) Line Diff Algorithm
function computeLcsDiff(oldLines, newLines) {
  const dp = Array(oldLines.length + 1).fill(null).map(() => Array(newLines.length + 1).fill(0));
  
  for (let i = 1; i <= oldLines.length; i++) {
    for (let j = 1; j <= newLines.length; j++) {
      if (oldLines[i - 1] === newLines[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
  }
  
  let i = oldLines.length;
  let j = newLines.length;
  const diff = [];
  
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && oldLines[i - 1] === newLines[j - 1]) {
      diff.unshift({
        type: 'unchanged',
        text: oldLines[i - 1],
        old_line: i,
        new_line: j
      });
      i--;
      j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      diff.unshift({
        type: 'added',
        text: newLines[j - 1],
        old_line: null,
        new_line: j
      });
      j--;
    } else {
      diff.unshift({
        type: 'removed',
        text: oldLines[i - 1],
        old_line: i,
        new_line: null
      });
      i--;
    }
  }
  
  return diff;
}

// Switch Tab inside Diff Panel (Split, Unified, Raw)
function setDiffMode(mode) {
  currentDiffMode = mode;
  document.querySelectorAll('.diff-mode-selectors .btn-toggle').forEach(b => b.classList.remove('active'));
  document.getElementById(`diff-mode-${mode}`).classList.add('active');
  
  const diffContent = document.getElementById('diff-view-content');
  if (diffContent.dataset.currentDiff) {
    const diffData = JSON.parse(diffContent.dataset.currentDiff);
    renderDiffVisuals(diffData);
  }
}

function renderDiffVisuals(diffData) {
  const container = document.getElementById('diff-view-content');
  container.innerHTML = '';
  
  if (currentDiffMode === 'raw') {
    // Plaintext raw output
    const pre = document.createElement('pre');
    pre.className = 'raw-text-view';
    pre.innerText = diffData.current_text || '[Empty version content]';
    container.appendChild(pre);
    return;
  }
  
  if (currentDiffMode === 'unified') {
    // Line-by-line unified diff
    const table = document.createElement('table');
    table.className = 'diff-table';
    
    diffData.diff.forEach(line => {
      const row = document.createElement('tr');
      row.className = `diff-row ${line.type}`;
      
      const oldNo = line.old_line !== null ? line.old_line : '';
      const newNo = line.new_line !== null ? line.new_line : '';
      const symbol = line.type === 'added' ? '+' : (line.type === 'removed' ? '-' : ' ');
      
      row.innerHTML = `
        <td class="diff-cell line-number">${oldNo}</td>
        <td class="diff-cell line-number">${newNo}</td>
        <td class="diff-cell line-number" style="width: 25px; text-align: center; border-right: none;">${symbol}</td>
        <td class="diff-cell content">${escapeHtml(line.text)}</td>
      `;
      table.appendChild(row);
    });
    
    container.appendChild(table);
  } else if (currentDiffMode === 'split') {
    // Side by Side split column view
    const splitContainer = document.createElement('div');
    splitContainer.className = 'diff-split-container';
    
    const leftCol = document.createElement('div');
    leftCol.className = 'diff-split-col';
    leftCol.innerHTML = '<div class="diff-split-header">⏮️ Previous Version</div><div class="diff-split-body" id="split-left-body"></div>';
    
    const rightCol = document.createElement('div');
    rightCol.className = 'diff-split-col';
    rightCol.innerHTML = '<div class="diff-split-header">⏭️ Current Version</div><div class="diff-split-body" id="split-right-body"></div>';
    
    splitContainer.appendChild(leftCol);
    splitContainer.appendChild(rightCol);
    container.appendChild(splitContainer);
    
    const leftBody = document.getElementById('split-left-body');
    const rightBody = document.getElementById('split-right-body');
    
    // We align lines side-by-side. 
    // To do this properly, we iterate and align adds/removes or insert spacer blocks
    let idx = 0;
    const diff = diffData.diff;
    
    while (idx < diff.length) {
      const line = diff[idx];
      
      if (line.type === 'unchanged') {
        appendSplitRow(leftBody, line.old_line, line.text, 'unchanged');
        appendSplitRow(rightBody, line.new_line, line.text, 'unchanged');
        idx++;
      } else if (line.type === 'removed') {
        // Look ahead for matching insert to align side by side
        let nextLine = diff[idx + 1];
        if (nextLine && nextLine.type === 'added') {
          appendSplitRow(leftBody, line.old_line, line.text, 'removed');
          appendSplitRow(rightBody, nextLine.new_line, nextLine.text, 'added');
          idx += 2;
        } else {
          appendSplitRow(leftBody, line.old_line, line.text, 'removed');
          appendSplitRow(rightBody, '', '', 'empty');
          idx++;
        }
      } else if (line.type === 'added') {
        appendSplitRow(leftBody, '', '', 'empty');
        appendSplitRow(rightBody, line.new_line, line.text, 'added');
        idx++;
      }
    }
  }
}

function appendSplitRow(container, lineNum, text, type) {
  const row = document.createElement('div');
  row.className = `diff-split-row ${type}`;
  
  const numSpan = document.createElement('span');
  numSpan.className = 'diff-cell line-number';
  numSpan.style.width = '45px';
  numSpan.innerText = lineNum;
  
  const textSpan = document.createElement('span');
  textSpan.className = 'diff-cell content';
  textSpan.innerText = text;
  
  row.appendChild(numSpan);
  row.appendChild(textSpan);
  container.appendChild(row);
}

// Form accordion toggler
function toggleAccordion(id) {
  const section = document.querySelector(`.accordion-section`);
  section.classList.toggle('open');
  
  const icon = document.getElementById(`${id}-icon`);
  const content = document.getElementById(id);
  
  if (section.classList.contains('open')) {
    content.style.display = 'block';
    icon.innerText = '▲';
  } else {
    content.style.display = 'none';
    icon.innerText = '▼';
  }
}

// Toast helper
function showToast(message, isError = false) {
  const toast = document.getElementById('toast');
  toast.innerText = message;
  
  if (isError) {
    toast.style.borderColor = 'var(--color-danger)';
    toast.style.boxShadow = '0 10px 25px rgba(0,0,0,0.5), 0 0 20px rgba(239, 68, 68, 0.2)';
  } else {
    toast.style.borderColor = 'var(--color-primary)';
    toast.style.boxShadow = '0 10px 25px rgba(0,0,0,0.5), var(--shadow-neon)';
  }
  
  toast.classList.add('show');
  
  setTimeout(() => {
    toast.classList.remove('show');
  }, 4000);
}

// Relative times converter
function formatRelativeTime(isoString) {
  try {
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffSec = Math.floor(diffMs / 1000);
    const diffMin = Math.floor(diffSec / 60);
    const diffHour = Math.floor(diffMin / 60);
    const diffDay = Math.floor(diffHour / 24);
    
    if (diffSec < 60) return 'Just now';
    if (diffMin < 60) return `${diffMin}m ago`;
    if (diffHour < 24) return `${diffHour}h ago`;
    if (diffDay < 7) return `${diffDay}d ago`;
    
    return date.toLocaleDateString();
  } catch (err) {
    return 'unknown';
  }
}

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
