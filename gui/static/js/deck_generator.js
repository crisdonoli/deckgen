(function() {
const form = document.getElementById('deckform');
const previewBtn = document.getElementById('preview-btn');
const previewImg = document.getElementById('preview');
const overlay = document.getElementById('loading-overlay');
const errorMessage = document.getElementById('error-message');
const saveResult = document.getElementById('save-result');
const colorText = document.getElementById('color-text');
const colorPicker = document.getElementById('color-picker');
const progressBar = document.getElementById('progress-bar');
const progressStatus = document.getElementById('progress-status');
const sourceUploadBtn = document.getElementById('source-upload-btn');
const sourceFilesInput = document.getElementById('source-files');
const clearCacheBtn = document.getElementById('clear-cache-btn');

sourceUploadBtn.addEventListener('click', function() {
  sourceFilesInput.click();
});

if (clearCacheBtn) {
  clearCacheBtn.addEventListener('click', async function() {
    setLoading(true);
    setError('');
    try {
      const res = await fetch('/clear-cache', { method: 'POST' });
      const data = await res.json();
      saveResult.innerHTML = '<p style="color: var(--ok);">Cache cleared successfully (' + data.cleared + ' files removed).</p>';
    } catch (err) {
      setError('Error clearing cache: ' + err.message);
    } finally {
      setLoading(false);
    }
  });
}

colorPicker.addEventListener('input', function() {
  colorText.value = colorPicker.value;
});

colorText.addEventListener('input', function() {
  if (/^#[0-9A-Fa-f]{6}$/.test(colorText.value)) {
    colorPicker.value = colorText.value;
  }
});

const cardSpacingInput = document.getElementById('card-spacing');
const cardSpacingValue = document.getElementById('card-spacing-value');
const cardSpacingGroup = document.getElementById('card-spacing-group');
const cutSelect = document.getElementById('cut-select');

function updateCardSpacingValue() {
  cardSpacingValue.textContent = cardSpacingInput.value;
}

function updateCardSpacingVisibility() {
  cardSpacingGroup.hidden = cutSelect.value === 'none';
}

cardSpacingInput.addEventListener('input', updateCardSpacingValue);
cutSelect.addEventListener('change', updateCardSpacingVisibility);
updateCardSpacingValue();
updateCardSpacingVisibility();

function setLoading(show) {
  overlay.classList.toggle('active', show);
}

function setError(message) {
  errorMessage.textContent = message;
}

window.addEventListener('load', function() { setLoading(false); });
window.addEventListener('error', function() { setLoading(false); });
window.addEventListener('unhandledrejection', function() { setLoading(false); });

const deckTabs = document.querySelectorAll('.deck-tab');
const deckTabPanels = document.querySelectorAll('.deck-tab-panel');
const faceSelect = document.getElementById('face-select');
const previewPrevBtn = document.getElementById('preview-prev-btn');
const previewNextBtn = document.getElementById('preview-next-btn');
const previewPageLabel = document.getElementById('preview-page-label');
let mainPreviewUrl = null;
let previewRequestId = 0;
let previewDebounceTimer = null;
let currentPreviewPage = 0;
let totalPreviewPages = 1;

function getActiveTabName() {
  const active = document.querySelector('.deck-tab.active');
  return active ? active.getAttribute('data-tab') : 'fronts';
}

function updatePagerUI() {
  if (previewPageLabel) {
    previewPageLabel.textContent = 'Page ' + (currentPreviewPage + 1) + ' / ' + totalPreviewPages;
  }
  if (previewPrevBtn) previewPrevBtn.disabled = currentPreviewPage <= 0;
  if (previewNextBtn) previewNextBtn.disabled = currentPreviewPage >= totalPreviewPages - 1;
}

const localCustomBacks = {};
const exportDirInput = document.getElementById('export-dir');
const exportDirBrowseBtn = document.getElementById('export-dir-browse-btn');
const dirBrowserModal = document.getElementById('dir-browser-modal');
const dirBrowserCloseBtn = document.getElementById('dir-browser-close-btn');
const dirBrowserCancelBtn = document.getElementById('dir-browser-cancel-btn');
const dirBrowserUpBtn = document.getElementById('dir-browser-up-btn');
const dirBrowserCurrent = document.getElementById('dir-browser-current');
const dirBrowserList = document.getElementById('dir-browser-list');
const dirBrowserNewName = document.getElementById('dir-browser-new-name');
const dirBrowserMkdirBtn = document.getElementById('dir-browser-mkdir-btn');
const dirBrowserSelectBtn = document.getElementById('dir-browser-select-btn');
const dirBrowserError = document.getElementById('dir-browser-error');

let dirBrowserParent = null;

function showDirBrowserError(msg) {
  if (!dirBrowserError) return;
  dirBrowserError.textContent = msg || '';
  dirBrowserError.style.display = msg ? 'block' : 'none';
}

async function loadDirBrowser(path) {
  showDirBrowserError('');
  try {
    const url = '/browse-dirs' + (path ? ('?path=' + encodeURIComponent(path)) : '');
    const res = await fetch(url);
    const data = await res.json();
    if (!res.ok || data.error) {
      showDirBrowserError(data.error || 'Could not open folder.');
      return;
    }
    if (dirBrowserCurrent) dirBrowserCurrent.value = data.current;
    dirBrowserParent = data.parent || null;
    if (dirBrowserUpBtn) dirBrowserUpBtn.disabled = !dirBrowserParent;
    if (dirBrowserList) {
      dirBrowserList.innerHTML = '';
      if (!data.dirs || data.dirs.length === 0) {
        const empty = document.createElement('div');
        empty.style.padding = '12px';
        empty.style.color = 'var(--muted)';
        empty.style.fontSize = '12px';
        empty.textContent = '(No subfolders)';
        dirBrowserList.appendChild(empty);
      } else {
        data.dirs.forEach(function(name) {
          const item = document.createElement('button');
          item.type = 'button';
          item.style.display = 'flex';
          item.style.alignItems = 'center';
          item.style.gap = '8px';
          item.style.width = '100%';
          item.style.textAlign = 'left';
          item.style.padding = '8px 12px';
          item.style.border = '0';
          item.style.borderBottom = '1px solid var(--table-border)';
          item.style.background = 'transparent';
          item.style.color = 'var(--fg)';
          item.style.cursor = 'pointer';
          item.style.fontSize = '13px';
          item.textContent = '📁 ' + name;
          item.addEventListener('click', function() {
            const sep = data.current.endsWith('/') ? '' : '/';
            loadDirBrowser(data.current + sep + name);
          });
          dirBrowserList.appendChild(item);
        });
      }
    }
  } catch (err) {
    showDirBrowserError('Error loading folders: ' + err.message);
  }
}

function closeDirBrowserModal() {
  if (dirBrowserModal) dirBrowserModal.classList.remove('active');
}

if (exportDirBrowseBtn) {
  exportDirBrowseBtn.addEventListener('click', function() {
    if (dirBrowserModal) dirBrowserModal.classList.add('active');
    loadDirBrowser(exportDirInput ? exportDirInput.value.trim() : '');
  });
}

if (dirBrowserCloseBtn) dirBrowserCloseBtn.addEventListener('click', closeDirBrowserModal);
if (dirBrowserCancelBtn) dirBrowserCancelBtn.addEventListener('click', closeDirBrowserModal);
if (dirBrowserModal) {
  dirBrowserModal.addEventListener('click', function(e) {
    if (e.target === dirBrowserModal) closeDirBrowserModal();
  });
}

if (dirBrowserUpBtn) {
  dirBrowserUpBtn.addEventListener('click', function() {
    if (dirBrowserParent) loadDirBrowser(dirBrowserParent);
  });
}

if (dirBrowserMkdirBtn) {
  dirBrowserMkdirBtn.addEventListener('click', async function() {
    const current = dirBrowserCurrent ? dirBrowserCurrent.value.trim() : '';
    const name = dirBrowserNewName ? dirBrowserNewName.value.trim() : '';
    if (!name) {
      showDirBrowserError('Enter a folder name.');
      return;
    }
    showDirBrowserError('');
    const body = new FormData();
    body.append('current', current);
    body.append('folder_name', name);
    try {
      const res = await fetch('/browse-dirs', { method: 'POST', body: body });
      const data = await res.json();
      if (!res.ok || data.error) {
        showDirBrowserError(data.error || 'Could not create folder.');
        return;
      }
      if (dirBrowserNewName) dirBrowserNewName.value = '';
      loadDirBrowser(data.created || current);
    } catch (err) {
      showDirBrowserError('Error creating folder: ' + err.message);
    }
  });
}

if (dirBrowserSelectBtn) {
  dirBrowserSelectBtn.addEventListener('click', function() {
    if (exportDirInput && dirBrowserCurrent) {
      exportDirInput.value = dirBrowserCurrent.value;
    }
    closeDirBrowserModal();
    scheduleMainPreview(50, true);
  });
}

function appendLocalCustomBacks(formData) {
  const keys = Object.keys(localCustomBacks);
  if (keys.length === 0) return;
  const mapObj = {};
  const fileToKey = new Map();
  let idx = 0;
  keys.forEach(function(cardFilename) {
    const file = localCustomBacks[cardFilename];
    if (!file) return;
    let fieldKey = fileToKey.get(file);
    if (!fieldKey) {
      fieldKey = 'custom_back_file_' + (idx++);
      fileToKey.set(file, fieldKey);
      formData.append(fieldKey, file);
    }
    mapObj[cardFilename] = fieldKey;
  });
  formData.append('custom_back_map', JSON.stringify(mapObj));
}

function getSourceFrontFilesList() {
  if (!sourceFilesInput || !sourceFilesInput.files) return [];
  const out = [];
  for (let i = 0; i < sourceFilesInput.files.length; i++) {
    const f = sourceFilesInput.files[i];
    const rel = (f.webkitRelativePath || f.name).replace(/\\/g, '/');
    const lower = rel.toLowerCase();
    if (!lower.endsWith('.pdf')) continue;
    const parts = lower.split('/');
    const base = parts[parts.length - 1];
    if (parts.indexOf('backs') !== -1 || parts.indexOf('_backs') !== -1) continue;
    if (base.startsWith('deckgen_') || base.startsWith('cardback') || base.startsWith('back.')) continue;
    out.push(f);
  }
  out.sort(function(a, b) { return a.name.localeCompare(b.name); });
  return out;
}

const pagePreviewCache = new Map();
let previewCacheEpoch = 0;

function invalidatePreviewPageCache() {
  previewCacheEpoch += 1;
  pagePreviewCache.forEach(function(entry) {
    if (entry && entry.url) URL.revokeObjectURL(entry.url);
  });
  pagePreviewCache.clear();
}

function getPreviewCacheKey(face, page) {
  const s = getDeckGenStateObject();
  return [
    previewCacheEpoch,
    face,
    page,
    s.export_dir,
    s.paper,
    s.landscape,
    s.cut,
    s.card_spacing,
    s.color,
    s.thickness,
    s.mark_len,
  ].join('|');
}

async function refreshMainPreview(faceOverride, showOverlay) {
  const reqId = ++previewRequestId;
  const activeTab = getActiveTabName();
  const face = faceOverride || (activeTab === 'backs' ? 'backs' : activeTab === 'fronts' ? 'fronts' : (faceSelect ? faceSelect.value : 'fronts'));
  const cacheKey = getPreviewCacheKey(face, currentPreviewPage);
  const cached = pagePreviewCache.get(cacheKey);
  if (cached && cached.url) {
    totalPreviewPages = cached.totalPages;
    currentPreviewPage = cached.page;
    updatePagerUI();
    previewImg.src = cached.url;
    previewImg.style.display = 'block';
    setError('');
    return;
  }
  if (showOverlay) setLoading(true);
  setError('');
  try {
    const body = new FormData(form);
    body.set('face', face);
    body.set('page', String(currentPreviewPage));
    appendLocalCustomBacks(body);
    const response = await fetch('/preview', { method: 'POST', body: body });
    if (reqId !== previewRequestId) return;
    if (!response.ok) {
      setError('Preview failed: ' + await response.text());
      previewImg.style.display = 'none';
      return;
    }
    const hdrTotal = parseInt(response.headers.get('X-Total-Pages') || '1', 10);
    const hdrPage = parseInt(response.headers.get('X-Current-Page') || '0', 10);
    totalPreviewPages = Number.isFinite(hdrTotal) && hdrTotal > 0 ? hdrTotal : 1;
    currentPreviewPage = Number.isFinite(hdrPage) && hdrPage >= 0 ? hdrPage : 0;
    updatePagerUI();
    const blob = await response.blob();
    if (reqId !== previewRequestId) return;
    const objUrl = URL.createObjectURL(blob);
    pagePreviewCache.set(getPreviewCacheKey(face, currentPreviewPage), {
      url: objUrl,
      totalPages: totalPreviewPages,
      page: currentPreviewPage,
    });
    mainPreviewUrl = objUrl;
    previewImg.src = objUrl;
    previewImg.style.display = 'block';
  } catch (err) {
    if (reqId !== previewRequestId) return;
    setError('Preview failed: ' + err.message);
  } finally {
    if (showOverlay) setLoading(false);
  }
}

function scheduleMainPreview(delayMs, resetPage) {
  clearTimeout(previewDebounceTimer);
  if (resetPage) currentPreviewPage = 0;
  previewDebounceTimer = setTimeout(function() {
    refreshMainPreview(null, false);
  }, delayMs || 150);
}

if (previewPrevBtn) {
  previewPrevBtn.addEventListener('click', function() {
    if (currentPreviewPage > 0) {
      currentPreviewPage -= 1;
      saveDeckGenState();
      updatePagerUI();
      refreshMainPreview(null, false);
    }
  });
}

if (previewNextBtn) {
  previewNextBtn.addEventListener('click', function() {
    if (currentPreviewPage < totalPreviewPages - 1) {
      currentPreviewPage += 1;
      saveDeckGenState();
      updatePagerUI();
      refreshMainPreview(null, false);
    }
  });
}

const DG_STATE_KEY = 'deckgen-dg-state';
let lastWatchedSignature = null;
let lastWatchedDir = '';
let watchPollInFlight = false;

function getDeckGenStateObject() {
  return {
    export_dir: exportDirInput ? exportDirInput.value : '',
    paper: document.getElementById('paper-select')?.value || 'a4',
    landscape: Boolean(document.getElementById('landscape-check')?.checked),
    cut: cutSelect ? cutSelect.value : 'corners',
    card_spacing: cardSpacingInput ? cardSpacingInput.value : '0',
    color: colorText ? colorText.value : '#00ff00',
    thickness: document.getElementById('thickness-input')?.value || '0.5',
    mark_len: document.getElementById('mark-len-input')?.value || '3',
    face: faceSelect ? faceSelect.value : 'fronts',
    active_tab: getActiveTabName(),
    page: currentPreviewPage,
  };
}

function saveDeckGenState() {
  try {
    localStorage.setItem(DG_STATE_KEY, JSON.stringify(getDeckGenStateObject()));
  } catch (e) {}
}

function activateTabByName(target) {
  deckTabs.forEach(function(t) {
    const active = t.getAttribute('data-tab') === target;
    t.classList.toggle('active', active);
    t.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  deckTabPanels.forEach(function(panel) {
    panel.classList.toggle('active', panel.getAttribute('data-panel') === target);
  });
}

function applyDeckGenStateObject(state, overwriteExportDir) {
  if (!state || typeof state !== 'object') return;
  if (exportDirInput && typeof state.export_dir === 'string' && (overwriteExportDir || !exportDirInput.value)) {
    exportDirInput.value = state.export_dir;
  }
  const paperEl = document.getElementById('paper-select');
  if (paperEl && state.paper) paperEl.value = state.paper;
  const landEl = document.getElementById('landscape-check');
  if (landEl && typeof state.landscape === 'boolean') landEl.checked = state.landscape;
  if (cutSelect && state.cut) cutSelect.value = state.cut;
  if (cardSpacingInput && state.card_spacing !== undefined) cardSpacingInput.value = state.card_spacing;
  if (colorText && state.color) {
    colorText.value = state.color;
    if (colorPicker && /^#[0-9A-Fa-f]{6}$/.test(state.color)) colorPicker.value = state.color;
  }
  const thickEl = document.getElementById('thickness-input');
  if (thickEl && state.thickness !== undefined) thickEl.value = state.thickness;
  const markEl = document.getElementById('mark-len-input');
  if (markEl && state.mark_len !== undefined) markEl.value = state.mark_len;
  if (faceSelect && state.face) faceSelect.value = state.face;
  if (state.active_tab) activateTabByName(state.active_tab);
  if (typeof state.page === 'number' && state.page >= 0) currentPreviewPage = state.page;
  updateCardSpacingValue();
  updateCardSpacingVisibility();
}

function restoreDeckGenState() {
  try {
    const raw = localStorage.getItem(DG_STATE_KEY);
    if (!raw) return;
    applyDeckGenStateObject(JSON.parse(raw), false);
  } catch (e) {}
}

window.__deckgenGetDeckGeneratorState = getDeckGenStateObject;
window.__deckgenApplyDeckGeneratorState = function(state) {
  applyDeckGenStateObject(state, true);
  saveDeckGenState();
  lastWatchedDir = '';
  lastWatchedSignature = null;
  updatePagerUI();
  refreshMainPreview(null, false);
  checkWatchedDir(false);
  checkCustomBacksCount();
};

async function checkWatchedDir(forceRefreshOnInit) {
  if (watchPollInFlight || document.visibilityState !== 'visible') return;
  const dir = exportDirInput ? exportDirInput.value.trim() : '';
  if (!dir) {
    lastWatchedSignature = null;
    lastWatchedDir = '';
    return;
  }
  watchPollInFlight = true;
  try {
    const res = await fetch('/deck/watch?export_dir=' + encodeURIComponent(dir));
    if (!res.ok) return;
    const data = await res.json();
    if (!data.valid) return;
    if (lastWatchedDir !== dir) {
      lastWatchedDir = dir;
      lastWatchedSignature = data.signature;
      if (forceRefreshOnInit) {
        refreshMainPreview(null, false);
        checkCustomBacksCount();
      }
      return;
    }
    if (lastWatchedSignature !== null && data.signature !== lastWatchedSignature) {
      lastWatchedSignature = data.signature;
      invalidatePreviewPageCache();
      refreshMainPreview(null, false);
      checkCustomBacksCount();
    } else {
      lastWatchedSignature = data.signature;
    }
  } catch (e) {
  } finally {
    watchPollInFlight = false;
  }
}

deckTabs.forEach(function(tab) {
  tab.addEventListener('click', function() {
    const target = tab.getAttribute('data-tab');
    activateTabByName(target);
    if (target === 'fronts' || target === 'backs') {
      if (faceSelect) faceSelect.value = target;
      saveDeckGenState();
      refreshMainPreview(target, false);
    } else {
      saveDeckGenState();
      refreshMainPreview(null, false);
    }
  });
});

['paper-select', 'landscape-check', 'cut-select', 'duplex-flip', 'face-select', 'source-files', 'back-file', 'export-dir'].forEach(function(id) {
  const el = document.getElementById(id);
  if (el) el.addEventListener('change', function() {
    saveDeckGenState();
    if (id === 'source-files' || id === 'back-file' || id === 'export-dir') {
      invalidatePreviewPageCache();
    }
    if (id === 'export-dir') {
      lastWatchedDir = '';
      lastWatchedSignature = null;
      checkWatchedDir(false);
    }
    scheduleMainPreview(80, id === 'source-files' || id === 'export-dir' || id === 'paper-select' || id === 'landscape-check');
  });
});
['card-spacing', 'color-text', 'color-picker', 'thickness-input', 'mark-len-input'].forEach(function(id) {
  const el = document.getElementById(id);
  if (el) el.addEventListener('input', function() {
    saveDeckGenState();
    scheduleMainPreview(250, false);
  });
});

if (dirBrowserSelectBtn) {
  dirBrowserSelectBtn.addEventListener('click', function() {
    setTimeout(function() {
      saveDeckGenState();
      lastWatchedDir = '';
      lastWatchedSignature = null;
      checkWatchedDir(false);
    }, 0);
  });
}

restoreDeckGenState();
updatePagerUI();
refreshMainPreview(null, false);
checkWatchedDir(false);

setInterval(function() { checkWatchedDir(false); }, 3000);
document.addEventListener('visibilitychange', function() {
  if (document.visibilityState === 'visible') checkWatchedDir(false);
});
window.addEventListener('focus', function() { checkWatchedDir(false); });

const floatingPreviewBtn = document.getElementById('floating-preview-btn');
const previewModal = document.getElementById('preview-modal');
const previewModalCloseBtn = document.getElementById('preview-modal-close-btn');
const previewFrontImg = document.getElementById('preview-front');
const previewBackImg = document.getElementById('preview-back');

let previewObjectUrls = [];

async function fetchSheetPreview(face) {
  const body = new FormData(form);
  body.set('face', face);
  appendLocalCustomBacks(body);
  const response = await fetch('/preview', { method: 'POST', body: body });
  if (!response.ok) throw new Error(await response.text());
  return response.blob();
}

function setPreviewImage(img, blob) {
  const url = URL.createObjectURL(blob);
  previewObjectUrls.push(url);
  img.src = url;
}

floatingPreviewBtn.addEventListener('click', async function() {
  previewObjectUrls.forEach(function(url) { URL.revokeObjectURL(url); });
  previewObjectUrls = [];
  previewFrontImg.src = '';
  previewBackImg.src = '';
  setError('');
  previewModal.classList.add('active');
  try {
    const blobs = await Promise.all([fetchSheetPreview('fronts'), fetchSheetPreview('backs')]);
    setPreviewImage(previewFrontImg, blobs[0]);
    setPreviewImage(previewBackImg, blobs[1]);
  } catch (err) {
    previewModal.classList.remove('active');
    setError('Preview failed: ' + err.message);
  }
});

function closePreviewModal() {
  previewModal.classList.remove('active');
}

previewModalCloseBtn.addEventListener('click', closePreviewModal);

previewModal.addEventListener('click', function(e) {
  if (e.target === previewModal) {
    closePreviewModal();
  }
});

previewBtn.addEventListener('click', function() {
  refreshMainPreview(faceSelect ? faceSelect.value : null, true);
});

form.addEventListener('submit', async function(event) {
  event.preventDefault();
  setLoading(true);
  setError('');
  progressBar.style.width = '0%';
  progressStatus.textContent = 'Starting...';
  const intervalId = setInterval(async function() {
    try {
      const response = await fetch('/progress');
      const data = await response.json();
      progressBar.style.width = data.percent + '%';
      progressStatus.textContent = data.status;
      if (data.done) {
        clearInterval(intervalId);
      }
    } catch (err) {
      clearInterval(intervalId);
    }
  }, 500);
  try {
    const body = new FormData(form);
    appendLocalCustomBacks(body);
    const response = await fetch('/generate', { method: 'POST', body: body });
    clearInterval(intervalId);
    if (!response.ok) {
      let msg = await response.text();
      try {
        const errData = JSON.parse(msg);
        if (errData.error) msg = errData.error;
      } catch (parseErr) {}
      setError('Generate failed: ' + msg);
      saveResult.innerHTML = '';
      return;
    }
    const data = await response.json();
    setError('');
    saveResult.innerHTML = '';
    const pathP = document.createElement('p');
    pathP.textContent = 'Saved to: ' + data.path;
    saveResult.appendChild(pathP);
    if (data.download_url) {
      const link = document.createElement('a');
      link.href = data.download_url;
      link.textContent = 'Download PDF';
      link.target = '_blank';
      saveResult.appendChild(link);
    }
  } catch (err) {
    clearInterval(intervalId);
    setError('Generate failed: ' + err.message);
  } finally {
    setLoading(false);
  }
});

// Modal Deck Inspector
const checkDeckBtn = document.getElementById('check-deck-btn');
const deckModal = document.getElementById('deck-modal');
const modalCloseBtn = document.getElementById('modal-close-btn');
const modalCloseFooterBtn = document.getElementById('modal-close-footer-btn');
const xmlSelect = document.getElementById('xml-select');
const xmlFileInput = document.getElementById('xml-file-input');
const xmlRefreshBtn = document.getElementById('xml-refresh-btn');
const autoDuplicateBtn = document.getElementById('auto-duplicate-btn');
const deckSearchInput = document.getElementById('deck-search-input');
const deckFeedback = document.getElementById('deck-feedback');
const deckTableBody = document.getElementById('deck-table-body');
const tabBtns = document.querySelectorAll('.tab-btn');

let currentDeckData = null;
let currentTab = 'all';

function showDeckFeedback(msg, isError) {
  deckFeedback.style.display = 'block';
  deckFeedback.style.background = isError ? 'var(--danger-bg)' : 'var(--ok-bg)';
  deckFeedback.style.color = isError ? 'var(--danger)' : 'var(--ok)';
  deckFeedback.textContent = msg;
}

function hideDeckFeedback() {
  deckFeedback.style.display = 'none';
}

async function loadDeckData(xmlPath, xmlFile) {
  const exportDir = document.getElementById('export-dir').value.trim();
  if (!exportDir && !xmlFile) {
    showDeckFeedback('Please enter the deck directory path in "Export directory".', true);
    deckTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--danger); padding: 2em;">Missing "Export directory".</td></tr>';
    return;
  }
  hideDeckFeedback();
  deckTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--muted); padding: 2em;">Inspecting cards and comparing against deck list (.txt / .xml)...</td></tr>';
  
  const formData = new FormData();
  formData.append('export_dir', exportDir);
  if (xmlPath) {
    formData.append('deck_path', xmlPath);
    formData.append('xml_path', xmlPath);
  }
  if (xmlFile) {
    formData.append('deck_file', xmlFile);
    formData.append('xml_file', xmlFile);
  }

  try {
    const res = await fetch('/deck/check', { method: 'POST', body: formData });
    const data = await res.json();
    if (data.error) {
      showDeckFeedback(data.error, true);
      deckTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--danger); padding: 2em;">' + data.error + '</td></tr>';
      return;
    }
    currentDeckData = data;
    updateModalHeaderAndStats(data);
    renderDeckTable();
  } catch (err) {
    showDeckFeedback('Connection error: ' + err.message, true);
  }
}

function updateModalHeaderAndStats(data) {
  document.getElementById('stat-target').textContent = data.quantity || 100;
  document.getElementById('stat-disk').textContent = data.total_files_disk;
  const countCards = data.total_cards || data.total_cards_xml || 0;
  document.getElementById('stat-xml').textContent = countCards + ' (' + data.total_slots + ' slots)';
  
  let needsCount = 0;
  let missingCount = 0;
  let okCount = 0;
  data.cards.forEach(function(c) {
    if (c.status === 'needs_copies') needsCount++;
    else if (c.status === 'missing') missingCount++;
    else if (c.status === 'ok') okCount++;
  });
  document.getElementById('stat-needs').textContent = needsCount;
  document.getElementById('stat-missing').textContent = missingCount;

  document.getElementById('count-all').textContent = data.cards.length;
  document.getElementById('count-needs').textContent = needsCount;
  document.getElementById('count-missing').textContent = missingCount;
  document.getElementById('count-ok').textContent = okCount;
  document.getElementById('count-extra').textContent = data.extra_files ? data.extra_files.length : 0;

  xmlSelect.innerHTML = '';
  const fileList = data.available_files || data.available_xmls || [];
  const currentSelected = data.deck_file_path || data.xml_path;
  if (fileList && fileList.length > 0) {
    fileList.forEach(function(xp) {
      const opt = document.createElement('option');
      opt.value = xp;
      opt.textContent = xp;
      if (xp === currentSelected) opt.selected = true;
      xmlSelect.appendChild(opt);
    });
  } else if (currentSelected) {
    const opt = document.createElement('option');
    opt.value = currentSelected;
    opt.textContent = currentSelected;
    opt.selected = true;
    xmlSelect.appendChild(opt);
  }
}

function renderDeckTable() {
  if (!currentDeckData) return;
  const q = deckSearchInput.value.toLowerCase().trim();
  deckTableBody.innerHTML = '';

  if (currentTab === 'extra') {
    const extras = currentDeckData.extra_files || [];
    const filteredExtras = extras.filter(function(f) {
      return !q || f.toLowerCase().indexOf(q) !== -1;
    });
    if (filteredExtras.length === 0) {
      deckTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--muted); padding: 2em;">No extra/token files.</td></tr>';
      return;
    }
    filteredExtras.forEach(function(f) {
      const tr = document.createElement('tr');
      tr.innerHTML = '<td>-</td>' +
        '<td><strong>' + f + '</strong></td>' +
        '<td>-</td>' +
        '<td>1</td>' +
        '<td><span class="badge badge-extra">Token / Extra</span></td>' +
        '<td><button type="button" class="btn-action-small btn-dup" data-file="' + encodeURIComponent(f) + '" data-count="1">+1 Duplicate</button></td>';
      deckTableBody.appendChild(tr);
    });
    return;
  }

  const filteredCards = currentDeckData.cards.filter(function(c) {
    if (currentTab === 'needs_copies' && c.status !== 'needs_copies') return false;
    if (currentTab === 'missing' && c.status !== 'missing') return false;
    if (currentTab === 'ok' && c.status !== 'ok') return false;
    if (q) {
      const matchName = c.name && c.name.toLowerCase().indexOf(q) !== -1;
      const matchQuery = c.query && c.query.toLowerCase().indexOf(q) !== -1;
      const matchFile = c.matched_file && c.matched_file.toLowerCase().indexOf(q) !== -1;
      if (!matchName && !matchQuery && !matchFile) return false;
    }
    return true;
  });

  if (filteredCards.length === 0) {
    deckTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--muted); padding: 2em;">No cards found in this filter.</td></tr>';
    return;
  }

  filteredCards.forEach(function(c) {
    const tr = document.createElement('tr');
    let statusBadge = '';
    let actionBtn = '';

    if (c.status === 'ok') {
      statusBadge = '<span class="badge badge-ok">✅ Complete</span>';
      if (c.matched_file) {
        actionBtn = '<button type="button" class="btn-action-small btn-dup" data-file="' + encodeURIComponent(c.matched_file) + '" data-count="1">+1 Duplicate</button>';
      }
    } else if (c.status === 'needs_copies') {
      const diff = c.required_count - c.existing_copies;
      statusBadge = '<span class="badge badge-warn">⚠️ Missing ' + diff + '</span>';
      if (c.matched_file) {
        actionBtn = '<button type="button" class="btn-action-small btn-dup" style="background: #d97706;" data-file="' + encodeURIComponent(c.matched_file) + '" data-count="' + diff + '">⚡ Duplicate ' + diff + '</button>';
      }
    } else {
      statusBadge = '<span class="badge badge-missing">❌ Not on disk</span>';
      actionBtn = '<span style="color: var(--muted); font-size: 0.85em;">(Missing file)</span>';
    }

    const slotsDisplay = c.slots.join(', ');
    const matchedDisplay = c.matched_file ? '<div style="color: var(--ok); font-size: 0.85em;">📄 ' + c.matched_file + '</div>' : '';

    tr.innerHTML = '<td><code style="font-size: 0.82em; background: var(--table-head-bg); padding: 2px 4px; color: var(--fg); border-radius: 3px;">' + slotsDisplay + '</code></td>' +
      '<td><strong>' + c.name + '</strong>' +
      (c.query && c.query !== c.name ? '<div style="color: #64748b; font-size: 0.85em;">Query: ' + c.query + '</div>' : '') +
      matchedDisplay + '</td>' +
      '<td><strong>' + c.required_count + '</strong></td>' +
      '<td>' + c.existing_copies + '</td>' +
      '<td>' + statusBadge + '</td>' +
      '<td>' + actionBtn + '</td>';
    deckTableBody.appendChild(tr);
  });
}

