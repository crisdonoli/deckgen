import {
  getActiveRootDir,
  initThemeAndNavbar,
  loadActiveWorkspaceState,
  pickFolder,
  promptCollisionResolution,
  saveActiveWorkspaceState,
  setGlobalLoading,
  showToast,
} from './modules/workspace_client.js?v=23';
import { CropMaskModal, loadImageElement } from './modules/crop_masks.js?v=3';
import {
  DEFAULT_LAYER_ORDER,
  LayerManager,
  applyPopOutOrder,
  buildCardExportSpec,
  applyTemplateLayoutToFace,
  buildLayoutFromProjectFace,
  ensureSymbolsCatalog,
  getSymbolsCatalog,
  normalizeManaCode,
  renderProjectFace,
  resetCardToOriginalFace,
  resolveManaSymbolUrl,
  resolveSetSymbolUrl,
  syncCardWithProjectFace,
  syncProjectFaceFromCard,
} from './modules/layer_manager.js?v=52';

initThemeAndNavbar('card-builder');

let workspaceState = null;
let catalog = {};
let activeCardId = null;
let activeTool = 'select';
let draftShape = null;
let boardViewMode = 'grid';
let boardLargeIndex = 0;
let renderSeq = 0;

const imgCache = new Map();
const transparentLayerCache = new Map();
const manaGlyphCache = new Map();
const keyruneGlyphCache = new Map();

const listsView = document.getElementById('cb-lists-view');
const detailView = document.getElementById('cb-detail-view');
const loadedGrid = document.getElementById('cb-loaded-grid');
const readyList = document.getElementById('cb-ready-list');
const loadedCountEl = document.getElementById('cb-loaded-count');
const readyCountEl = document.getElementById('cb-ready-count');
const filterInput = document.getElementById('cb-filter-input');
const readyFilterSel = document.getElementById('cb-ready-filter');
const READY_FILTER_KEY = 'deckgen-cb-ready-filter';
try {
  const saved = localStorage.getItem(READY_FILTER_KEY);
  if (readyFilterSel && ['all', 'not_ready', 'ready'].includes(saved)) readyFilterSel.value = saved;
} catch {}

// Board cards matching the text filter and the Ready filter (All / Not ready / Ready only).
function visibleBoardCards() {
  const readySet = getReadyIds();
  const q = (filterInput?.value || '').trim().toLowerCase();
  const mode = readyFilterSel?.value || 'all';
  return getCards().filter((c) => {
    if (q && !cardDisplayName(c).toLowerCase().includes(q)) return false;
    if (mode === 'not_ready') return !readySet.has(c.id);
    if (mode === 'ready') return readySet.has(c.id);
    return true;
  });
}
const canvas = document.getElementById('card-canvas');
const ctx = canvas.getContext('2d');

let layerManager = null;
let cropModal = null;

const state = { project: null, faceIndex: 0, faces: {}, dirty: false };

function toSameOriginUrl(src) {
  if (!src) return '';
  if (/^https?:\/\//i.test(src)) {
    return `/api/art/proxy?url=${encodeURIComponent(src)}`;
  }
  return src;
}

function encodeAssetPath(relPath) {
  return '/assets/' + relPath.split('/').map((seg) => encodeURIComponent(seg)).join('/');
}

function ensureCardBuilderState() {
  if (!workspaceState) {
    workspaceState = {
      project_name: 'Temporal',
      root_dir: getActiveRootDir(),
      card_builder: { cards: [], ready_ids: [], global_frame_style: 'M15Regular' },
      deck_generator: {},
    };
  }
  workspaceState.card_builder = workspaceState.card_builder || { cards: [], ready_ids: [] };
  workspaceState.card_builder.cards = workspaceState.card_builder.cards || [];
  workspaceState.card_builder.ready_ids = workspaceState.card_builder.ready_ids || [];
  return workspaceState.card_builder;
}

function getCards() { return ensureCardBuilderState().cards; }
function getReadyIds() { return new Set(ensureCardBuilderState().ready_ids); }
function getActiveCard() { return getCards().find((c) => c.id === activeCardId) || null; }

const historyStacks = new Map();
const MAX_HISTORY = 40;

function cloneCardSnapshot(card) {
  return JSON.parse(JSON.stringify({
    name: card.name,
    original_name: card.original_name || '',
    official_name: card.official_name || '',
    mana_cost: card.mana_cost,
    type_line: card.type_line,
    set: card.set,
    rarity: card.rarity,
    oracle_text: card.oracle_text,
    flavor_text: card.flavor_text,
    power: card.power,
    toughness: card.toughness,
    artist: card.artist,
    bg_color: card.bg_color || '#111111',
    brightness: card.brightness ?? 1.0,
    art_crop_url: card.art_crop_url,
    custom_art_data: card.custom_art_data || null,
    art_over_top: Boolean(card.art_over_top),
    hide_card_text: Boolean(card.hide_card_text),
    crop_mask: card.crop_mask || 'classic_box',
    layer_order: card.layer_order || null,
    hidden_layers: card.hidden_layers || {},
    layer_opacities: card.layer_opacities || {},
    layer_colors: card.layer_colors || {},
    frame_components: card.frame_components || {},
    layout: card.layout || {},
    shapes: card.shapes || [],
  }));
}

// Per-face edits of a project card, persisted in state.json as card.faces_ui[faceIndex]
// (the card's top-level fields only hold the face currently shown, and showing a face rebuilds
// them from the project defaults). Captured on every save and face switch, restored when the
// face is shown again, and used by the export so each face keeps its own design.
function faceEditsSnapshot(card, face) {
  const snap = cloneCardSnapshot(card);
  snap.adventure = card.adventure ? JSON.parse(JSON.stringify(card.adventure)) : null;
  snap.loyalty = card.loyalty ?? null;
  snap.template = face?.template || null;
  snap._official_manually_edited = Boolean(card._official_manually_edited);
  return snap;
}

function applyFaceSnapshot(target, snap, face) {
  if (!target || !snap) return false;
  const { template, ...fields } = JSON.parse(JSON.stringify(snap));
  Object.assign(target, fields);
  if (face && template) face.template = template;
  if (face) syncProjectFaceFromCard(target, face);
  return true;
}

// "Face 1 // Face 2" for double-faced cards (card.face_names, kept in state.json), else the
// card's name. card.name itself is the title drawn on the face currently shown.
function cardDisplayName(card) {
  const names = Array.isArray(card?.face_names) ? card.face_names.filter((n) => String(n || '').trim()) : [];
  if (names.length >= 2) return names.join(' // ');
  return card?.name || 'Untitled';
}

function updateFaceNames(card) {
  const faces = state.project?.faces || [];
  if (!card || faces.length < 2 || (card.project_id || card.id) !== state.project.project_id) return;
  const current = currentProjectFace();
  card.face_names = faces.map((f, pos) => {
    const idx = String(f.face_index ?? pos);
    if (f === current) return card.name || '';
    return card.faces_ui?.[idx]?.name || f.text_layers?.title?.text || card.face_names?.[pos] || '';
  });
}

function captureActiveFaceEdits() {
  const card = getActiveCard();
  const face = currentProjectFace();
  if (!card || !face || !state.project) return;
  if ((card.project_id || card.id) !== state.project.project_id) return;
  card.faces_ui = card.faces_ui || {};
  card.faces_ui[String(face.face_index ?? state.faceIndex ?? 0)] = faceEditsSnapshot(card, face);
  updateFaceNames(card);
}

function getCardHistory(cardId) {
  if (!historyStacks.has(cardId)) historyStacks.set(cardId, { undo: [], redo: [] });
  return historyStacks.get(cardId);
}

function updateUndoRedoButtons() {
  const undoBtn = document.getElementById('cb-undo-btn');
  const redoBtn = document.getElementById('cb-redo-btn');
  const card = getActiveCard();
  if (!card) {
    if (undoBtn) undoBtn.disabled = true;
    if (redoBtn) redoBtn.disabled = true;
    return;
  }
  const h = getCardHistory(card.id);
  if (undoBtn) undoBtn.disabled = h.undo.length === 0;
  if (redoBtn) redoBtn.disabled = h.redo.length === 0;
}

function pushUndoState(card = getActiveCard(), customSnap = null) {
  if (!card) return;
  const h = getCardHistory(card.id);
  const snap = customSnap || cloneCardSnapshot(card);
  if (h.undo.length > 0 && JSON.stringify(h.undo[h.undo.length - 1]) === JSON.stringify(snap)) return;
  h.undo.push(snap);
  if (h.undo.length > MAX_HISTORY) h.undo.shift();
  h.redo = [];
  updateUndoRedoButtons();
}

function performUndo() {
  const card = getActiveCard();
  if (!card) return;
  const h = getCardHistory(card.id);
  if (h.undo.length === 0) return;
  h.redo.push(cloneCardSnapshot(card));
  Object.assign(card, JSON.parse(JSON.stringify(h.undo.pop())));
  populateDetailControls(card);
  updateUndoRedoButtons();
  renderCardCanvas(card);
  updateUndoRedoButtons();
  persistState(true);
}

function performRedo() {
  const card = getActiveCard();
  if (!card) return;
  const h = getCardHistory(card.id);
  if (h.redo.length === 0) return;
  h.undo.push(cloneCardSnapshot(card));
  Object.assign(card, JSON.parse(JSON.stringify(h.redo.pop())));
  populateDetailControls(card);
  renderCardCanvas(card);
  updateUndoRedoButtons();
  persistState(true);
}


let _persistTimer = null;
async function _flushPersist(silent = true) {
  if (!workspaceState?.root_dir) return;
  try {
    await saveActiveWorkspaceState(workspaceState);
    if (!silent) showToast('State saved to state.json');
  } catch {
    if (!silent) showToast('Error saving state.json');
  }
}

async function persistState(silent = true) {
  if (!workspaceState?.root_dir) return;
  captureActiveFaceEdits();
  if (!silent) {
    if (_persistTimer) { clearTimeout(_persistTimer); _persistTimer = null; }
    return _flushPersist(false);
  }
  if (_persistTimer) clearTimeout(_persistTimer);
  _persistTimer = setTimeout(() => {
    _persistTimer = null;
    _flushPersist(true);
  }, 600);
}

function loadCachedImage(src) {
  if (!src) return Promise.resolve(null);
  const resolved = toSameOriginUrl(src);
  if (imgCache.has(resolved)) return Promise.resolve(imgCache.get(resolved));
  return new Promise((resolve) => {
    const im = new Image();
    im.onload = () => {
      if (imgCache.size > 150) {
        const firstKey = imgCache.keys().next().value;
        imgCache.delete(firstKey);
      }
      imgCache.set(resolved, im);
      resolve(im);
    };
    im.onerror = () => resolve(null);
    im.src = resolved;
  });
}

const ART_BOX = { x: 34, y: 109, w: 682, h: 477 };

const DEFAULT_LAYOUT = {
  art: { x: 34, y: 109, w: 682, h: 477, scale: 1.0, offset_x: 0, offset_y: 0 },
  title: { x: 56, y: 90, max_w: 490, font_size: 38, color: '#111111' },
  official_title: { x: 56, y: 114, max_w: 490, font_size: 23, color: '#111111' },
  mana_cost: { x: 692, y: 88, size: 35 },
  type_line: { x: 56, y: 629, max_w: 550, font_size: 31, color: '#111111' },
  set_symbol: { x: 692, y: 620, size: 41 },
  oracle_box: { x: 56, y: 663, w: 638, h: 303, font_size: 30, color: '#111111' },
  pt_text: { x: 648, y: 970, font_size: 38, color: '#111111' },
  artist: { x: 47, y: 1022, font_size: 18, color: '#ffffff' },
  // Adventure spell (card.adventure): left page of the adventure textbox.
  adventure_title: { x: 60, y: 694, max_w: 240, font_size: 28, color: '#111111' },
  adventure_mana_cost: { x: 362, y: 692, size: 26 },
  adventure_type_line: { x: 60, y: 742, max_w: 290, font_size: 25, color: '#ffffff' },
  adventure_oracle_box: { x: 58, y: 764, w: 306, h: 196, font_size: 26, color: '#111111' },
};

const ADVENTURE_KEYS = ['adventure_title', 'adventure_mana_cost', 'adventure_type_line', 'adventure_oracle_box'];
const TEXT_KEYS = ['mana_cost', 'title', 'official_title', 'set_symbol', 'type_line', 'pt_text', 'oracle_box', 'artist', ...ADVENTURE_KEYS];

let selectedElementKey = null;
let hoveredElementKey = null;
let dragState = null;
const HANDLE_SIZE = 10;

function ensureCardLayout(card) {
  if (!card) return DEFAULT_LAYOUT;
  card.layout = card.layout || {};
  for (const [k, def] of Object.entries(DEFAULT_LAYOUT)) {
    card.layout[k] = { ...def, ...(card.layout[k] || {}) };
  }
  return card.layout;
}

// Applies a per-style layout patch to a card.
function applyStyleLayoutPatch(card, data) {
  if (!card || !data) return;
  const L = ensureCardLayout(card);
  for (const [k, fields] of Object.entries(data.layout_patch || {})) {
    L[k] = { ...(L[k] || {}), ...fields };
  }
  const defaultOrder = ['background', 'art', 'pinlines', 'name_box', 'crown', 'border', 'pt_box'];
  const order = (card.layer_order || defaultOrder).filter((k) => k !== 'art');
  const bgIdx = order.indexOf('background');
  if (bgIdx !== -1) {
    order.splice(data.art_below_frame ? bgIdx : bgIdx + 1, 0, 'art');
    card.layer_order = order;
  }
}

function drawSingleShape(targetCtx, s, opOverride = undefined) {
  if (!s) return;
  const op = opOverride !== undefined
    ? Math.max(0, Math.min(1, Number(opOverride)))
    : (s.opacity !== undefined ? Math.max(0, Math.min(1, Number(s.opacity))) : 0.55);
  if (op <= 0.001) return;
  targetCtx.save();
  targetCtx.globalAlpha = op;
  targetCtx.fillStyle = s.color || '#000000';
  if (s.type === 'circle') {
    targetCtx.beginPath();
    targetCtx.ellipse(
      s.x + s.w / 2,
      s.y + s.h / 2,
      Math.max(1, s.w / 2),
      Math.max(1, s.h / 2),
      0,
      0,
      Math.PI * 2
    );
    targetCtx.fill();
  } else if (s.type === 'rounded') {
    const r = Math.min(Math.max(0, Number(s.radius ?? 14)), s.w / 2, s.h / 2);
    targetCtx.beginPath();
    targetCtx.roundRect(s.x, s.y, s.w, s.h, r);
    targetCtx.fill();
  } else {
    targetCtx.fillRect(s.x, s.y, s.w, s.h);
  }
  targetCtx.restore();
}

function drawOverlayShapes(targetCtx, card) {
  if (!Array.isArray(card.shapes) || card.shapes.length === 0) return;
  const orderSet = new Set(Array.isArray(card.layer_order) ? card.layer_order : []);
  const hidden = Array.isArray(card.hidden_layers)
    ? Object.fromEntries(card.hidden_layers.map((k) => [k, true]))
    : (card.hidden_layers || {});
  card.shapes.forEach((s) => {
    const key = `shape:${s.id}`;
    if (orderSet.has(key) || hidden[key]) return;
    drawSingleShape(targetCtx, s);
  });
}

function renderShapesList(card) {
  const shapesListEl = document.getElementById('cb-shapes-list');
  if (!shapesListEl) return;
  shapesListEl.innerHTML = '';
  if (!card) return;
  const shapes = Array.isArray(card.shapes) ? card.shapes : [];
  if (!shapes.length) {
    shapesListEl.innerHTML = '<div style="font-size:11px; color:var(--text-muted);">No boxes added.</div>';
    return;
  }

  const labelMap = { rect: 'Rectangle', rounded: 'Rounded', circle: 'Circle' };
  shapes.forEach((s, idx) => {
    const item = document.createElement('div');
    const key = `shape:${s.id}`;
    item.style.cssText = `padding:6px 8px; border:1px solid ${selectedElementKey === key ? 'var(--accent)' : 'var(--border)'}; border-radius:6px; background:var(--surface); display:flex; flex-direction:column; gap:4px;`;
    const opPct = Math.round((s.opacity ?? 0.55) * 100);
    const radVal = Math.round(s.radius ?? 14);
    item.innerHTML = `
      <div class="row-between" style="cursor:pointer;" data-act="select">
        <span style="font-size:11.5px; font-weight:600;">${labelMap[s.type] || 'Forma'} #${idx + 1}</span>
        <div class="row" style="gap:4px;">
          <input type="color" class="cb-shape-color" value="${s.color || '#000000'}" title="Solid color" style="width:24px; height:20px; border:none; background:none; cursor:pointer;">
          <button type="button" class="btn btn-sm cb-shape-dup" title="Duplicate component" style="padding:2px 6px; font-size:11px;">⧉</button>
          <button type="button" class="btn btn-sm cb-shape-del" title="Delete" style="padding:2px 6px; font-size:11px;">✕</button>
        </div>
      </div>
      <div class="row" style="font-size:10.5px;">
        <span style="min-width:48px; color:var(--text-muted);">Opacity</span>
        <input type="range" class="cb-shape-op" min="0" max="1" step="0.05" value="${s.opacity ?? 0.55}" style="flex:1;">
        <span class="cb-shape-op-val" style="min-width:32px; text-align:right;">${opPct}%</span>
      </div>
      ${s.type === 'rounded' ? `
      <div class="row" style="font-size:10.5px;">
        <span style="min-width:48px; color:var(--text-muted);">Radius</span>
        <input type="range" class="cb-shape-rad" min="0" max="60" step="2" value="${radVal}" style="flex:1;">
        <span class="cb-shape-rad-val" style="min-width:32px; text-align:right;">${radVal}px</span>
      </div>` : ''}
    `;

    item.querySelector('[data-act="select"]').addEventListener('click', (e) => {
      if (e.target.closest('input, button')) return;
      selectedElementKey = key;
      renderShapesList(card);
      renderCardCanvas(card);
    });

    item.querySelector('.cb-shape-color').addEventListener('input', (e) => {
      s.color = e.target.value;
      scheduleRender(card);
      persistState(true);
    });

    const opIn = item.querySelector('.cb-shape-op');
    const opValEl = item.querySelector('.cb-shape-op-val');
    opIn.addEventListener('input', () => {
      s.opacity = Math.max(0, Math.min(1, parseFloat(opIn.value) || 0));
      opValEl.textContent = Math.round(s.opacity * 100) + '%';
      scheduleRender(card);
      persistState(true);
    });

    const radIn = item.querySelector('.cb-shape-rad');
    const radValEl = item.querySelector('.cb-shape-rad-val');
    if (radIn) {
      radIn.addEventListener('input', () => {
        s.radius = Math.max(0, Math.min(60, parseInt(radIn.value, 10) || 0));
        radValEl.textContent = s.radius + 'px';
        renderCardCanvas(card);
        persistState(true);
      });
    }

    item.querySelector('.cb-shape-dup').addEventListener('click', () => {
      pushUndoState(card);
      const clone = JSON.parse(JSON.stringify(s));
      clone.id = 's_' + Date.now() + '_' + (++_shapeSeq);
      clone.x = Math.min(700, (clone.x || 56) + 18);
      clone.y = Math.min(980, (clone.y || 650) + 18);
      card.shapes.push(clone);
      selectedElementKey = `shape:${clone.id}`;
      renderShapesList(card);
      scheduleRender(card);
      persistState(true);
      showToast('Component duplicated');
    });

    item.querySelector('.cb-shape-del').addEventListener('click', () => {
      pushUndoState(card);
      card.shapes.splice(idx, 1);
      if (selectedElementKey === key) selectedElementKey = null;
      renderShapesList(card);
      scheduleRender(card);
      persistState(true);
    });

    shapesListEl.appendChild(item);
  });
}

let _shapeSeq = 0;
function addOverlayShape(type) {
  const card = getActiveCard();
  if (!card) return;
  pushUndoState(card);
  if (!Array.isArray(card.shapes)) card.shapes = [];
  const id = 's_' + Date.now() + '_' + (++_shapeSeq);
  card.shapes.push({
    id,
    type,
    x: 56,
    y: 650,
    w: 638,
    h: 316,
    color: '#000000',
    opacity: 0.55,
    radius: type === 'rounded' ? 16 : 0,
  });
  selectedElementKey = `shape:${id}`;
  renderShapesList(card);
  renderCardCanvas(card);
  persistState(true);
}

