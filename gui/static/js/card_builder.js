import {
  getActiveRootDir,
  initThemeAndNavbar,
  loadActiveWorkspaceState,
  pickFolder,
  promptCollisionResolution,
  saveActiveWorkspaceState,
  setGlobalLoading,
  showToast,
} from './modules/workspace_client.js?v=21';
import { CropMaskModal } from './modules/crop_masks.js?v=21';
import { LayerManager } from './modules/layer_manager.js?v=21';

initThemeAndNavbar('card-builder');

let workspaceState = null;
let catalog = {};
let activeCardId = null;
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
const canvas = document.getElementById('card-canvas');
const ctx = canvas.getContext('2d');

let layerManager = null;
let cropModal = null;

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
      card_builder: { cards: [], ready_ids: [], global_frame_style: 'Automated Templates/normal' },
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
    crop_mask: card.crop_mask || 'classic_box',
    layer_order: card.layer_order || null,
    hidden_layers: card.hidden_layers || {},
    layer_opacities: card.layer_opacities || {},
    frame_components: card.frame_components || {},
    layout: card.layout || {},
    shapes: card.shapes || [],
  }));
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
};

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

function drawOverlayShapes(targetCtx, card) {
  if (!Array.isArray(card.shapes) || card.shapes.length === 0) return;
  card.shapes.forEach((s) => {
    const op = s.opacity !== undefined ? Math.max(0, Math.min(1, Number(s.opacity))) : 0.55;
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

  regions.push({
    key: 'oracle_box',
    label: 'Oracle Text',
    x: L.oracle_box.x,
    y: L.oracle_box.y,
    w: L.oracle_box.w,
    h: L.oracle_box.h,
    resizable: true,
  });

  regions.push({
    key: 'artist',
    label: 'Artist',
    x: L.artist.x,
    y: L.artist.y - (L.artist.font_size || 16) * 0.9,
    w: 260,
    h: (L.artist.font_size || 16) * 1.25,
    resizable: true,
  });

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

    const cls = symbolToManaClass(sym);
    const glyph = getIconGlyph(cls, manaGlyphCache);
    targetCtx.save();
    targetCtx.fillStyle = '#111111';
    targetCtx.textAlign = 'center';
    targetCtx.textBaseline = 'middle';
    if (glyph.char) {
      targetCtx.font = `${Math.round(size * 0.76)}px ${glyph.fontFamily || 'Mana'}`;
      targetCtx.fillText(glyph.char, curX, baselineY - size * 0.3);
    } else {
      targetCtx.font = `bold ${Math.round(size * 0.65)}px sans-serif`;
      targetCtx.fillText(sym.replace(/[{}]/g, ''), curX, baselineY - size * 0.3);
    }
    targetCtx.restore();
    curX -= step;
  }
}

function drawSetSymbol(targetCtx, setCode, rarity, rightX, centerY, size) {
  const cls = `ss ss-${(setCode || 'mtg').toLowerCase()}`;
  const glyph = getIconGlyph(cls, keyruneGlyphCache);
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
  if (glyph.char) {
    targetCtx.font = `${size}px ${glyph.fontFamily || 'Keyrune'}`;
    targetCtx.strokeText(glyph.char, rightX, centerY);
    targetCtx.fillText(glyph.char, rightX, centerY);
  } else {
    targetCtx.font = `bold ${Math.round(size * 0.6)}px "BelerenLocal", serif`;
    targetCtx.fillText((setCode || 'MTG').toUpperCase(), rightX, centerY);
  }
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

    // Many Automated Template frame JPGs (border/pinlines/crown/name_box) have white outer corners
    // AND a solid black (#000000) art-box mask interior. Key out pure-black inside the art-box
    // so Artwork stays visible beneath the frame in default layer order.
    if (layerKey && layerKey !== 'background' && layerKey !== 'pt_box') {
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
    card.frame_components || null,
  ]);
}