deckTableBody.addEventListener('click', function(e) {
  const btn = e.target.closest('.btn-dup');
  if (btn) {
    const file = btn.getAttribute('data-file');
    const count = parseInt(btn.getAttribute('data-count'), 10) || 1;
    duplicateCard(file, count);
  }
});

window.duplicateCard = async function(encodedFile, count) {
  const fileName = decodeURIComponent(encodedFile);
  const exportDir = document.getElementById('export-dir').value.trim();
  const body = new FormData();
  body.append('export_dir', exportDir);
  body.append('target_file', fileName);
  body.append('copies_to_add', count);
  try {
    const res = await fetch('/deck/duplicate', { method: 'POST', body: body });
    const data = await res.json();
    if (data.error) {
      showDeckFeedback('Error duplicating: ' + data.error, true);
    } else {
      showDeckFeedback(data.message || ('Created ' + count + ' copy(ies).'), false);
      loadDeckData(xmlSelect.value);
    }
  } catch (err) {
    showDeckFeedback('Error: ' + err.message, true);
  }
};

autoDuplicateBtn.addEventListener('click', async function() {
  const exportDir = document.getElementById('export-dir').value.trim();
  if (!exportDir) {
    showDeckFeedback('Specify "Export directory".', true);
    return;
  }
  autoDuplicateBtn.disabled = true;
  autoDuplicateBtn.textContent = 'Duplicating...';
  const body = new FormData();
  body.append('export_dir', exportDir);
  body.append('auto_deck', 'true');
  body.append('auto_xml', 'true');
  if (xmlSelect.value) {
    body.append('deck_path', xmlSelect.value);
    body.append('xml_path', xmlSelect.value);
  }
  try {
    const res = await fetch('/deck/duplicate', { method: 'POST', body: body });
    const data = await res.json();
    if (data.error) {
      showDeckFeedback('Error: ' + data.error, true);
    } else {
      showDeckFeedback(data.message || ('Duplication completed: ' + data.count + ' files created.'), false);
      loadDeckData(xmlSelect.value);
    }
  } catch (err) {
    showDeckFeedback('Duplication error: ' + err.message, true);
  } finally {
    autoDuplicateBtn.disabled = false;
    autoDuplicateBtn.innerHTML = '<span>⚡</span> Duplicate repeated cards per list';
  }
});

