import {
  clearActiveProject,
  getActiveRootDir,
  getProjectsHistory,
  initThemeAndNavbar,
  loadActiveWorkspaceState,
  pickFolder,
  recordProjectInHistory,
  removeProjectFromHistory,
  setActiveRootDir,
  setGlobalLoading,
  showToast,
  updateProjectBadge,
} from './modules/workspace_client.js?v=23';

initThemeAndNavbar('home');

const createBtn = document.getElementById('btn-create-project');
const loadBtn = document.getElementById('btn-load-project');
const choiceModal = document.getElementById('load-choice-modal');
const choiceClose = document.getElementById('load-choice-close');
const loadByFolderBtn = document.getElementById('btn-load-by-folder');
const loadByFileBtn = document.getElementById('btn-load-by-file');
const loadFileInput = document.getElementById('load-state-file-input');
const clearActiveBtn = document.getElementById('btn-clear-active-project');

function formatUpdatedAt(isoStr) {
  if (!isoStr) return 'No date';
  try {
    const d = new Date(isoStr);
    if (Number.isNaN(d.getTime())) return isoStr;
    return d.toLocaleString();
  } catch {
    return isoStr;
  }
}

function renderActiveBanner(state) {
  const box = document.getElementById('landing-active-info');
  if (!box) return;
  if (!state) {
    box.style.display = 'none';
    return;
  }
  document.getElementById('landing-project-name').textContent = state.project_name || 'Project';
  document.getElementById('landing-project-path').textContent = state.root_dir || '';
  box.style.display = 'block';
}

function renderProjectsHistory() {
  const section = document.getElementById('landing-projects-section');
  const listEl = document.getElementById('landing-projects-list');
  if (!section || !listEl) return;
  const projects = getProjectsHistory();
  const activeRoot = getActiveRootDir();

  if (projects.length === 0) {
    section.style.display = 'none';
    listEl.innerHTML = '';
    return;
  }

  section.style.display = 'block';
  listEl.innerHTML = '';
  projects.forEach((p) => {
    const isActive = Boolean(activeRoot && p.root_dir === activeRoot);
    const row = document.createElement('div');
    row.style.cssText = `display:flex; align-items:center; justify-content:space-between; gap:8px; padding:8px 10px; border:1px solid ${isActive ? 'var(--accent)' : 'var(--border)'}; border-radius:6px; background:var(--surface-2);`;
    row.innerHTML = `
      <div style="min-width:0; flex:1;">
        <div style="font-weight:600; font-size:12.5px; color:var(--text); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
          ${isActive ? '🟢 ' : ''}${p.project_name || 'Project'}
        </div>
        <div style="font-family:monospace; font-size:10.5px; color:var(--text-muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${p.root_dir}</div>
        <div style="font-size:10.5px; color:var(--text-muted);">Last updated: ${formatUpdatedAt(p.updated_at)}</div>
      </div>
      <div class="row" style="gap:4px;">
        <button type="button" class="btn btn-sm ${isActive ? '' : 'btn-primary'}" data-act="activate">${isActive ? 'Open' : 'Activate'}</button>
        <button type="button" class="btn btn-sm" data-act="remove" title="Remove from list">✕</button>
      </div>
    `;

    row.querySelector('[data-act="activate"]').addEventListener('click', async () => {
      const resp = await fetch('/api/workspace/load', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ root_dir: p.root_dir }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        showToast(data.detail || 'Could not load this project');
        return;
      }
      setActiveRootDir(data.state.root_dir);
      recordProjectInHistory(data.state);
      updateProjectBadge(data.state);
      renderActiveBanner(data.state);
      renderProjectsHistory();
      window.location.href = '/card-builder';
    });

    row.querySelector('[data-act="remove"]').addEventListener('click', () => {
      removeProjectFromHistory(p.root_dir);
      if (getActiveRootDir() === p.root_dir) {
        clearActiveProject();
        renderActiveBanner(null);
      }
      renderProjectsHistory();
      showToast('Project removed from list');
    });

    listEl.appendChild(row);
  });
}