function getInteractiveRegions(card) {
  const L = ensureCardLayout(card);
  const regions = [];

  if (!card.hide_card_text) {
  const manaTokens = (card.mana_cost || '').match(/\{[^}]+\}/g) || [];
  const manaCount = Math.max(1, manaTokens.length);
  const manaStep = (L.mana_cost.size || 28) + 5;
  const manaW = manaCount * manaStep;
  const manaH = (L.mana_cost.size || 28) * 1.15;
  regions.push({
    key: 'mana_cost',
    label: 'Mana Cost',
    x: L.mana_cost.x - manaW,
    y: L.mana_cost.y - (L.mana_cost.size || 28) * 0.88,
    w: manaW,
    h: manaH,
    resizable: true,
  });

  regions.push({
    key: 'title',
    label: 'Title',
    x: L.title.x,
    y: L.title.y - (L.title.font_size || 32) * 0.9,
    w: L.title.max_w || 470,
    h: (L.title.font_size || 32) * 1.15,
    resizable: true,
  });

  if ((card.official_name || '').trim()) {
    const ot = L.official_title || DEFAULT_LAYOUT.official_title;
    regions.push({
      key: 'official_title',
      label: 'Original Name',
      x: ot.x,
      y: ot.y - (ot.font_size || 23) * 0.9,
      w: ot.max_w || 490,
      h: (ot.font_size || 23) * 1.15,
      resizable: true,
    });
  }

  const setSize = L.set_symbol.size || 32;
  const setY = L.set_symbol.y ?? 620;
  regions.push({
    key: 'set_symbol',
    label: 'Set Symbol',
    x: L.set_symbol.x - setSize * 1.15,
    y: setY - setSize * 0.75,
    w: setSize * 1.2,
    h: setSize * 1.15,
    resizable: true,
  });

  regions.push({
    key: 'type_line',
    label: 'Type Line',
    x: L.type_line.x,
    y: L.type_line.y - (L.type_line.font_size || 27) * 0.9,
    w: L.type_line.max_w || 520,
    h: (L.type_line.font_size || 27) * 1.15,
    resizable: true,
  });

  if (card.power !== null && card.power !== undefined && String(card.power).trim() !== '') {
    const ptFontSize = L.pt_text.font_size || 34;
    const ptTextW = 90;
    const ptTextH = ptFontSize * 1.2;
    regions.push({
      key: 'pt_text',
      label: 'P/T',
      x: L.pt_text.x - ptTextW / 2,
      y: L.pt_text.y - ptTextH / 2,
      w: ptTextW,
      h: ptTextH,
      resizable: true,
    });
  }

  if (!L.oracle_box.hidden) {
    regions.push({
      key: 'oracle_box',
      label: 'Oracle Text',
      x: L.oracle_box.x,
      y: L.oracle_box.y,
      w: L.oracle_box.w,
      h: L.oracle_box.h,
      resizable: true,
    });
  }

  if (card.adventure) {
    const A = card.adventure;
    const at = L.adventure_title;
    regions.push({
      key: 'adventure_title', label: 'Adventure Title',
      x: at.x, y: at.y - at.font_size * 0.9, w: at.max_w, h: at.font_size * 1.15, resizable: true,
    });
    const advMana = (A.mana_cost || '').match(/\{[^}]+\}/g) || [];
    const am = L.adventure_mana_cost;
    const amW = Math.max(1, advMana.length) * (am.size + 5);
    regions.push({
      key: 'adventure_mana_cost', label: 'Adventure Mana Cost',
      x: am.x - amW, y: am.y - am.size * 0.88, w: amW, h: am.size * 1.15, resizable: true,
    });
    const aty = L.adventure_type_line;
    regions.push({
      key: 'adventure_type_line', label: 'Adventure Type Line',
      x: aty.x, y: aty.y - aty.font_size * 0.9, w: aty.max_w, h: aty.font_size * 1.15, resizable: true,
    });
    if (!L.adventure_oracle_box.hidden) {
      const ao = L.adventure_oracle_box;
      regions.push({ key: 'adventure_oracle_box', label: 'Adventure Text', x: ao.x, y: ao.y, w: ao.w, h: ao.h, resizable: true });
    }
  }

  regions.push({
    key: 'artist',
    label: 'Artist',
    x: L.artist.x,
    y: L.artist.y - (L.artist.font_size || 16) * 0.9,
    w: 260,
    h: (L.artist.font_size || 16) * 1.25,
    resizable: true,
  });
  }

  if (Array.isArray(card.shapes)) {
    card.shapes.forEach((s, i) => {
      regions.push({
        key: `shape:${s.id}`,
        label: `Box #${i + 1}`,
        x: s.x,
        y: s.y,
        w: s.w,
        h: s.h,
        resizable: true,
      });
    });
  }

  regions.push({
    key: 'art',
    label: 'Artwork (Shift+Drag to Pan)',
    x: L.art.x,
    y: L.art.y,
    w: L.art.w,
    h: L.art.h,
    resizable: true,
  });

  return regions;
}

function getHandlesForRegion(r) {
  if (!r || !r.resizable) return [];
  const cx = r.x + r.w / 2;
  const cy = r.y + r.h / 2;
  return [
    { id: 'nw', x: r.x, y: r.y, cursor: 'nwse-resize' },
    { id: 'n', x: cx, y: r.y, cursor: 'ns-resize' },
    { id: 'ne', x: r.x + r.w, y: r.y, cursor: 'nesw-resize' },
    { id: 'e', x: r.x + r.w, y: cy, cursor: 'ew-resize' },
    { id: 'se', x: r.x + r.w, y: r.y + r.h, cursor: 'nwse-resize' },
    { id: 's', x: cx, y: r.y + r.h, cursor: 'ns-resize' },
    { id: 'sw', x: r.x, y: r.y + r.h, cursor: 'nesw-resize' },
    { id: 'w', x: r.x, y: cy, cursor: 'ew-resize' },
  ];
}

function drawInteractiveOverlays(targetCtx, card) {
  const interactiveCheck = document.getElementById('cb-interactive-mode');
  if (!interactiveCheck || !interactiveCheck.checked || !card) return;
  const regions = getInteractiveRegions(card);

  regions.forEach((r) => {
    const isSelected = r.key === selectedElementKey;
    const isHovered = r.key === hoveredElementKey;
    if (!isSelected && !isHovered) return;

    targetCtx.save();
    targetCtx.strokeStyle = isSelected ? '#3b82f6' : 'rgba(59, 130, 246, 0.65)';
    targetCtx.lineWidth = isSelected ? 2.5 : 1.5;
    targetCtx.setLineDash(isSelected ? [] : [6, 4]);
    targetCtx.strokeRect(r.x, r.y, r.w, r.h);

    targetCtx.setLineDash([]);
    targetCtx.font = 'bold 12px sans-serif';
    const tagText = r.label;
    const textW = targetCtx.measureText(tagText).width + 10;
    const tagY = Math.max(4, r.y - 20);
    targetCtx.fillStyle = isSelected ? '#2563eb' : 'rgba(37, 99, 235, 0.85)';
    targetCtx.beginPath();
    targetCtx.roundRect(r.x, tagY, textW, 18, 3);
    targetCtx.fill();
    targetCtx.fillStyle = '#ffffff';
    targetCtx.textAlign = 'left';
    targetCtx.textBaseline = 'middle';
    targetCtx.fillText(tagText, r.x + 5, tagY + 9);

    if (isSelected) {
      getHandlesForRegion(r).forEach((h) => {
        targetCtx.fillStyle = '#ffffff';
        targetCtx.strokeStyle = '#1d4ed8';
        targetCtx.lineWidth = 2;
        targetCtx.fillRect(h.x - HANDLE_SIZE / 2, h.y - HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE);
        targetCtx.strokeRect(h.x - HANDLE_SIZE / 2, h.y - HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE);
      });
    }
    targetCtx.restore();
  });
}



function getIconGlyph(className, cache) {
  if (cache.has(className)) {
    const cached = cache.get(className);
    if (cached && cached.char) return cached;
  }
  const span = document.createElement('i');
  span.className = className;
  span.style.position = 'fixed';
  span.style.left = '-9999px';
  span.style.top = '-9999px';
  document.body.appendChild(span);

  const beforeStyle = window.getComputedStyle(span, '::before');
  const baseStyle = window.getComputedStyle(span);
  const content = beforeStyle.content;
  const fontFamily = beforeStyle.fontFamily && beforeStyle.fontFamily !== 'none'
    ? beforeStyle.fontFamily
    : baseStyle.fontFamily;

  document.body.removeChild(span);

  let char = '';
  if (content && content !== 'none' && content !== 'normal') {
    char = content.replace(/^["']|["']$/g, '');
    if (char.startsWith('\\')) {
      const code = parseInt(char.slice(1), 16);
      if (!Number.isNaN(code)) char = String.fromCodePoint(code);
    }
  }
  const result = { char, fontFamily };
  if (char) cache.set(className, result);
  return result;
}

function symbolToManaClass(sym) {
  const clean = sym.replace(/[{}]/g, '').toLowerCase().replace('/', '');
  if (clean === 't') return 'ms ms-tap';
  if (clean === 'q') return 'ms ms-untap';
  return `ms ms-${clean}`;
}

function getManaCircleColor(sym) {
  const s = sym.replace(/[{}]/g, '').toUpperCase();
  if (s.includes('W')) return '#f8f6d8';
  if (s.includes('U')) return '#c1d7e9';
  if (s.includes('B')) return '#bab1ab';
  if (s.includes('R')) return '#e49977';
  if (s.includes('G')) return '#a3c095';
  return '#cbc2bf';
}

function isLightColor(hex) {
  if (!hex) return false;
  const clean = hex.replace('#', '');
  if (clean.length < 6) return false;
  const r = parseInt(clean.slice(0, 2), 16);
  const g = parseInt(clean.slice(2, 4), 16);
  const b = parseInt(clean.slice(4, 6), 16);
  return (r * 299 + g * 587 + b * 114) / 1000 > 145;
}

function applyTextShadowIfLight(targetCtx, hexColor) {
  if (isLightColor(hexColor)) {
    targetCtx.shadowColor = 'rgba(0, 0, 0, 0.85)';
    targetCtx.shadowBlur = 3;
    targetCtx.shadowOffsetX = 1;
    targetCtx.shadowOffsetY = 1;
  } else {
    targetCtx.shadowColor = 'transparent';
    targetCtx.shadowBlur = 0;
    targetCtx.shadowOffsetX = 0;
    targetCtx.shadowOffsetY = 0;
  }
}

function drawManaCost(targetCtx, manaStr, rightX, baselineY, size) {
  if (!manaStr) return;
  const tokens = manaStr.match(/\{[^}]+\}/g) || [];
  const step = size + 5;
  let curX = rightX - size / 2;

  for (let i = tokens.length - 1; i >= 0; i--) {
    const sym = tokens[i];
    const svgUrl = resolveManaSymbolUrl(sym);
    const cachedImg = svgUrl ? imgCache.get(svgUrl) : null;
    if (svgUrl && !cachedImg) {
      loadCachedImage(svgUrl);
    }
    if (cachedImg) {
      targetCtx.save();
      targetCtx.beginPath();
      targetCtx.arc(curX - 1, baselineY - size * 0.32 + 2, size * 0.48, 0, Math.PI * 2);
      targetCtx.fillStyle = 'rgba(0,0,0,0.55)';
      targetCtx.fill();
      targetCtx.drawImage(cachedImg, curX - size / 2, baselineY - size * 0.82, size, size);
      targetCtx.restore();
      curX -= step;
      continue;
    }

    targetCtx.save();
    targetCtx.beginPath();
    targetCtx.arc(curX, baselineY - size * 0.32, size * 0.54, 0, Math.PI * 2);
    targetCtx.fillStyle = getManaCircleColor(sym);
    targetCtx.shadowColor = 'rgba(0,0,0,0.5)';
    targetCtx.shadowBlur = 3;
    targetCtx.shadowOffsetX = -1;
    targetCtx.shadowOffsetY = 2;
    targetCtx.fill();
    targetCtx.restore();

    targetCtx.save();
    targetCtx.fillStyle = '#111111';
    targetCtx.textAlign = 'center';
    targetCtx.textBaseline = 'middle';
    targetCtx.font = `bold ${Math.round(size * 0.65)}px "BelerenLocal", sans-serif`;
    targetCtx.fillText(sym.replace(/[{}]/g, ''), curX, baselineY - size * 0.3);
    targetCtx.restore();
    curX -= step;
  }
}

function drawSetSymbol(targetCtx, setCode, rarity, rightX, centerY, size) {
  const symUrl = resolveSetSymbolUrl(setCode, rarity);
  const cachedImg = symUrl ? imgCache.get(symUrl) : null;
  if (symUrl && !cachedImg) {
    loadCachedImage(symUrl);
  }
  if (cachedImg) {
    const iw = cachedImg.naturalWidth || cachedImg.width || size;
    const ih = cachedImg.naturalHeight || cachedImg.height || size;
    const scale = Math.min((size * 1.4) / iw, size / ih);
    const dw = Math.round(iw * scale);
    const dh = Math.round(ih * scale);
    targetCtx.drawImage(cachedImg, rightX - dw, centerY - Math.round(dh / 2), dw, dh);
    return;
  }
  const rarityColors = {
    common: '#111111',
    uncommon: '#8da2b0',
    rare: '#d4af37',
    mythic: '#e05a26',
  };
  const r = (rarity || 'common').toLowerCase();
  targetCtx.save();
  targetCtx.fillStyle = rarityColors[r] || '#111111';
  targetCtx.strokeStyle = r === 'common' ? '#ffffff' : '#111111';
  targetCtx.lineWidth = r === 'common' ? 2.5 : 3.5;
  targetCtx.lineJoin = 'round';
  targetCtx.textAlign = 'right';
  targetCtx.textBaseline = 'middle';
  targetCtx.font = `bold ${Math.round(size * 0.6)}px "BelerenLocal", serif`;
  targetCtx.fillText((setCode || 'MTG').toUpperCase(), rightX, centerY);
  targetCtx.restore();
}

function measureOracleBlockHeight(targetCtx, oracleText, flavorText, boxW, fontSize) {
  const lineHeight = Math.round(fontSize * 1.24);
  let totalH = 0;
  targetCtx.font = `${fontSize}px "MPlantinLocal", Georgia, serif`;
  const spaceW = targetCtx.measureText(' ').width;

  const paragraphs = (oracleText || '').split('\n').filter((p) => p.trim().length > 0);
  paragraphs.forEach((para) => {
    const words = para.trim().split(/\s+/);
    let lineW = 0;
    let lines = 1;
    words.forEach((word) => {
      const parts = word.split(/(\{[^}]+\})/g).filter(Boolean);
      let wordW = 0;
      parts.forEach((part) => {
        wordW += (part.startsWith('{') && part.endsWith('}'))
          ? fontSize * 0.9
          : targetCtx.measureText(part).width;
      });
      if (lineW + wordW > boxW && lineW > 0) {
        lines++;
        lineW = wordW + spaceW;
      } else {
        lineW += wordW + spaceW;
      }
    });
    totalH += lines * lineHeight + Math.round(lineHeight * 0.22);
  });

  if (flavorText && flavorText.trim()) {
    totalH += 14;
    targetCtx.font = `italic ${Math.round(fontSize * 0.92)}px "MPlantinLocal", Georgia, serif`;
    const fWords = flavorText.trim().split(/\s+/);
    let fLine = '';
    let fLines = 1;
    fWords.forEach((w) => {
      const test = fLine ? `${fLine} ${w}` : w;
      if (targetCtx.measureText(test).width > boxW) {
        fLines++;
        fLine = w;
      } else {
        fLine = test;
      }
    });
    totalH += fLines * Math.round(lineHeight * 0.92);
  }
  return totalH;
}

function drawRichOracleText(targetCtx, oracleText, flavorText, box) {
  let fontSize = box.font_size || 24;
  const textColor = box.color || '#111111';
  const maxW = box.w;
  const maxH = box.h;

  while (fontSize > 16 && measureOracleBlockHeight(targetCtx, oracleText, flavorText, maxW, fontSize) > maxH - 6) {
    fontSize -= 1;
  }

  const lineHeight = Math.round(fontSize * 1.24);
  const contentHeight = measureOracleBlockHeight(targetCtx, oracleText, flavorText, maxW, fontSize);
  const verticalOffset = Math.max(0, Math.floor((maxH - contentHeight) / 2));
  let curY = box.y + fontSize + verticalOffset;

  targetCtx.save();
  targetCtx.beginPath();
  targetCtx.rect(box.x - 2, box.y - 2, box.w + 4, box.h + 4);
  targetCtx.clip();
  targetCtx.textAlign = 'left';
  targetCtx.textBaseline = 'alphabetic';

  const paragraphs = (oracleText || '').split('\n').filter((p) => p.trim().length > 0);
  paragraphs.forEach((para) => {
    const words = para.trim().split(/\s+/);
    let lineTokens = [];
    let lineWidth = 0;

    function flushLine(tokens, y) {
      let x = box.x;
      tokens.forEach((tk) => {
        if (tk.type === 'mana') {
          const r = fontSize * 0.42;
          const cx = x + r;
          const cy = y - fontSize * 0.32;
          targetCtx.save();
          targetCtx.beginPath();
          targetCtx.arc(cx, cy, r, 0, Math.PI * 2);
          targetCtx.fillStyle = getManaCircleColor(tk.raw);
          targetCtx.fill();
          const g = getIconGlyph(symbolToManaClass(tk.raw), manaGlyphCache);
          targetCtx.fillStyle = '#111111';
          targetCtx.textAlign = 'center';
          targetCtx.textBaseline = 'middle';
          targetCtx.font = `${Math.round(fontSize * 0.64)}px ${g.fontFamily || 'Mana'}`;
          targetCtx.fillText(g.char || tk.raw.replace(/[{}]/g, ''), cx, cy);
          targetCtx.restore();
          x += tk.width;
        } else {
          targetCtx.save();
          targetCtx.font = `${fontSize}px "MPlantinLocal", Georgia, serif`;
          targetCtx.fillStyle = textColor;
          applyTextShadowIfLight(targetCtx, textColor);
          targetCtx.textAlign = 'left';
          targetCtx.textBaseline = 'alphabetic';
          targetCtx.fillText(tk.text, x, y);
          targetCtx.restore();
          x += tk.width;
        }
      });
    }

    targetCtx.font = `${fontSize}px "MPlantinLocal", Georgia, serif`;
    const spaceW = targetCtx.measureText(' ').width;

    words.forEach((word) => {
      const parts = word.split(/(\{[^}]+\})/g).filter(Boolean);
      const wordTokens = [];
      let wordW = 0;
      parts.forEach((part) => {
        if (part.startsWith('{') && part.endsWith('}')) {
          const w = fontSize * 0.9;
          wordTokens.push({ type: 'mana', raw: part, width: w });
          wordW += w;
        } else {
          targetCtx.font = `${fontSize}px "MPlantinLocal", Georgia, serif`;
          const w = targetCtx.measureText(part).width;
          wordTokens.push({ type: 'text', text: part, width: w });
          wordW += w;
        }
      });

      if (lineWidth + wordW > maxW && lineTokens.length > 0) {
        flushLine(lineTokens, curY);
        curY += lineHeight;
        lineTokens = [...wordTokens, { type: 'text', text: ' ', width: spaceW }];
        lineWidth = wordW + spaceW;
      } else {
        lineTokens.push(...wordTokens, { type: 'text', text: ' ', width: spaceW });
        lineWidth += wordW + spaceW;
      }
    });

    if (lineTokens.length > 0) {
      flushLine(lineTokens, curY);
      curY += Math.round(lineHeight * 1.22);
    }
  });

  if (flavorText && flavorText.trim()) {
    curY += 4;
    targetCtx.strokeStyle = isLightColor(textColor) ? 'rgba(255,255,255,0.28)' : 'rgba(0,0,0,0.22)';
    targetCtx.lineWidth = 1;
    targetCtx.beginPath();
    targetCtx.moveTo(box.x + 30, curY - fontSize * 0.68);
    targetCtx.lineTo(box.x + maxW - 30, curY - fontSize * 0.68);
    targetCtx.stroke();
    curY += 10;

    targetCtx.font = `italic ${Math.round(fontSize * 0.92)}px "MPlantinLocal", Georgia, serif`;
    targetCtx.fillStyle = textColor;
    applyTextShadowIfLight(targetCtx, textColor);
    targetCtx.textAlign = 'left';
    targetCtx.textBaseline = 'alphabetic';
    const fWords = flavorText.trim().split(/\s+/);
    let fLine = '';
    fWords.forEach((w) => {
      const test = fLine ? `${fLine} ${w}` : w;
      if (targetCtx.measureText(test).width > maxW) {
        targetCtx.fillText(fLine, box.x, curY);
        curY += Math.round(lineHeight * 0.92);
        fLine = w;
      } else {
        fLine = test;
      }
    });
    if (fLine) targetCtx.fillText(fLine, box.x, curY);
  }
  targetCtx.restore();
}