checkDeckBtn.addEventListener('click', function() {
  deckModal.classList.add('active');
  loadDeckData();
});

modalCloseBtn.addEventListener('click', function() {
  deckModal.classList.remove('active');
});

modalCloseFooterBtn.addEventListener('click', function() {
  deckModal.classList.remove('active');
});

xmlSelect.addEventListener('change', function() {
  loadDeckData(this.value);
});

xmlFileInput.addEventListener('change', function() {
  if (this.files.length) {
    loadDeckData(null, this.files[0]);
  }
});

xmlRefreshBtn.addEventListener('click', function() {
  loadDeckData(xmlSelect.value);
});

deckSearchInput.addEventListener('input', renderDeckTable);

tabBtns.forEach(function(btn) {
  btn.addEventListener('click', function() {
    tabBtns.forEach(function(b) { b.classList.remove('active'); });
    this.classList.add('active');
    currentTab = this.getAttribute('data-tab');
    renderDeckTable();
  });
});

// Custom Card Backs (MDFC) Modal
const openCustomBacksBtn = document.getElementById('open-custom-backs-btn');
const customBacksBadge = document.getElementById('custom-backs-badge');
const customBacksModal = document.getElementById('custom-backs-modal');
const cbModalCloseBtn = document.getElementById('cb-modal-close-btn');
const cbModalFooterCloseBtn = document.getElementById('cb-modal-footer-close-btn');
const cbFeedback = document.getElementById('cb-feedback');
const cbTableBody = document.getElementById('cb-table-body');
const cbSearchInput = document.getElementById('cb-search-input');
const cbFilterSelect = document.getElementById('cb-filter-select');
const cbAutodetectBtn = document.getElementById('cb-autodetect-btn');
const cbBulkAssignBtn = document.getElementById('cb-bulk-assign-btn');
const cbBulkRemoveBtn = document.getElementById('cb-bulk-remove-btn');
const cbSelectAll = document.getElementById('cb-select-all');
const cbSingleUpload = document.getElementById('cb-single-upload');
const cbBulkUpload = document.getElementById('cb-bulk-upload');
const cbSelectedCount = document.getElementById('cb-selected-count');