function drawCardForeground(octx, card) {
  drawOverlayShapes(octx, card);

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

  drawRichOracleText(octx, card.oracle_text || '', card.flavor_text || '', {
    x: card.layout?.oracle_box?.x || 56,
    y: card.layout?.oracle_box?.y || 663,
    w: card.layout?.oracle_box?.w || 638,
    h: card.layout?.oracle_box?.h || 303,
    font_size: card.layout?.oracle_box?.font_size || 30,
    color: card.layout?.oracle_box?.color || '#111111',
  });

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

async function renderCardCanvas(card) {
  if (!card) return;
  const seq = ++renderSeq;
  const W = 750;
  const H = 1050;

  const baseKey = computeBaseLayerKey(card);
  if (baseKey !== _baseCacheKey) {
    const hidden = Array.isArray(card.hidden_layers)
      ? Object.fromEntries(card.hidden_layers.map((k) => [k, true]))
      : (card.hidden_layers || {});

    if (!hidden.background) {
      _baseCtx.fillStyle = card.bg_color || '#111111';
      _baseCtx.fillRect(0, 0, W, H);
    } else {
      _baseCtx.clearRect(0, 0, W, H);
    }

    const order = Array.isArray(card.layer_order) && card.layer_order.length
      ? card.layer_order
      : ['background', 'art', 'pinlines', 'name_box', 'crown', 'border', 'pt_box'];
    const opacities = card.layer_opacities || {};
    const fc = card.frame_components || {};

    const drawFrameComp = async (key, clipYRange = null) => {
      if (seq !== renderSeq || hidden[key]) return;
      const op = opacities[key] ?? 1.0;
      if (op <= 0.01 || !fc[key]) return;
      _baseCtx.save();
      if (clipYRange) {
        _baseCtx.beginPath();
        _baseCtx.rect(0, clipYRange[0], W, clipYRange[1] - clipYRange[0]);
        _baseCtx.clip();
      }
      _baseCtx.globalAlpha = op;
      if (key === 'background') {
        const bgImg = await loadCachedImage(encodeAssetPath(fc[key]));
        if (seq !== renderSeq) { _baseCtx.restore(); return; }
        if (bgImg) {
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
        }
      } else {
        const layerCanvas = await loadTransparentLayer(fc[key], key);
        if (seq !== renderSeq) { _baseCtx.restore(); return; }
        if (layerCanvas) _baseCtx.drawImage(layerCanvas, 0, 0, W, H);
      }
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
      if (popOutTop) {
        // Allow transparent PNG pop-out art to overlap title/crown/top border up to y=0, clipped at bottom of art window
        _baseCtx.rect(0, 0, W, Math.max(587, (lay.y || 109) + (lay.h || 477)));
      } else {
        _baseCtx.rect(lay.x, lay.y, lay.w, lay.h);
      }
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

    if (card.art_over_top) {
      const splitY = 587;
      for (const key of order) {
        if (key === 'art' || key === 'pt_box') continue;
        if (key === 'pinlines' || key === 'border') await drawFrameComp(key, [0, splitY]);
        else await drawFrameComp(key);
      }
      await drawArtComp(true);
      for (const key of order) {
        if (key === 'pinlines' || key === 'border') await drawFrameComp(key, [splitY, H]);
        else if (key === 'pt_box') await drawFrameComp(key);
      }
    } else {
      const artIdx = order.indexOf('art');
      const nameIdx = order.indexOf('name_box');
      const popOutByOrder = artIdx > nameIdx && nameIdx !== -1;
      for (const key of order) {
        if (key === 'art') await drawArtComp(popOutByOrder);
        else await drawFrameComp(key);
      }
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
  drawInteractiveOverlays(ctx, card);
}

function renderLists() {
  const cards = getCards();
  const readySet = getReadyIds();
  const q = (filterInput?.value || '').trim().toLowerCase();

  const filtered = cards.filter((c) => !q || (c.name || '').toLowerCase().includes(q));
  loadedCountEl.textContent = String(cards.length);
  loadedGrid.innerHTML = '';

  if (filtered.length === 0) {
    loadedGrid.innerHTML = '<p style="color:var(--text-muted); grid-column:1/-1;">No cards loaded. Search or import a .txt / .png to get started.</p>';
  } else {
    filtered.forEach((card) => {
      const isReady = readySet.has(card.id);
      const item = document.createElement('div');
      item.className = 'cb-grid-item';
      const thumbSrc = toSameOriginUrl(card.custom_art_data || card.art_crop_url || '');
      item.innerHTML = `
        <img class="cb-grid-thumb" src="${thumbSrc}" alt="${card.name || ''}">
        <div style="font-weight:600; font-size:12.5px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${card.name || 'Untitled'}</div>
        <div class="row-between" style="font-size:11px; color:var(--text-muted);">
          <span>×${card.count || 1}</span>
          <label class="row" style="gap:4px; cursor:pointer;" data-stop="1">
            <input type="checkbox" class="cb-ready-cb" ${isReady ? 'checked' : ''}>
            <span>Ready</span>
          </label>
        </div>
      `;
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

function toggleReady(cardId, isReady) {
  const cb = ensureCardBuilderState();
  const set = new Set(cb.ready_ids);
  if (isReady) set.add(cardId);
  else set.delete(cardId);
  cb.ready_ids = [...set];
  renderLists();
  persistState(true);
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
  const left = Math.max(10, anchorRect.left - 172);
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
  const styleKey = card.frame_components?.style || 'Automated Templates/normal';
  const styleCat = catalog[styleKey] || {};
  const keys = [
    ['background', 'Background'],
    ['pinlines', 'Pinlines / Textbox'],
    ['name_box', 'Name Box'],
    ['crown', 'Crown'],
    ['border', 'Border'],
    ['pt_box', 'PT Box'],
  ];
  container.innerHTML = '';

  keys.forEach(([k, title]) => {
    const items = styleCat[k] || [];
    const currentVal = card.frame_components?.[k] || '';
    const currentItem = items.find((it) => it.rel_path === currentVal);

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

    trigger.addEventListener('mouseenter', () => {
      const selItem = items.find((it) => it.rel_path === (card.frame_components?.[k] || ''));
      if (selItem) showFrameHoverPreview(selItem, trigger.getBoundingClientRect());
    });
    trigger.addEventListener('mouseleave', hideFrameHoverPreview);

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
      }
    });

    searchIn.addEventListener('input', () => renderItems(searchIn.value));
    searchIn.addEventListener('click', (e) => e.stopPropagation());
    container.appendChild(wrap);
  });
}

function openDetail(cardId) {
  activeCardId = cardId;
  const card = getActiveCard();
  if (!card) return;
  listsView.style.display = 'none';
  detailView.style.display = 'grid';
  populateDetailControls(card);
  renderCardCanvas(card);
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
  document.getElementById('cb-color-title').value = card.layout?.title?.color || '#111111';
  document.getElementById('cb-color-official').value = card.layout?.official_title?.color || '#111111';
  document.getElementById('cb-color-type').value = card.layout?.type_line?.color || '#111111';
  document.getElementById('cb-color-oracle').value = card.layout?.oracle_box?.color || '#111111';
  document.getElementById('cb-color-pt').value = card.layout?.pt_text?.color || '#111111';
  document.getElementById('cb-color-artist').value = card.layout?.artist?.color || '#ffffff';

  const popEl = document.getElementById('cb-art-over-top');
  if (popEl) popEl.checked = Boolean(card.art_over_top);
  const br = card.brightness ?? 1.0;
  document.getElementById('cb-brightness').value = br;
  document.getElementById('cb-brightness-val').textContent = Number(br).toFixed(2);

  const lay = card.layout?.art || { scale: 1.0, offset_x: 0, offset_y: 0 };
  document.getElementById('cb-art-scale').value = lay.scale ?? 1.0;
  document.getElementById('cb-art-scale-val').textContent = Number(lay.scale ?? 1.0).toFixed(2);
  document.getElementById('cb-art-ox').value = lay.offset_x ?? 0;
  document.getElementById('cb-art-oy').value = lay.offset_y ?? 0;

  const bg = card.bg_color || '#111111';
  document.getElementById('cb-bg-color-picker').value = bg;
  document.getElementById('cb-bg-color-text').value = bg;

  const styleSel = document.getElementById('cb-detail-style-select');
  if (card.frame_components?.style) styleSel.value = card.frame_components.style;

  renderFrameSelectors(card);
  renderShapesList(card);
  layerManager.render(card);
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

  document.getElementById('cb-art-over-top')?.addEventListener('change', (e) => {
    const card = getActiveCard();
    if (!card) return;
    pushUndoState(card);
    card.art_over_top = e.target.checked;
    renderCardCanvas(card);
    persistState(true);
  });

  document.getElementById('cb-detail-ready-check').addEventListener('change', (e) => {
    if (activeCardId) toggleReady(activeCardId, e.target.checked);
  });

  document.getElementById('cb-detail-style-select').addEventListener('change', async (e) => {
    const card = getActiveCard();
    if (!card) return;
    const styleKey = e.target.value;
    try {
      const resp = await fetch('/api/card-builder/auto-frame', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ card, style_key: styleKey }),
      });
      if (resp.ok) {
        const data = await resp.json();
        card.frame_components = data.frame_components;
        card.hidden_layers = card.hidden_layers || {};
        ['background', 'pinlines', 'name_box', 'crown', 'pt_box'].forEach((k) => {
          if (!card.frame_components?.[k]) card.hidden_layers[k] = true;
          else delete card.hidden_layers[k];
        });
        card.hidden_layers.border = true;
        layerManager.render(card);
        renderFrameSelectors(card);
        renderCardCanvas(card);
        persistState(true);
      }
    } catch {}
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
  syncField('cb-brightness', (c, v) => {
    c.brightness = parseFloat(v);
    document.getElementById('cb-brightness-val').textContent = Number(c.brightness).toFixed(2);
  });
  syncField('cb-art-scale', (c, v) => {
    c.layout = c.layout || {};
    c.layout.art = c.layout.art || { x: 34, y: 109, w: 682, h: 477 };
    c.layout.art.scale = parseFloat(v);
    document.getElementById('cb-art-scale-val').textContent = Number(v).toFixed(2);
  });
  syncField('cb-art-ox', (c, v) => {
    c.layout = c.layout || {}; c.layout.art = c.layout.art || { x: 34, y: 109, w: 682, h: 477 }; c.layout.art.offset_x = parseFloat(v) || 0;
  });
  syncField('cb-art-oy', (c, v) => {
    c.layout = c.layout || {}; c.layout.art = c.layout.art || { x: 34, y: 109, w: 682, h: 477 }; c.layout.art.offset_y = parseFloat(v) || 0;
  });

  const bgPicker = document.getElementById('cb-bg-color-picker');
  const bgText = document.getElementById('cb-bg-color-text');
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
    card.bg_color = e.target.value;
    bgPicker.value = e.target.value;
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
    await exportCardsBatch([card], 'fronts', 'pdf', 1200, true);
  });

  const interactiveCheck = document.getElementById('cb-interactive-mode');
  interactiveCheck?.addEventListener('change', () => {
    const card = getActiveCard();
    if (card) renderCardCanvas(card);
  });

  document.getElementById('cb-reset-layout-btn')?.addEventListener('click', () => {
    const card = getActiveCard();
    if (!card) return;
    pushUndoState(card);
    const prevColors = {
      title: card.layout?.title?.color || '#111111',
      official_title: card.layout?.official_title?.color || '#111111',
      type_line: card.layout?.type_line?.color || '#111111',
      oracle_box: card.layout?.oracle_box?.color || '#111111',
      pt_text: card.layout?.pt_text?.color || '#111111',
      artist: card.layout?.artist?.color || '#ffffff',
    };
    card.layout = JSON.parse(JSON.stringify(DEFAULT_LAYOUT));
    card.layout.title.color = prevColors.title;
    card.layout.official_title.color = prevColors.official_title;
    card.layout.type_line.color = prevColors.type_line;
    card.layout.oracle_box.color = prevColors.oracle_box;
    card.layout.pt_text.color = prevColors.pt_text;
    card.layout.artist.color = prevColors.artist;
    populateDetailControls(card);
    renderCardCanvas(card);
    persistState(true);
    showToast('Positions reset');
  });

  function getCanvasMouseCoords(evt) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: (evt.clientX - rect.left) * (canvas.width / rect.width),
      y: (evt.clientY - rect.top) * (canvas.height / rect.height),
    };
  }

  function findHitTarget(mx, my, card) {
    const regions = getInteractiveRegions(card);
    const selRegion = regions.find((r) => r.key === selectedElementKey);
    if (selRegion) {
      for (const h of getHandlesForRegion(selRegion)) {
        if (Math.abs(mx - h.x) <= HANDLE_SIZE && Math.abs(my - h.y) <= HANDLE_SIZE) {
          return { type: 'handle', key: selRegion.key, handle: h.id, cursor: h.cursor, region: selRegion };
        }
      }
    }
    for (const r of regions) {
      if (mx >= r.x && mx <= r.x + r.w && my >= r.y && my <= r.y + r.h) {
        return { type: 'region', key: r.key, cursor: 'move', region: r };
      }
    }
    return null;
  }

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

  canvas.addEventListener('mousedown', (evt) => {
    const card = getActiveCard();
    if (!interactiveCheck?.checked || !card) return;
    const { x: mx, y: my } = getCanvasMouseCoords(evt);
    const hit = findHitTarget(mx, my, card);
    if (!hit) {
      selectedElementKey = null;
      renderCardCanvas(card);
      return;
    }
    selectedElementKey = hit.key;
    const L = ensureCardLayout(card);
    const preDragSnap = cloneCardSnapshot(card);
    const initialLayout = JSON.parse(JSON.stringify(L));
    const initialShapes = JSON.parse(JSON.stringify(card.shapes || []));
    if (hit.type === 'handle') {
      dragState = { mode: 'resize', key: hit.key, handle: hit.handle, startX: mx, startY: my, initialLayout, initialShapes, changed: false, preDragSnap };
    } else if (hit.key === 'art' && evt.shiftKey) {
      dragState = { mode: 'pan-art', key: 'art', startX: mx, startY: my, initialLayout, initialShapes, changed: false, preDragSnap };
    } else {
      dragState = { mode: 'move', key: hit.key, startX: mx, startY: my, initialLayout, initialShapes, changed: false, preDragSnap };
    }
    renderCardCanvas(card);
  });

  window.addEventListener('mousemove', (evt) => {
    const card = getActiveCard();
    if (!card || detailView.style.display === 'none') return;
    const { x: mx, y: my } = getCanvasMouseCoords(evt);

    if (!dragState) {
      if (!interactiveCheck?.checked) {
        canvas.style.cursor = 'default';
        return;
      }
      const hit = findHitTarget(mx, my, card);
      const prevHover = hoveredElementKey;
      hoveredElementKey = hit ? hit.key : null;
      canvas.style.cursor = hit ? hit.cursor : 'default';
      if (prevHover !== hoveredElementKey) scheduleRender(card);
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
      } else if (k === 'art' || k === 'oracle_box') {
        let nx = init[k].x, ny = init[k].y, nw = init[k].w, nh = init[k].h;
        if (h.includes('e')) nw = Math.max(60, init[k].w + dx);
        if (h.includes('s')) nh = Math.max(40, init[k].h + dy);
        if (h.includes('w')) { const pw = init[k].w - dx; if (pw >= 60) { nw = pw; nx = init[k].x + dx; } }
        if (h.includes('n')) { const ph = init[k].h - dy; if (ph >= 40) { nh = ph; ny = init[k].y + dy; } }
        L[k].x = nx; L[k].y = ny; L[k].w = nw; L[k].h = nh;
      } else if (k === 'title' || k === 'type_line' || k === 'official_title') {
        if (h.includes('e')) L[k].max_w = Math.max(100, (init[k].max_w || 470) + dx);
        if (h.includes('w')) { L[k].x = init[k].x + dx; L[k].max_w = Math.max(100, (init[k].max_w || 470) - dx); }
        if (h.includes('s') || h.includes('n')) {
          const df = h.includes('s') ? dy : -dy;
          L[k].font_size = Math.max(10, Math.min(72, (init[k].font_size || 28) + df * 0.5));
        }
      } else if (k === 'mana_cost') {
        const delta = h.includes('s') || h.includes('e') ? dy + dx * 0.3 : -(dy + dx * 0.3);
        L.mana_cost.size = Math.max(14, Math.min(64, (init.mana_cost.size || 28) + delta * 0.4));
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
    const changed = dragState.changed;
    const preSnap = dragState.preDragSnap;
    dragState = null;
    if (card) {
      if (changed && preSnap) pushUndoState(card, preSnap);
      renderCardCanvas(card);
      if (changed) persistState(true);
    }
  });

  canvas.addEventListener('wheel', (evt) => {
    const card = getActiveCard();
    if (!interactiveCheck?.checked || !card) return;
    const { x: mx, y: my } = getCanvasMouseCoords(evt);
    const hit = findHitTarget(mx, my, card);
    if (!hit) return;
    evt.preventDefault();
    pushUndoState(card);
    selectedElementKey = hit.key;
    const L = ensureCardLayout(card);
    const dir = evt.deltaY < 0 ? 1 : -1;
    if (hit.key === 'art') L.art.scale = Math.max(0.2, Math.min(4.0, (L.art.scale || 1.0) + dir * 0.04));
    else if (hit.key === 'oracle_box') L.oracle_box.font_size = Math.max(12, Math.min(48, (L.oracle_box.font_size || 24) + dir));
    else if (hit.key === 'title') L.title.font_size = Math.max(14, Math.min(72, (L.title.font_size || 32) + dir));
    else if (hit.key === 'official_title') L.official_title.font_size = Math.max(10, Math.min(64, (L.official_title.font_size || 23) + dir));
    else if (hit.key === 'type_line') L.type_line.font_size = Math.max(12, Math.min(54, (L.type_line.font_size || 27) + dir));
    else if (hit.key === 'mana_cost') L.mana_cost.size = Math.max(14, Math.min(64, (L.mana_cost.size || 28) + dir));
    else if (hit.key === 'set_symbol') L.set_symbol.size = Math.max(14, Math.min(68, (L.set_symbol.size || 32) + dir));
    else if (hit.key === 'pt_text') L.pt_text.font_size = Math.max(14, Math.min(64, (L.pt_text.font_size || 34) + dir));
    else if (hit.key.startsWith('shape:') && Array.isArray(card.shapes)) {
      const s = card.shapes.find((sh) => sh.id === hit.key.slice(6));
      if (s) {
        s.opacity = Math.max(0.05, Math.min(1.0, Math.round(((s.opacity ?? 0.55) + dir * 0.05) * 100) / 100));
        renderShapesList(card);
      }
    }
    syncArtInputsFromLayout(L);
    scheduleRender(card);
    persistState(true);
  }, { passive: false });

}

async function exportCardsBatch(cards, face, format, dpi, singleCard = false) {
  const rootDir = getActiveRootDir();
  if (!rootDir) return showToast('Create or load a project on Home first.');

  if (singleCard && cards.length === 1) {
    const c = cards[0];
    const payload = {
      root_dir: rootDir,
      cards: [{
        card: c,
        text_overlay_data_url: face === 'fronts' ? renderTextOverlayDataUrl(c, 4) : '',
      }],
      face,
      export_format: format,
      export_dpi: dpi,
      single_card: true,
      collision_mode: 'check',
    };
    setGlobalLoading(true, `Exporting ${c.name || 'card'}...`);
    try {
      let resp = await fetch('/api/card-builder/export-batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      let data = await resp.json();
      if (data.status === 'collision') {
        setGlobalLoading(false);
        const choice = await promptCollisionResolution(data.collision);
        if (!choice) return;
        payload.collision_mode = choice;
        setGlobalLoading(true, `Exporting ${c.name || 'card'}...`);
        resp = await fetch('/api/card-builder/export-batch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        data = await resp.json();
      }
      if (!resp.ok) return showToast(data.detail || 'Error exporting cards');
      showToast(`Exported ${c.name || 'card'} to ${data.dest_dir}`);
    } finally {
      setGlobalLoading(false);
    }
    return;
  }

  // Batch export with live progress bar
  const modal = document.getElementById('cb-import-progress-modal');
  const txtEl = document.getElementById('cb-import-progress-text');
  const barEl = document.getElementById('cb-import-progress-bar');
  const subEl = document.getElementById('cb-import-progress-sub');

  const firstCard = cards[0];
  const firstPayload = {
    root_dir: rootDir,
    cards: [{
      card: firstCard,
      text_overlay_data_url: face === 'fronts' ? renderTextOverlayDataUrl(firstCard, 4) : '',
    }],
    face,
    export_format: format,
    export_dpi: dpi,
    collision_mode: 'check',
  };

  setGlobalLoading(true, 'Preparing export...');
  let firstResp = await fetch('/api/card-builder/export-batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(firstPayload),
  });
  let firstData = await firstResp.json();
  setGlobalLoading(false);

  if (firstData.status === 'collision') {
    const choice = await promptCollisionResolution(firstData.collision);
    if (!choice) return;
    firstPayload.collision_mode = choice;
    setGlobalLoading(true, `Exporting 1 / ${cards.length}: ${firstCard.name}...`);
    firstResp = await fetch('/api/card-builder/export-batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(firstPayload),
    });
    firstData = await firstResp.json();
    setGlobalLoading(false);
  }
  if (!firstResp.ok) return showToast(firstData.detail || 'Error exporting cards');

  const targetDir = firstData.dest_dir;
  if (cards.length === 1) {
    return showToast(`Exported 1 card to ${targetDir}`);
  }

  modal.classList.add('open');
  let exportedCount = 1;
  try {
    for (let i = 1; i < cards.length; i++) {
      const c = cards[i];
      txtEl.textContent = `Exporting: ${c.name || 'Card'}...`;
      const pct = Math.round((i / cards.length) * 100);
      barEl.style.width = `${pct}%`;
      subEl.textContent = `${i} / ${cards.length} (${pct}%)`;
      const r = await fetch('/api/card-builder/export-batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          root_dir: rootDir,
          target_dir: targetDir,
          cards: [{
            card: c,
            text_overlay_data_url: face === 'fronts' ? renderTextOverlayDataUrl(c, 4) : '',
          }],
          face,
          export_format: format,
          export_dpi: dpi,
          collision_mode: 'overwrite',
        }),
      });
      if (r.ok) exportedCount++;
    }
    barEl.style.width = '100%';
    subEl.textContent = `${cards.length} / ${cards.length} (100%)`;
    showToast(`Exported ${exportedCount} cards to ${targetDir}`);
  } finally {
    modal.classList.remove('open');
  }
}