async function loadTransparentLayer(relPath, layerKey = '') {
  if (!relPath) return null;
  const cacheKey = `${layerKey}::${relPath}`;
  if (transparentLayerCache.has(cacheKey)) return transparentLayerCache.get(cacheKey);

  const img = await loadCachedImage(encodeAssetPath(relPath));
  if (!img) return null;

  const off = document.createElement('canvas');
  off.width = 750;
  off.height = 1050;
  const octx = off.getContext('2d', { willReadFrequently: true });

  const w = img.naturalWidth || img.width;
  const h = img.naturalHeight || img.height;
  const ratio = h ? w / h : 0;
  if (w < h && ratio >= 0.724 && ratio <= 0.742) {
    const bx = Math.round(w * (144.0 / 3288.0));
    const by = Math.round(h * (144.0 / 4488.0));
    octx.drawImage(img, bx, by, w - bx * 2, h - by * 2, 0, 0, 750, 1050);
  } else {
    octx.drawImage(img, 0, 0, 750, 1050);
  }

  try {
    const imgData = octx.getImageData(0, 0, 750, 1050);
    const d = imgData.data;
    const cIndices = [0, (750 - 1) * 4, (1050 - 1) * 750 * 4, (1050 * 750 - 1) * 4];
    let rSum = 0, gSum = 0, bSum = 0;
    cIndices.forEach((idx) => { rSum += d[idx]; gSum += d[idx + 1]; bSum += d[idx + 2]; });
    const br = rSum / 4, bg = gSum / 4, bb = bSum / 4;
    const isWhiteBg = br > 235 && bg > 235 && bb > 235;
    const isBlackBg = br < 20 && bg < 20 && bb < 20;

    if (isWhiteBg || isBlackBg) {
      const tol = 28;
      for (let i = 0; i < d.length; i += 4) {
        const diff = Math.max(Math.abs(d[i] - br), Math.abs(d[i + 1] - bg), Math.abs(d[i + 2] - bb));
        if (diff < tol) {
          d[i + 3] = 0;
        } else if (diff < tol + 24) {
          d[i + 3] = Math.min(d[i + 3], Math.round(((diff - tol) / 24) * 255));
        }
      }
    }

    // Border JPGs have no alpha channel: their entire card interior (title/art/type/oracle)
    // is solid black (#000000) while the outer frame may be white, silver, or black.
    // Key out pure-black across the whole layer when the interior is black so Border never
    // covers Name Box, Type Line, or Oracle Text.
    if (layerKey === 'border') {
      const borderInteriorPts = [
        [375, 340], [375, 780], [200, 780], [550, 780],
      ];
      const hasBlackInterior = borderInteriorPts.every(([sx, sy]) => {
        const idx = (sy * 750 + sx) * 4;
        return d[idx] < 22 && d[idx + 1] < 22 && d[idx + 2] < 22 && d[idx + 3] > 200;
      });
      if (hasBlackInterior) {
        for (let i = 0; i < d.length; i += 4) {
          const mx = Math.max(d[i], d[i + 1], d[i + 2]);
          if (mx < 22) {
            d[i + 3] = 0;
          } else if (mx < 44) {
            d[i + 3] = Math.min(d[i + 3], Math.round(((mx - 22) / 22) * 255));
          }
        }
      }
    } else if (layerKey && layerKey !== 'background' && layerKey !== 'pt_box') {
      const samplePts = [
        [375, 340], [180, 220], [560, 220], [180, 460], [560, 460],
      ];
      const allBlackInterior = samplePts.every(([sx, sy]) => {
        const idx = (sy * 750 + sx) * 4;
        return d[idx] < 22 && d[idx + 1] < 22 && d[idx + 2] < 22 && d[idx + 3] > 200;
      });
      if (allBlackInterior) {
        const x0 = ART_BOX.x, x1 = ART_BOX.x + ART_BOX.w;
        const y0 = ART_BOX.y, y1 = ART_BOX.y + ART_BOX.h;
        for (let py = y0; py < y1; py++) {
          for (let px = x0; px < x1; px++) {
            const idx = (py * 750 + px) * 4;
            const mx = Math.max(d[idx], d[idx + 1], d[idx + 2]);
            if (mx < 22) {
              d[idx + 3] = 0;
            } else if (mx < 44) {
              d[idx + 3] = Math.min(d[idx + 3], Math.round(((mx - 22) / 22) * 255));
            }
          }
        }
      }
    }

    octx.putImageData(imgData, 0, 0);
  } catch (e) {
    console.warn('Chroma-key skipped:', e);
  }

  if (transparentLayerCache.size > 80) {
    const firstKey = transparentLayerCache.keys().next().value;
    transparentLayerCache.delete(firstKey);
  }
  transparentLayerCache.set(cacheKey, off);
  return off;
}

let _rafId = 0;
let _pendingCard = null;
const _offCanvas = document.createElement('canvas');
_offCanvas.width = 750;
_offCanvas.height = 1050;
const _offCtx = _offCanvas.getContext('2d');

const _baseCanvas = document.createElement('canvas');
_baseCanvas.width = 750;
_baseCanvas.height = 1050;
const _baseCtx = _baseCanvas.getContext('2d');
let _baseCacheKey = '';

function scheduleRender(card) {
  if (!card) return;
  _pendingCard = card;
  if (_rafId) return;
  _rafId = requestAnimationFrame(() => {
    _rafId = 0;
    const target = _pendingCard;
    _pendingCard = null;
    if (target) renderCardCanvas(target);
  });
}

function computeBaseLayerKey(card) {
  const lay = card.layout?.art || {};
  return JSON.stringify([
    card.id,
    card.bg_color || '#111111',
    Boolean(card.art_over_top),
    card.brightness ?? 1.0,
    card.custom_art_data ? card.custom_art_data.length : 0,
    card.art_crop_url || '',
    lay.x, lay.y, lay.w, lay.h, lay.scale, lay.offset_x, lay.offset_y,
    card.layer_order || null,
    card.hidden_layers || null,
    card.layer_opacities || null,
    card.layer_colors || null,
    card.frame_components || null,
    card.shapes || null,
  ]);
}

function drawCardForeground(octx, card) {
  drawOverlayShapes(octx, card);
  if (card.hide_card_text) return;

  // Dynamic title width so title never overlaps mana cost symbols
  const manaTokens = (card.mana_cost || '').match(/\{[^}]+\}/g) || [];
  const manaSize = card.layout?.mana_cost?.size || 35;
  const manaRightX = card.layout?.mana_cost?.x || 692;
  const titleX = card.layout?.title?.x || 56;
  const titleMaxW = Math.max(160, manaRightX - manaTokens.length * (manaSize + 5) - titleX - 12);

  const titleColor = card.layout?.title?.color || '#111111';
  octx.save();
  octx.fillStyle = titleColor;
  applyTextShadowIfLight(octx, titleColor);
  octx.font = `bold ${card.layout?.title?.font_size || 38}px "BelerenLocal", Georgia, serif`;
  octx.fillText(card.name || '', titleX, card.layout?.title?.y || 88, titleMaxW);
  octx.restore();

  const officialTitle = (card.official_name || '').trim();
  if (officialTitle) {
    const ot = card.layout?.official_title || DEFAULT_LAYOUT.official_title;
    const otColor = ot.color || '#111111';
    octx.save();
    octx.fillStyle = otColor;
    applyTextShadowIfLight(octx, otColor);
    octx.font = `italic ${ot.font_size || 23}px "BelerenLocal", "MPlantinLocal", Georgia, serif`;
    octx.textAlign = 'left';
    octx.textBaseline = 'alphabetic';
    octx.fillText(`(${officialTitle})`, ot.x ?? 56, ot.y ?? 114, ot.max_w || 490);
    octx.restore();
  }

  if (card.mana_cost) {
    drawManaCost(octx, card.mana_cost, manaRightX, card.layout?.mana_cost?.y || 88, manaSize);
  }

  const typeColor = card.layout?.type_line?.color || '#111111';
  const setSize = card.layout?.set_symbol?.size || 41;
  const setRightX = card.layout?.set_symbol?.x || 692;
  const typeX = card.layout?.type_line?.x || 56;
  const typeMaxW = Math.max(180, setRightX - setSize - typeX - 12);
  octx.save();
  octx.fillStyle = typeColor;
  applyTextShadowIfLight(octx, typeColor);
  octx.font = `bold ${card.layout?.type_line?.font_size || 31}px "BelerenLocal", Georgia, serif`;
  octx.fillText(card.type_line || '', typeX, card.layout?.type_line?.y || 626, typeMaxW);
  octx.restore();

  drawSetSymbol(octx, card.set, card.rarity, setRightX, card.layout?.set_symbol?.y || 620, setSize);

  if (!card.layout?.oracle_box?.hidden) drawRichOracleText(octx, card.oracle_text || '', card.flavor_text || '', {
    x: card.layout?.oracle_box?.x || 56,
    y: card.layout?.oracle_box?.y || 663,
    w: card.layout?.oracle_box?.w || 638,
    h: card.layout?.oracle_box?.h || 303,
    font_size: card.layout?.oracle_box?.font_size || 30,
    color: card.layout?.oracle_box?.color || '#111111',
  });

  if (card.adventure) drawAdventureText(octx, card);

  if (card.power !== null && card.power !== undefined && String(card.power) !== '') {
    const ptColor = card.layout?.pt_text?.color || '#111111';
    octx.save();
    octx.fillStyle = ptColor;
    applyTextShadowIfLight(octx, ptColor);
    octx.font = `bold ${card.layout?.pt_text?.font_size || 38}px "BelerenLocal", serif`;
    octx.textAlign = 'center';
    octx.textBaseline = 'middle';
    octx.fillText(`${card.power}/${card.toughness ?? ''}`, card.layout?.pt_text?.x || 648, card.layout?.pt_text?.y || 970);
    octx.restore();
  }

  if (card.artist) {
    const aLay = card.layout?.artist || DEFAULT_LAYOUT.artist;
    octx.save();
    octx.fillStyle = aLay.color || '#ffffff';
    octx.font = `600 ${aLay.font_size || 16}px sans-serif`;
    octx.fillText(`🖌 ${card.artist}`, aLay.x ?? 48, aLay.y ?? 1022);
    octx.restore();
  }

}

// Adventure spell on the left page of the adventure textbox (card.adventure, see
// extract_scryfall_card_payload): title + mana cost, type line, rules text.
function drawAdventureText(octx, card) {
  const A = card.adventure;
  const L = ensureCardLayout(card);
  const drawLine = (lay, text) => {
    const color = lay.color || '#111111';
    octx.save();
    octx.fillStyle = color;
    applyTextShadowIfLight(octx, color);
    octx.font = `bold ${lay.font_size}px "BelerenLocal", Georgia, serif`;
    octx.textAlign = 'left';
    octx.textBaseline = 'alphabetic';
    octx.fillText(text || '', lay.x, lay.y, lay.max_w);
    octx.restore();
  };
  const manaTokens = (A.mana_cost || '').match(/\{[^}]+\}/g) || [];
  const am = L.adventure_mana_cost;
  // keep the title clear of the mana symbols
  const titleLay = { ...L.adventure_title };
  titleLay.max_w = Math.max(80, Math.min(titleLay.max_w, am.x - manaTokens.length * (am.size + 5) - titleLay.x - 8));
  drawLine(titleLay, A.name);
  if (A.mana_cost) drawManaCost(octx, A.mana_cost, am.x, am.y, am.size);
  drawLine(L.adventure_type_line, A.type_line);
  const ao = L.adventure_oracle_box;
  if (!ao.hidden) drawRichOracleText(octx, A.oracle_text || '', A.flavor_text || '', ao);
}

function renderTextOverlayDataUrl(card, requestedScale = 4) {
  let scale = Math.max(1.5, Math.min(4.0, Number(requestedScale) || 4));
  while (scale >= 1.5) {
    const off = document.createElement('canvas');
    try {
      off.width = Math.round(750 * scale);
      off.height = Math.round(1050 * scale);
      const octx = off.getContext('2d');
      if (!octx) throw new Error('Canvas 2D unavailable');
      octx.scale(scale, scale);
      drawCardForeground(octx, card);
      const url = off.toDataURL('image/png');
      off.width = 0;
      off.height = 0;
      return url;
    } catch {
      off.width = 0;
      off.height = 0;
      scale -= 1.0;
    }
  }
  return '';
}

const _projectCleanCanvas = document.createElement('canvas');
_projectCleanCanvas.width = 1500;
_projectCleanCanvas.height = 2100;
let _projectCleanReady = false;

function paintProjectWithOverlays(projectCanvas, card) {
  if (!projectCanvas) return;
  const pCtx = projectCanvas.getContext('2d');
  if (_projectCleanReady) {
    pCtx.clearRect(0, 0, projectCanvas.width, projectCanvas.height);
    pCtx.drawImage(_projectCleanCanvas, 0, 0, projectCanvas.width, projectCanvas.height);
  }
  pCtx.save();
  pCtx.scale(projectCanvas.width / 750, projectCanvas.height / 1050);
  if (draftShape) {
    drawSingleShape(pCtx, draftShape);
    pCtx.save();
    pCtx.strokeStyle = '#38bdf8';
    pCtx.lineWidth = 2;
    pCtx.setLineDash([6, 4]);
    pCtx.strokeRect(draftShape.x, draftShape.y, draftShape.w, draftShape.h);
    pCtx.restore();
  }
  drawInteractiveOverlays(pCtx, card);
  pCtx.restore();
}

async function renderCardCanvas(card) {
  if (!card) return;
  const legacyWrap = document.getElementById('cb-legacy-wrap');
  const projectWrap = document.getElementById('cb-project-wrap');
  const projectCanvas = document.getElementById('cb-project-canvas');
  if (state.project && currentProjectFace() && projectCanvas) {
    const seq = ++renderSeq;
    const face = currentProjectFace();
    syncProjectFaceFromCard(card, face);
    if (legacyWrap) legacyWrap.style.display = 'none';
    if (projectWrap) projectWrap.style.display = 'flex';
    await renderProjectFace(face, _projectCleanCanvas, {
      card,
      set_symbol: state.project?.set_symbol,
    });
    if (seq !== renderSeq) return;
    projectCanvas.width = _projectCleanCanvas.width;
    projectCanvas.height = _projectCleanCanvas.height;
    projectCanvas.style.maxWidth = '100%';
    projectCanvas.style.height = 'auto';
    _projectCleanReady = true;
    paintProjectWithOverlays(projectCanvas, card);
    return;
  }
  if (projectWrap) projectWrap.style.display = 'none';
  if (legacyWrap) legacyWrap.style.display = 'flex';
  const seq = ++renderSeq;
  const W = 750;
  const H = 1050;

  const baseKey = computeBaseLayerKey(card);
  if (baseKey !== _baseCacheKey) {
    const hidden = Array.isArray(card.hidden_layers)
      ? Object.fromEntries(card.hidden_layers.map((k) => [k, true]))
      : (card.hidden_layers || {});

    // True card background (outer border + bottom collector/artist strip)
    _baseCtx.fillStyle = (/^#[0-9a-fA-F]{6}$/.test((card.bg_color || '').trim()) ? card.bg_color.trim() : '#111111');
    _baseCtx.fillRect(0, 0, W, H);

    const order = Array.isArray(card.layer_order) && card.layer_order.length
      ? card.layer_order
      : ['background', 'art', 'pinlines', 'name_box', 'crown', 'border', 'pt_box'];
    const opacities = card.layer_opacities || {};
    const fc = card.frame_components || {};

    const _tintCanvas = document.createElement('canvas');
    _tintCanvas.width = W;
    _tintCanvas.height = H;
    const _tintCtx = _tintCanvas.getContext('2d');

    const getLayerColorOverride = (key) => {
      const explicit = card.layer_colors && card.layer_colors[key];
      if (explicit && /^#[0-9a-fA-F]{6}$/.test(explicit.trim())) return explicit.trim();
      return '';
    };

    const drawFrameComp = async (key, clipYRange = null) => {
      if (seq !== renderSeq || hidden[key]) return;
      const op = opacities[key] ?? 1.0;
      if (op <= 0.01 || !fc[key]) return;
      const overrideColor = getLayerColorOverride(key);

      let drawSrc = null;
      if (overrideColor) {
        if (key === 'background') {
          // Fill the exact rounded Frame silhouette (preserving the black card border & bottom collector band)
          _baseCtx.save();
          if (clipYRange) {
            _baseCtx.beginPath();
            _baseCtx.rect(0, clipYRange[0], W, clipYRange[1] - clipYRange[0]);
            _baseCtx.clip();
          }
          _baseCtx.globalAlpha = op;
          _baseCtx.fillStyle = overrideColor;
          _baseCtx.beginPath();
          _baseCtx.roundRect(27, 28, 696, 946, 26);
          _baseCtx.fill();
          _baseCtx.restore();
          return;
        }
        // Tint solid color onto the exact alpha silhouette of the frame component
        const maskCanvas = await loadTransparentLayer(fc[key], key);
        if (seq !== renderSeq || !maskCanvas) return;
        _tintCtx.clearRect(0, 0, W, H);
        _tintCtx.globalCompositeOperation = 'source-over';
        _tintCtx.drawImage(maskCanvas, 0, 0, W, H);
        _tintCtx.globalCompositeOperation = 'source-atop';
        _tintCtx.fillStyle = overrideColor;
        _tintCtx.fillRect(0, 0, W, H);
        _tintCtx.globalCompositeOperation = 'source-over';
        drawSrc = _tintCanvas;
      } else if (key === 'background' && order.indexOf('art') < order.indexOf('background')) {
        drawSrc = await loadTransparentLayer(fc[key], key);
        if (seq !== renderSeq || !drawSrc) return;
      } else if (key === 'background') {
        const bgImg = await loadCachedImage(encodeAssetPath(fc[key]));
        if (seq !== renderSeq || !bgImg) return;
        _baseCtx.save();
        if (clipYRange) {
          _baseCtx.beginPath();
          _baseCtx.rect(0, clipYRange[0], W, clipYRange[1] - clipYRange[0]);
          _baseCtx.clip();
        }
        // Clip textured Frame JPG to the exact rounded Frame silhouette so the true Background color remains visible
        _baseCtx.beginPath();
        _baseCtx.roundRect(27, 28, 696, 946, 26);
        _baseCtx.clip();
        _baseCtx.globalAlpha = op;
        const w = bgImg.naturalWidth || bgImg.width;
        const h = bgImg.naturalHeight || bgImg.height;
        const ratio = h ? w / h : 0;
        if (w < h && ratio >= 0.724 && ratio <= 0.742) {
          const bx = Math.round(w * (144.0 / 3288.0));
          const by = Math.round(h * (144.0 / 4488.0));
          _baseCtx.drawImage(bgImg, bx, by, w - bx * 2, h - by * 2, 0, 0, W, H);
        } else {
          _baseCtx.drawImage(bgImg, 0, 0, W, H);
        }
        _baseCtx.restore();
        return;
      } else {
        const layerCanvas = await loadTransparentLayer(fc[key], key);
        if (seq !== renderSeq || !layerCanvas) return;
        drawSrc = layerCanvas;
      }

      if (!drawSrc) return;
      _baseCtx.save();
      if (clipYRange) {
        _baseCtx.beginPath();
        _baseCtx.rect(0, clipYRange[0], W, clipYRange[1] - clipYRange[0]);
        _baseCtx.clip();
      }
      _baseCtx.globalAlpha = op;
      _baseCtx.drawImage(drawSrc, 0, 0, W, H);
      _baseCtx.restore();
    };

    const drawArtComp = async (popOutTop = false) => {
      if (seq !== renderSeq || hidden.art) return;
      const op = opacities.art ?? 1.0;
      if (op <= 0.01) return;
      const artSrc = card.custom_art_data || card.art_crop_url;
      const artImg = await loadCachedImage(artSrc);
      if (seq !== renderSeq || !artImg) return;
      const lay = card.layout?.art || { x: 34, y: 109, w: 682, h: 477, scale: 1.0, offset_x: 0, offset_y: 0 };
      const bright = card.brightness ?? 1.0;
      _baseCtx.save();
      _baseCtx.globalAlpha = op;
      if (Math.abs(bright - 1.0) > 0.01) _baseCtx.filter = `brightness(${bright})`;
      _baseCtx.beginPath();
      _baseCtx.rect(lay.x, lay.y, lay.w, lay.h);
      _baseCtx.clip();
      const baseScale = Math.max(lay.w / artImg.width, lay.h / artImg.height) * (lay.scale || 1.0);
      const dw = artImg.width * baseScale;
      const dh = artImg.height * baseScale;
      _baseCtx.drawImage(
        artImg,
        lay.x + (lay.w - dw) / 2 + (lay.offset_x || 0),
        lay.y + (lay.h - dh) / 2 + (lay.offset_y || 0),
        dw,
        dh
      );
      _baseCtx.filter = 'none';
      _baseCtx.restore();
    };

    const drawShapeComp = (key) => {
      if (seq !== renderSeq || hidden[key]) return;
      const sid = key.slice(6);
      const shape = (card.shapes || []).find((s) => s.id === sid);
      if (!shape) return;
      const op = opacities[key] ?? shape.opacity ?? 0.55;
      drawSingleShape(_baseCtx, shape, op);
    };

    const splitY = 584;
    const rawOrder = Array.isArray(order) ? [...order] : [...DEFAULT_LAYER_ORDER];
    if (!rawOrder.includes('textbox')) {
      const cIdx = rawOrder.indexOf('crown');
      const bIdx = rawOrder.indexOf('background');
      const ins = Math.max(cIdx, bIdx);
      rawOrder.splice(ins >= 0 ? ins + 1 : rawOrder.length, 0, 'textbox');
    }
    const artIdx = rawOrder.indexOf('art');
    const bgIdx = rawOrder.indexOf('background');
    const crownIdx = rawOrder.indexOf('crown');
    const popOutByOrder = artIdx >= 0 && ((bgIdx >= 0 && artIdx > bgIdx) || (crownIdx >= 0 && artIdx > crownIdx));
    for (const key of rawOrder) {
      if (key === 'art') await drawArtComp(popOutByOrder);
      else if (key.startsWith('shape:')) drawShapeComp(key);
      else if (key === 'background') await drawFrameComp('background', [0, splitY]);
      else if (key === 'textbox') {
        const tbKey = fc.textbox ? 'textbox' : 'background';
        await drawFrameComp(tbKey, [splitY, H]);
      } else await drawFrameComp(key);
    }
    if (seq !== renderSeq) return;
    _baseCacheKey = baseKey;
  }

  _offCtx.clearRect(0, 0, W, H);
  _offCtx.drawImage(_baseCanvas, 0, 0);
  const octx = _offCtx;
  if (seq !== renderSeq) return;

  drawCardForeground(octx, card);

  ctx.clearRect(0, 0, W, H);
  ctx.drawImage(_offCanvas, 0, 0);
  if (draftShape) {
    drawSingleShape(ctx, draftShape);
    ctx.save();
    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 4]);
    ctx.strokeRect(draftShape.x, draftShape.y, draftShape.w, draftShape.h);
    ctx.restore();
  }
  drawInteractiveOverlays(ctx, card);
}