let currentCbData = null;
let pendingUploadCardFiles = [];

function showCbFeedback(msg, isError) {
  cbFeedback.style.display = 'block';
  cbFeedback.style.background = isError ? 'var(--danger-bg)' : 'var(--ok-bg)';
  cbFeedback.style.color = isError ? 'var(--danger)' : 'var(--ok)';
  cbFeedback.textContent = msg;
}

function hideCbFeedback() {
  cbFeedback.style.display = 'none';
}

function updateMainBadge(count) {
  if (count > 0) {
    customBacksBadge.style.display = 'inline-block';
    customBacksBadge.textContent = count + ' MDFC';
  } else {
    customBacksBadge.style.display = 'none';
  }
}

async function checkCustomBacksCount() {
  const exportDir = document.getElementById('export-dir').value.trim();
  if (!exportDir) {
    updateMainBadge(0);
    return;
  }
  try {
    const res = await fetch('/deck/custom_backs?export_dir=' + encodeURIComponent(exportDir));
    const data = await res.json();
    if (data.status === 'ok') {
      updateMainBadge(data.custom_count || 0);
    }
  } catch (e) {}
}

async function loadCustomBacksData() {
  const exportDir = document.getElementById('export-dir').value.trim();
  const frontFiles = getSourceFrontFilesList();
  if (!exportDir) {
    if (frontFiles.length === 0) {
      showCbFeedback('Please load PDF cards in the Fronts tab (📁 Load PDF Folder) or enter a server Export directory.', true);
      cbTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--danger); padding: 2em;">No front PDF cards loaded.</td></tr>';
      return;
    }
    hideCbFeedback();
    document.getElementById('cb-footer-dir').textContent = 'Loaded Fronts (' + frontFiles.length + ' PDFs)';
    let customCount = 0;
    const cardsList = frontFiles.map(function(f, idx) {
      const assigned = localCustomBacks[f.name] || null;
      if (assigned) customCount++;
      return {
        index: idx + 1,
        name: f.name.replace(/\.pdf$/i, ''),
        filename: f.name,
        is_custom: Boolean(assigned),
        custom_back: assigned ? assigned.name : null,
        custom_back_filename: assigned ? assigned.name : null,
        xml_paired_back: null
      };
    });
    currentCbData = {
      status: 'ok',
      total_cards: cardsList.length,
      generic_count: cardsList.length - customCount,
      custom_count: customCount,
      available_backs: [],
      cards: cardsList
    };
    document.getElementById('cb-stat-total').textContent = currentCbData.total_cards;
    document.getElementById('cb-stat-generic').textContent = currentCbData.generic_count;
    document.getElementById('cb-stat-custom').textContent = currentCbData.custom_count;
    document.getElementById('cb-stat-available').textContent = 0;
    updateMainBadge(customCount);
    renderCustomBacksTable();
    return;
  }
  hideCbFeedback();
  cbTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--muted); padding: 2em;">Loading deck cards...</td></tr>';
  document.getElementById('cb-footer-dir').textContent = exportDir;

  try {
    const formData = new FormData();
    formData.append('action', 'inspect');
    formData.append('export_dir', exportDir);
    const res = await fetch('/deck/custom_backs', { method: 'POST', body: formData });
    const data = await res.json();
    if (data.error) {
      showCbFeedback(data.error, true);
      cbTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--danger); padding: 2em;">' + data.error + '</td></tr>';
      return;
    }
    currentCbData = data;
    document.getElementById('cb-stat-total').textContent = data.total_cards || 0;
    document.getElementById('cb-stat-generic').textContent = data.generic_count || 0;
    document.getElementById('cb-stat-custom').textContent = data.custom_count || 0;
    document.getElementById('cb-stat-available').textContent = (data.available_backs || []).length;
    updateMainBadge(data.custom_count || 0);
    renderCustomBacksTable();
  } catch (err) {
    showCbFeedback('Connection error: ' + err.message, true);
    cbTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--danger); padding: 2em;">Error connecting to the server.</td></tr>';
  }
}

