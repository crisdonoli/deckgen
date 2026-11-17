import {
  getActiveRootDir,
  initThemeAndNavbar,
  loadActiveWorkspaceState,
  pickFolder,
  promptCollisionResolution,
  saveActiveWorkspaceState,
  setGlobalLoading,
  showToast,
} from './modules/workspace_client.js';

initThemeAndNavbar('deck-generator');

let workspaceState = null;
let frontPage = 0;
let backPage = 0;
let selectedSlotIndex = null;

function ensureDgConfig() {
  if (!workspaceState) {
    workspaceState = {
      root_dir: getActiveRootDir(),
      card_builder: {},
      deck_generator: {
        source_folder: '',
        paper: 'a4',
        landscape: false,
        cut: 'corners',
        card_spacing: 0,
        color: '#ff0000',
        thickness: 0.5,
        mark_len: 3.0,
        duplex_flip: true,
        view_mode: 'both',
        card_scales: {},
      },
    };
  }
  workspaceState.deck_generator = workspaceState.deck_generator || {};
  workspaceState.deck_generator.card_scales = workspaceState.deck_generator.card_scales || {};
  workspaceState.deck_generator.custom_backs = workspaceState.deck_generator.custom_backs || {};
  return workspaceState.deck_generator;
}

function readControlsToConfig() {
  const cfg = ensureDgConfig();
  cfg.paper = document.getElementById('dg-paper').value;
  cfg.landscape = document.getElementById('dg-landscape').checked;
  cfg.card_spacing = parseFloat(document.getElementById('dg-spacing').value) || 0;
  cfg.cut = document.getElementById('dg-cut').value;
  cfg.color = document.getElementById('dg-cut-color').value;
  cfg.thickness = parseFloat(document.getElementById('dg-thickness').value) || 0.5;
  cfg.mark_len = parseFloat(document.getElementById('dg-mark-len').value) || 3.0;
  cfg.view_mode = document.getElementById('dg-view-mode').value;
  cfg.duplex_flip = document.getElementById('dg-duplex-flip').checked;
  return cfg;
}

function applyConfigToControls(cfg) {
  document.getElementById('dg-paper').value = cfg.paper || 'a4';
  document.getElementById('dg-landscape').checked = Boolean(cfg.landscape);
  document.getElementById('dg-spacing').value = cfg.card_spacing ?? 0;
  document.getElementById('dg-cut').value = cfg.cut || 'corners';
  document.getElementById('dg-cut-color').value = cfg.color || '#ff0000';
  document.getElementById('dg-thickness').value = cfg.thickness ?? 0.5;
  document.getElementById('dg-mark-len').value = cfg.mark_len ?? 3.0;
  document.getElementById('dg-view-mode').value = cfg.view_mode || 'both';
  document.getElementById('dg-duplex-flip').checked = cfg.duplex_flip !== false;
  document.getElementById('dg-back-label').textContent = cfg.generic_back ? cfg.generic_back.split('/').pop() : 'None';
  document.getElementById('dg-source-label').textContent = cfg.source_folder
    ? cfg.source_folder.split('/').pop()
    : 'cards/fronts';
  applyViewMode(cfg.view_mode || 'both');
}

function applyViewMode(mode) {
  const grid = document.getElementById('dg-dual-preview');
  const pFront = document.getElementById('dg-pane-fronts');
  const pBack = document.getElementById('dg-pane-backs');
  pFront.style.display = mode === 'backs' ? 'none' : 'flex';
  pBack.style.display = mode === 'fronts' ? 'none' : 'flex';
  grid.classList.toggle('single-pane', mode !== 'both');
}

let _activeFrontSlot = null;
function renderSlotHitboxes(containerEl, slots, face = 'fronts') {
  containerEl.innerHTML = '';
  const cfg = ensureDgConfig();
  (slots || []).forEach((slot) => {
    const box = document.createElement('div');
    box.className = 'dg-slot-hitbox' + (selectedSlotIndex === slot.index ? ' selected' : '');
    box.style.left = `${slot.x_pct * 100}%`;
    box.style.top = `${slot.y_pct * 100}%`;
    box.style.width = `${slot.w_pct * 100}%`;
    box.style.height = `${slot.h_pct * 100}%`;
    box.title = `${slot.name} — Escala: ${slot.scale.toFixed(2)}×`;

    const badge = document.createElement('span');
    badge.className = 'dg-slot-badge';
    badge.textContent = `${slot.scale.toFixed(2)}×`;
    box.appendChild(badge);

    box.addEventListener('click', () => {
      selectedSlotIndex = slot.index;
      const curScale = cfg.card_scales[String(slot.index)] ?? 1.0;
      document.getElementById('dg-selected-slot-label').textContent = `#${slot.index + 1} ${slot.name.slice(0, 14)}`;
      const slider = document.getElementById('dg-slot-scale');
      const resetBtn = document.getElementById('dg-slot-scale-reset');
      slider.disabled = false;
      resetBtn.disabled = false;
      slider.value = curScale;
      document.getElementById('dg-slot-scale-val').textContent = `${Number(curScale).toFixed(2)}×`;
      renderSlotHitboxes(containerEl, slots, face);
      if (face === 'fronts') openFrontCardModal(slot);
    });
    containerEl.appendChild(box);
  });
}