function renderLists() {
  const cards = getCards();
  const readySet = getReadyIds();
  const filtered = visibleBoardCards();
  loadedCountEl.textContent = filtered.length === cards.length ? String(cards.length) : `${filtered.length} / ${cards.length}`;
  loadedGrid.className = 'cb-card-grid' + (boardViewMode === 'list' ? ' view-list' : (boardViewMode === 'large' ? ' view-large' : ''));
  loadedGrid.innerHTML = '';

  if (filtered.length === 0) {
    const emptyMsg = cards.length
      ? ((readyFilterSel?.value || 'all') === 'not_ready' ? 'All cards are marked Ready.' : 'No cards match the current filter.')
      : 'No cards loaded. Search or import a .txt / .png to get started.';
    loadedGrid.innerHTML = `<p style="color:var(--text-muted); grid-column:1/-1;">${emptyMsg}</p>`;
  } else if (boardViewMode === 'list') {
    filtered.forEach((card) => {
      const isReady = readySet.has(card.id);
      const row = document.createElement('div');
      row.className = 'cb-list-row';
      const thumbSrc = toSameOriginUrl(card.custom_art_data || card.art_crop_url || '');
      row.innerHTML = `
        <img class="cb-list-thumb" src="${thumbSrc}" alt="${card.name || ''}">
        <div style="flex:1; min-width:0;">
          <div style="font-weight:600; font-size:12.5px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${dfcBadgeHtml(card)}${cardDisplayName(card)}</div>
          <div style="font-size:10.5px; color:var(--text-muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${card.type_line || ''}</div>
        </div>
        <span style="font-size:11px; color:var(--text-muted);">×${card.count || 1}</span>
        <label class="row" style="gap:4px; cursor:pointer; font-size:11px;" data-stop="1">
          <input type="checkbox" class="cb-ready-cb" ${isReady ? 'checked' : ''}>
          <span>Ready</span>
        </label>
        <button type="button" class="btn btn-sm cb-list-del" title="Remove card from board" style="padding:2px 6px;">✕</button>
      `;
      row.querySelector('.cb-ready-cb').addEventListener('change', (e) => {
        e.stopPropagation();
        toggleReady(card.id, e.target.checked);
      });
      row.querySelector('[data-stop="1"]').addEventListener('click', (e) => e.stopPropagation());
      row.querySelector('.cb-list-del').addEventListener('click', (e) => {
        e.stopPropagation();
        removeCardFromBoard(card.id);
      });
      row.addEventListener('click', () => openDetail(card.id));
      loadedGrid.appendChild(row);
    });
  } else if (boardViewMode === 'large') {
    boardLargeIndex = Math.max(0, Math.min(filtered.length - 1, boardLargeIndex));
    const card = filtered[boardLargeIndex];
    const isReady = readySet.has(card.id);
    const thumbSrc = toSameOriginUrl(card.custom_art_data || card.art_crop_url || '');

    const stage = document.createElement('div');
    stage.className = 'cb-large-stage';
    stage.innerHTML = `
      <button type="button" class="btn cb-large-prev" title="Previous card" ${filtered.length <= 1 ? 'disabled' : ''}>◀ Prev</button>
      <div class="cb-large-card">
        <img class="cb-large-thumb" src="${thumbSrc}" alt="${card.name || ''}" title="Click to edit card">
        <div class="row-between" style="gap:8px;">
          <div style="min-width:0;">
            <div style="font-weight:700; font-size:14px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${dfcBadgeHtml(card)}${cardDisplayName(card)}</div>
            <div style="font-size:11px; color:var(--text-muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${card.type_line || ''} · ×${card.count || 1}</div>
          </div>
          <label class="row" style="gap:4px; cursor:pointer; font-size:12px; flex-shrink:0;">
            <input type="checkbox" class="cb-ready-cb" ${isReady ? 'checked' : ''}>
            <span>Ready</span>
          </label>
        </div>
        <div class="row-between" style="gap:6px; margin-top:2px;">
          <span style="font-size:11px; color:var(--text-muted);">${boardLargeIndex + 1} / ${filtered.length}</span>
          <div class="row" style="gap:6px;">
            <button type="button" class="btn btn-sm btn-primary cb-large-edit">✎ Edit Card</button>
            <button type="button" class="btn btn-sm cb-large-del" title="Remove card from board">🗑</button>
          </div>
        </div>
      </div>
      <button type="button" class="btn cb-large-next" title="Next card" ${filtered.length <= 1 ? 'disabled' : ''}>Next ▶</button>
    `;
    stage.querySelector('.cb-large-prev').addEventListener('click', () => {
      boardLargeIndex = (boardLargeIndex - 1 + filtered.length) % filtered.length;
      renderLists();
    });
    stage.querySelector('.cb-large-next').addEventListener('click', () => {
      boardLargeIndex = (boardLargeIndex + 1) % filtered.length;
      renderLists();
    });
    stage.querySelector('.cb-large-thumb').addEventListener('click', () => openDetail(card.id));
    stage.querySelector('.cb-large-edit').addEventListener('click', () => openDetail(card.id));
    stage.querySelector('.cb-ready-cb').addEventListener('change', (e) => toggleReady(card.id, e.target.checked));
    stage.querySelector('.cb-large-del').addEventListener('click', () => removeCardFromBoard(card.id));
    loadedGrid.appendChild(stage);
  } else {
    filtered.forEach((card) => {
      const isReady = readySet.has(card.id);
      const item = document.createElement('div');
      item.className = 'cb-grid-item';
      const thumbSrc = toSameOriginUrl(card.custom_art_data || card.art_crop_url || '');
      item.innerHTML = `
        <button type="button" class="cb-grid-del-btn" title="Remove card from board" aria-label="Remove card">✕</button>
        <img class="cb-grid-thumb" src="${thumbSrc}" alt="${card.name || ''}">
        <div style="font-weight:600; font-size:12.5px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${dfcBadgeHtml(card)}${cardDisplayName(card)}</div>
        <div class="row-between" style="font-size:11px; color:var(--text-muted);">
          <span>×${card.count || 1}</span>
          <label class="row" style="gap:4px; cursor:pointer;" data-stop="1">
            <input type="checkbox" class="cb-ready-cb" ${isReady ? 'checked' : ''}>
            <span>Ready</span>
          </label>
        </div>
      `;
      item.querySelector('.cb-grid-del-btn').addEventListener('click', (e) => {
        e.stopPropagation();
        removeCardFromBoard(card.id);
      });
      item.querySelector('.cb-ready-cb').addEventListener('change', (e) => {
        e.stopPropagation();
        toggleReady(card.id, e.target.checked);
      });
      item.querySelector('[data-stop="1"]').addEventListener('click', (e) => e.stopPropagation());
      item.addEventListener('click', () => openDetail(card.id));
      loadedGrid.appendChild(item);
    });
  }

  const readyCards = cards.filter((c) => readySet.has(c.id));
  readyCountEl.textContent = String(readyCards.length);
  updateTxtCheckBadge();
  readyList.innerHTML = '';
  if (readyCards.length === 0) {
    readyList.innerHTML = '<p style="color:var(--text-muted); font-size:12px;">Check "Ready" on finished cards to list them here.</p>';
  } else {
    readyCards.forEach((card) => {
      const row = document.createElement('div');
      row.className = 'cb-ready-item';
      row.innerHTML = `
        <span style="font-weight:500; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${card.name} (×${card.count || 1})</span>
        <button type="button" class="btn btn-sm" data-act="unready" title="Return to editing">✕</button>
      `;
      row.querySelector('[data-act="unready"]').addEventListener('click', (e) => {
        e.stopPropagation();
        toggleReady(card.id, false);
      });
      row.addEventListener('click', () => openDetail(card.id));
      readyList.appendChild(row);
    });
  }
}

// Small "⇄ Front/Back" tag for the faces of a double-faced card (see card.dfc), '' otherwise.
function dfcBadgeHtml(card) {
  const dfc = card?.dfc;
  if (!dfc || !Array.isArray(dfc.face_names) || dfc.face_names.length < 2) return '';
  const isFront = dfc.face_index === 0;
  const other = dfc.face_names[isFront ? 1 : 0] || '';
  const tip = `Double-faced card (${card.scryfall_layout || 'dfc'}): ${isFront ? 'front' : 'back'} face. Other face: ${other}`;
  return `<span class="cb-dfc-badge${isFront ? '' : ' is-back'}" title="${tip.replace(/"/g, '&quot;')}">⇄ ${isFront ? 'Front' : 'Back'}</span>`;
}

function computeTxtCheckStatus() {
  const cb = ensureCardBuilderState();
  const manifest = cb.txt_manifest;
  if (!manifest || !Array.isArray(manifest.entries) || !manifest.entries.length) return null;
  const cards = getCards();
  const readySet = getReadyIds();

  const norm = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  const cardNormIndex = new Map();
  cards.forEach((c) => {
    [c.name, c.official_name, c.original_name, c.dfc?.full_name, cardDisplayName(c), ...(c.face_names || [])].forEach((n) => {
      const k = norm(n);
      if (k && !cardNormIndex.has(k)) cardNormIndex.set(k, c);
    });
  });

  const detected = [];
  const missing = [];
  let totalCopies = 0;
  let detectedCopies = 0;
  let readyMatched = 0;

  manifest.entries.forEach((entry) => {
    const qty = entry.count || 1;
    totalCopies += qty;
    const match = cardNormIndex.get(norm(entry.name));
    if (match) {
      const isReady = readySet.has(match.id);
      if (isReady) readyMatched++;
      detectedCopies += qty;
      detected.push({ entry, card: match, isReady });
    } else {
      missing.push(entry);
    }
  });

  return {
    filename: manifest.filename || 'deck.txt',
    totalUnique: manifest.entries.length,
    totalCopies,
    detected,
    missing,
    detectedCopies,
    readyMatched,
  };
}

function updateTxtCheckBadge() {
  const btn = document.getElementById('cb-check-txt-btn');
  if (!btn) return;
  const status = computeTxtCheckStatus();
  if (!status) {
    btn.textContent = '📋 Check .txt';
    return;
  }
  if (status.missing.length === 0) {
    btn.textContent = `📋 .txt ✓ (${status.detected.length}/${status.totalUnique})`;
  } else {
    btn.textContent = `📋 .txt (${status.detected.length}/${status.totalUnique} · -${status.missing.length})`;
  }
}

function toggleReady(cardId, isReady) {
  const cb = ensureCardBuilderState();
  const set = new Set(cb.ready_ids);
  if (isReady) set.add(cardId);
  else set.delete(cardId);
  cb.ready_ids = [...set];
  renderLists();
  persistState(true);
}

function removeCardFromBoard(cardId) {
  const cb = ensureCardBuilderState();
  const target = (cb.cards || []).find((c) => c.id === cardId);
  if (!target) return;
  cb.cards = (cb.cards || []).filter((c) => c.id !== cardId);
  cb.ready_ids = (cb.ready_ids || []).filter((id) => id !== cardId);
  historyStacks.delete(cardId);
  if (activeCardId === cardId) {
    activeCardId = null;
    detailView.style.display = 'none';
    listsView.style.display = 'flex';
  }
  renderLists();
  persistState(true);
  showToast(`Removed "${target.name || 'card'}" from board.`);
}

function showFrameHoverPreview(item, anchorRect) {
  const box = document.getElementById('cb-layer-hover-preview');
  const img = document.getElementById('cb-layer-hover-img');
  const cap = document.getElementById('cb-layer-hover-caption');
  if (!box || !img || !cap || !item?.url) {
    if (box) box.style.display = 'none';
    return;
  }
  img.src = item.url;
  cap.textContent = item.label || '';
  box.style.display = 'block';
  const sidebarRect = document.getElementById('cb-sidebar')?.getBoundingClientRect();
  const baseRight = sidebarRect ? Math.max(sidebarRect.right, anchorRect.right) : anchorRect.right;
  const left = Math.min(window.innerWidth - 185, baseRight + 12);
  const top = Math.min(window.innerHeight - 250, Math.max(54, anchorRect.top - 30));
  box.style.left = `${left}px`;
  box.style.top = `${top}px`;
}

function hideFrameHoverPreview() {
  const box = document.getElementById('cb-layer-hover-preview');
  if (box) box.style.display = 'none';
}

function renderFrameSelectors(card) {
  const container = document.getElementById('cb-frame-selectors');
  if (!container) return;
  const styleKey = card.frame_components?.style || 'M15Regular';
  const symCat = getSymbolsCatalog();
  const roleFrames = symCat.frames_by_role || {};
  const styleCat = catalog[styleKey] || roleFrames;
  const keys = [
    ['background', 'Frame'],
    ['pinlines', 'Pinlines / Textbox'],
    ['name_box', 'Holo Stamp / Badge'],
    ['crown', 'Crown'],
    ['border', 'Border'],
    ['pt_box', 'PT Box'],
  ];
  container.innerHTML = '';

  keys.forEach(([k, title]) => {
    const items = (styleCat[k] && styleCat[k].length ? styleCat[k] : roleFrames[k]) || [];
    let currentVal = card.frame_components?.[k] || '';
    let currentItem = items.find((it) => it.rel_path === currentVal || it.url === currentVal);
    if (!currentItem && currentVal) {
      const baseName = currentVal.split('/').pop();
      currentItem = { label: baseName, rel_path: currentVal, url: currentVal };
    }

    const wrap = document.createElement('div');
    wrap.style.cssText = 'position:relative; margin-bottom:8px;';
    wrap.innerHTML = `
      <label class="label" style="margin-top:0;">${title}</label>
      <button type="button" class="btn btn-sm" style="width:100%; justify-content:space-between; text-align:left;">
        <span class="cb-fs-val" style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${currentItem ? currentItem.label : '(None)'}</span>
        <span>▾</span>
      </button>
      <div class="cb-fs-menu" style="display:none; position:relative; z-index:20; margin-top:4px; border:1px solid var(--border); border-radius:6px; background:var(--surface); padding:6px; max-height:190px; overflow-y:auto;">
        <input type="text" class="input cb-fs-search" placeholder="Filter..." style="margin-bottom:4px; padding:4px 6px; font-size:11px;">
        <div class="cb-fs-list" style="display:flex; flex-direction:column; gap:2px;"></div>
      </div>
    `;

    const trigger = wrap.querySelector('button');
    const valSpan = wrap.querySelector('.cb-fs-val');
    const menu = wrap.querySelector('.cb-fs-menu');
    const searchIn = wrap.querySelector('.cb-fs-search');
    const listEl = wrap.querySelector('.cb-fs-list');

    function renderItems(q = '') {
      const ql = q.toLowerCase().trim();
      listEl.innerHTML = '';
      const noneBtn = document.createElement('button');
      noneBtn.type = 'button';
      noneBtn.className = 'btn btn-sm';
      noneBtn.style.cssText = 'justify-content:flex-start; font-size:11px; border:none;';
      noneBtn.textContent = '(None)';
      noneBtn.addEventListener('mouseenter', hideFrameHoverPreview);
      noneBtn.addEventListener('click', () => {
        card.frame_components = card.frame_components || {};
        card.frame_components[k] = '';
        card.hidden_layers = card.hidden_layers || {};
        card.hidden_layers[k] = true;
        valSpan.textContent = '(None)';
        menu.style.display = 'none';
        hideFrameHoverPreview();
        layerManager.render(card);
        renderCardCanvas(card);
        persistState(true);
      });
      listEl.appendChild(noneBtn);

      items.forEach((it) => {
        if (ql && !it.label.toLowerCase().includes(ql) && !(it.folder || '').toLowerCase().includes(ql)) return;
        const opt = document.createElement('button');
        opt.type = 'button';
        opt.className = 'btn btn-sm';
        opt.style.cssText = `justify-content:flex-start; font-size:11px; border:none; ${card.frame_components?.[k] === it.rel_path ? 'background:var(--accent-soft); color:var(--accent); font-weight:600;' : ''}`;
        opt.textContent = it.folder && it.folder !== '.' ? `${it.label} (${it.folder})` : it.label;
        opt.addEventListener('mouseenter', () => showFrameHoverPreview(it, opt.getBoundingClientRect()));
        opt.addEventListener('mouseleave', hideFrameHoverPreview);
        opt.addEventListener('click', () => {
          card.frame_components = card.frame_components || {};
          card.frame_components[k] = it.rel_path;
          card.hidden_layers = card.hidden_layers || {};
          delete card.hidden_layers[k];
          valSpan.textContent = it.label;
          menu.style.display = 'none';
          hideFrameHoverPreview();
          layerManager.render(card);
          renderCardCanvas(card);
          persistState(true);
        });
        listEl.appendChild(opt);
      });
    }

    trigger.addEventListener('click', (e) => {
      e.stopPropagation();
      const open = menu.style.display === 'block';
      container.querySelectorAll('.cb-fs-menu').forEach((m) => { m.style.display = 'none'; });
      hideFrameHoverPreview();
      if (!open) {
        menu.style.display = 'block';
        searchIn.value = '';
        renderItems('');
        searchIn.focus();
        const selItem = items.find((it) => it.rel_path === (card.frame_components?.[k] || ''));
        if (selItem) showFrameHoverPreview(selItem, menu.getBoundingClientRect());
      }
    });

    menu.addEventListener('mouseleave', hideFrameHoverPreview);

    searchIn.addEventListener('input', () => renderItems(searchIn.value));
    searchIn.addEventListener('click', (e) => e.stopPropagation());
    container.appendChild(wrap);
  });
}

async function openDetail(cardId) {
  activeCardId = cardId;
  const card = getActiveCard();
  if (!card) return;
  listsView.style.display = 'none';
  detailView.style.display = 'flex';
  await ensureSymbolsCatalog();

  if (!card.project_id && (card.official_name || card.original_name || card.name)) {
    try {
      const impResp = await fetch('/api/card-builder/import-scryfall', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: card.official_name || card.original_name || card.name,
          set: card.set || '',
          root_dir: getActiveRootDir(),
        }),
      });
      if (impResp.ok) {
        const proj = await impResp.json();
        card.project_id = proj.project_id;
        state.project = proj;
        state.faceIndex = proj.faces?.[0]?.face_index ?? 0;
        syncProjectFaceSelect();
        await showProjectFace(state.faceIndex);
        persistState(true);
        return;
      }
    } catch {}
  }

  if (card.project_id) {
    try {
      const resp = await fetch(`/api/card-builder/project/${encodeURIComponent(card.project_id)}`);
      if (resp.ok) {
        const project = await resp.json();
        state.project = project;
        state.faceIndex = project.faces?.[0]?.face_index ?? 0;
        syncProjectFaceSelect();
        await showProjectFace(state.faceIndex);
        return;
      }
    } catch {}
  }

  state.project = null;
  populateDetailControls(card);
  renderCardCanvas(card);
}

function updateSetPreviewIcon(setCode, rarity) {
  const setIcon = document.getElementById('cb-set-preview-icon');
  if (!setIcon) return;
  const face = currentProjectFace();
  const symUrl = resolveSetSymbolUrl(setCode, rarity) || face?.set_symbol?.url || state.project?.set_symbol?.url;
  if (symUrl) {
    setIcon.className = '';
    setIcon.innerHTML = `<img src="${symUrl}" alt="${setCode}" style="height:22px; width:auto; vertical-align:middle;">`;
  } else {
    setIcon.innerHTML = '';
    setIcon.textContent = String(setCode || 'MTG').toUpperCase();
  }
}

function populateDetailControls(card) {
  document.getElementById('cb-detail-ready-check').checked = getReadyIds().has(card.id);
  if (card.original_name === undefined) card.original_name = card.official_name || card.name || '';
  document.getElementById('cb-field-name').value = card.name || '';
  document.getElementById('cb-field-official-name').value = card.official_name || '';
  document.getElementById('cb-field-mana').value = card.mana_cost || '';
  document.getElementById('cb-field-type').value = card.type_line || '';
  document.getElementById('cb-field-oracle').value = card.oracle_text || '';
  document.getElementById('cb-field-pt').value = card.power != null ? `${card.power}/${card.toughness ?? ''}` : '';
  document.getElementById('cb-field-artist').value = card.artist || '';
  const setIn = document.getElementById('cb-field-set');
  const rarSel = document.getElementById('cb-field-rarity');
  if (setIn) setIn.value = (card.set || 'mtg').toLowerCase();
  if (rarSel) rarSel.value = (card.rarity || 'common').toLowerCase();
  updateSetPreviewIcon(card.set || 'mtg', card.rarity || 'common');
  document.getElementById('cb-color-title').value = card.layout?.title?.color || '#111111';
  document.getElementById('cb-color-official').value = card.layout?.official_title?.color || '#111111';
  document.getElementById('cb-color-type').value = card.layout?.type_line?.color || '#111111';
  document.getElementById('cb-color-oracle').value = card.layout?.oracle_box?.color || '#111111';
  document.getElementById('cb-color-pt').value = card.layout?.pt_text?.color || '#111111';
  document.getElementById('cb-color-artist').value = card.layout?.artist?.color || '#ffffff';
  const adv = card.adventure || {};
  document.getElementById('cb-field-adv-name').value = adv.name || '';
  document.getElementById('cb-field-adv-mana').value = adv.mana_cost || '';
  document.getElementById('cb-field-adv-type').value = adv.type_line || '';
  document.getElementById('cb-field-adv-oracle').value = adv.oracle_text || '';
  document.getElementById('cb-color-adv-title').value = card.layout?.adventure_title?.color || '#111111';
  document.getElementById('cb-color-adv-type').value = card.layout?.adventure_type_line?.color || '#ffffff';
  document.getElementById('cb-color-adv-oracle').value = card.layout?.adventure_oracle_box?.color || '#111111';

  const popEl = document.getElementById('cb-art-over-top');
  if (popEl) popEl.checked = Boolean(card.art_over_top);
  const hideTxtEl = document.getElementById('cb-hide-card-text');
  if (hideTxtEl) hideTxtEl.checked = Boolean(card.hide_card_text);
  const br = card.brightness ?? 1.0;
  document.getElementById('cb-brightness').value = br;
  document.getElementById('cb-brightness-val').textContent = Number(br).toFixed(2);

  const lay = card.layout?.art || { scale: 1.0 };
  const scEl = document.getElementById('cb-art-scale');
  const scValEl = document.getElementById('cb-art-scale-val');
  if (scEl) scEl.value = lay.scale ?? 1.0;
  if (scValEl) scValEl.textContent = Number(lay.scale ?? 1.0).toFixed(2);

  const bgVal = /^#[0-9a-fA-F]{6}$/.test((card.bg_color || '').trim()) ? card.bg_color.trim() : '#111111';
  document.getElementById('cb-bg-color-picker').value = bgVal;
  document.getElementById('cb-bg-color-text').value = bgVal;

  const styleSel = document.getElementById('cb-detail-style-select');
  if (styleSel && card.frame_components?.style) styleSel.value = card.frame_components.style;

  populateTaxonomyAndLayoutControls(card);
  renderFrameSelectors(card);
  renderShapesList(card);
  layerManager.render(card);
}