function renderCustomBacksTable() {
  if (!currentCbData || !currentCbData.cards) return;
  const q = cbSearchInput.value.toLowerCase().trim();
  const filter = cbFilterSelect.value;
  const available = currentCbData.available_backs || [];

  cbTableBody.innerHTML = '';
  cbSelectAll.checked = false;
  updateSelectedCount();

  const filtered = currentCbData.cards.filter(function(c) {
    if (filter === 'custom' && !c.is_custom) return false;
    if (filter === 'generic' && c.is_custom) return false;
    if (q) {
      const matchName = (c.name || '').toLowerCase().includes(q);
      const matchFile = (c.filename || '').toLowerCase().includes(q);
      const matchBack = (c.custom_back_filename || '').toLowerCase().includes(q);
      if (!matchName && !matchFile && !matchBack) return false;
    }
    return true;
  });

  if (filtered.length === 0) {
    cbTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--muted); padding: 2em;">No cards match the filters.</td></tr>';
    return;
  }

  filtered.forEach(function(c) {
    const tr = document.createElement('tr');
    const encodedFile = encodeURIComponent(c.filename);

    let backBadgeHtml = '';
    if (c.is_custom) {
      backBadgeHtml = '<span class="badge badge-custom" title="Path: ' + (c.custom_back || '') + '">📄 ' + (c.custom_back_filename || 'Custom PDF') + '</span>';
    } else {
      backBadgeHtml = '<span class="badge badge-generic">Generic</span>';
      if (c.xml_paired_back) {
        backBadgeHtml += ' <span style="font-size: 0.75em; color: var(--info);" title="Detected in XML: ' + c.xml_paired_back + '">💡 Suggested: ' + c.xml_paired_back + '</span>';
      }
    }

    let selectHtml = '';
    if (available.length > 0) {
      selectHtml = '<select class="cb-select-back" data-file="' + encodedFile + '" style="max-width: 130px; font-size: 0.8em; padding: 2px 4px; border: 1px solid var(--border); border-radius: 3px; margin-left: 4px;">';
      selectHtml += '<option value="">-- from backs/ --</option>';
      available.forEach(function(b) {
        const bBase = b.replace(/^backs\//, '');
        const isSel = (c.custom_back === b || c.custom_back === bBase) ? ' selected' : '';
        selectHtml += '<option value="' + encodeURIComponent(b) + '"' + isSel + '>' + bBase + '</option>';
      });
      selectHtml += '</select>';
    }

    let removeBtnHtml = '';
    if (c.is_custom) {
      removeBtnHtml = '<button type="button" class="btn-action-small cb-btn-remove" data-file="' + encodedFile + '" style="background: var(--danger); margin-left: 4px;" title="Restore to generic back">✕</button>';
    }

    tr.innerHTML = '<td style="text-align: center;"><input type="checkbox" class="cb-card-check" data-file="' + encodedFile + '"></td>' +
      '<td style="color: #64748b; font-size: 0.85em;">' + c.index + '</td>' +
      '<td style="font-weight: 600; color: var(--fg);">' + c.name + '</td>' +
      '<td><code style="font-size: 0.8em; background: var(--table-head-bg); padding: 2px 4px; color: var(--fg); border-radius: 3px;">' + c.filename + '</code></td>' +
      '<td>' + backBadgeHtml + '</td>' +
      '<td style="text-align: right; white-space: nowrap;">' +
        '<button type="button" class="btn-action-small cb-btn-upload" data-file="' + encodedFile + '" style="background: var(--accent);">📎 Upload PDF</button>' +
        selectHtml +
        removeBtnHtml +
      '</td>';

    cbTableBody.appendChild(tr);
  });
}

