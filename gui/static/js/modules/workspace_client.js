const ACTIVE_ROOT_KEY = 'deckgen-active-root';
const PROJECTS_HISTORY_KEY = 'deckgen-projects-history';

export function getProjectsHistory() {
  try {
    const raw = localStorage.getItem(PROJECTS_HISTORY_KEY);
    const list = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(list)) return [];
    return list.sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')));
  } catch {
    return [];
  }
}

export function recordProjectInHistory(state) {
  if (!state || !state.root_dir) return;
  const list = getProjectsHistory().filter((p) => p.root_dir !== state.root_dir);
  list.unshift({
    root_dir: state.root_dir,
    project_name: state.project_name || state.root_dir.split(/[\/]/).filter(Boolean).pop() || 'Proyecto',
    updated_at: state.updated_at || new Date().toISOString(),
  });
  localStorage.setItem(PROJECTS_HISTORY_KEY, JSON.stringify(list.slice(0, 20)));
}

export function removeProjectFromHistory(rootDir) {
  const list = getProjectsHistory().filter((p) => p.root_dir !== rootDir);
  localStorage.setItem(PROJECTS_HISTORY_KEY, JSON.stringify(list));
}

export function clearActiveProject() {
  setActiveRootDir('');
  updateProjectBadge(null);
}

export function initThemeAndNavbar(activeNav) {
  const savedTheme = localStorage.getItem('deckgen-theme');
  const dark = savedTheme ? savedTheme === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');

  const themeBtn = document.getElementById('theme-toggle');
  if (themeBtn) {
    themeBtn.textContent = dark ? '☀️' : '🌙';
    themeBtn.addEventListener('click', () => {
      const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('deckgen-theme', next);
      themeBtn.textContent = next === 'dark' ? '☀️' : '🌙';
    });
  }

  document.querySelectorAll('.navbar-link[data-nav]').forEach((el) => {
    if (el.getAttribute('data-nav') === activeNav) {
      el.classList.add('active');
    }
  });
}

export function showToast(msg, duration = 3500) {
  const existing = document.querySelector('.toast-banner');
  if (existing) existing.remove();
  const el = document.createElement('div');
  el.className = 'toast-banner';
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => { if (el.parentNode) el.remove(); }, duration);
}

export function getActiveRootDir() {
  return localStorage.getItem(ACTIVE_ROOT_KEY) || '';
}

export function setActiveRootDir(rootDir) {
  if (rootDir) localStorage.setItem(ACTIVE_ROOT_KEY, rootDir);
  else localStorage.removeItem(ACTIVE_ROOT_KEY);
}

export function updateProjectBadge(state) {
  const badge = document.getElementById('nav-project-badge');
  const saveBtn = document.getElementById('nav-save-state-btn');
  if (!badge) return;
  if (state && state.root_dir) {
    badge.textContent = `📁 ${state.project_name || 'Proyecto'}`;
    badge.title = state.root_dir;
    badge.classList.add('active');
    if (saveBtn) saveBtn.disabled = false;
  } else {
    badge.textContent = 'No project';
    badge.title = 'No active project';
    badge.classList.remove('active');
    if (saveBtn) saveBtn.disabled = true;
  }
}

export async function loadActiveWorkspaceState() {
  const rootDir = getActiveRootDir();
  if (!rootDir) return null;
  try {
    const resp = await fetch(`/api/workspace/state?root_dir=${encodeURIComponent(rootDir)}`);
    if (!resp.ok) return null;
    const data = await resp.json();
    recordProjectInHistory(data.state);
    updateProjectBadge(data.state);
    return data.state;
  } catch {
    return null;
  }
}

export async function saveActiveWorkspaceState(state) {
  if (!state || !state.root_dir) return null;
  const resp = await fetch('/api/workspace/state', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ root_dir: state.root_dir, state }),
  });
  if (!resp.ok) throw new Error('Error saving state.json');
  const data = await resp.json();
  recordProjectInHistory(data.state);
  updateProjectBadge(data.state);
  return data.state;
}

export async function pickFolder(initialDir = '') {
  // Try native OS folder dialog first
  try {
    const nat = await fetch('/api/workspace/native-pick', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ initial_dir: initialDir || getActiveRootDir() || '' }),
    });
    if (nat.ok) {
      const natData = await nat.json();
      if (natData.supported && natData.path) return natData.path;
      if (natData.supported && !natData.path) return null; // user cancelled native dialog
    }
  } catch { /* fallback to server browser modal */ }

  return openFolderBrowserModal(initialDir || getActiveRootDir() || '');
}