function populateTaxonomyAndLayoutControls(card) {
  const cat = getSymbolsCatalog();
  const layoutSel = document.getElementById('cb-layout-select');
  const templates = cat.templates || {};
  const tplKeys = Object.keys(templates).sort();
  if (layoutSel && tplKeys.length && layoutSel.options.length !== tplKeys.length) {
    layoutSel.innerHTML = tplKeys.map((k) => `<option value="${k}">${k}</option>`).join('');
  }
  const face = currentProjectFace();
  const activeLayout = face?.template || card?.frame_components?.style || 'M15Regular';
  if (layoutSel && tplKeys.includes(activeLayout)) {
    layoutSel.value = activeLayout;
  }

  const taxOpts = cat.taxonomy_options || {};
  const fillTax = (id, allLabel, list) => {
    const el = document.getElementById(id);
    if (!el || !Array.isArray(list)) return;
    if (el.options.length === list.length + 1) return;
    const prev = el.value;
    el.innerHTML = `<option value="">${allLabel}</option>` + list.map((o) => `<option value="${o.value}">${o.label}</option>`).join('');
    el.value = prev;
  };
  fillTax('cb-tax-era', 'Era: Todas', taxOpts.frame_era);
  fillTax('cb-tax-layout', 'Tipo: Todos', [
    ...(taxOpts.layout || []),
    ...(taxOpts.structural || []),
  ]);
  fillTax('cb-tax-material', 'Material: Todos', taxOpts.material);
  fillTax('cb-tax-showcase', 'Showcase: Todos', taxOpts.showcase_style);
}

// Normalize template profile key for display
function styleDisplayName(styleKey) {
  return String(styleKey || '');
}

function bindDetailEvents() {
  document.getElementById('cb-add-rect-btn')?.addEventListener('click', () => addOverlayShape('rect'));
  document.getElementById('cb-add-round-btn')?.addEventListener('click', () => addOverlayShape('rounded'));
  document.getElementById('cb-add-circle-btn')?.addEventListener('click', () => addOverlayShape('circle'));
  document.getElementById('cb-undo-btn')?.addEventListener('click', performUndo);
  document.getElementById('cb-redo-btn')?.addEventListener('click', performRedo);
  window.addEventListener('keydown', (evt) => {
    if (detailView.style.display === 'none') return;
    const tag = document.activeElement ? document.activeElement.tagName.toLowerCase() : '';
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
    if ((evt.ctrlKey || evt.metaKey) && evt.key.toLowerCase() === 'z') {
      evt.preventDefault();
      if (evt.shiftKey) performRedo();
      else performUndo();
    } else if ((evt.ctrlKey || evt.metaKey) && evt.key.toLowerCase() === 'y') {
      evt.preventDefault();
      performRedo();
    }
  });

  document.getElementById('cb-back-btn').addEventListener('click', () => {
    detailView.style.display = 'none';
    listsView.style.display = 'flex';
    renderLists();
    persistState(true);
  });

  document.getElementById('cb-delete-card-btn')?.addEventListener('click', () => {
    if (!activeCardId) return;
    removeCardFromBoard(activeCardId);
  });

  document.getElementById('cb-art-over-top')?.addEventListener('change', (e) => {
    const card = getActiveCard();
    if (!card) return;
    pushUndoState(card);
    applyPopOutOrder(card, e.target.checked);
    layerManager?.render(card);
    renderCardCanvas(card);
    persistState(true);
  });

  document.getElementById('cb-hide-card-text')?.addEventListener('change', (e) => {
    const card = getActiveCard();
    if (!card) return;
    pushUndoState(card);
    card.hide_card_text = e.target.checked;
    renderCardCanvas(card);
    persistState(true);
  });

  document.getElementById('cb-detail-ready-check').addEventListener('change', (e) => {
    if (activeCardId) toggleReady(activeCardId, e.target.checked);
  });

  async function applyTemplateStyleToActiveCard(styleKey) {
    const card = getActiveCard();
    if (!card || !styleKey) return;
    pushUndoState(card);
    card.frame_components = card.frame_components || {};
    card.frame_components.style = styleKey;
    const face = currentProjectFace();
    if (face) applyTemplateLayoutToFace(card, face, styleKey);
    const sel = document.getElementById('cb-detail-style-select');
    if (sel) sel.value = styleKey;
    layerManager.render(card);
    renderFrameSelectors(card);
    renderCardCanvas(card);
    persistState(true);
  }

  document.getElementById('cb-detail-style-select')?.addEventListener('change', (e) => {
    applyTemplateStyleToActiveCard(e.target.value);
  });

  // Visual Template Picker Modal
  const tplModal = document.getElementById('cb-template-modal');
  const tplGrid = document.getElementById('cb-tpl-grid');
  const tplFilter = document.getElementById('cb-tpl-filter');
  const tplCloseBtn = document.getElementById('cb-tpl-close');

  function renderTemplatePickerGrid() {
    if (!tplGrid) return;
    const card = getActiveCard();
    const activeStyle = card?.frame_components?.style || document.getElementById('cb-detail-style-select')?.value || '';
    const q = (tplFilter?.value || '').trim().toLowerCase();
    const keys = Object.keys(catalog || {}).filter((k) => !q || k.toLowerCase().includes(q));
    tplGrid.innerHTML = '';
    if (!keys.length) {
      tplGrid.innerHTML = '<div style="font-size:12px; color:var(--text-muted); grid-column:1/-1;">No templates match your search.</div>';
      return;
    }
    keys.forEach((styleKey) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'cb-tpl-card' + (styleKey === activeStyle ? ' active' : '');
      const shortName = styleDisplayName(styleKey);
      btn.innerHTML = `
        <span class="cb-tpl-name" title="${styleKey}">${shortName}</span>
      `;
      btn.addEventListener('click', async () => {
        await applyTemplateStyleToActiveCard(styleKey);
        tplModal?.classList.remove('open');
      });
      tplGrid.appendChild(btn);
    });
  }

  document.getElementById('cb-browse-templates-btn')?.addEventListener('click', () => {
    if (tplFilter) tplFilter.value = '';
    renderTemplatePickerGrid();
    tplModal?.classList.add('open');
  });
  tplFilter?.addEventListener('input', renderTemplatePickerGrid);
  tplCloseBtn?.addEventListener('click', () => tplModal?.classList.remove('open'));
  tplModal?.addEventListener('click', (e) => {
    if (e.target === tplModal) tplModal.classList.remove('open');
  });

  const syncField = (id, fn) => {
    const el = document.getElementById(id);
    el.addEventListener('focus', () => { const c = getActiveCard(); if (c) pushUndoState(c); });
    el.addEventListener('input', (e) => {
      const card = getActiveCard();
      if (!card) return;
      fn(card, e.target.value);
      scheduleRender(card);
      persistState(true);
    });
  };

  syncField('cb-field-name', (c, v) => {
    if (c.original_name === undefined) c.original_name = c.official_name || c.name || '';
    c.name = v;
    if (!c._official_manually_edited && c.original_name) {
      if (v.trim() && v.trim() !== c.original_name.trim()) {
        c.official_name = c.original_name;
      } else if (v.trim() === c.original_name.trim()) {
        c.official_name = '';
      }
      const offEl = document.getElementById('cb-field-official-name');
      if (offEl) offEl.value = c.official_name || '';
    }
  });
  syncField('cb-field-official-name', (c, v) => {
    c._official_manually_edited = true;
    c.official_name = v;
  });
  syncField('cb-field-mana', (c, v) => { c.mana_cost = v; });
  syncField('cb-field-type', (c, v) => { c.type_line = v; });
  syncField('cb-field-oracle', (c, v) => { c.oracle_text = v; });
  syncField('cb-field-artist', (c, v) => { c.artist = v; });
  syncField('cb-field-set', (c, v) => {
    const code = (v || 'mtg').trim().toLowerCase() || 'mtg';
    c.set = code;
    updateSetPreviewIcon(code, c.rarity || 'common');
  });
  document.getElementById('cb-field-rarity')?.addEventListener('change', (e) => {
    const c = getActiveCard();
    if (!c) return;
    pushUndoState(c);
    c.rarity = (e.target.value || 'common').toLowerCase();
    updateSetPreviewIcon(c.set || 'mtg', c.rarity);
    renderCardCanvas(c);
    persistState(true);
  });
  syncField('cb-field-pt', (c, v) => {
    const parts = v.split('/');
    c.power = parts[0]?.trim() || null;
    c.toughness = parts[1]?.trim() || null;
  });
  const bindTextColor = (elId, layoutKey) => {
    syncField(elId, (c, v) => {
      c.layout = c.layout || {};
      c.layout[layoutKey] = c.layout[layoutKey] || {};
      c.layout[layoutKey].color = v;
    });
  };
  bindTextColor('cb-color-title', 'title');
  bindTextColor('cb-color-official', 'official_title');
  bindTextColor('cb-color-type', 'type_line');
  bindTextColor('cb-color-oracle', 'oracle_box');
  bindTextColor('cb-color-pt', 'pt_text');
  bindTextColor('cb-color-artist', 'artist');
  bindTextColor('cb-color-adv-title', 'adventure_title');
  bindTextColor('cb-color-adv-type', 'adventure_type_line');
  bindTextColor('cb-color-adv-oracle', 'adventure_oracle_box');
  const syncAdventureField = (id, prop) => syncField(id, (c, v) => {
    if (c.adventure) c.adventure[prop] = v;
  });
  syncAdventureField('cb-field-adv-name', 'name');
  syncAdventureField('cb-field-adv-mana', 'mana_cost');
  syncAdventureField('cb-field-adv-type', 'type_line');
  syncAdventureField('cb-field-adv-oracle', 'oracle_text');
  syncField('cb-brightness', (c, v) => {
    c.brightness = parseFloat(v);
    document.getElementById('cb-brightness-val').textContent = Number(c.brightness).toFixed(2);
  });
  syncField('cb-art-scale', (c, v) => {
    const L = ensureCardLayout(c);
    L.art.scale = parseFloat(v) || 1.0;
    const sv = document.getElementById('cb-art-scale-val');
    if (sv) sv.textContent = Number(L.art.scale).toFixed(2);
  });

  const bgPicker = document.getElementById('cb-bg-color-picker');
  const bgText = document.getElementById('cb-bg-color-text');
  const bgClearBtn = document.getElementById('cb-bg-color-clear');
  bgPicker.addEventListener('input', (e) => {
    const card = getActiveCard();
    if (!card) return;
    card.bg_color = e.target.value;
    bgText.value = e.target.value;
    renderCardCanvas(card);
    persistState(true);
  });
  bgText.addEventListener('change', (e) => {
    const card = getActiveCard();
    if (!card) return;
    const val = (e.target.value || '').trim();
    if (!val) {
      card.bg_color = '#111111';
      bgText.value = '#111111';
      bgPicker.value = '#111111';
    } else if (/^#[0-9a-fA-F]{6}$/.test(val)) {
      card.bg_color = val;
      bgPicker.value = val;
    }
    renderCardCanvas(card);
    persistState(true);
  });
  bgClearBtn?.addEventListener('click', () => {
    const card = getActiveCard();
    if (!card) return;
    pushUndoState(card);
    card.bg_color = '#111111';
    bgText.value = '#111111';
    bgPicker.value = '#111111';
    renderCardCanvas(card);
    persistState(true);
  });

  document.getElementById('cb-crop-art-btn').addEventListener('click', () => {
    const card = getActiveCard();
    if (!card) return;
    const src = card.custom_art_data || card.art_crop_url;
    if (!src) return showToast('This card has no artwork loaded.');
    cropModal.open(src, card.crop_mask || 'classic_box');
  });

  document.getElementById('cb-save-single-btn').addEventListener('click', async () => {
    const card = getActiveCard();
    if (!card) return;
    await persistState(false);
  });

  document.getElementById('cb-export-single-pdf-btn').addEventListener('click', async () => {
    const card = getActiveCard();
    if (!card) return;
    await exportCardsBatch([card], 'fronts', 'pdf', SINGLE_PDF_EXPORT_DPI, true);
  });

  const interactiveCheck = document.getElementById('cb-interactive-mode');
  interactiveCheck?.addEventListener('change', () => {
    const card = getActiveCard();
    if (card) renderCardCanvas(card);
  });

  document.getElementById('cb-reset-all-btn')?.addEventListener('click', async () => {
    const card = getActiveCard();
    if (!card) return;
    pushUndoState(card);
    const face = currentProjectFace();
    if (face && face._original_ui_state) {
      resetCardToOriginalFace(card, face);
    } else {
      card.layout = face ? buildLayoutFromProjectFace(face) : JSON.parse(JSON.stringify(DEFAULT_LAYOUT));
      card.layer_order = [...DEFAULT_LAYER_ORDER];
      card.layer_opacities = {};
      card.layer_colors = {};
      card.hidden_layers = { border: true };
      if (card.scryfall_art_url) {
        card.custom_art_data = null;
        card.art_crop_url = card.scryfall_art_url;
      }
    }
    card.brightness = 1.0;
    card.bg_color = '';
    card.art_over_top = false;
    card.hide_card_text = false;
    card.crop_mask = 'free';
    card.frame_opacity = 1.0;
    card.shapes = [];
    selectedElementKey = null;
    populateDetailControls(card);
    layerManager.render(card);
    renderFrameSelectors(card);
    renderCardCanvas(card);
    persistState(true);
    showToast('Card reset to original state.');
  });

  // Independent Layout selector (changes text/art geometry & filters component submenus to this template)
  document.getElementById('cb-layout-select')?.addEventListener('change', (e) => {
    const card = getActiveCard();
    const tplName = e.target.value;
    if (!card || !tplName) return;
    pushUndoState(card);
    const face = currentProjectFace();
    if (face) {
      applyTemplateLayoutToFace(card, face, tplName);
    } else {
      card.frame_components = card.frame_components || {};
      card.frame_components.style = tplName;
    }
    layerManager?.setLayoutFilter(tplName, card, { backFace: (state.project?.faces || []).indexOf(face) === 1 });
    // Swap the frame components to the new layout's pack so the art matches the geometry.
    const framesChanged = layerManager?.applyLayoutPackFrames(card) || 0;
    if (framesChanged) layerManager?.render(card);
    populateDetailControls(card);
    renderCardCanvas(card);
    persistState(true);
    showToast(framesChanged ? `Layout applied: ${tplName} (frames updated)` : `Layout applied: ${tplName}`);
  });

  function getActiveStageCanvas() {
    const projectWrap = document.getElementById('cb-project-wrap');
    const projectCanvas = document.getElementById('cb-project-canvas');
    if (projectWrap && projectWrap.style.display !== 'none' && projectCanvas) {
      return projectCanvas;
    }
    return canvas;
  }

  function getCanvasMouseCoords(evt) {
    const activeCanvas = getActiveStageCanvas();
    const rect = activeCanvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return { x: 0, y: 0 };
    return {
      x: (evt.clientX - rect.left) * (750 / rect.width),
      y: (evt.clientY - rect.top) * (1050 / rect.height),
    };
  }

  function isFramePixelOpaque(card, layerKey, mx, my) {
    const fc = card.frame_components || {};
    const relPath = fc[layerKey];
    if (!relPath) return false;
    if (layerKey === 'background') {
      // Let clicks inside the artwork window pass through the transparent RGBA frame cutout to Artwork
      const L = ensureCardLayout(card);
      const a = L.art;
      if (a && mx >= a.x && mx <= a.x + a.w && my >= a.y && my <= a.y + a.h) return false;
      return true;
    }
    const cacheKey = `${layerKey}::${relPath}`;
    const off = transparentLayerCache.get(cacheKey);
    if (!off) return false;
    const px = Math.max(0, Math.min(749, Math.round(mx)));
    const py = Math.max(0, Math.min(1049, Math.round(my)));
    try {
      const data = off.getContext('2d', { willReadFrequently: true }).getImageData(px, py, 1, 1).data;
      return data[3] > 20;
    } catch {
      return false;
    }
  }

  function findAllHitTargets(mx, my, card) {
    const hits = [];
    const regions = getInteractiveRegions(card);
    const selRegion = regions.find((r) => r.key === selectedElementKey);
    if (selRegion) {
      for (const h of getHandlesForRegion(selRegion)) {
        if (Math.abs(mx - h.x) <= HANDLE_SIZE && Math.abs(my - h.y) <= HANDLE_SIZE) {
          hits.push({ type: 'handle', key: selRegion.key, handle: h.id, cursor: h.cursor, region: selRegion });
          return hits;
        }
      }
    }

    // 1. Text & icon foreground regions (topmost)
    const textKeys = new Set(TEXT_KEYS);
    for (const r of regions) {
      if (!textKeys.has(r.key)) continue;
      if (mx >= r.x && mx <= r.x + r.w && my >= r.y && my <= r.y + r.h) {
        hits.push({ type: 'region', key: r.key, cursor: 'move', region: r });
      }
    }

    // 2. Layer stack from topmost to bottommost (shapes, art, and frame components)
    const hidden = Array.isArray(card.hidden_layers)
      ? Object.fromEntries(card.hidden_layers.map((k) => [k, true]))
      : (card.hidden_layers || {});
    const order = Array.isArray(card.layer_order) && card.layer_order.length
      ? card.layer_order
      : ['background', 'art', 'pinlines', 'name_box', 'crown', 'border', 'pt_box'];
    const regionMap = new Map(regions.map((r) => [r.key, r]));

    for (let i = order.length - 1; i >= 0; i--) {
      const key = order[i];
      if (hidden[key]) continue;
      if (key.startsWith('shape:') || key === 'art') {
        const r = regionMap.get(key);
        if (r && mx >= r.x && mx <= r.x + r.w && my >= r.y && my <= r.y + r.h) {
          hits.push({ type: 'region', key, cursor: 'move', region: r });
        }
      } else if (isFramePixelOpaque(card, key, mx, my)) {
        hits.push({ type: 'frame', key, cursor: 'pointer', region: null });
      }
    }
    return hits;
  }

  function findHitTarget(mx, my, card) {
    const hits = findAllHitTargets(mx, my, card);
    return hits.length ? hits[0] : null;
  }

  function setActiveTool(tool) {
    activeTool = tool || 'select';
    document.querySelectorAll('#cb-ps-toolbox .cb-tool-btn').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.tool === activeTool);
    });
    const cur = activeTool === 'select' ? 'default' : 'crosshair';
    canvas.style.cursor = cur;
    const pc = document.getElementById('cb-project-canvas');
    if (pc) pc.style.cursor = cur;
  }

  document.querySelectorAll('#cb-ps-toolbox .cb-tool-btn[data-tool]').forEach((btn) => {
    btn.addEventListener('click', () => {
      setActiveTool(btn.dataset.tool || 'select');
      if (activeTool !== 'select') closeTextPopover();
    });
  });

  // Contextual Text Inspector Popover inside Toolbox
  const TEXT_POPOVER_KEYS = new Set(TEXT_KEYS);
  const TEXT_POPOVER_LABELS = {
    title: 'Card Title',
    official_title: 'Official / Original Name',
    mana_cost: 'Mana Cost',
    type_line: 'Type Line',
    set_symbol: 'Set Symbol (Keyrune)',
    oracle_box: 'Oracle Rules Text',
    pt_text: 'Power / Toughness',
    artist: 'Artist',
    adventure_title: 'Adventure Title',
    adventure_mana_cost: 'Adventure Mana Cost',
    adventure_type_line: 'Adventure Type Line',
    adventure_oracle_box: 'Adventure Rules Text',
  };
  const textPopoverEl = document.getElementById('cb-text-popover');
  const textPopoverTitleEl = document.getElementById('cb-text-popover-title');
  const toolTextBtn = document.getElementById('cb-tool-text-btn');
  const toolOfficialBtn = document.getElementById('cb-tool-official-btn');
  let activeTextPopoverKey = 'title';

  function syncTextSizeInputs(card) {
    if (!card) return;
    const L = ensureCardLayout(card);
    document.querySelectorAll('.cb-text-size-input').forEach((inp) => {
      const k = inp.dataset.sizeKey;
      if (k === 'mana_cost' || k === 'adventure_mana_cost') inp.value = Math.round(L[k]?.size ?? 35);
      else if (k === 'set_symbol') inp.value = Math.round(L.set_symbol?.size ?? 41);
      else if (L[k]) inp.value = Math.round(L[k].font_size ?? 24);
    });
  }

  function openTextPopover(textKey, focusInput = false) {
    if (!textPopoverEl) return;
    const key = TEXT_POPOVER_KEYS.has(textKey) ? textKey : 'title';
    activeTextPopoverKey = key;
    const card = getActiveCard();
    if (card) syncTextSizeInputs(card);
    if (textPopoverTitleEl) textPopoverTitleEl.textContent = TEXT_POPOVER_LABELS[key] || 'Text Settings';
    textPopoverEl.querySelectorAll('.cb-text-tab[data-adventure]').forEach((t) => {
      t.style.display = card?.adventure ? '' : 'none';
    });
    textPopoverEl.querySelectorAll('.cb-text-tab').forEach((t) => {
      t.classList.toggle('active', t.dataset.textTab === key);
    });
    textPopoverEl.querySelectorAll('.cb-text-group').forEach((g) => {
      g.classList.toggle('active', g.dataset.textKey === key);
    });
    textPopoverEl.style.display = 'block';
    toolTextBtn?.classList.toggle('active', key !== 'official_title');
    toolOfficialBtn?.classList.toggle('active', key === 'official_title');
    if (focusInput) {
      const inp = textPopoverEl.querySelector(`.cb-text-group[data-text-key="${key}"] input[type="text"], .cb-text-group[data-text-key="${key}"] textarea`);
      inp?.focus();
    }
  }

  function closeTextPopover() {
    if (!textPopoverEl) return;
    textPopoverEl.style.display = 'none';
    toolTextBtn?.classList.remove('active');
    toolOfficialBtn?.classList.remove('active');
  }

  toolTextBtn?.addEventListener('click', () => {
    if (textPopoverEl?.style.display === 'block' && activeTextPopoverKey !== 'official_title') {
      closeTextPopover();
    } else {
      const k = TEXT_POPOVER_KEYS.has(selectedElementKey) ? selectedElementKey : 'title';
      openTextPopover(k, true);
    }
  });

  toolOfficialBtn?.addEventListener('click', () => {
    if (textPopoverEl?.style.display === 'block' && activeTextPopoverKey === 'official_title') {
      closeTextPopover();
    } else {
      openTextPopover('official_title', true);
    }
  });

  document.getElementById('cb-text-popover-close')?.addEventListener('click', closeTextPopover);
  document.querySelectorAll('#cb-text-tabs .cb-text-tab').forEach((tab) => {
    tab.addEventListener('click', () => openTextPopover(tab.dataset.textTab, true));
  });

  document.querySelectorAll('.cb-text-size-input').forEach((inp) => {
    inp.addEventListener('focus', () => { const c = getActiveCard(); if (c) pushUndoState(c); });
    inp.addEventListener('input', () => {
      const card = getActiveCard();
      if (!card) return;
      const L = ensureCardLayout(card);
      const k = inp.dataset.sizeKey;
      const val = parseInt(inp.value, 10);
      if (!Number.isFinite(val)) return;
      if (k === 'mana_cost' || k === 'adventure_mana_cost') L[k].size = Math.max(14, Math.min(64, val));
      else if (k === 'set_symbol') L.set_symbol.size = Math.max(14, Math.min(72, val));
      else if (L[k]) L[k].font_size = Math.max(10, Math.min(72, val));
      scheduleRender(card);
      persistState(true);
    });
  });

  // Movable floating Photoshop Toolbox
  const toolboxEl = document.getElementById('cb-ps-toolbox');
  const toolboxHandle = document.getElementById('cb-toolbox-drag-handle');
  if (toolboxEl && toolboxHandle) {
    let tbDrag = null;
    toolboxHandle.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      const stageRect = toolboxEl.closest('.cb-stage')?.getBoundingClientRect();
      const tbRect = toolboxEl.getBoundingClientRect();
      if (!stageRect) return;
      tbDrag = {
        startX: e.clientX,
        startY: e.clientY,
        origLeft: tbRect.left - stageRect.left,
        origTop: tbRect.top - stageRect.top,
        maxLeft: Math.max(0, stageRect.width - tbRect.width - 8),
        maxTop: Math.max(0, stageRect.height - tbRect.height - 8),
      };
      toolboxHandle.setPointerCapture?.(e.pointerId);
    });
    window.addEventListener('pointermove', (e) => {
      if (!tbDrag) return;
      const nx = Math.max(6, Math.min(tbDrag.maxLeft, tbDrag.origLeft + (e.clientX - tbDrag.startX)));
      const ny = Math.max(6, Math.min(tbDrag.maxTop, tbDrag.origTop + (e.clientY - tbDrag.startY)));
      toolboxEl.style.left = `${Math.round(nx)}px`;
      toolboxEl.style.top = `${Math.round(ny)}px`;
    });
    window.addEventListener('pointerup', () => { tbDrag = null; });
  }

  // Collapsible left sidebar & icon-only rail
  const sidebarEl = document.getElementById('cb-sidebar');
  document.getElementById('cb-sidebar-collapse-btn')?.addEventListener('click', () => {
    sidebarEl?.classList.add('collapsed');
  });
  document.getElementById('cb-sidebar-expand-btn')?.addEventListener('click', () => {
    sidebarEl?.classList.remove('collapsed');
  });
  sidebarEl?.querySelectorAll('.cb-rail-btn[data-rail-act="back"]').forEach((btn) => {
    btn.addEventListener('click', () => document.getElementById('cb-back-btn')?.click());
  });
  sidebarEl?.querySelectorAll('.cb-rail-btn[data-rail-sec]').forEach((btn) => {
    btn.addEventListener('click', () => {
      sidebarEl.classList.remove('collapsed');
      const sec = btn.dataset.railSec;
      const acc = sidebarEl.querySelector(`details[data-section="${sec}"]`);
      if (acc) {
        acc.open = true;
        acc.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    });
  });

  function syncArtInputsFromLayout(L) {
    const scEl = document.getElementById('cb-art-scale');
    const scValEl = document.getElementById('cb-art-scale-val');
    const oxEl = document.getElementById('cb-art-ox');
    const oyEl = document.getElementById('cb-art-oy');
    if (scEl) scEl.value = L.art.scale ?? 1.0;
    if (scValEl) scValEl.textContent = Number(L.art.scale ?? 1.0).toFixed(2);
    if (oxEl) oxEl.value = Math.round(L.art.offset_x ?? 0);
    if (oyEl) oyEl.value = Math.round(L.art.offset_y ?? 0);
  }

  const handleStageMouseDown = (evt) => {
    const card = getActiveCard();
    if (!interactiveCheck?.checked || !card) return;
    const { x: mx, y: my } = getCanvasMouseCoords(evt);

    // Photoshop-style Shape Tool drawing
    if (activeTool !== 'select') {
      const color = document.getElementById('cb-tool-color')?.value || '#000000';
      const opacity = parseFloat(document.getElementById('cb-tool-opacity')?.value || '0.55');
      const preDragSnap = cloneCardSnapshot(card);
      draftShape = {
        id: 's_' + Date.now() + '_' + Math.floor(Math.random() * 1000),
        type: activeTool,
        x: mx,
        y: my,
        w: 1,
        h: 1,
        color,
        opacity: Number.isFinite(opacity) ? opacity : 0.55,
        radius: activeTool === 'rounded' ? 16 : 0,
      };
      dragState = { mode: 'draw-shape', startX: mx, startY: my, changed: false, preDragSnap };
      renderCardCanvas(card);
      return;
    }

    const hits = findAllHitTargets(mx, my, card);
    if (!hits.length) {
      selectedElementKey = null;
      layerManager?.setSelected(null);
      closeTextPopover();
      renderCardCanvas(card);
      return;
    }

    let hit = hits[0];
    if (evt.shiftKey && hit.type !== 'handle' && hits.length > 1) {
      const curIdx = hits.findIndex((h) => h.key === selectedElementKey);
      hit = hits[(curIdx + 1) % hits.length];
    }

    selectedElementKey = hit.key;
    layerManager?.setSelected(hit.key);

    if (TEXT_POPOVER_KEYS.has(hit.key)) {
      openTextPopover(hit.key, false);
    } else {
      closeTextPopover();
    }

    if (hit.type === 'frame') {
      renderCardCanvas(card);
      return;
    }

    const L = ensureCardLayout(card);
    const preDragSnap = cloneCardSnapshot(card);
    const initialLayout = JSON.parse(JSON.stringify(L));
    const initialShapes = JSON.parse(JSON.stringify(card.shapes || []));
    if (hit.type === 'handle') {
      dragState = { mode: 'resize', key: hit.key, handle: hit.handle, startX: mx, startY: my, initialLayout, initialShapes, changed: false, preDragSnap };
    } else if (hit.key === 'art' && evt.altKey) {
      dragState = { mode: 'pan-art', key: 'art', startX: mx, startY: my, initialLayout, initialShapes, changed: false, preDragSnap };
    } else {
      dragState = { mode: 'move', key: hit.key, startX: mx, startY: my, initialLayout, initialShapes, changed: false, preDragSnap };
    }
    renderCardCanvas(card);
  };

  canvas.addEventListener('mousedown', handleStageMouseDown);
  document.getElementById('cb-project-canvas')?.addEventListener('mousedown', handleStageMouseDown);

  window.addEventListener('mousemove', (evt) => {
    const card = getActiveCard();
    if (!card || detailView.style.display === 'none') return;
    const { x: mx, y: my } = getCanvasMouseCoords(evt);

    if (!dragState) {
      const activeStage = getActiveStageCanvas();
      if (!interactiveCheck?.checked) {
        activeStage.style.cursor = 'default';
        return;
      }
      if (activeTool !== 'select') {
        activeStage.style.cursor = 'crosshair';
        return;
      }
      const hit = findHitTarget(mx, my, card);
      const prevHover = hoveredElementKey;
      hoveredElementKey = hit ? hit.key : null;
      activeStage.style.cursor = hit ? hit.cursor : 'default';
      if (prevHover !== hoveredElementKey) {
        if (state.project && currentProjectFace() && _projectCleanReady) {
          paintProjectWithOverlays(document.getElementById('cb-project-canvas'), card);
        } else {
          scheduleRender(card);
        }
      }
      return;
    }

    if (dragState.mode === 'draw-shape' && draftShape) {
      const nx = Math.min(dragState.startX, mx);
      const ny = Math.min(dragState.startY, my);
      const nw = Math.abs(mx - dragState.startX);
      const nh = Math.abs(my - dragState.startY);
      draftShape.x = Math.round(nx);
      draftShape.y = Math.round(ny);
      draftShape.w = Math.max(1, Math.round(nw));
      draftShape.h = Math.max(1, Math.round(nh));
      if (nw > 4 || nh > 4) dragState.changed = true;
      scheduleRender(card);
      return;
    }

    const dx = mx - dragState.startX;
    const dy = my - dragState.startY;
    if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) dragState.changed = true;

    const init = dragState.initialLayout;
    const L = ensureCardLayout(card);
    const k = dragState.key;

    if (dragState.mode === 'pan-art') {
      L.art.offset_x = (init.art.offset_x || 0) + dx;
      L.art.offset_y = (init.art.offset_y || 0) + dy;
    } else if (dragState.mode === 'move') {
      if (k === 'art') { L.art.x = init.art.x + dx; L.art.y = init.art.y + dy; }
      else if (k === 'title') { L.title.x = init.title.x + dx; L.title.y = init.title.y + dy; }
      else if (k === 'official_title') { L.official_title.x = init.official_title.x + dx; L.official_title.y = init.official_title.y + dy; }
      else if (k === 'mana_cost') { L.mana_cost.x = init.mana_cost.x + dx; L.mana_cost.y = init.mana_cost.y + dy; }
      else if (k === 'type_line') { L.type_line.x = init.type_line.x + dx; L.type_line.y = init.type_line.y + dy; }
      else if (k === 'set_symbol') { L.set_symbol.x = init.set_symbol.x + dx; L.set_symbol.y = (init.set_symbol.y ?? 620) + dy; }
      else if (k === 'oracle_box') { L.oracle_box.x = init.oracle_box.x + dx; L.oracle_box.y = init.oracle_box.y + dy; }
      else if (k === 'pt_text') { L.pt_text.x = init.pt_text.x + dx; L.pt_text.y = init.pt_text.y + dy; }
      else if (k === 'artist') { L.artist.x = init.artist.x + dx; L.artist.y = init.artist.y + dy; }
      else if (ADVENTURE_KEYS.includes(k)) { L[k].x = init[k].x + dx; L[k].y = init[k].y + dy; }
      else if (k.startsWith('shape:') && Array.isArray(card.shapes)) {
        const sid = k.slice(6);
        const sInit = (dragState.initialShapes || []).find((s) => s.id === sid);
        const sCur = card.shapes.find((s) => s.id === sid);
        if (sInit && sCur) { sCur.x = sInit.x + dx; sCur.y = sInit.y + dy; }
      }
    } else if (dragState.mode === 'resize') {
      const h = dragState.handle;
      if (k.startsWith('shape:') && Array.isArray(card.shapes)) {
        const sid = k.slice(6);
        const sInit = (dragState.initialShapes || []).find((s) => s.id === sid);
        const sCur = card.shapes.find((s) => s.id === sid);
        if (sInit && sCur) {
          let nx = sInit.x, ny = sInit.y, nw = sInit.w, nh = sInit.h;
          if (h.includes('e')) nw = Math.max(20, sInit.w + dx);
          if (h.includes('s')) nh = Math.max(20, sInit.h + dy);
          if (h.includes('w')) { const pw = sInit.w - dx; if (pw >= 20) { nw = pw; nx = sInit.x + dx; } }
          if (h.includes('n')) { const ph = sInit.h - dy; if (ph >= 20) { nh = ph; ny = sInit.y + dy; } }
          sCur.x = nx; sCur.y = ny; sCur.w = nw; sCur.h = nh;
        }
      } else if (k === 'art') {
        const initArt = init.art;
        let nx = initArt.x, ny = initArt.y, nw = initArt.w, nh = initArt.h;
        if (h.includes('e')) nw = Math.max(60, initArt.w + dx);
        if (h.includes('s')) nh = Math.max(40, initArt.h + dy);
        if (h.includes('w')) { const pw = initArt.w - dx; if (pw >= 60) { nw = pw; nx = initArt.x + dx; } }
        if (h.includes('n')) { const ph = initArt.h - dy; if (ph >= 40) { nh = ph; ny = initArt.y + dy; } }

        const artSrc = toSameOriginUrl(card.custom_art_data || card.art_crop_url || '');
        const artImg = imgCache.get(artSrc);
        if (artImg && (artImg.naturalWidth || artImg.width) > 0) {
          const imgW = artImg.naturalWidth || artImg.width;
          const imgH = artImg.naturalHeight || artImg.height;
          const initBase = Math.max(initArt.w / imgW, initArt.h / imgH) * (initArt.scale || 1.0);
          const initDrawW = imgW * initBase;
          const initDrawH = imgH * initBase;
          const initImgX = initArt.x + (initArt.w - initDrawW) / 2 + (initArt.offset_x || 0);
          const initImgY = initArt.y + (initArt.h - initDrawH) / 2 + (initArt.offset_y || 0);
          const initRight = initImgX + initDrawW;
          const initBottom = initImgY + initDrawH;

          // Keep image stationary when extending within its bounds; only zoom if box passes image edges.
          let kZoom = 1.0;
          if (nx + nw > initRight) kZoom = Math.max(kZoom, (nx + nw - initImgX) / initDrawW);
          if (nx < initImgX) kZoom = Math.max(kZoom, (initRight - nx) / initDrawW);
          if (ny + nh > initBottom) kZoom = Math.max(kZoom, (ny + nh - initImgY) / initDrawH);
          if (ny < initImgY) kZoom = Math.max(kZoom, (initBottom - ny) / initDrawH);
          kZoom = Math.max(kZoom, nw / initDrawW, nh / initDrawH);

          const newDrawW = initDrawW * kZoom;
          const newDrawH = initDrawH * kZoom;

          let targetImgX = (h.includes('w') && nx < initImgX) ? (initRight - newDrawW) : initImgX;
          if (targetImgX > nx) targetImgX = nx;
          if (targetImgX + newDrawW < nx + nw) targetImgX = nx + nw - newDrawW;

          let targetImgY = (h.includes('n') && ny < initImgY) ? (initBottom - newDrawH) : initImgY;
          if (targetImgY > ny) targetImgY = ny;
          if (targetImgY + newDrawH < ny + nh) targetImgY = ny + nh - newDrawH;

          const newBase1 = Math.max(nw / imgW, nh / imgH);
          L.art.x = nx; L.art.y = ny; L.art.w = nw; L.art.h = nh;
          L.art.scale = Math.max(0.1, Math.min(8.0, newDrawW / (imgW * newBase1)));
          L.art.offset_x = targetImgX - (nx + (nw - newDrawW) / 2);
          L.art.offset_y = targetImgY - (ny + (nh - newDrawH) / 2);
        } else {
          L.art.x = nx; L.art.y = ny; L.art.w = nw; L.art.h = nh;
        }
      } else if (k === 'oracle_box' || k === 'adventure_oracle_box') {
        let nx = init[k].x, ny = init[k].y, nw = init[k].w, nh = init[k].h;
        if (h.includes('e')) nw = Math.max(60, init[k].w + dx);
        if (h.includes('s')) nh = Math.max(40, init[k].h + dy);
        if (h.includes('w')) { const pw = init[k].w - dx; if (pw >= 60) { nw = pw; nx = init[k].x + dx; } }
        if (h.includes('n')) { const ph = init[k].h - dy; if (ph >= 40) { nh = ph; ny = init[k].y + dy; } }
        L[k].x = nx; L[k].y = ny; L[k].w = nw; L[k].h = nh;
      } else if (['title', 'type_line', 'official_title', 'adventure_title', 'adventure_type_line'].includes(k)) {
        if (h.includes('e')) L[k].max_w = Math.max(100, (init[k].max_w || 470) + dx);
        if (h.includes('w')) { L[k].x = init[k].x + dx; L[k].max_w = Math.max(100, (init[k].max_w || 470) - dx); }
        if (h.includes('s') || h.includes('n')) {
          const df = h.includes('s') ? dy : -dy;
          L[k].font_size = Math.max(10, Math.min(72, (init[k].font_size || 28) + df * 0.5));
        }
      } else if (k === 'mana_cost' || k === 'adventure_mana_cost') {
        const delta = h.includes('s') || h.includes('e') ? dy + dx * 0.3 : -(dy + dx * 0.3);
        L[k].size = Math.max(14, Math.min(64, (init[k].size || 28) + delta * 0.4));
      } else if (k === 'set_symbol') {
        const delta = h.includes('s') || h.includes('e') ? dy : -dy;
        L.set_symbol.size = Math.max(16, Math.min(72, (init.set_symbol.size || 32) + delta * 0.5));
      } else if (k === 'pt_text') {
        const dir = h.includes('s') || h.includes('e') ? 1 : -1;
        L.pt_text.font_size = Math.max(16, Math.min(64, (init.pt_text.font_size || 34) + (dy + dx * 0.5) * dir * 0.4));
      } else if (k === 'artist') {
        const delta = h.includes('s') ? dy : -dy;
        L.artist.font_size = Math.max(10, Math.min(36, (init.artist.font_size || 16) + delta * 0.4));
      }
    }

    syncArtInputsFromLayout(L);
    scheduleRender(card);
  });

  window.addEventListener('mouseup', () => {
    if (!dragState) return;
    const card = getActiveCard();
    const mode = dragState.mode;
    const changed = dragState.changed;
    const preSnap = dragState.preDragSnap;
    dragState = null;

    if (mode === 'draw-shape' && draftShape && card) {
      const s = { ...draftShape };
      draftShape = null;
      if (s.w < 16 && s.h < 16) {
        s.w = 260;
        s.h = 120;
        s.x = Math.max(10, Math.min(740 - s.w, Math.round(s.x - s.w / 2)));
        s.y = Math.max(10, Math.min(1040 - s.h, Math.round(s.y - s.h / 2)));
      }
      if (preSnap) pushUndoState(card, preSnap);
      if (!Array.isArray(card.shapes)) card.shapes = [];
      card.shapes.push(s);
      const key = `shape:${s.id}`;
      if (!Array.isArray(card.layer_order)) {
        card.layer_order = [...DEFAULT_LAYER_ORDER];
      }
      card.layer_order.push(key);
      card.layer_opacities = card.layer_opacities || {};
      card.layer_opacities[key] = s.opacity ?? 0.55;
      selectedElementKey = key;
      setActiveTool('select');
      layerManager?.setSelected(key);
      layerManager?.render(card);
      renderCardCanvas(card);
      persistState(true);
      return;
    }

    if (card) {
      if (changed && preSnap) pushUndoState(card, preSnap);
      renderCardCanvas(card);
      if (changed) persistState(true);
    }
  });
}