function getSelectedCardFiles() {
  const checks = cbTableBody.querySelectorAll('.cb-card-check:checked');
  const files = [];
  checks.forEach(function(chk) {
    files.push(decodeURIComponent(chk.dataset.file));
  });
  return files;
}

function updateSelectedCount() {
  const sel = getSelectedCardFiles();
  cbSelectedCount.textContent = sel.length;
}

cbTableBody.addEventListener('change', function(e) {
  if (e.target.classList.contains('cb-card-check')) {
    updateSelectedCount();
  } else if (e.target.classList.contains('cb-select-back')) {
    const file = decodeURIComponent(e.target.dataset.file);
    const backVal = decodeURIComponent(e.target.value);
    if (backVal) {
      assignExistingCustomBack([file], backVal);
    }
  }
});

cbTableBody.addEventListener('click', function(e) {
  const btnUpload = e.target.closest('.cb-btn-upload');
  if (btnUpload) {
    const file = decodeURIComponent(btnUpload.dataset.file);
    pendingUploadCardFiles = [file];
    cbSingleUpload.value = '';
    cbSingleUpload.click();
    return;
  }
  const btnRemove = e.target.closest('.cb-btn-remove');
  if (btnRemove) {
    const file = decodeURIComponent(btnRemove.dataset.file);
    removeCustomBack([file]);
    return;
  }
});