async function fetchFacePreview(face, page) {
  const cfg = readControlsToConfig();
  const resp = await fetch('/api/deck/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      root_dir: getActiveRootDir(),
      source_folder: cfg.source_folder,
      face,
      paper: cfg.paper,
      landscape: cfg.landscape,
      cut: cfg.cut,
      color: cfg.color,
      thickness: cfg.thickness,
      mark_len: cfg.mark_len,
      card_spacing: cfg.card_spacing,
      duplex_flip: cfg.duplex_flip,
      page,
      card_scales: cfg.card_scales,
      generic_back: cfg.generic_back || null,
      custom_backs: cfg.custom_backs || {},
    }),
  });
  if (!resp.ok) return null;
  return resp.json();
}

async function refreshPreviews() {
  const cfg = readControlsToConfig();
  setGlobalLoading(true, 'Rendering sheet preview...');
  try {
  if (cfg.view_mode !== 'backs') {
    const fData = await fetchFacePreview('fronts', frontPage);
    if (fData) {
      document.getElementById('dg-front-img').src = fData.image_data_url;
      frontPage = fData.meta.page;
      const maxP = Math.max(0, fData.meta.total_pages - 1);
      const slider = document.getElementById('dg-front-slider');
      slider.max = String(maxP);
      slider.value = String(frontPage);
      document.getElementById('dg-front-page-label').textContent = `${frontPage + 1} / ${fData.meta.total_pages}`;
      renderSlotHitboxes(document.getElementById('dg-front-hitboxes'), fData.meta.slots, 'fronts');
      if (fData.meta.did_background_convert) {
        showToast('Imágenes PNG/JPG convertidas a PDF en segundo plano automáticamente.');
      }
    }
  }
  if (cfg.view_mode !== 'fronts') {
    const bData = await fetchFacePreview('backs', backPage);
    if (bData) {
      document.getElementById('dg-back-img').src = bData.image_data_url;
      backPage = bData.meta.page;
      const maxP = Math.max(0, bData.meta.total_pages - 1);
      const slider = document.getElementById('dg-back-slider');
      slider.max = String(maxP);
      slider.value = String(backPage);
      document.getElementById('dg-back-page-label').textContent = `${backPage + 1} / ${bData.meta.total_pages}`;
      renderSlotHitboxes(document.getElementById('dg-back-hitboxes'), bData.meta.slots, 'backs');
    }
  }
  } finally { setGlobalLoading(false); }
}

async function persist() {
  if (!workspaceState?.root_dir) return;
  try { workspaceState = await saveActiveWorkspaceState(workspaceState); } catch {}
}