async function exportCardsBatch(cards, face, format, dpi, singleCard = false) {
  const rootDir = getActiveRootDir();
  if (!rootDir) return showToast('Create or load a project on Home first.');

  const projectIds = cards
    .map((c) => c.project_id || c.id || state.project?.project_id)
    .filter(Boolean);
  if (!projectIds.length) {
    if (state.project) return exportCard();
    return showToast('No project cards available for export.');
  }

  setGlobalLoading(true, `Exporting ${projectIds.length} card(s)...`);
  try {
    captureActiveFaceEdits();
    // Describe each face as the preview draws it (frames, art, shapes and text). Double-faced
    // cards send both faces: the server writes face 2 to cards/backs for the Deck Generator.
    const frameSpecs = {};
    for (const c of cards) {
      const pid = c.project_id || c.id || state.project?.project_id;
      if (!pid || frameSpecs[pid]) continue;
      try {
        const isOpen = pid === state.project?.project_id;
        let project = isOpen ? state.project : null;
        if (!project) {
          const pr = await fetch(`/api/card-builder/project/${encodeURIComponent(pid)}`);
          if (pr.ok) project = await pr.json();
        }
        const faces = project?.faces || [];
        const specs = {};
        for (const [pos, f] of faces.slice(0, 2).entries()) {
          const idx = f.face_index ?? pos;
          let faceCard;
          if (isOpen && idx === state.faceIndex) {
            // The face on screen: the live card object.
            faceCard = c;
          } else if (!c.faces_ui && !isOpen && pos === 0) {
            // Card saved before per-face edits existed: its fields are face 1's.
            faceCard = c;
          } else {
            // Project defaults for this face, then the edits saved for it (if any).
            faceCard = { id: pid, project_id: pid, set: project.set || c.set, count: c.count };
            syncCardWithProjectFace(faceCard, f, project);
            applyFaceSnapshot(faceCard, c.faces_ui?.[String(idx)], f);
          }
          syncProjectFaceFromCard(faceCard, f);
          const spec = await buildCardExportSpec(faceCard, f, { set_symbol: project.set_symbol });
          if (spec) specs[idx] = spec;
        }
        if (Object.keys(specs).length) frameSpecs[pid] = specs;
      } catch {}
    }
    const resp = await fetch('/api/card-builder/export-batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        root_dir: rootDir,
        project_ids: projectIds,
        frame_specs: frameSpecs,
        face,
        export_format: format,
        export_dpi: dpi,
      }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) return showToast(data.detail || 'Error exporting cards');
    const backsNote = data.back_count ? ` + ${data.back_count} back face(s) to ${data.backs_dir}` : '';
    showToast(`Exported ${data.exported_count || projectIds.length} card(s) to ${data.dest_dir}${backsNote}`);
  } finally {
    setGlobalLoading(false);
  }
}