export function openFolderBrowserModal(initialPath = '') {
  return new Promise((resolve) => {
    let overlay = document.getElementById('dg-folder-browser-modal');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'dg-folder-browser-modal';
      overlay.className = 'modal-overlay';
      overlay.innerHTML = `
        <div class="modal-content" style="width: 560px; max-width: 94vw;">
          <div class="modal-header">
            <span>📁 Select Folder</span>
            <button type="button" class="modal-close" data-act="close">&times;</button>
          </div>
          <div class="modal-body" style="display:flex; flex-direction:column; gap:10px;">
            <div class="row">
              <button type="button" class="btn btn-sm" data-act="up">⬆ Subir</button>
              <input type="text" class="input" data-el="current" readonly style="font-family:monospace;">
            </div>
            <div class="row">
              <input type="text" class="input" data-el="new-name" placeholder="Nueva carpeta...">
              <button type="button" class="btn btn-sm" data-act="mkdir">+ Crear</button>
            </div>
            <div data-el="list" style="max-height:260px; overflow-y:auto; border:1px solid var(--border); border-radius:6px; padding:4px;"></div>
            <div data-el="err" style="color:var(--danger); font-size:12px; display:none;"></div>
            <div class="row" style="justify-content:flex-end;">
              <button type="button" class="btn" data-act="cancel">Cancel</button>
              <button type="button" class="btn btn-primary" data-act="select">Select this folder</button>
            </div>
          </div>
        </div>`;
      document.body.appendChild(overlay);
    }

    const curInput = overlay.querySelector('[data-el="current"]');
    const newInput = overlay.querySelector('[data-el="new-name"]');
    const listEl = overlay.querySelector('[data-el="list"]');
    const errEl = overlay.querySelector('[data-el="err"]');
    let currentDir = initialPath || '';
    let parentDir = null;

    async function browse(path) {
      errEl.style.display = 'none';
      const resp = await fetch(`/api/fs/browse?path=${encodeURIComponent(path || '')}`);
      const data = await resp.json();
      if (!resp.ok) {
        errEl.textContent = data.detail || 'Error listando carpeta';
        errEl.style.display = 'block';
        return;
      }
      currentDir = data.current;
      parentDir = data.parent;
      curInput.value = currentDir;
      listEl.innerHTML = '';
      if (data.dirs.length === 0) {
        const empty = document.createElement('div');
        empty.style.padding = '12px';
        empty.style.color = 'var(--text-muted)';
        empty.textContent = 'Carpeta vacía' + (data.has_state_json ? ' (contiene state.json)' : '');
        listEl.appendChild(empty);
      } else {
        data.dirs.forEach((d) => {
          const item = document.createElement('div');
          item.style.cssText = 'padding:6px 10px; cursor:pointer; border-radius:4px; display:flex; align-items:center; gap:6px;';
          item.textContent = `📁 ${d}`;
          item.addEventListener('mouseenter', () => { item.style.background = 'var(--surface-hover)'; });
          item.addEventListener('mouseleave', () => { item.style.background = 'transparent'; });
          item.addEventListener('click', () => browse(`${currentDir.replace(/\/$/, '')}/${d}`));
          listEl.appendChild(item);
        });
      }
    }

    function cleanup(val) {
      overlay.classList.remove('open');
      overlay.onclick = null;
      resolve(val);
    }

    overlay.onclick = async (e) => {
      const act = e.target?.getAttribute?.('data-act');
      if (act === 'close' || act === 'cancel') return cleanup(null);
      if (act === 'select') return cleanup(currentDir);
      if (act === 'up' && parentDir) return browse(parentDir);
      if (act === 'mkdir') {
        const name = newInput.value.trim();
        if (!name) return;
        const r = await fetch('/api/fs/mkdir', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ current: currentDir, folder_name: name }),
        });
        if (r.ok) {
          const d = await r.json();
          newInput.value = '';
          await browse(d.created);
        }
      }
    };

    overlay.classList.add('open');
    browse(currentDir);
  });
}

export function promptCollisionResolution(collisionInfo) {
  return new Promise((resolve) => {
    let overlay = document.getElementById('dg-collision-modal');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'dg-collision-modal';
      overlay.className = 'modal-overlay';
      overlay.innerHTML = `
        <div class="modal-content" style="width: 460px; max-width: 94vw;">
          <div class="modal-header">
            <span>⚠️ Existing folder detected</span>
            <button type="button" class="modal-close" data-act="cancel">&times;</button>
          </div>
          <div class="modal-body" style="display:flex; flex-direction:column; gap:12px;">
            <p data-el="msg" style="margin:0;"></p>
            <div class="row" style="justify-content:flex-end; flex-wrap:wrap;">
              <button type="button" class="btn" data-act="cancel">Cancel</button>
              <button type="button" class="btn btn-danger" data-act="overwrite">Overwrite</button>
              <button type="button" class="btn btn-primary" data-act="version">Create new version</button>
            </div>
          </div>
        </div>`;
      document.body.appendChild(overlay);
    }

    const msgEl = overlay.querySelector('[data-el="msg"]');
    const verBtn = overlay.querySelector('[data-act="version"]');
    msgEl.textContent = `La carpeta "${collisionInfo.target}" ya contiene archivos. ¿Cómo deseas proceder?`;
    verBtn.textContent = `Crear versión (${collisionInfo.next_version.split('/').pop()})`;

    overlay.onclick = (e) => {
      const act = e.target?.getAttribute?.('data-act');
      if (!act) return;
      overlay.classList.remove('open');
      overlay.onclick = null;
      resolve(act === 'cancel' ? null : act);
    };
    overlay.classList.add('open');
  });
}

export function setGlobalLoading(show, text = 'Loading...') {
  let el = document.getElementById('dg-global-loading');
  if (!el) {
    el = document.createElement('div');
    el.id = 'dg-global-loading';
    el.style.cssText = 'display:none; position:fixed; inset:0; z-index:400; background:rgba(10,14,23,0.45); align-items:center; justify-content:center; backdrop-filter:blur(2px);';
    el.innerHTML = `
      <div style="background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:16px 22px; box-shadow:var(--shadow); display:flex; align-items:center; gap:12px; min-width:220px;">
        <div style="width:18px; height:18px; border:3px solid var(--border); border-top-color:var(--accent); border-radius:50%; animation:dgSpin 0.8s linear infinite;"></div>
        <span id="dg-global-loading-text" style="font-size:13px; font-weight:500; color:var(--text);">Loading...</span>
      </div>
    `;
    const st = document.createElement('style');
    st.textContent = '@keyframes dgSpin { to { transform: rotate(360deg); } }';
    document.head.appendChild(st);
    document.body.appendChild(el);
  }
  const txtEl = document.getElementById('dg-global-loading-text');
  if (txtEl) txtEl.textContent = text;
  el.style.display = show ? 'flex' : 'none';
}