(async function init() {
  workspaceState = await loadActiveWorkspaceState();
  applyConfigToControls(ensureDgConfig());
  await refreshPreviews();

  document.getElementById('nav-save-state-btn')?.addEventListener('click', async () => {
    readControlsToConfig();
    await persist();
    showToast('Configuración guardada en state.json');
  });

  ['dg-paper', 'dg-landscape', 'dg-spacing', 'dg-cut', 'dg-cut-color', 'dg-thickness', 'dg-mark-len', 'dg-duplex-flip'].forEach((id) => {
    document.getElementById(id).addEventListener('change', () => {
      readControlsToConfig();
      persist();
      refreshPreviews();
    });
  });

  document.getElementById('dg-view-mode').addEventListener('change', (e) => {
    applyViewMode(e.target.value);
    readControlsToConfig();
    persist();
    refreshPreviews();
  });

  document.getElementById('dg-pick-source-btn').addEventListener('click', async () => {
    const dir = await pickFolder(getActiveRootDir());
    if (!dir) return;
    ensureDgConfig().source_folder = dir;
    document.getElementById('dg-source-label').textContent = dir.split('/').pop();
    frontPage = 0;
    backPage = 0;
    persist();
    refreshPreviews();
  });

  // Independent pagers
  document.getElementById('dg-front-prev').addEventListener('click', () => { if (frontPage > 0) { frontPage--; refreshPreviews(); } });
  document.getElementById('dg-front-next').addEventListener('click', () => { frontPage++; refreshPreviews(); });
  document.getElementById('dg-front-slider').addEventListener('input', (e) => { frontPage = parseInt(e.target.value, 10); refreshPreviews(); });

  document.getElementById('dg-back-prev').addEventListener('click', () => { if (backPage > 0) { backPage--; refreshPreviews(); } });
  document.getElementById('dg-back-next').addEventListener('click', () => { backPage++; refreshPreviews(); });
  document.getElementById('dg-back-slider').addEventListener('input', (e) => { backPage = parseInt(e.target.value, 10); refreshPreviews(); });

  // Individual card scale
  const scaleSlider = document.getElementById('dg-slot-scale');
  scaleSlider.addEventListener('input', (e) => {
    if (selectedSlotIndex === null) return;
    const val = parseFloat(e.target.value);
    document.getElementById('dg-slot-scale-val').textContent = `${val.toFixed(2)}×`;
    ensureDgConfig().card_scales[String(selectedSlotIndex)] = val;
  });
  scaleSlider.addEventListener('change', () => { persist(); refreshPreviews(); });

  document.getElementById('dg-slot-scale-reset').addEventListener('click', () => {
    if (selectedSlotIndex === null) return;
    delete ensureDgConfig().card_scales[String(selectedSlotIndex)];
    scaleSlider.value = '1.0';
    document.getElementById('dg-slot-scale-val').textContent = '1.00×';
    persist();
    refreshPreviews();
  });

  // Export Sheet DPI popup
  const exportModal = document.getElementById('dg-export-modal');
  document.getElementById('dg-export-sheet-btn').addEventListener('click', () => {
    if (!getActiveRootDir()) return showToast('Primero crea o carga un proyecto en Home.');
    exportModal.classList.add('open');
  });
  document.getElementById('dg-export-close').addEventListener('click', () => exportModal.classList.remove('open'));
  document.getElementById('dg-export-cancel').addEventListener('click', () => exportModal.classList.remove('open'));

  document.getElementById('dg-export-confirm').addEventListener('click', async () => {
    const cfg = readControlsToConfig();
    const face = document.getElementById('dg-export-face').value;
    const exportDpi = parseInt(document.getElementById('dg-export-dpi').value, 10);
    const progEl = document.getElementById('dg-export-progress');
    progEl.style.display = 'block';

    const payload = {
      root_dir: getActiveRootDir(),
      source_folder: cfg.source_folder,
      face,
      paper: cfg.paper,
      landscape: cfg.landscape,
      cut: cfg.cut,
      color: cfg.color,
      thickness: cfg.thickness,
      mark_len: cfg.mark_len,
      card_spacing: cfg.card_spacing,
      duplex_flip: cfg.duplex_flip,
      export_dpi: exportDpi,
      card_scales: cfg.card_scales,
      collision_mode: 'check',
    };

    let resp = await fetch('/api/deck/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    let data = await resp.json();
    if (data.status === 'collision') {
      const choice = await promptCollisionResolution(data.collision);
      if (!choice) { progEl.style.display = 'none'; return; }
      payload.collision_mode = choice;
      resp = await fetch('/api/deck/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      data = await resp.json();
    }
    progEl.style.display = 'none';
    exportModal.classList.remove('open');
    if (!resp.ok) return showToast(data.detail || 'Error exportando hoja');
    showToast(`PDF generado en ${data.pdf_path}`);
  });
})();

let _cachedProjectCards = [];

function renderProjectCardsBackGrid(filterText = '') {
  const grid = document.getElementById('dg-fc-project-grid');
  if (!grid) return;
  const q = filterText.trim().toLowerCase();
  const filtered = _cachedProjectCards.filter((it) => !q || it.name.toLowerCase().includes(q) || it.folder.toLowerCase().includes(q));
  grid.innerHTML = '';
  if (!filtered.length) {
    grid.innerHTML = '<p style="color:var(--text-muted); grid-column:1/-1; font-size:12px;">No project cards found.</p>';
    return;
  }
  filtered.forEach((it) => {
    const el = document.createElement('div');
    el.className = 'art-result-card';
    el.innerHTML = `
      <img src="${it.thumb_url}" loading="lazy" style="aspect-ratio:5/7; object-fit:contain; background:#111;">
      <div style="font-size:11px; font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${it.name}">${it.name}</div>
      <div style="font-size:10px; color:var(--text-muted);">${it.folder}</div>
    `;
    el.addEventListener('click', async () => {
      if (!_activeFrontSlot) return;
      const cfg = ensureDgConfig();
      cfg.custom_backs[_activeFrontSlot.name] = it.path;
      document.getElementById('dg-fc-back-status').textContent = `Custom: ${it.filename}`;
      document.getElementById('dg-front-card-modal')?.classList.remove('open');
      await persist();
      await refreshPreviews();
      showToast(`Custom back set to ${it.name}`);
    });
    grid.appendChild(el);
  });
}

async function openFrontCardModal(slot) {
  _activeFrontSlot = slot;
  const modal = document.getElementById('dg-front-card-modal');
  if (!modal || !slot) return;
  const cfg = ensureDgConfig();
  document.getElementById('dg-fc-title').textContent = `Front Card: ${slot.name}`;
  const customPath = (cfg.custom_backs || {})[slot.name];
  document.getElementById('dg-fc-back-status').textContent = customPath
    ? `Custom: ${customPath.split('/').pop()}`
    : (cfg.generic_back ? `Generic: ${cfg.generic_back.split('/').pop()}` : 'None (Blank)');
  const filterEl = document.getElementById('dg-fc-filter');
  if (filterEl) filterEl.value = '';
  const grid = document.getElementById('dg-fc-project-grid');
  if (grid) grid.innerHTML = '<p style="color:var(--text-muted); font-size:12px;">Loading project cards...</p>';
  modal.classList.add('open');

  try {
    const rootDir = getActiveRootDir();
    const resp = await fetch(`/api/deck/project-cards?root_dir=${encodeURIComponent(rootDir)}&source_folder=${encodeURIComponent(cfg.source_folder || '')}`);
    const data = await resp.json();
    _cachedProjectCards = data.cards || [];
    renderProjectCardsBackGrid('');
  } catch {
    if (grid) grid.innerHTML = '<p style="color:var(--danger); font-size:12px;">Error loading project cards.</p>';
  }
}

document.getElementById('dg-fc-filter')?.addEventListener('input', (e) => {
  renderProjectCardsBackGrid(e.target.value);
});

document.getElementById('dg-fc-close')?.addEventListener('click', () => {
  document.getElementById('dg-front-card-modal')?.classList.remove('open');
});

document.getElementById('dg-fc-upload-back-btn')?.addEventListener('click', () => {
  document.getElementById('dg-fc-back-input')?.click();
});

document.getElementById('dg-fc-back-input')?.addEventListener('change', async (e) => {
  const file = e.target.files?.[0];
  e.target.value = '';
  if (!file || !_activeFrontSlot) return;
  const rootDir = getActiveRootDir();
  if (!rootDir) return showToast('Create or load a project on Home first.');
  const fd = new FormData();
  fd.append('file', file);
  fd.append('root_dir', rootDir);
  fd.append('card_name', _activeFrontSlot.name);
  setGlobalLoading(true, 'Uploading & converting custom back...');
  try {
    const resp = await fetch('/api/deck/upload-back', { method: 'POST', body: fd });
    const data = await resp.json();
    if (!resp.ok) return showToast(data.detail || 'Error uploading custom back');
    const cfg = ensureDgConfig();
    cfg.custom_backs[_activeFrontSlot.name] = data.path;
    document.getElementById('dg-fc-back-status').textContent = `Custom: ${data.filename}`;
    await persist();
    await refreshPreviews();
    showToast(`Custom back updated for ${_activeFrontSlot.name}`);
  } finally {
    setGlobalLoading(false);
  }
});

document.getElementById('dg-fc-reset-back-btn')?.addEventListener('click', async () => {
  if (!_activeFrontSlot) return;
  const cfg = ensureDgConfig();
  delete cfg.custom_backs[_activeFrontSlot.name];
  document.getElementById('dg-fc-back-status').textContent = cfg.generic_back
    ? `Generic: ${cfg.generic_back.split('/').pop()}`
    : 'None (Blank)';
  await persist();
  await refreshPreviews();
  showToast('Reset to generic back');
});

document.getElementById('dg-pick-back-btn')?.addEventListener('click', () => {
  if (!getActiveRootDir()) return showToast('Create or load a project on Home first.');
  document.getElementById('dg-back-file-input')?.click();
});

document.getElementById('dg-back-file-input')?.addEventListener('change', async (e) => {
  const file = e.target.files?.[0];
  e.target.value = '';
  if (!file) return;
  const rootDir = getActiveRootDir();
  if (!rootDir) return showToast('Create or load a project on Home first.');
  const fd = new FormData();
  fd.append('file', file);
  fd.append('root_dir', rootDir);
  fd.append('card_name', '');
  setGlobalLoading(true, 'Uploading & converting back to PDF...');
  try {
    const resp = await fetch('/api/deck/upload-back', { method: 'POST', body: fd });
    const data = await resp.json();
    if (!resp.ok) return showToast(data.detail || 'Error uploading back');
    ensureDgConfig().generic_back = data.path;
    document.getElementById('dg-back-label').textContent = data.filename;
    await persist();
    await refreshPreviews();
    showToast(`Back set: ${data.filename}`);
  } finally {
    setGlobalLoading(false);
  }
});