function bindChangeArtModal() {
  const modal = document.getElementById('cb-change-art-modal');
  const closeBtn = document.getElementById('cb-ca-close');
  const tabs = modal.querySelectorAll('.cb-ca-tab');
  const panels = {
    json: document.getElementById('cb-ca-panel-json'),
    scryfall: document.getElementById('cb-ca-panel-scryfall'),
    mpcfill: document.getElementById('cb-ca-panel-mpcfill'),
    wikimedia: document.getElementById('cb-ca-panel-wikimedia'),
    upload: document.getElementById('cb-ca-panel-upload'),
  };

  function selectArt(url, artist) {
    if (pendingProjectArt) {
      pendingProjectArt = false;
      modal.classList.remove('open');
      applyProjectArt(url);
      return;
    }
    const card = getActiveCard();
    if (!card) return;
    card.custom_art_data = url.startsWith('data:') ? url : '';
    if (!url.startsWith('data:')) card.art_crop_url = url;
    if (artist) card.artist = artist;
    modal.classList.remove('open');
    renderCardCanvas(card);
    persistState(true);
    showToast('Artwork applied');
  }

  function updatePinterestLink(queryText) {
    const link = document.getElementById('cb-ca-pinterest-link');
    if (!link) return;
    const q = (queryText || '').trim();
    const fullQ = q ? `${q} mtg art` : 'mtg art';
    link.href = `https://www.pinterest.com/search/pins/?q=${encodeURIComponent(fullQ)}`;
  }

  document.getElementById('cb-change-art-btn').addEventListener('click', () => {
    const card = getActiveCard();
    if (!card) return;
    const defaultQ = (card.official_name || card.original_name || card.name || '').trim();
    document.getElementById('cb-ca-json-q').value = defaultQ;
    document.getElementById('cb-ca-sf-q').value = defaultQ;
    const mpcQ = document.getElementById('cb-ca-mpc-q');
    const wmQ = document.getElementById('cb-ca-wm-q');
    if (mpcQ) mpcQ.value = defaultQ;
    if (wmQ) wmQ.value = defaultQ;
    updatePinterestLink(defaultQ);
    modal.classList.add('open');
    searchLocalJsonArt();
  });

  ['cb-ca-json-q', 'cb-ca-sf-q', 'cb-ca-mpc-q', 'cb-ca-wm-q'].forEach((id) => {
    document.getElementById(id)?.addEventListener('input', (e) => updatePinterestLink(e.target.value));
  });
  closeBtn.addEventListener('click', () => modal.classList.remove('open'));

  tabs.forEach((btn) => {
    btn.addEventListener('click', () => {
      tabs.forEach((b) => b.classList.remove('btn-primary'));
      btn.classList.add('btn-primary');
      Object.values(panels).forEach((p) => { if (p) p.style.display = 'none'; });
      const targetPanel = panels[btn.dataset.tab];
      if (targetPanel) targetPanel.style.display = 'block';
      if (btn.dataset.tab === 'mpcfill' && !document.getElementById('cb-ca-mpc-grid')?.children.length) {
        searchMpcFillArt();
      } else if (btn.dataset.tab === 'wikimedia' && !document.getElementById('cb-ca-wm-grid')?.children.length) {
        searchWikimediaArt();
      } else if (btn.dataset.tab === 'scryfall' && !document.getElementById('cb-ca-sf-grid')?.children.length) {
        searchScryfallPrints();
      }
    });
  });

  async function searchLocalJsonArt() {
    const q = document.getElementById('cb-ca-json-q').value.trim();
    const grid = document.getElementById('cb-ca-json-grid');
    grid.innerHTML = 'Searching...';
    try {
      const resp = await fetch(`/api/art/search?q=${encodeURIComponent(q)}&limit=36`);
      const data = await resp.json();
      grid.innerHTML = '';
      if (!resp.ok || !data.results?.length) {
        grid.innerHTML = `
          <div style="grid-column:1/-1; color:var(--text-muted); display:flex; flex-direction:column; gap:8px; align-items:flex-start;">
            <span>No matches found for "${q}" in local JSONs.</span>
            <button type="button" class="btn btn-sm btn-primary" id="cb-ca-jump-sf">🔍 Search "${q}" on Scryfall</button>
          </div>`;
        grid.querySelector('#cb-ca-jump-sf')?.addEventListener('click', () => {
          modal.querySelector('.cb-ca-tab[data-tab="scryfall"]')?.click();
          document.getElementById('cb-ca-sf-q').value = q;
          searchScryfallPrints();
        });
        return;
      }
    data.results.forEach((it) => {
      const el = document.createElement('div');
      el.className = 'art-result-card';
      el.innerHTML = `<img src="${toSameOriginUrl(it.image_url)}" loading="lazy"><div style="font-size:11px; font-weight:600;">${it.name}</div><div style="font-size:10px; color:var(--text-muted);">${it.set || ''} ${it.artist || ''}</div>`;
      el.addEventListener('click', () => selectArt(it.image_url, it.artist));
      grid.appendChild(el);
    });
    } catch (err) {
      grid.innerHTML = '<p style="color:var(--danger);">Error consultando el índice JSON local.</p>';
    }
  }

  async function searchScryfallPrints() {
    const q = document.getElementById('cb-ca-sf-q').value.trim();
    const grid = document.getElementById('cb-ca-sf-grid');
    grid.innerHTML = 'Querying Scryfall...';
    const resp = await fetch(`/api/art/scryfall-prints?name=${encodeURIComponent(q)}`);
    const data = await resp.json();
    grid.innerHTML = '';
    if (!data.prints?.length) {
      grid.innerHTML = '<p style="color:var(--text-muted);">No results found on Scryfall.</p>';
      return;
    }
    data.prints.forEach((it) => {
      const el = document.createElement('div');
      el.className = 'art-result-card';
      el.innerHTML = `<img src="${toSameOriginUrl(it.art_crop_url)}" loading="lazy"><div style="font-size:11px; font-weight:600;">${it.set}</div><div style="font-size:10px; color:var(--text-muted);">${it.artist || ''}</div>`;
      el.addEventListener('click', () => selectArt(it.art_crop_url, it.artist));
      grid.appendChild(el);
    });
  }

  async function searchMpcFillArt() {
    const q = (document.getElementById('cb-ca-mpc-q')?.value || '').trim();
    const grid = document.getElementById('cb-ca-mpc-grid');
    if (!grid || !q) return;
    grid.innerHTML = 'Querying MPCFill...';
    try {
      const resp = await fetch(`/api/art/mpcfill?q=${encodeURIComponent(q)}&limit=36`);
      const data = await resp.json();
      grid.innerHTML = '';
      if (!resp.ok || !data.results?.length) {
        grid.innerHTML = `<p style="color:var(--text-muted); grid-column:1/-1;">No results found on MPCFill for "${q}".</p>`;
        return;
      }
      data.results.forEach((it) => {
        const el = document.createElement('div');
        el.className = 'art-result-card';
        const dpiBadge = it.dpi ? `${it.dpi} DPI · ` : '';
        el.innerHTML = `<img src="${toSameOriginUrl(it.thumb_url)}" loading="lazy"><div style="font-size:11px; font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${it.name}</div><div style="font-size:10px; color:var(--text-muted);">${dpiBadge}${it.source || 'MPCFill'}</div>`;
        el.addEventListener('click', () => {
          const mode = document.querySelector('input[name="cb-ca-mpc-mode"]:checked')?.value || 'crop';
          if (mode === 'full_card') {
            const card = getActiveCard();
            if (!card) return;
            pushUndoState(card);
            card.custom_art_data = '';
            card.art_crop_url = `/api/art/proxy?url=${encodeURIComponent(it.image_url)}&trim_bleed=1`;
            const L = ensureCardLayout(card);
            L.art = { x: 0, y: 0, w: 750, h: 1050, scale: 1.0, offset_x: 0, offset_y: 0 };
            card.art_over_top = false;
            card.hide_card_text = true;
            card.hidden_layers = {
              ...(card.hidden_layers || {}),
              background: true,
              pinlines: true,
              name_box: true,
              crown: true,
              border: true,
              pt_box: true,
            };
            delete card.hidden_layers.art;
            modal.classList.remove('open');
            populateDetailControls(card);
            renderCardCanvas(card);
            persistState(true);
            showToast('Full MPCFill card applied — toggle vector layers in Layer Manager anytime');
          } else {
            const card = getActiveCard();
            if (card && card.hide_card_text) {
              pushUndoState(card);
              card.hide_card_text = false;
              const L = ensureCardLayout(card);
              L.art = { ...DEFAULT_LAYOUT.art };
              card.hidden_layers = card.hidden_layers || {};
              ['background', 'pinlines', 'name_box', 'crown', 'pt_box'].forEach((k) => {
                if (card.frame_components?.[k]) delete card.hidden_layers[k];
                else card.hidden_layers[k] = true;
              });
              card.hidden_layers.border = true;
              populateDetailControls(card);
            }
            const chosenUrl = `/api/art/proxy?url=${encodeURIComponent(it.image_url)}&crop_art=1`;
            selectArt(chosenUrl, it.source);
          }
        });
        grid.appendChild(el);
      });
    } catch {
      grid.innerHTML = '<p style="color:var(--danger); grid-column:1/-1;">Error querying MPCFill.</p>';
    }
  }

  async function searchWikimediaArt() {
    const q = (document.getElementById('cb-ca-wm-q')?.value || '').trim();
    const grid = document.getElementById('cb-ca-wm-grid');
    if (!grid || !q) return;
    grid.innerHTML = 'Querying Wikimedia Commons...';
    try {
      const resp = await fetch(`/api/art/wikimedia?q=${encodeURIComponent(q)}&limit=30`);
      const data = await resp.json();
      grid.innerHTML = '';
      if (!resp.ok || !data.results?.length) {
        grid.innerHTML = `<p style="color:var(--text-muted); grid-column:1/-1;">No results found on Wikimedia Commons for "${q}".</p>`;
        return;
      }
      data.results.forEach((it) => {
        const el = document.createElement('div');
        el.className = 'art-result-card';
        el.innerHTML = `<img src="${toSameOriginUrl(it.thumb_url)}" loading="lazy"><div style="font-size:11px; font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${it.title}</div><div style="font-size:10px; color:var(--text-muted);">${it.artist || 'Wikimedia'}</div>`;
        el.addEventListener('click', () => selectArt(it.image_url, it.artist));
        grid.appendChild(el);
      });
    } catch {
      grid.innerHTML = '<p style="color:var(--danger); grid-column:1/-1;">Error querying Wikimedia Commons.</p>';
    }
  }

  document.getElementById('cb-ca-json-btn').addEventListener('click', searchLocalJsonArt);
  document.getElementById('cb-ca-json-q').addEventListener('keydown', (e) => { if (e.key === 'Enter') searchLocalJsonArt(); });
  document.getElementById('cb-ca-sf-btn').addEventListener('click', searchScryfallPrints);
  document.getElementById('cb-ca-sf-q').addEventListener('keydown', (e) => { if (e.key === 'Enter') searchScryfallPrints(); });
  document.getElementById('cb-ca-mpc-btn')?.addEventListener('click', searchMpcFillArt);
  document.getElementById('cb-ca-mpc-q')?.addEventListener('keydown', (e) => { if (e.key === 'Enter') searchMpcFillArt(); });
  document.getElementById('cb-ca-wm-btn')?.addEventListener('click', searchWikimediaArt);
  document.getElementById('cb-ca-wm-q')?.addEventListener('keydown', (e) => { if (e.key === 'Enter') searchWikimediaArt(); });
  const upInput = document.getElementById('cb-ca-upload-input');
  document.getElementById('cb-ca-upload-btn').addEventListener('click', () => upInput.click());
  upInput.addEventListener('change', () => {
    const file = upInput.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => selectArt(reader.result, '');
    reader.readAsDataURL(file);
  });
}

let pendingProjectArt = false;

const PROJECT_TEXT_FIELDS = {
  'cb-field-name': 'title',
  'cb-field-mana': 'mana_cost',
  'cb-field-type': 'type_line',
  'cb-field-oracle': 'oracle_text',
  'cb-field-pt': 'pt',
  'cb-field-artist': 'collector_info',
};

function currentProjectFace() {
  const faces = state.project?.faces || [];
  return faces.find((f, idx) => (f.face_index ?? idx) === state.faceIndex) || faces[0] || null;
}

function projectFaceEntry(face, key) {
  face.text_layers = face.text_layers || {};
  if (!face.text_layers[key]) face.text_layers[key] = { text: '', bounds: null };
  return face.text_layers[key];
}

function projectFaceValue(face, key) {
  const entry = face?.text_layers?.[key];
  if (!entry) return '';
  if (key === 'pt') return [entry.power, entry.toughness].filter(Boolean).join('/');
  if (key === 'collector_info') return entry.artist || '';
  return entry.text || '';
}

function readProjectTextPanels(face) {
  if (!face) return null;
  for (const [id, key] of Object.entries(PROJECT_TEXT_FIELDS)) {
    const el = document.getElementById(id);
    if (!el) continue;
    const entry = projectFaceEntry(face, key);
    if (key === 'pt') {
      const [power, toughness] = el.value.split('/');
      entry.power = (power || '').trim() || null;
      entry.toughness = (toughness || '').trim() || null;
    } else if (key === 'collector_info') {
      entry.artist = el.value.trim() || null;
    } else {
      entry.text = el.value;
    }
  }
  return face;
}

function populateProjectTextPanels(face) {
  if (!face) return;
  for (const [id, key] of Object.entries(PROJECT_TEXT_FIELDS)) {
    const el = document.getElementById(id);
    if (el) el.value = projectFaceValue(face, key);
  }
}

function syncProjectFaceSelect() {
  const faces = state.project?.faces || [];
  ['cb-sf-face', 'cb-stage-face-select'].forEach((id) => {
    const sel = document.getElementById(id);
    if (!sel) return;
    sel.innerHTML = faces.length
      ? faces.map((f, idx) => {
        const val = f.face_index ?? idx;
        return `<option value="${val}">Cara ${idx + 1}${f.face_ref ? ` — ${f.face_ref}` : ''}</option>`;
      }).join('')
      : '<option value="0">Cara 1</option>';
    sel.value = String(state.faceIndex ?? 0);
  });
}

async function showProjectFace(faceIndex) {
  await ensureSymbolsCatalog();
  state.faceIndex = faceIndex;
  const face = currentProjectFace();
  ['cb-sf-face', 'cb-stage-face-select'].forEach((id) => {
    const sel = document.getElementById(id);
    if (sel) sel.value = String(state.faceIndex);
  });
  if (!face) return;

  let card = getActiveCard();
  if (!card && state.project) {
    card = {
      id: state.project.project_id,
      project_id: state.project.project_id,
      name: state.project.name || face.face_ref || 'Untitled',
      set: state.project.set || 'mtg',
      count: 1,
    };
    getCards().push(card);
    activeCardId = card.id;
  }

  if (card) {
    // Cards saved before per-face edits existed keep their edits as face 1's.
    const firstIndex = state.project?.faces?.[0]?.face_index ?? 0;
    const legacySnap = (!card.faces_ui && card.frame_components && !face._ui_state && faceIndex === firstIndex)
      ? faceEditsSnapshot(card, null)
      : null;
    syncCardWithProjectFace(card, face, state.project);
    const saved = card.faces_ui?.[String(face.face_index ?? faceIndex)] || legacySnap;
    if (saved) {
      applyFaceSnapshot(card, saved, face);
    } else {
      // First time this face is shown: its own printed name is the "original" one
      // (the other face's name must not leak into the official-title line).
      card.original_name = card.name || '';
      card.official_name = '';
      card._official_manually_edited = false;
    }
    updateFaceNames(card);
    populateDetailControls(card);
    // Show this face's template pack in the Layer Manager's Frame / P/T browsers.
    const facePos = (state.project?.faces || []).indexOf(face);
    layerManager?.setLayoutFilter(face.template || card.frame_components?.style || '', card, { backFace: facePos === 1 });
  } else {
    populateProjectTextPanels(face);
  }

  const legacyWrap = document.getElementById('cb-legacy-wrap');
  const projectWrap = document.getElementById('cb-project-wrap');
  if (legacyWrap) legacyWrap.style.display = 'none';
  if (projectWrap) projectWrap.style.display = 'flex';
  const canvasEl = document.getElementById('cb-project-canvas');
  if (canvasEl) {
    await renderProjectFace(face, _projectCleanCanvas, {
      card,
      set_symbol: state.project?.set_symbol,
    });
    canvasEl.width = _projectCleanCanvas.width;
    canvasEl.height = _projectCleanCanvas.height;
    canvasEl.style.maxWidth = '100%';
    canvasEl.style.height = 'auto';
    _projectCleanReady = true;
    paintProjectWithOverlays(canvasEl, card);
  }
}

function rememberProjectFaceEdits() {
  const face = currentProjectFace();
  if (!face) return;
  const card = getActiveCard();
  if (card) syncProjectFaceFromCard(card, face);
  captureActiveFaceEdits();
  readProjectTextPanels(face);
  state.faces[face.face_index ?? 0] = face.text_layers;
  state.dirty = true;
}

async function switchProjectFace(faceIndex) {
  const next = Number(faceIndex);
  if (!state.project || Number.isNaN(next) || next === state.faceIndex) return;
  rememberProjectFaceEdits();
  await showProjectFace(next);
}

async function importFromScryfall() {
  const statusEl = document.getElementById('cb-sf-status');
  const errorEl = document.getElementById('cb-sf-error');
  if (errorEl) errorEl.style.display = 'none';
  if (statusEl) statusEl.textContent = 'Importing from Scryfall...';
  const faceIndexRaw = document.getElementById('cb-sf-face')?.value;
  const faceIndex = faceIndexRaw !== undefined && faceIndexRaw !== '' ? Number(faceIndexRaw) : null;
  const rawJson = (document.getElementById('cb-sf-json')?.value || '').trim();
  const payload = {
    card: rawJson ? JSON.parse(rawJson) : null,
    url: (document.getElementById('cb-sf-url')?.value || '').trim(),
    name: (document.getElementById('cb-sf-name')?.value || '').trim(),
    set: (document.getElementById('cb-sf-set')?.value || '').trim(),
    face_index: null,
    showcase_style_override: (document.getElementById('cb-sf-showcase')?.value || '').trim(),
    root_dir: getActiveRootDir(),
  };
  let resp;
  try {
    resp = await fetch('/api/card-builder/import-scryfall', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    if (errorEl) { errorEl.textContent = String(err); errorEl.style.display = 'block'; }
    if (statusEl) statusEl.textContent = '';
    return;
  }
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({ detail: `HTTP ${resp.status}` }));
    if (errorEl) { errorEl.textContent = detail.detail || `HTTP ${resp.status}`; errorEl.style.display = 'block'; }
    if (statusEl) statusEl.textContent = '';
    return;
  }
  const project = await resp.json();
  const edits = state.faces || {};
  state.project = project;
  state.faces = {};
  (project.faces || []).forEach((face) => {
    const saved = edits[face.face_index ?? 0];
    face.text_layers = face.text_layers || {};
    if (saved) {
      Object.entries(saved).forEach(([key, entry]) => {
        face.text_layers[key] = { ...(face.text_layers[key] || {}), ...entry };
      });
    }
    state.faces[face.face_index ?? 0] = face.text_layers;
  });
  state.faceIndex = (faceIndex !== null && (project.faces || []).some((f) => f.face_index === faceIndex))
    ? faceIndex
    : (project.faces?.[0]?.face_index ?? 0);
  state.dirty = false;

  let existingCard = getCards().find((c) => c.project_id === project.project_id || c.id === project.project_id);
  if (!existingCard) {
    existingCard = {
      id: project.project_id,
      project_id: project.project_id,
      name: project.name || project.faces?.[0]?.face_ref || 'Untitled',
      set: project.set || 'mtg',
      art_crop_url: project.faces?.[0]?.art_layer?.url || '',
      count: 1,
    };
    getCards().push(existingCard);
  }
  activeCardId = existingCard.id;

  syncProjectFaceSelect();
  listsView.style.display = 'none';
  detailView.style.display = 'flex';
  await showProjectFace(state.faceIndex);
  const warnings = [...(project.warnings || []), ...(project.faces || []).flatMap((f) => f.warnings || [])];
  if (statusEl) statusEl.textContent = warnings.length ? `Imported. Warnings: ${warnings.join(', ')}` : 'Imported.';
  document.getElementById('cb-sf-import-modal')?.classList.remove('open');
}

// DPI of the two single-card export buttons; keep in sync with their labels in card_builder.html.
const SINGLE_PDF_EXPORT_DPI = 1200;
const SINGLE_PNG_EXPORT_DPI = 600;