cbSelectAll.addEventListener('change', function() {
  const checks = cbTableBody.querySelectorAll('.cb-card-check');
  const checked = this.checked;
  checks.forEach(function(c) { c.checked = checked; });
  updateSelectedCount();
});

cbBulkAssignBtn.addEventListener('click', function() {
  const selected = getSelectedCardFiles();
  if (selected.length === 0) {
    showCbFeedback('Please check the boxes of the cards you want to assign the back to.', true);
    return;
  }
  pendingUploadCardFiles = selected;
  cbBulkUpload.value = '';
  cbBulkUpload.click();
});

cbBulkRemoveBtn.addEventListener('click', function() {
  const selected = getSelectedCardFiles();
  if (selected.length === 0) {
    showCbFeedback('Please select at least one card to remove its custom back.', true);
    return;
  }
  removeCustomBack(selected);
});

cbSingleUpload.addEventListener('change', function() {
  if (this.files && this.files[0] && pendingUploadCardFiles.length > 0) {
    uploadAndAssignCustomBack(pendingUploadCardFiles, this.files[0]);
  }
});

cbBulkUpload.addEventListener('change', function() {
  if (this.files && this.files[0] && pendingUploadCardFiles.length > 0) {
    uploadAndAssignCustomBack(pendingUploadCardFiles, this.files[0]);
  }
});