(async () => {
  const state = await loadActiveWorkspaceState();
  if (state) renderActiveBanner(state);
  renderProjectsHistory();
})();

// Landing preview carousel
(function initLandingCarousel() {
  const wrap = document.getElementById('landing-carousel');
  const track = document.getElementById('landing-carousel-track');
  const prevBtn = document.getElementById('landing-carousel-prev');
  const nextBtn = document.getElementById('landing-carousel-next');
  const dots = Array.from(document.querySelectorAll('#landing-carousel-dots .landing-carousel-dot'));
  if (!wrap || !track || !dots.length) return;

  let idx = 0;
  const total = dots.length;
  let timer = null;

  function goTo(nextIdx) {
    idx = (nextIdx + total) % total;
    track.style.transform = `translateX(-${idx * 100}%)`;
    dots.forEach((d, i) => d.classList.toggle('active', i === idx));
  }

  function startAuto() {
    stopAuto();
    timer = setInterval(() => goTo(idx + 1), 6000);
  }
  function stopAuto() {
    if (timer) { clearInterval(timer); timer = null; }
  }

  prevBtn?.addEventListener('click', () => { goTo(idx - 1); startAuto(); });
  nextBtn?.addEventListener('click', () => { goTo(idx + 1); startAuto(); });
  dots.forEach((d) => {
    d.addEventListener('click', () => { goTo(parseInt(d.dataset.slide || '0', 10)); startAuto(); });
  });
  wrap.addEventListener('mouseenter', stopAuto);
  wrap.addEventListener('mouseleave', startAuto);
  startAuto();
})();

clearActiveBtn?.addEventListener('click', () => {
  clearActiveProject();
  renderActiveBanner(null);
  renderProjectsHistory();
  showToast('Active project cleared');
});

createBtn.addEventListener('click', async () => {
  const folder = await pickFolder();
  if (!folder) return;
  setGlobalLoading(true, 'Creating project...');
  try {
  const resp = await fetch('/api/workspace/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ root_dir: folder }),
  });
  const data = await resp.json();
  if (!resp.ok) {
    showToast(data.detail || 'Error creating project');
    return;
  }
  setActiveRootDir(data.state.root_dir);
  recordProjectInHistory(data.state);
  updateProjectBadge(data.state);
  renderActiveBanner(data.state);
  renderProjectsHistory();
  showToast('Project initialized at ' + data.state.root_dir);
  window.location.href = '/card-builder';
  } finally { setGlobalLoading(false); }
});

loadBtn.addEventListener('click', () => {
  choiceModal.classList.add('open');
});
choiceClose.addEventListener('click', () => choiceModal.classList.remove('open'));

loadByFolderBtn.addEventListener('click', async () => {
  choiceModal.classList.remove('open');
  const folder = await pickFolder();
  if (!folder) return;
  const resp = await fetch('/api/workspace/load', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ root_dir: folder }),
  });
  const data = await resp.json();
  if (!resp.ok) {
    showToast(data.detail || 'Could not load project');
    return;
  }
  setActiveRootDir(data.state.root_dir);
  recordProjectInHistory(data.state);
  updateProjectBadge(data.state);
  renderActiveBanner(data.state);
  renderProjectsHistory();
  showToast('Project loaded successfully');
  window.location.href = '/card-builder';
});

loadByFileBtn.addEventListener('click', () => loadFileInput.click());

loadFileInput.addEventListener('change', async () => {
  const file = loadFileInput.files?.[0];
  if (!file) return;
  try {
    const raw = JSON.parse(await file.text());
    const resp = await fetch('/api/workspace/load-json', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ state: raw }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      showToast(data.detail || 'Invalid state.json file');
      return;
    }
    choiceModal.classList.remove('open');
    setActiveRootDir(data.state.root_dir);
    recordProjectInHistory(data.state);
    updateProjectBadge(data.state);
    renderActiveBanner(data.state);
    renderProjectsHistory();
    showToast('Project restored from state.json');
    window.location.href = '/card-builder';
  } catch {
    showToast('Could not read JSON file');
  }
});