async function exportCard() {
  const errorEl = document.getElementById('cb-sf-error');
  if (!state.project) return;
  const face = currentProjectFace();
  const card = getActiveCard();
  if (card && face) syncProjectFaceFromCard(card, face);
  const payload = {
    project_id: state.project.project_id,
    face_index: state.faceIndex,
    text_layers: face?.text_layers || null,
    frame_spec: card ? await buildCardExportSpec(card, face, { set_symbol: state.project?.set_symbol }) : null,
    export_dpi: SINGLE_PNG_EXPORT_DPI,
  };
  if (face?.art_layer?.url?.startsWith('data:image/')) {
    payload.art_override_dataurl = face.art_layer.url;
  }
  const resp = await fetch('/api/card-builder/export', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (resp.status !== 200) {
    const detail = await resp.json().catch(() => ({ detail: `HTTP ${resp.status}` }));
    if (errorEl) { errorEl.textContent = detail.detail || `HTTP ${resp.status}`; errorEl.style.display = 'block'; }
    return;
  }
  const blob = await resp.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${state.project.name || state.project.project_id}-face${state.faceIndex}.png`;
  a.click();
  URL.revokeObjectURL(a.href);
}

async function applyProjectArt(url) {
  const face = currentProjectFace();
  if (!face || !url) return;
  face.art_layer = { ...(face.art_layer || {}), url };
  const card = getActiveCard();
  if (card) {
    if (url.startsWith('data:')) card.custom_art_data = url;
    else { card.custom_art_data = ''; card.art_crop_url = url; }
  }
  state.dirty = true;
  const canvasEl = document.getElementById('cb-project-canvas');
  if (canvasEl) await renderProjectFace(face, canvasEl, { card, set_symbol: state.project?.set_symbol });
}

async function upscaleDataUrl(dataUrl, factor) {
  const img = await loadImageElement(dataUrl);
  const target = document.createElement('canvas');
  target.width = img.naturalWidth * factor;
  target.height = img.naturalHeight * factor;
  const targetCtx = target.getContext('2d');
  targetCtx.imageSmoothingEnabled = true;
  targetCtx.imageSmoothingQuality = 'high';
  targetCtx.drawImage(img, 0, 0, target.width, target.height);
  return target.toDataURL('image/png');
}

function openArtMenu() {
  document.getElementById('cb-art-menu')?.remove();
  const menu = document.createElement('div');
  menu.id = 'cb-art-menu';
  menu.style.cssText = 'position:fixed; z-index:9999; top:110px; left:50%; transform:translateX(-50%); background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-sm); padding:10px; display:flex; flex-direction:column; gap:8px; min-width:230px; box-shadow:0 12px 30px rgba(0,0,0,0.35);';
  const fileInput = document.createElement('input');
  fileInput.type = 'file';
  fileInput.accept = 'image/png,image/jpeg,image/webp';
  fileInput.hidden = true;
  fileInput.addEventListener('change', async () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    const raw = await new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.readAsDataURL(file);
    });
    const factor = Number(document.getElementById('cb-ca-upscale')?.value || 1);
    await applyProjectArt(factor > 1 ? await upscaleDataUrl(raw, factor) : raw);
    menu.remove();
  });
  const uploadBtn = document.createElement('button');
  uploadBtn.type = 'button';
  uploadBtn.className = 'btn btn-sm';
  uploadBtn.textContent = 'Upload image';
  uploadBtn.addEventListener('click', () => fileInput.click());
  const searchBtn = document.createElement('button');
  searchBtn.type = 'button';
  searchBtn.className = 'btn btn-sm';
  searchBtn.textContent = 'Search art library';
  searchBtn.addEventListener('click', () => {
    pendingProjectArt = true;
    menu.remove();
    document.getElementById('cb-change-art-btn')?.click();
  });
  const upscaleBtn = document.createElement('button');
  upscaleBtn.type = 'button';
  upscaleBtn.className = 'btn btn-sm';
  upscaleBtn.textContent = 'Upscale current art';
  upscaleBtn.addEventListener('click', async () => {
    const face = currentProjectFace();
    const factor = Number(document.getElementById('cb-ca-upscale')?.value || 1);
    if (face?.art_layer?.url && factor > 1) await applyProjectArt(await upscaleDataUrl(face.art_layer.url, factor));
    menu.remove();
  });
  menu.append(uploadBtn, searchBtn, upscaleBtn, fileInput);
  document.body.appendChild(menu);
}

function bindProjectPanels() {
  document.getElementById('cb-scryfall-import-btn')?.addEventListener('click', () => {
    const statusEl = document.getElementById('cb-sf-status');
    const errorEl = document.getElementById('cb-sf-error');
    if (statusEl) statusEl.textContent = '';
    if (errorEl) errorEl.style.display = 'none';
    syncProjectFaceSelect();
    document.getElementById('cb-sf-import-modal')?.classList.add('open');
  });
  document.getElementById('cb-sf-close')?.addEventListener('click', () => {
    document.getElementById('cb-sf-import-modal')?.classList.remove('open');
  });
  document.getElementById('cb-sf-cancel')?.addEventListener('click', () => {
    document.getElementById('cb-sf-import-modal')?.classList.remove('open');
  });
  document.getElementById('cb-sf-import')?.addEventListener('click', importFromScryfall);
  document.getElementById('cb-sf-face')?.addEventListener('change', (e) => switchProjectFace(e.target.value));
  document.getElementById('cb-stage-face-select')?.addEventListener('change', (e) => switchProjectFace(e.target.value));
  document.getElementById('cb-export-single-png-btn')?.addEventListener('click', exportCard);
  document.getElementById('cb-replace-art-btn')?.addEventListener('click', openArtMenu);
}

(async function init() {
  if (document.fonts && document.fonts.ready) {
    await Promise.allSettled([
      document.fonts.load('bold 24px "BelerenLocal"'),
      document.fonts.load('24px "MPlantinLocal"'),
      document.fonts.ready,
    ]);
    document.fonts.addEventListener('loadingdone', () => {
      const c = getActiveCard();
      if (c) renderCardCanvas(c);
    });
  }
  workspaceState = await loadActiveWorkspaceState();
  const symCat = await ensureSymbolsCatalog();
  catalog = {};
  const tplNames = Object.keys(symCat.templates || {});
  const roleFrames = symCat.frames_by_role || {};
  (tplNames.length ? tplNames : ['M15Regular']).forEach((k) => {
    catalog[k] = roleFrames;
  });

  const styleKeys = Object.keys(catalog);
  ['cb-detail-style-select'].forEach((id) => {
    const sel = document.getElementById(id);
    if (!sel) return;
    sel.innerHTML = styleKeys.length
      ? styleKeys.map((k) => `<option value="${k}" title="${k}">${styleDisplayName(k)}</option>`).join('')
      : '<option value="M15Regular">M15Regular</option>';
  });

  layerManager = new LayerManager(
    document.getElementById('cb-layer-list'),
    (changedCard) => {
      const card = changedCard || getActiveCard();
      if (card) {
        const popEl = document.getElementById('cb-art-over-top');
        if (popEl) popEl.checked = Boolean(card.art_over_top);
        renderCardCanvas(card);
        persistState(true);
      }
    },
    (selectedKey, changedCard) => {
      selectedElementKey = selectedKey || null;
      const card = changedCard || getActiveCard();
      if (card) renderCardCanvas(card);
    }
  );

  cropModal = new CropMaskModal(document.getElementById('cb-crop-modal'), (dataUrl, maskType) => {
    const card = getActiveCard();
    if (!card) return;
    pushUndoState(card);
    card.custom_art_data = dataUrl;
    card.crop_mask = maskType;
    if (maskType === 'borderless_bottom_curve') {
      const L = ensureCardLayout(card);
      L.art = { x: 0, y: 0, w: 750, h: 970, scale: 1.0, offset_x: 0, offset_y: 0 };
      const scEl = document.getElementById('cb-art-scale');
      const scValEl = document.getElementById('cb-art-scale-val');
      if (scEl) scEl.value = 1.0;
      if (scValEl) scValEl.textContent = '1.00';
    }
    renderCardCanvas(card);
    persistState(true);
    showToast('Crop mask applied');
  });

  bindDetailEvents();
  bindChangeArtModal();
  bindProjectPanels();
  renderLists();

  document.getElementById('nav-save-state-btn')?.addEventListener('click', () => persistState(false));
  filterInput.addEventListener('input', renderLists);
  readyFilterSel?.addEventListener('change', () => {
    try { localStorage.setItem(READY_FILTER_KEY, readyFilterSel.value); } catch {}
    boardLargeIndex = 0;
    renderLists();
  });

  document.getElementById('cb-select-all-btn')?.addEventListener('click', () => {
    const visible = visibleBoardCards();
    if (!visible.length) return;
    const readySet = getReadyIds();
    const allSelected = visible.every((c) => readySet.has(c.id));
    visible.forEach((c) => {
      if (allSelected) readySet.delete(c.id);
      else readySet.add(c.id);
    });
    ensureCardBuilderState().ready_ids = [...readySet];
    renderLists();
    persistState(true);
  });

  // A /search response holds results / cards array from Scryfall search.
  async function addSearchedCards(data, count) {
    const rawList = data?.cards?.length ? data.cards : (data?.results?.length ? data.results : (data?.card ? [data.card] : []));
    if (!rawList.length) return [];
    const target = rawList[0];
    try {
      const impResp = await fetch('/api/card-builder/import-scryfall', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scryfall_id: target.id,
          name: target.name,
          set: target.set,
          root_dir: getActiveRootDir(),
        }),
      });
      if (impResp.ok) {
        const project = await impResp.json();
        const cardItem = {
          ...target,
          id: project.project_id,
          project_id: project.project_id,
          art_crop_url: project.faces?.[0]?.art_layer?.url || target.art_crop_url || target.art_crop || '',
          count: count || 1,
        };
        getCards().push(cardItem);
        return [cardItem];
      }
    } catch {}
    if (count) target.count = count;
    getCards().push(target);
    return [target];
  }

  const searchPickerModal = document.getElementById('cb-search-picker-modal');
  const searchPickerClose = document.getElementById('cb-search-picker-close');
  const searchPickerGrid = document.getElementById('cb-search-picker-grid');
  const searchPickerSub = document.getElementById('cb-search-picker-sub');
  searchPickerClose?.addEventListener('click', () => searchPickerModal?.classList.remove('open'));
  searchPickerModal?.addEventListener('click', (e) => {
    if (e.target === searchPickerModal) searchPickerModal.classList.remove('open');
  });

  function openSearchPickerModal(query, results) {
    if (!searchPickerModal || !searchPickerGrid) return;
    if (searchPickerSub) {
      searchPickerSub.textContent = `Found ${results.length} matches for "${query}". Click the card you want to add:`;
    }
    searchPickerGrid.innerHTML = '';
    results.forEach((item) => {
      const tile = document.createElement('div');
      tile.className = 'art-result-card';
      tile.style.cursor = 'pointer';
      const imgUrl = toSameOriginUrl(item.image || item.art_crop || '');
      tile.innerHTML = `
        <img src="${imgUrl}" loading="lazy" alt="${item.name || ''}" style="width:100%; aspect-ratio:5/7; object-fit:cover; border-radius:4px; background:#111;">
        <div style="font-size:11px; font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${item.name || ''}">${item.name || ''}</div>
        <div style="font-size:10px; color:var(--text-muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${(item.set || '').toUpperCase()} · ${item.type_line || ''}</div>
      `;
      tile.addEventListener('click', async () => {
        searchPickerModal.classList.remove('open');
        setGlobalLoading(true, `Importing ${item.name}...`);
        try {
          const added = await addSearchedCards({ results: [item] });
          renderLists();
          persistState(true);
          showToast(`Added: ${added.map((c) => c.name).join(' + ')}`);
        } finally {
          setGlobalLoading(false);
        }
      });
      searchPickerGrid.appendChild(tile);
    });
    searchPickerModal.classList.add('open');
  }

  async function runBoardCardSearch() {
    const q = document.getElementById('cb-search-input').value.trim();
    if (!q) return;
    const tokens = !!document.getElementById('cb-search-tokens')?.checked;
    setGlobalLoading(true, `Searching ${tokens ? 'tokens ' : ''}${q}...`);
    try {
      const resp = await fetch('/api/card-builder/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q, tokens, root_dir: getActiveRootDir() }),
      });
      const data = await resp.json();
      if (!resp.ok) return showToast(data.detail || 'Card not found');
      const results = Array.isArray(data.results) ? data.results : [];
      if (!results.length && !data.card) {
        return showToast(`No ${tokens ? 'tokens' : 'cards'} found for "${q}"`);
      }
      if (results.length > 1) {
        setGlobalLoading(false);
        openSearchPickerModal(q, results);
        return;
      }
      const added = await addSearchedCards(data);
      renderLists();
      persistState(true);
      showToast(`Added: ${added.map((c) => c.name).join(' + ')}`);
    } finally {
      setGlobalLoading(false);
    }
  }

  document.getElementById('cb-search-btn').addEventListener('click', runBoardCardSearch);
  document.getElementById('cb-search-input')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') runBoardCardSearch();
  });

  function parseMtgoLines(text) {
    const entries = [];
    for (const rawLine of text.split(/\r?\n/)) {
      const line = rawLine.trim();
      if (!line || line.startsWith('//') || /^(sideboard|commander|companion|deck)$/i.test(line)) continue;
      const m = line.match(/^(\d+)[xX]?\s+(.+?)(?:\s+\([A-Za-z0-9]+\)\s*\d*.*)?$/);
      if (m) {
        entries.push({ count: parseInt(m[1], 10) || 1, name: m[2].trim() });
      } else {
        entries.push({ count: 1, name: line });
      }
    }
    return entries;
  }

  const txtInput = document.getElementById('cb-import-txt-input');
  const txtBtn = document.getElementById('cb-import-txt-btn');
  txtBtn.addEventListener('click', () => txtInput.click());
  txtInput.addEventListener('change', async () => {
    const file = txtInput.files?.[0];
    if (!file) return;
    const content = await file.text();
    txtInput.value = '';
    const entries = parseMtgoLines(content);
    if (!entries.length) return showToast('The .txt file contains no valid cards.');

    ensureCardBuilderState().txt_manifest = {
      filename: file.name,
      entries: entries.map((e) => ({ name: e.name, count: e.count })),
    };

    const modal = document.getElementById('cb-import-progress-modal');
    const txtEl = document.getElementById('cb-import-progress-text');
    const barEl = document.getElementById('cb-import-progress-bar');
    const subEl = document.getElementById('cb-import-progress-sub');

    txtBtn.disabled = true;
    modal.classList.add('open');
    barEl.style.width = '0%';
    subEl.textContent = `0 / ${entries.length}`;

    let imported = 0;
    const styleKey = ensureCardBuilderState().global_frame_style || 'M15Regular';

    try {
      for (let i = 0; i < entries.length; i++) {
        const entry = entries[i];
        txtEl.textContent = `Downloading: ${entry.name}...`;
        try {
          const resp = await fetch('/api/card-builder/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: entry.name, count: entry.count, style_key: styleKey, root_dir: getActiveRootDir() }),
          });
          if (resp.ok) {
            const data = await resp.json();
            if ((await addSearchedCards(data, entry.count)).length) imported++;
          }
        } catch {}
        const pct = Math.round(((i + 1) / entries.length) * 100);
        barEl.style.width = `${pct}%`;
        subEl.textContent = `${i + 1} / ${entries.length} (${pct}%)`;
      }
      renderLists();
      await persistState(false);
      showToast(`Imported ${imported} of ${entries.length} cards`);
    } finally {
      txtBtn.disabled = false;
      modal.classList.remove('open');
    }
  });

  document.querySelectorAll('#cb-view-switcher .cb-view-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      boardViewMode = btn.dataset.view || 'grid';
      document.querySelectorAll('#cb-view-switcher .cb-view-btn').forEach((b) => {
        b.classList.toggle('btn-primary', b === btn);
      });
      renderLists();
    });
  });

  window.addEventListener('keydown', (e) => {
    if (boardViewMode !== 'large' || detailView.style.display !== 'none') return;
    const tag = (e.target?.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
    if (e.key === 'ArrowLeft') {
      loadedGrid.querySelector('.cb-large-prev')?.click();
    } else if (e.key === 'ArrowRight') {
      loadedGrid.querySelector('.cb-large-next')?.click();
    }
  });

  // --- .txt Deck Checklist Modal ---
  const txtCheckModal = document.getElementById('cb-txt-check-modal');
  const txtCheckClose = document.getElementById('cb-txt-check-close');

  async function retryFetchCardFromTxt(entry) {
    const styleKey = ensureCardBuilderState().global_frame_style || 'M15Regular';
    const resp = await fetch('/api/card-builder/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: entry.name, count: entry.count || 1, style_key: styleKey, root_dir: getActiveRootDir() }),
    });
    if (!resp.ok) return false;
    const data = await resp.json();
    return (await addSearchedCards(data, entry.count || 1)).length > 0;
  }

  function renderTxtCheckModal() {
    const sumEl = document.getElementById('cb-txt-check-summary');
    const actEl = document.getElementById('cb-txt-check-actions');
    const missWrap = document.getElementById('cb-txt-check-missing-wrap');
    const missCountEl = document.getElementById('cb-txt-missing-count');
    const missListEl = document.getElementById('cb-txt-missing-list');
    const foundWrap = document.getElementById('cb-txt-check-found-wrap');
    const foundCountEl = document.getElementById('cb-txt-found-count');
    const foundListEl = document.getElementById('cb-txt-found-list');
    if (!sumEl) return;

    const status = computeTxtCheckStatus();
    actEl.innerHTML = '';
    if (!status) {
      sumEl.innerHTML = '<span style="color:var(--text-muted);">No .txt deck list uploaded yet. Upload an MTGO .txt file to compare detected vs. missing cards.</span>';
      missWrap.style.display = 'none';
      foundWrap.style.display = 'none';
      const upBtn = document.createElement('button');
      upBtn.type = 'button';
      upBtn.className = 'btn btn-sm btn-primary';
      upBtn.textContent = '📄 Upload MTGO .txt';
      upBtn.addEventListener('click', () => {
        txtCheckModal?.classList.remove('open');
        txtInput?.click();
      });
      actEl.appendChild(upBtn);
      return;
    }

    sumEl.innerHTML = `
      <div><strong>File:</strong> ${status.filename}</div>
      <div style="margin-top:4px; display:flex; gap:12px; flex-wrap:wrap;">
        <span><strong>In .txt:</strong> ${status.totalUnique} unique (${status.totalCopies} total)</span>
        <span style="color:var(--ok, #22c55e);"><strong>Detected:</strong> ${status.detected.length} (${status.detectedCopies} copies)</span>
        <span style="color:${status.missing.length ? 'var(--danger)' : 'var(--ok, #22c55e)'};"><strong>Missing:</strong> ${status.missing.length}</span>
        <span><strong>Ready:</strong> ${status.readyMatched}/${status.totalUnique}</span>
      </div>
    `;

    if (status.missing.length > 0) {
      const retryAllBtn = document.createElement('button');
      retryAllBtn.type = 'button';
      retryAllBtn.className = 'btn btn-sm btn-primary';
      retryAllBtn.textContent = `⚡ Retry All Missing (${status.missing.length})`;
      retryAllBtn.addEventListener('click', async () => {
        retryAllBtn.disabled = true;
        retryAllBtn.textContent = 'Retrying...';
        let added = 0;
        for (const entry of status.missing) {
          try { if (await retryFetchCardFromTxt(entry)) added++; } catch {}
        }
        renderLists();
        await persistState(true);
        renderTxtCheckModal();
        showToast(`Recovered ${added}/${status.missing.length} missing cards`);
      });
      actEl.appendChild(retryAllBtn);
    }

    missCountEl.textContent = String(status.missing.length);
    missListEl.innerHTML = '';
    missWrap.style.display = status.missing.length ? 'block' : 'none';
    status.missing.forEach((entry) => {
      const row = document.createElement('div');
      row.className = 'row-between';
      row.style.cssText = 'font-size:12px; gap:8px; padding:2px 4px;';
      row.innerHTML = `
        <span>×${entry.count || 1} <strong>${entry.name}</strong></span>
        <button type="button" class="btn btn-sm" style="padding:2px 7px; font-size:11px;">+ Retry</button>
      `;
      row.querySelector('button').addEventListener('click', async (e) => {
        const b = e.currentTarget;
        b.disabled = true;
        b.textContent = '...';
        const ok = await retryFetchCardFromTxt(entry);
        if (ok) {
          renderLists();
          await persistState(true);
          renderTxtCheckModal();
          showToast(`Added ${entry.name}`);
        } else {
          b.disabled = false;
          b.textContent = '+ Retry';
          showToast(`Not found: ${entry.name}`);
        }
      });
      missListEl.appendChild(row);
    });

    foundCountEl.textContent = String(status.detected.length);
    foundListEl.innerHTML = '';
    foundWrap.style.display = status.detected.length ? 'block' : 'none';
    status.detected.forEach(({ entry, card, isReady }) => {
      const row = document.createElement('div');
      row.className = 'row-between';
      row.style.cssText = 'padding:2px 4px; cursor:pointer;';
      row.innerHTML = `
        <span>✓ ×${entry.count || 1} ${entry.name}${card.name !== entry.name ? ` <small style="opacity:0.7;">(as "${card.name}")</small>` : ''}</span>
        <span style="font-size:10.5px; opacity:0.8;">${isReady ? '✅ Ready' : 'Editing'}</span>
      `;
      row.addEventListener('click', () => {
        txtCheckModal?.classList.remove('open');
        openDetail(card.id);
      });
      foundListEl.appendChild(row);
    });
  }

  document.getElementById('cb-check-txt-btn')?.addEventListener('click', () => {
    renderTxtCheckModal();
    txtCheckModal?.classList.add('open');
  });
  txtCheckClose?.addEventListener('click', () => txtCheckModal?.classList.remove('open'));
  txtCheckModal?.addEventListener('click', (e) => {
    if (e.target === txtCheckModal) txtCheckModal.classList.remove('open');
  });

  document.getElementById('cb-export-ready-btn').addEventListener('click', async () => {
    const readySet = getReadyIds();
    const readyCards = getCards().filter((c) => readySet.has(c.id));
    if (!readyCards.length) return showToast('No hay cartas en Ready to Export.');
    const face = document.getElementById('cb-export-face').value;
    const format = document.getElementById('cb-export-format').value;
    const dpi = parseInt(document.getElementById('cb-export-dpi').value, 10);
    await exportCardsBatch(readyCards, face, format, dpi);
  });
})();