async function uploadAndAssignCustomBack(files, pdfFile) {
  const exportDir = document.getElementById('export-dir').value.trim();
  if (!exportDir) {
    files.forEach(function(f) {
      localCustomBacks[f] = pdfFile;
    });
    showCbFeedback('Back "' + pdfFile.name + '" assigned to ' + files.length + ' card(s).', false);
    loadCustomBacksData();
    scheduleMainPreview(50, false);
    return;
  }
  const formData = new FormData();
  formData.append('action', 'assign');
  formData.append('export_dir', exportDir);
  formData.append('card_filenames', JSON.stringify(files));
  formData.append('back_pdf', pdfFile);
  showCbFeedback('Uploading and assigning back PDF...', false);
  try {
    const res = await fetch('/deck/custom_backs', { method: 'POST', body: formData });
    const data = await res.json();
    if (data.error) {
      showCbFeedback('Error: ' + data.error, true);
    } else {
      showCbFeedback(data.message || 'Back assigned successfully.', false);
      loadCustomBacksData();
    }
  } catch (err) {
    showCbFeedback('Connection error: ' + err.message, true);
  }
}

async function assignExistingCustomBack(files, backFilename) {
  const exportDir = document.getElementById('export-dir').value.trim();
  const formData = new FormData();
  formData.append('action', 'assign');
  formData.append('export_dir', exportDir);
  formData.append('card_filenames', JSON.stringify(files));
  formData.append('back_filename', backFilename);
  try {
    const res = await fetch('/deck/custom_backs', { method: 'POST', body: formData });
    const data = await res.json();
    if (data.error) {
      showCbFeedback('Error: ' + data.error, true);
    } else {
      showCbFeedback(data.message || 'Back assigned successfully.', false);
      loadCustomBacksData();
    }
  } catch (err) {
    showCbFeedback('Connection error: ' + err.message, true);
  }
}

async function removeCustomBack(files) {
  const exportDir = document.getElementById('export-dir').value.trim();
  if (!exportDir) {
    files.forEach(function(f) {
      delete localCustomBacks[f];
    });
    showCbFeedback('Back restored to generic.', false);
    loadCustomBacksData();
    scheduleMainPreview(50, false);
    return;
  }
  const formData = new FormData();
  formData.append('action', 'remove');
  formData.append('export_dir', exportDir);
  formData.append('card_filenames', JSON.stringify(files));
  try {
    const res = await fetch('/deck/custom_backs', { method: 'POST', body: formData });
    const data = await res.json();
    if (data.error) {
      showCbFeedback('Error: ' + data.error, true);
    } else {
      showCbFeedback(data.message || 'Back restored to generic.', false);
      loadCustomBacksData();
    }
  } catch (err) {
    showCbFeedback('Connection error: ' + err.message, true);
  }
}

cbAutodetectBtn.addEventListener('click', function() {
  const exportDir = document.getElementById('export-dir').value.trim();
  if (!exportDir) {
    showCbFeedback('Specify "Export directory".', true);
    return;
  }
  const formData = new FormData();
  formData.append('action', 'auto_detect');
  formData.append('export_dir', exportDir);
  showCbFeedback('Searching for backs in XML and backs/ folder...', false);
  fetch('/deck/custom_backs', { method: 'POST', body: formData })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.error) {
        showCbFeedback('Error: ' + data.error, true);
      } else {
        showCbFeedback(data.message || ('Auto-detection completed: ' + data.detected_count + ' backs detected.'), false);
        loadCustomBacksData();
      }
    })
    .catch(function(err) {
      showCbFeedback('Auto-detection error: ' + err.message, true);
    });
});

openCustomBacksBtn.addEventListener('click', function() {
  customBacksModal.classList.add('active');
  loadCustomBacksData();
});

cbModalCloseBtn.addEventListener('click', function() {
  customBacksModal.classList.remove('active');
});

cbModalFooterCloseBtn.addEventListener('click', function() {
  customBacksModal.classList.remove('active');
});

customBacksModal.addEventListener('click', function(e) {
  if (e.target === customBacksModal) {
    customBacksModal.classList.remove('active');
  }
});

cbSearchInput.addEventListener('input', renderCustomBacksTable);
cbFilterSelect.addEventListener('change', renderCustomBacksTable);

// Initial check of custom backs badge
checkCustomBacksCount();
})();