function bindChangeArtModal() {
  const modal = document.getElementById('cb-change-art-modal');
  const closeBtn = document.getElementById('cb-ca-close');
  const tabs = modal.querySelectorAll('.cb-ca-tab');
  const panels = {
    json: document.getElementById('cb-ca-panel-json'),
    scryfall: document.getElementById('cb-ca-panel-scryfall'),
    upload: document.getElementById('cb-ca-panel-upload'),
  };

  function selectArt(url, artist) {
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

  document.getElementById('cb-change-art-btn').addEventListener('click', () => {
    const card = getActiveCard();
    if (!card) return;
    const defaultQ = (card.official_name || card.original_name || card.name || '').trim();
    document.getElementById('cb-ca-json-q').value = defaultQ;
    document.getElementById('cb-ca-sf-q').value = defaultQ;
    modal.classList.add('open');
    searchLocalJsonArt();
  });
  closeBtn.addEventListener('click', () => modal.classList.remove('open'));

  tabs.forEach((btn) => {
    btn.addEventListener('click', () => {
      tabs.forEach((b) => b.classList.remove('btn-primary'));
      btn.classList.add('btn-primary');
      Object.values(panels).forEach((p) => { p.style.display = 'none'; });
      panels[btn.dataset.tab].style.display = 'block';
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

  document.getElementById('cb-ca-json-btn').addEventListener('click', searchLocalJsonArt);
  document.getElementById('cb-ca-json-q').addEventListener('keydown', (e) => { if (e.key === 'Enter') searchLocalJsonArt(); });
  document.getElementById('cb-ca-sf-btn').addEventListener('click', searchScryfallPrints);
  document.getElementById('cb-ca-sf-q').addEventListener('keydown', (e) => { if (e.key === 'Enter') searchScryfallPrints(); });
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

(async function init() {
  if (document.fonts) {
    await Promise.allSettled([
      document.fonts.load('24px Mana'),
      document.fonts.load('24px Keyrune'),
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
  try {
    const tResp = await fetch('/api/card-builder/templates');
    const tData = await tResp.json();
    catalog = tData.catalog || {};
  } catch { catalog = {}; }

  const styleKeys = Object.keys(catalog);
  ['cb-global-style-select', 'cb-detail-style-select'].forEach((id) => {
    const sel = document.getElementById(id);
    if (!sel) return;
    sel.innerHTML = styleKeys.length
      ? styleKeys.map((k) => `<option value="${k}">${k}</option>`).join('')
      : '<option value="Automated Templates/normal">Automated Templates/normal</option>';
  });

  layerManager = new LayerManager(document.getElementById('cb-layer-list'), (changedCard) => {
    const card = changedCard || getActiveCard();
    if (card) { renderCardCanvas(card); persistState(true); }
  });

  cropModal = new CropMaskModal(document.getElementById('cb-crop-modal'), (dataUrl, maskType) => {
    const card = getActiveCard();
    if (!card) return;
    card.custom_art_data = dataUrl;
    card.crop_mask = maskType;
    renderCardCanvas(card);
    persistState(true);
    showToast('Crop mask applied');
  });

  bindDetailEvents();
  bindChangeArtModal();
  renderLists();

  document.getElementById('nav-save-state-btn')?.addEventListener('click', () => persistState(false));
  filterInput.addEventListener('input', renderLists);

  document.getElementById('cb-select-all-btn')?.addEventListener('click', () => {
    const allCards = getCards();
    const q = (filterInput?.value || '').trim().toLowerCase();
    const visible = allCards.filter((c) => !q || (c.name || '').toLowerCase().includes(q));
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

  document.getElementById('cb-search-btn').addEventListener('click', async () => {
    const q = document.getElementById('cb-search-input').value.trim();
    if (!q) return;
    setGlobalLoading(true, `Searching ${q}...`);
    try {
    const resp = await fetch('/api/card-builder/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: q, root_dir: getActiveRootDir() }),
    });
    const data = await resp.json();
    if (!resp.ok) return showToast(data.detail || 'Card not found');
    getCards().push(data.card);
    renderLists();
    persistState(true);
    showToast(`Added: ${data.card.name}`);
    } finally { setGlobalLoading(false); }
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

    const modal = document.getElementById('cb-import-progress-modal');
    const txtEl = document.getElementById('cb-import-progress-text');
    const barEl = document.getElementById('cb-import-progress-bar');
    const subEl = document.getElementById('cb-import-progress-sub');

    txtBtn.disabled = true;
    modal.classList.add('open');
    barEl.style.width = '0%';
    subEl.textContent = `0 / ${entries.length}`;

    let imported = 0;
    const styleKey = ensureCardBuilderState().global_frame_style || 'Automated Templates/normal';

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
            if (data.card) {
              data.card.count = entry.count;
              getCards().push(data.card);
              imported++;
            }
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

  const pngInput = document.getElementById('cb-import-png-input');
  document.getElementById('cb-import-png-btn').addEventListener('click', () => pngInput.click());
  pngInput.addEventListener('change', async () => {
    if (!pngInput.files?.length) return;
    const fd = new FormData();
    for (const f of pngInput.files) fd.append('files', f);
    const resp = await fetch('/api/card-builder/import-pngs', { method: 'POST', body: fd });
    const data = await resp.json();
    if (!resp.ok) return showToast('Error importing PNGs');
    getCards().push(...data.cards);
    renderLists();
    persistState(true);
    showToast(`Imported ${data.count} images`);
  });

  document.getElementById('cb-import-dir-btn').addEventListener('click', async () => {
    const dir = await pickFolder();
    if (!dir) return;
    const resp = await fetch('/api/card-builder/import-png-dir', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dir_path: dir }),
    });
    const data = await resp.json();
    if (!resp.ok) return showToast(data.detail || 'Error importing folder');
    getCards().push(...data.cards);
    renderLists();
    persistState(true);
    showToast(`Imported ${data.count} images desde carpeta`);
  });

  document.getElementById('cb-apply-global-style-btn').addEventListener('click', async () => {
    const style = document.getElementById('cb-global-style-select').value;
    ensureCardBuilderState().global_frame_style = style;
    const cards = getCards();
    for (const c of cards) {
      try {
        const resp = await fetch('/api/card-builder/auto-frame', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ card: c, style_key: style }),
        });
        if (resp.ok) {
          const data = await resp.json();
          c.frame_components = data.frame_components;
          c.hidden_layers = c.hidden_layers || {};
          c.hidden_layers.border = true;
        }
      } catch {}
    }
    persistState(true);
    showToast(`Applied style "${style}" to entire library`);
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
