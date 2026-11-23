import { iconSvg } from './icons.js?v=1';
import { applyMaskToCanvas, drawArtInto, loadImageElement } from './crop_masks.js?v=3';
import { createRecordingContext } from './canvas_recorder.js?v=1';

const LAYER_LABELS = {
  background: 'Frame (Top / Title)',
  textbox: 'Frame (Bottom / Textbox)',
  art: 'Artwork',
  name_box: 'Holo Stamp',
  crown: 'Crown',
  border: 'Border',
  pt_box: 'P/T Box',
};

// The frame is only split into Top/Bottom halves for pop-out cards (art drawn over the
// title half but under the textbox half). Otherwise it is a single "Frame" layer.
export function isSplitFrame(card) {
  return Boolean(card?.art_over_top);
}

function layerLabel(key, card) {
  if (key === 'background' && !isSplitFrame(card)) return 'Frame';
  return LAYER_LABELS[key] || key;
}

const FRAME_SLOT_ROLES = {
  background: 'base_frame',
  textbox: 'base_frame',
  pinlines: 'pinline',
  name_box: 'stamp',
  crown: 'crown',
  border: 'border',
  pt_box: 'pt_box',
};

const SHAPE_ICONS = {
  rect: 'rect',
  rounded: 'rounded-rect',
  circle: 'circle',
};

const COLORABLE_FRAME_KEYS = new Set(['background', 'textbox', 'name_box', 'crown', 'border', 'pt_box']);

export const DEFAULT_LAYER_ORDER = [
  'art',
  'background',
  'crown',
  'textbox',
  'name_box',
  'border',
  'pt_box',
];

export function applyPopOutOrder(card, enabled) {
  if (!card) return;
  card.art_over_top = Boolean(enabled);
  const base = Array.isArray(card.layer_order) && card.layer_order.length
    ? [...card.layer_order]
    : [...DEFAULT_LAYER_ORDER];
  DEFAULT_LAYER_ORDER.forEach((k) => { if (!base.includes(k)) base.push(k); });
  const withoutArt = base.filter((k) => k !== 'art');
  if (enabled) {
    // Place Artwork above Frame (Top / Title) & Crown, while keeping Frame (Bottom / Textbox) on top
    const tbIdx = withoutArt.indexOf('textbox');
    const bgIdx = withoutArt.indexOf('background');
    const crownIdx = withoutArt.indexOf('crown');
    const topEnd = Math.max(bgIdx, crownIdx);
    let insertIdx = tbIdx >= 0 ? tbIdx : (topEnd >= 0 ? topEnd + 1 : withoutArt.length);
    if (topEnd >= 0 && insertIdx <= topEnd) {
      // Ensure textbox sits above top frame/crown if user moved it earlier
      insertIdx = topEnd + 1;
    }
    withoutArt.splice(insertIdx, 0, 'art');
  } else {
    const bgIdx = withoutArt.indexOf('background');
    withoutArt.splice(bgIdx >= 0 ? bgIdx : 0, 0, 'art');
  }
  card.layer_order = withoutArt;
}

let _symbolsCatalog = null;
let _symbolsPromise = null;

export async function ensureSymbolsCatalog() {
  if (_symbolsCatalog) return _symbolsCatalog;
  if (!_symbolsPromise) {
    _symbolsPromise = fetch('/api/card-builder/symbols')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        _symbolsCatalog = data || { mana: {}, sets: {}, templates: {}, frames_by_role: {}, defaults_by_material: {} };
        return _symbolsCatalog;
      })
      .catch(() => {
        _symbolsCatalog = { mana: {}, sets: {}, templates: {}, frames_by_role: {}, defaults_by_material: {} };
        return _symbolsCatalog;
      });
  }
  return _symbolsPromise;
}

export function getSymbolsCatalog() {
  return _symbolsCatalog || { mana: {}, sets: {}, templates: {}, frames_by_role: {}, defaults_by_material: {} };
}

export function normalizeManaCode(raw) {
  const code = String(raw || '').replace(/[{}]/g, '').trim().toLowerCase().replace(/\//g, '');
  if (code === 'q') return 'untap';
  if (code === '∞') return 'inf';
  if (code === '12' || code === '½') return 'half';
  return code;
}

export function resolveManaSymbolUrl(raw) {
  const cat = getSymbolsCatalog();
  const norm = normalizeManaCode(raw);
  return (cat.mana && cat.mana[norm]) || null;
}

const RARITY_LETTER = { common: 'c', uncommon: 'u', rare: 'r', mythic: 'm', special: 's', bonus: 's' };

// The set's symbol for exactly this rarity in _shared/set_symbols (e.g. 10e-r), or null.
export function exactSetSymbolUrl(setCode, rarity = 'common') {
  const sets = getSymbolsCatalog().sets || {};
  const r = String(rarity || 'common').trim().toLowerCase();
  const key = `${String(setCode || '').trim().toLowerCase()}-${RARITY_LETTER[r] || r[0] || 'c'}`;
  return sets[key] || null;
}

// Fill gradients (dark-light-dark, as in the _shared/set_symbols SVGs) and outline per rarity.
const RARITY_SYMBOL_STYLE = {
  common: { stops: ['#111111'], outline: '#ffffff' },
  uncommon: { stops: ['#536e78', '#99aebc', '#d9eaf3', '#99aebc', '#536e78'], outline: '#000000' },
  rare: { stops: ['#8b723c', '#d2bb7b', '#ebd491', '#d2bb7b', '#8b723c'], outline: '#000000' },
  mythic: { stops: ['#bf331c', '#d3641c', '#f6b91d', '#d3641c', '#bf331c'], outline: '#000000' },
  special: { stops: ['#4b2063', '#8a5aa8', '#d7b8ea', '#8a5aa8', '#4b2063'], outline: '#000000' },
};

// A black set-symbol silhouette coloured for its rarity with a contrasting outline, like the
// printed symbol (visible on dark type bars such as M15Extended's). Built at 4x so it stays
// sharp in high-DPI exports; draw it at (x - pad, y - pad, w + 2 pad, h + 2 pad).
function styledSetSymbol(img, dw, dh, rarity) {
  const r = String(rarity || 'common').toLowerCase();
  const style = RARITY_SYMBOL_STYLE[r === 'bonus' ? 'special' : r] || RARITY_SYMBOL_STYLE.common;
  const k = 4;
  const pad = Math.max(2, Math.round(Math.min(dw, dh) * 0.07));
  const w = dw * k;
  const h = dh * k;
  const p = pad * k;
  const layer = (paint) => {
    const c = document.createElement('canvas');
    c.width = w;
    c.height = h;
    const x = c.getContext('2d');
    x.drawImage(img, 0, 0, w, h);
    x.globalCompositeOperation = 'source-in';
    x.fillStyle = paint(x);
    x.fillRect(0, 0, w, h);
    return c;
  };
  const outline = layer(() => style.outline);
  const fill = layer((x) => {
    if (style.stops.length === 1) return style.stops[0];
    const g = x.createLinearGradient(0, 0, w, 0);
    style.stops.forEach((col, i) => g.addColorStop(i / (style.stops.length - 1), col));
    return g;
  });
  const out = document.createElement('canvas');
  out.width = w + 2 * p;
  out.height = h + 2 * p;
  const ox = out.getContext('2d');
  for (let i = 0; i < 32; i += 1) {
    const a = (i / 32) * Math.PI * 2;
    ox.drawImage(outline, p + Math.cos(a) * p, p + Math.sin(a) * p);
  }
  ox.drawImage(fill, p, p);
  return { canvas: out, pad };
}

export function resolveSetSymbolUrl(setCode, rarity = 'common') {
  const cat = getSymbolsCatalog();
  const sets = cat.sets || {};
  const s = String(setCode || 'mtg').trim().toLowerCase();
  const r = String(rarity || 'common').trim().toLowerCase();
  const rChar = r ? r[0] : 'c';
  for (const cand of [`${s}-${rChar}`, `${s}-c`, s, `cc-${rChar}`, 'cc-c']) {
    if (sets[cand]) return sets[cand];
  }
  return null;
}

function normalizeHiddenLayers(raw) {
  if (Array.isArray(raw)) {
    const obj = {};
    raw.forEach((k) => { obj[k] = true; });
    return obj;
  }
  if (raw && typeof raw === 'object') return raw;
  return {};
}

// Text colour a template declares for a line in frame_layouts.json (e.g. M15Extended's type
// line is "white"), as a hex colour; '' when it declares none.
function templateTextColor(face, boundsKey, bounds) {
  const named = { white: '#ffffff', black: '#111111' };
  const raw = String(bounds?.color || getSymbolsCatalog().templates?.[face?.template]?.text_bounds?.[boundsKey]?.color || '').trim().toLowerCase();
  if (named[raw]) return named[raw];
  return /^#[0-9a-f]{6}$/.test(raw) ? raw : '';
}

export function buildLayoutFromProjectFace(face) {
  const defColor = defaultTextColorForFace(face);
  const tl = face?.text_layers || {};
  const ab = face?.art_layer?.bounds || { x: 115, y: 237, w: 1271, h: 930 };
  const tb = tl.title?.bounds || { x: 125, y: 110, w: 980, size: 74 };
  const mb = tl.mana_cost?.bounds || { x: 0, y: 118, width: 1394, size: 74 };
  const tyb = tl.type_line?.bounds || { x: 128, y: 1189, w: 1100, size: 64 };
  const rb = tl.oracle_text?.bounds || tl.flavor_text?.bounds || { x: 129, y: 1324, w: 1242, h: 604, size: 62 };
  const pb = tl.pt?.bounds || { x: 1189, y: 1894, w: 205, h: 78, size: 74 };
  const cb = tl.collector_info?.bounds || { x: 94, y: 2044 };
  const sb = face?.set_symbol_bounds || { x: 1384, y: 1241, width: 120, height: 80 };

  const titleSize = Math.min(Number(tb.size || tb.font_size || 72), 74);
  const titleH = Number(tb.h || tb.height || 114);
  const titleTopY = Number(tb.y || 108) + Math.round((titleH - titleSize) * 0.42);
  const manaSize = Math.min(Number(mb.size || mb.font_size || 68), 72);
  const manaRightX = Number(mb.width || mb.w)
    ? Number(mb.x || 0) + Number(mb.width || mb.w)
    : (Number(mb.x || 0) > 500 ? Number(mb.x) : 1394);
  const typeSize = Math.min(Number(tyb.size || tyb.font_size || 64), 66);
  const typeH = Number(tyb.h || tyb.height || 114);
  const typeTopY = Number(tyb.y || 1185) + Math.round((typeH - typeSize) * 0.42);
  const oracleSize = Math.min(Number(rb.size || rb.font_size || 60), 62);
  const ptSize = Number(pb.size || pb.font_size || 74);
  const ptW = Number(pb.w || pb.width || 205);
  const ptH = Number(pb.h || pb.height || 78);

  const advTb = tl.adventure_title?.bounds || { x: 120, y: 1330, width: 470, height: 84, size: 54 };
  const advMb = tl.adventure_mana_cost?.bounds || { x: 0, y: 1340, width: 724, height: 64, size: 52 };
  const advTyb = tl.adventure_type_line?.bounds || { x: 120, y: 1424, width: 584, height: 74, size: 46 };
  const advRb = tl.adventure_oracle_text?.bounds || { x: 118, y: 1516, width: 602, height: 400, size: 52 };

  const advTitleSize = Math.min(Number(advTb.size || advTb.font_size || 54), 56);
  const advTitleH = Number(advTb.h || advTb.height || 84);
  const advTitleTopY = Number(advTb.y || 1330) + Math.round((advTitleH - advTitleSize) * 0.42);
  const advManaSize = Math.min(Number(advMb.size || advMb.font_size || 52), 54);
  const advManaRightX = Number(advMb.width || advMb.w)
    ? Number(advMb.x || 0) + Number(advMb.width || advMb.w)
    : 724;
  const advTypeSize = Math.min(Number(advTyb.size || advTyb.font_size || 46), 48);
  const advTypeH = Number(advTyb.h || advTyb.height || 74);
  const advTypeTopY = Number(advTyb.y || 1424) + Math.round((advTypeH - advTypeSize) * 0.42);
  const advOracleSize = Math.min(Number(advRb.size || advRb.font_size || 52), 54);

  return {
    art: {
      x: Math.round(Number(ab.x || 0) / 2),
      y: Math.round(Number(ab.y || 0) / 2),
      w: Math.round(Number(ab.w || ab.width || 1271) / 2),
      h: Math.round(Number(ab.h || ab.height || 930) / 2),
      scale: Number(face?.art_layer?.transform?.scale || 1.0),
      offset_x: 0,
      offset_y: 0,
    },
    title: {
      x: Math.round((Number(tb.x || 125) + 4) / 2),
      y: Math.round((titleTopY + titleSize * 0.85) / 2),
      max_w: Math.round(Number(tb.max_w || tb.width || tb.w || 980) / 2),
      font_size: Math.round(titleSize / 2),
      color: defColor,
    },
    official_title: {
      x: Math.round((Number(tb.x || 125) + 4) / 2),
      y: Math.round((titleTopY + titleSize * 1.45) / 2),
      max_w: Math.round(Number(tb.max_w || tb.width || tb.w || 980) / 2),
      font_size: 22,
      color: defColor,
    },
    mana_cost: {
      x: Math.round(manaRightX / 2),
      y: Math.round((Number(mb.y || 126) + manaSize * 0.82) / 2),
      size: Math.round(manaSize / 2),
    },
    type_line: {
      x: Math.round((Number(tyb.x || 128) + 4) / 2),
      y: Math.round((typeTopY + typeSize * 0.85) / 2),
      max_w: Math.round(Number(tyb.max_w || tyb.width || tyb.w || 1100) / 2),
      font_size: Math.round(typeSize / 2),
      // The template's type-line colour wins (white on M15Extended / Seventh / Future).
      color: templateTextColor(face, 'type', tyb) || defColor,
    },
    set_symbol: {
      x: Math.round(Number(sb.x || 1384) / 2),
      y: Math.round(Number(sb.y || 1241) / 2),
      size: Math.round(Number(sb.height || sb.h || 80) / 2),
    },
    oracle_box: {
      x: Math.round((Number(rb.x || 129) + 18) / 2),
      y: Math.round((Number(rb.y || 1324) + 14) / 2),
      w: Math.round((Number(rb.w || rb.width || 1242) - 36) / 2),
      h: Math.round((Number(rb.h || rb.height || 604) - 28) / 2),
      font_size: Math.round(oracleSize / 2),
      color: defColor,
    },
    pt_text: {
      x: Math.round((Number(pb.x || 1189) + ptW / 2) / 2),
      y: Math.round((Number(pb.y || 1894) + ptH / 2) / 2),
      font_size: Math.round(ptSize / 2),
      color: defColor,
    },
    artist: {
      x: Math.round(Number(cb.x || 94) / 2),
      y: Math.round((Number(cb.y || 2044) + 26) / 2),
      font_size: 16,
      color: '#f2f2f2',
    },
    adventure_title: {
      x: Math.round((Number(advTb.x || 120) + 4) / 2),
      y: Math.round((advTitleTopY + advTitleSize * 0.85) / 2),
      max_w: Math.round(Number(advTb.max_w || advTb.width || advTb.w || 470) / 2),
      font_size: Math.round(advTitleSize / 2),
      color: '#ffffff',
    },
    adventure_mana_cost: {
      x: Math.round(advManaRightX / 2),
      y: Math.round((Number(advMb.y || 1340) + advManaSize * 0.82) / 2),
      size: Math.round(advManaSize / 2),
    },
    adventure_type_line: {
      x: Math.round((Number(advTyb.x || 120) + 4) / 2),
      y: Math.round((advTypeTopY + advTypeSize * 0.85) / 2),
      max_w: Math.round(Number(advTyb.max_w || advTyb.width || advTyb.w || 584) / 2),
      font_size: Math.round(advTypeSize / 2),
      color: '#ffffff',
    },
    adventure_oracle_box: {
      x: Math.round((Number(advRb.x || 118) + 12) / 2),
      y: Math.round((Number(advRb.y || 1516) + 10) / 2),
      w: Math.round((Number(advRb.w || advRb.width || 602) - 24) / 2),
      h: Math.round((Number(advRb.h || advRb.height || 400) - 20) / 2),
      font_size: Math.round(advOracleSize / 2),
      color: defColor,
    },
  };
}

export function applyTemplateLayoutToFace(card, face, templateName) {
  if (!face || !templateName) return;
  face.template = templateName;
  const tpl = getSymbolsCatalog().templates?.[templateName];
  if (tpl) {
    if (tpl.set_symbol_bounds) face.set_symbol_bounds = { ...tpl.set_symbol_bounds };
    if (tpl.art_bounds && tpl.art_bounds.width && tpl.art_bounds.height) {
      face.art_layer = face.art_layer || {};
      face.art_layer.bounds = {
        x: Number(tpl.art_bounds.x || 0),
        y: Number(tpl.art_bounds.y || 0),
        w: Number(tpl.art_bounds.width),
        h: Number(tpl.art_bounds.height),
      };
    }
    const tb = tpl.text_bounds || {};
    face.text_layers = face.text_layers || {};
    const keyMap = {
      title: 'title',
      mana_cost: 'mana',
      type_line: 'type',
      oracle_text: 'rules',
      flavor_text: 'rules',
      pt: 'pt',
      adventure_title: 'adventure_title',
      adventure_mana_cost: 'adventure_mana',
      adventure_type_line: 'adventure_type',
      adventure_oracle_text: 'adventure_rules',
    };
    for (const [tk, bk] of Object.entries(keyMap)) {
      if (tb[bk]) {
        face.text_layers[tk] = face.text_layers[tk] || { text: null };
        face.text_layers[tk].bounds = {
          ...tb[bk],
          w: tb[bk].w ?? tb[bk].width,
          h: tb[bk].h ?? tb[bk].height,
        };
      }
    }
  }
  const freshLayout = buildLayoutFromProjectFace(face);
  if (card) {
    card.layout = { ...(card.layout || {}), ...freshLayout };
    // Ensure art sits behind transparent RGBA frames (critical for Extended Art, Borderless, Tokens & Planeswalkers)
    if (!card.art_over_top && Array.isArray(card.layer_order)) {
      const artIdx = card.layer_order.indexOf('art');
      const bgIdx = card.layer_order.indexOf('background');
      if (artIdx > bgIdx && bgIdx >= 0) {
        const nextOrder = card.layer_order.filter((k) => k !== 'art');
        nextOrder.splice(bgIdx, 0, 'art');
        card.layer_order = nextOrder;
      }
    }
    if (face._ui_state) {
      face._ui_state.layout = card.layout;
      if (Array.isArray(card.layer_order)) face._ui_state.layer_order = card.layer_order;
    }
  }
}

export function syncCardWithProjectFace(card, face, project = null) {
  if (!card || !face) return;
  const cat = getSymbolsCatalog();
  const defaults = cat.defaults_by_material || {};
  const material = face?.taxonomy?.frame_texture_material || 'red_volcanic';

  // Preserve or initialize per-face UI state so switching faces doesn't clobber the other face
  if (!face._ui_state) {
    const stack = (Array.isArray(face.frame_stack) ? face.frame_stack : []).filter(
      (l) => l && l.url && !l.url.endsWith('4d82f3272976dc05.png') && l.asset_role !== 'mask' && l.asset_role !== 'pinline'
    );
    const baseFrames = stack.filter((l) => l.asset_role === 'base_frame' && l.url);
    const stampLayer = stack.find((l) => l.asset_role === 'stamp' && l.url);
    const crownLayer = stack.find((l) => l.asset_role === 'crown' && l.url);
    const borderLayer = stack.find((l) => l.asset_role === 'border' && l.url);
    const ptLayer = stack.find((l) => l.asset_role === 'pt_box' && l.url);

    const defaultCrown = (defaults.crown && (defaults.crown[material] || defaults.crown.gold_metallic || Object.values(defaults.crown)[0])) || '';
    const defaultPt = (defaults.pt_box && (defaults.pt_box[material] || defaults.pt_box.gold_metallic || Object.values(defaults.pt_box)[0])) || '';
    const defaultStamp = (defaults.stamp && (defaults.stamp.default || defaults.stamp[material] || Object.values(defaults.stamp)[0])) || '';
    const defaultBorder = (defaults.border && (defaults.border.default || Object.values(defaults.border)[0])) || '';

    const fc = {
      style: face.template || 'M15Regular',
      background: baseFrames[0]?.url || '',
      textbox: baseFrames[0]?.url || '',
      name_box: defaultStamp || stampLayer?.url || '',
      crown: crownLayer?.url || defaultCrown,
      border: borderLayer?.url || defaultBorder,
      pt_box: ptLayer?.url || defaultPt,
    };

    const hidden = {
      name_box: true,
    };
    if (!crownLayer) hidden.crown = true;
    if (!ptLayer) hidden.pt_box = true;

    // Ensure Planeswalker Tall vs Regular layout matches the actual resolved frame image
    const bgUrlLow = String(fc.background || '').toLowerCase();
    if (bgUrlLow.includes('/planeswalker/tall/') || bgUrlLow.includes('planeswalkertall')) {
      if (face.template !== 'PlaneswalkerTall') {
        face.template = 'PlaneswalkerTall';
        fc.style = 'PlaneswalkerTall';
        applyTemplateLayoutToFace(null, face, 'PlaneswalkerTall');
      }
    } else if (bgUrlLow.includes('/planeswalker/regular/') || bgUrlLow.includes('planeswalkerframe')) {
      if (face.template !== 'PlaneswalkerRegular') {
        face.template = 'PlaneswalkerRegular';
        fc.style = 'PlaneswalkerRegular';
        applyTemplateLayoutToFace(null, face, 'PlaneswalkerRegular');
      }
    }

    face._ui_state = {
      frame_components: fc,
      hidden_layers: hidden,
      layer_opacities: {},
      layer_colors: {},
      layer_order: [...DEFAULT_LAYER_ORDER],
      layout: buildLayoutFromProjectFace(face),
    };
    face._original_ui_state = JSON.parse(JSON.stringify(face._ui_state));
    face._original_template = face.template || 'M15Regular';
    face._original_art_url = face.art_layer?.url || '';
  }

  card.frame_components = face._ui_state.frame_components;
  card._original_frame_components = face._original_ui_state?.frame_components || { ...face._ui_state.frame_components };
  card.hidden_layers = face._ui_state.hidden_layers;
  card.layer_opacities = face._ui_state.layer_opacities;
  card.layer_colors = face._ui_state.layer_colors;
  card.layer_order = face._ui_state.layer_order;
  card.layout = { ...(card.layout || {}), ...(face._ui_state.layout || buildLayoutFromProjectFace(face)) };

  const tl = face.text_layers || {};
  card.name = tl.title?.text ?? face.face_ref ?? project?.name ?? card.name ?? '';
  card.mana_cost = tl.mana_cost?.text ?? '';
  card.type_line = tl.type_line?.text ?? '';
  card.oracle_text = tl.oracle_text?.text ?? '';
  card.flavor_text = tl.flavor_text?.text ?? '';
  card.power = tl.pt?.power ?? null;
  card.toughness = tl.pt?.toughness ?? null;
  card.artist = tl.collector_info?.artist ?? card.artist ?? '';
  card.set = (tl.collector_info?.set || project?.set || card.set || 'mtg').toLowerCase();
  card.rarity = (tl.collector_info?.rarity || card.rarity || 'common').toLowerCase();
  if (tl.adventure_title?.text || tl.adventure_type_line?.text || tl.adventure_oracle_text?.text) {
    card.adventure = {
      name: tl.adventure_title?.text || card.adventure?.name || '',
      mana_cost: tl.adventure_mana_cost?.text || card.adventure?.mana_cost || '',
      type_line: tl.adventure_type_line?.text || card.adventure?.type_line || '',
      oracle_text: tl.adventure_oracle_text?.text || card.adventure?.oracle_text || '',
    };
  }
  if (!face._original_text) {
    face._original_text = JSON.parse(JSON.stringify({
      name: card.name,
      official_name: card.official_name || '',
      mana_cost: card.mana_cost,
      type_line: card.type_line,
      oracle_text: card.oracle_text,
      flavor_text: card.flavor_text,
      power: card.power,
      toughness: card.toughness,
      artist: card.artist,
      set: card.set,
      rarity: card.rarity,
      adventure: card.adventure || null,
    }));
  }
  if (face.art_layer?.url) {
    card.art_crop_url = face.art_layer.url;
  }
}

export function resetCardToOriginalFace(card, face) {
  if (!card) return;
  if (face && face._original_ui_state) {
    const orig = JSON.parse(JSON.stringify(face._original_ui_state));
    face.template = face._original_template || face.template || 'M15Regular';
    face._ui_state = orig;
    card.frame_components = orig.frame_components;
    card._original_frame_components = { ...face._original_ui_state.frame_components };
    card.hidden_layers = orig.hidden_layers;
    card.layer_opacities = orig.layer_opacities;
    card.layer_colors = orig.layer_colors;
    card.layer_order = orig.layer_order;
    card.layout = orig.layout;
    if (face._original_text) {
      const ot = JSON.parse(JSON.stringify(face._original_text));
      card.name = ot.name;
      card.official_name = ot.official_name;
      card.mana_cost = ot.mana_cost;
      card.type_line = ot.type_line;
      card.oracle_text = ot.oracle_text;
      card.flavor_text = ot.flavor_text;
      card.power = ot.power;
      card.toughness = ot.toughness;
      card.artist = ot.artist;
      card.set = ot.set;
      card.rarity = ot.rarity;
      card.adventure = ot.adventure;
    }
    if (face._original_art_url) {
      card.custom_art_data = null;
      card.art_crop_url = face._original_art_url;
      if (face.art_layer) face.art_layer.url = face._original_art_url;
    }
    syncProjectFaceFromCard(card, face);
  }
}

export function syncProjectFaceFromCard(card, face) {
  if (!card || !face) return;
  face.text_layers = face.text_layers || {};
  const ensureEntry = (k) => {
    if (!face.text_layers[k]) face.text_layers[k] = { text: null, bounds: null };
    return face.text_layers[k];
  };
  ensureEntry('title').text = card.name || '';
  ensureEntry('mana_cost').text = card.mana_cost || '';
  ensureEntry('type_line').text = card.type_line || '';
  ensureEntry('oracle_text').text = card.oracle_text || '';
  ensureEntry('flavor_text').text = card.flavor_text || null;
  if (card.adventure) {
    ensureEntry('adventure_title').text = card.adventure.name || '';
    ensureEntry('adventure_mana_cost').text = card.adventure.mana_cost || '';
    ensureEntry('adventure_type_line').text = card.adventure.type_line || '';
    ensureEntry('adventure_oracle_text').text = card.adventure.oracle_text || '';
  }
  const ptEntry = ensureEntry('pt');
  ptEntry.power = card.power !== null && card.power !== undefined && String(card.power).trim() !== '' ? String(card.power).trim() : null;
  ptEntry.toughness = card.toughness !== null && card.toughness !== undefined && String(card.toughness).trim() !== '' ? String(card.toughness).trim() : null;
  if (ptEntry.power && card.hidden_layers?.pt_box && card._auto_pt_unhide !== false) {
    delete card.hidden_layers.pt_box;
    card._auto_pt_unhide = false;
  }
  const colEntry = ensureEntry('collector_info');
  colEntry.artist = card.artist || '';
  colEntry.set = card.set || colEntry.set || '';
  colEntry.rarity = card.rarity || colEntry.rarity || 'common';
  colEntry.text = colEntry.artist || '';

  if (card.custom_art_data) {
    face.art_layer = { ...(face.art_layer || {}), url: card.custom_art_data };
  } else if (card.art_crop_url) {
    face.art_layer = { ...(face.art_layer || {}), url: card.art_crop_url };
  }

  face._ui_state = {
    frame_components: card.frame_components || {},
    hidden_layers: card.hidden_layers || {},
    layer_opacities: card.layer_opacities || {},
    layer_colors: card.layer_colors || {},
    layer_order: card.layer_order || [...DEFAULT_LAYER_ORDER],
    layout: card.layout || face._ui_state?.layout || buildLayoutFromProjectFace(face),
  };
}

function openComponentFolder(url) {
  if (!url) return;
  fetch('/api/card-builder/open-component-folder', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  }).catch(() => {});
}

function showComponentContextMenu(evt, url, label = '') {
  if (!url) return;
  evt.preventDefault();
  evt.stopPropagation();
  let menu = document.getElementById('dg-comp-context-menu');
  if (!menu) {
    menu = document.createElement('div');
    menu.id = 'dg-comp-context-menu';
    menu.style.cssText = 'position:fixed; z-index:9999; min-width:210px; max-width:340px; background:var(--surface); border:1px solid var(--border); border-radius:6px; box-shadow:0 10px 28px rgba(0,0,0,0.45); padding:4px; display:none;';
    document.body.appendChild(menu);
    document.addEventListener('click', () => { menu.style.display = 'none'; });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') menu.style.display = 'none'; });
  }
  const shortPath = decodeURIComponent(String(url)).replace(/^\/assets\/resources\/frames\//, '').replace(/^\/assets\/resources\/_shared\//, '');
  menu.innerHTML = `
    <button type="button" data-act="open-folder" class="btn btn-sm" style="width:100%; justify-content:flex-start; gap:6px; border:none; background:transparent; text-align:left; padding:6px 8px;">
      <span>📁</span><span>Open containing folder</span>
    </button>
    <div style="padding:2px 8px 4px; font-family:monospace; font-size:9.5px; color:var(--text-muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${shortPath}">${shortPath}</div>
  `;
  menu.querySelector('[data-act="open-folder"]').onclick = (e) => {
    e.stopPropagation();
    menu.style.display = 'none';
    openComponentFolder(url);
  };
  menu.style.display = 'block';
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const mw = menu.offsetWidth || 230;
  const mh = menu.offsetHeight || 60;
  menu.style.left = `${Math.min(evt.clientX, vw - mw - 8)}px`;
  menu.style.top = `${Math.min(evt.clientY, vh - mh - 8)}px`;
}

export class LayerManager {
  constructor(listEl, onChange, onSelect = null) {
    this.listEl = listEl;
    this.onChange = onChange;
    this.onSelect = onSelect;
    this.dragKey = null;
    this.selectedKey = null;
    this.expandedKey = null;
    this.filterText = '';
    this.taxonomyFilters = { frame_era: '', layout: '', material: '', showcase_style: '' };
  }

  setTaxonomyFilters(filters, card = null) {
    this.taxonomyFilters = {
      frame_era: filters?.frame_era || '',
      layout: filters?.layout || '',
      material: filters?.material || '',
      showcase_style: filters?.showcase_style || '',
    };
    this.expandedKey = 'background';
    if (card) this.render(card);
  }

  // opts.backFace: the card's second face, which uses the "...Back" twin of a "...Front" pack
  // (e.g. TransformRegular -> M15TransformBack).
  setLayoutFilter(templateName, card = null, opts = {}) {
    this.currentTemplate = templateName || '';
    const cat = getSymbolsCatalog();
    const tpl = cat.templates?.[templateName];
    const rawPack = String(tpl?.pack || '').replace(/^pack/, '').replace(/\.js$/, '');
    const groups = cat.frame_catalog?.groups || [];
    let matchedGroup = null;
    let matchedPack = null;
    if (rawPack) {
      for (const g of groups) {
        const p = (g.packs || []).find((pk) => pk.id === rawPack);
        if (p) {
          matchedGroup = g;
          matchedPack = p;
          break;
        }
      }
    }
    if (opts.backFace && matchedPack && /Front$/.test(matchedPack.id)) {
      const backId = matchedPack.id.replace(/Front$/, 'Back');
      const backPack = (matchedGroup.packs || []).find((pk) => pk.id === backId);
      if (backPack) matchedPack = backPack;
    }
    this.layerCatalogSel = this.layerCatalogSel || {};
    // Layer key -> catalog slot (the Bottom/Textbox half browses the same frames as the top).
    for (const [layerKey, slotKey] of [['background', 'background'], ['textbox', 'background'], ['crown', 'crown'], ['pt_box', 'pt_box'], ['border', 'border'], ['name_box', 'name_box']]) {
      if (matchedPack && (matchedPack.items || []).some((it) => it.slot === slotKey)) {
        this.layerCatalogSel[layerKey] = { groupId: matchedGroup.id, packId: matchedPack.id };
      } else if (matchedGroup && (matchedGroup.packs || []).some((pk) => (pk.items || []).some((it) => it.slot === slotKey))) {
        this.layerCatalogSel[layerKey] = { groupId: matchedGroup.id, packId: '' };
      } else {
        this.layerCatalogSel[layerKey] = { groupId: '', packId: '' };
      }
    }
    this.filterText = '';
    if (card) this.render(card);
  }

  // After a Layout (Geometry) change: put each frame slot on the matching component of the new
  // layout's pack (selected by setLayoutFilter), so the frame art matches the new geometry.
  // A slot keeps its component if the pack already has it; otherwise it takes the pack's
  // component with the same label ("White Frame" -> "White Frame"), else the pack's first one.
  // Slots the pack doesn't cover are left alone, and hidden layers stay hidden.
  applyLayoutPackFrames(card) {
    if (!card) return 0;
    const cat = getSymbolsCatalog();
    const groups = cat.frame_catalog?.groups || [];
    const packFor = (sel) => {
      const g = groups.find((x) => x.id === sel?.groupId);
      return (g?.packs || []).find((pk) => pk.id === sel?.packId) || null;
    };
    const fc = card.frame_components = card.frame_components || {};
    const prevBackground = fc.background || '';
    let changed = 0;
    for (const [key, slot] of [['background', 'background'], ['textbox', 'background'], ['crown', 'crown'], ['pt_box', 'pt_box'], ['border', 'border']]) {
      const items = (packFor(this.layerCatalogSel?.[slot])?.items || []).filter((it) => it.slot === slot && it.url);
      if (!items.length) continue;
      if (key === 'textbox' && (!fc.textbox || fc.textbox === prevBackground)) {
        // Bottom half follows the top frame unless it was set separately (pop-out).
        if (fc.textbox !== fc.background) { fc.textbox = fc.background; changed += 1; }
        continue;
      }
      const pick = this._matchingPackItem(fc[key] || '', items);
      if (!pick) continue;
      fc[key] = pick.url;
      changed += 1;
    }
    return changed;
  }

  // The item of `items` that best replaces `currentUrl`: null if `currentUrl` is already one of
  // them, else the item with the same name ("Green Frame"), else the same colour (inferred from
  // name, file name or catalog material), else the first item.
  _matchingPackItem(currentUrl, items) {
    if (!items?.length) return null;
    const cat = getSymbolsCatalog();
    const groups = cat.frame_catalog?.groups || [];
    const norm = (u) => {
      try { return decodeURIComponent(String(u || '')).replace(/^https?:\/\/[^/]+/, '').replace(/^\/+/, ''); } catch { return String(u || ''); }
    };
    if (currentUrl && items.some((it) => norm(it.url) === norm(currentUrl))) return null;
    // Every catalog entry for a URL: pack items carry a name ("Green Frame"), role entries a material.
    const entriesFor = (url) => {
      const n = norm(url);
      const out = [];
      if (!n) return out;
      for (const g of groups) for (const pk of g.packs || []) for (const it of pk.items || []) if (norm(it.url) === n) out.push(it);
      for (const list of Object.values(cat.frames_by_role || {})) for (const it of list || []) if (norm(it.url) === n) out.push(it);
      return out;
    };
    const nameOf = (url) => entriesFor(url).map((e) => e.name || e.label || '').find(Boolean) || '';
    const colorOf = (url, name = '') => {
      const words = { white: 'w', blue: 'u', black: 'b', red: 'r', green: 'g', multicolored: 'm', multicolor: 'm', gold: 'm', artifact: 'a', land: 'l', colorless: 'c', snow: 'snow' };
      const fromWords = (txt) => {
        const w = String(txt || '').toLowerCase().match(/[a-z]+/g) || [];
        for (const t of w) if (words[t]) return words[t];
        return '';
      };
      const stem = (norm(url).split('/').pop() || '').replace(/\.[a-z0-9]+$/i, '');
      const fromFile = /snow/i.test(stem) ? 'snow'
        : ((stem.match(/^(?:.*frame)?([wubrgmalc])(?:regular|textless)?$/i) || [])[1] || '').toLowerCase();
      return fromWords(name) || fromFile || entriesFor(url).map((e) => fromWords(e.material) || fromWords(e.label)).find(Boolean) || '';
    };
    const name = nameOf(currentUrl);
    const color = colorOf(currentUrl, name);
    return (name && items.find((it) => it.name === name))
      || (color && items.find((it) => colorOf(it.url, it.name) === color))
      || items[0];
  }

  // The Layout (Geometry) template whose pack is `sel.packId` (its "...Front" twin for a "...Back"
  // pack), if it differs from the current template and the current template's pack is in the
  // same catalog group. Empty otherwise.
  _siblingTemplateForSel(sel) {
    if (!sel?.packId || !this.currentTemplate) return '';
    const cat = getSymbolsCatalog();
    const templates = cat.templates || {};
    const packOf = (name) => String(templates[name]?.pack || '').replace(/^pack/, '').replace(/\.js$/, '');
    const group = (cat.frame_catalog?.groups || []).find((g) => g.id === sel.groupId);
    const curPack = packOf(this.currentTemplate);
    if (!group || !(group.packs || []).some((pk) => pk.id === curPack || pk.id === curPack.replace(/Front$/, 'Back'))) return '';
    const wanted = [sel.packId, sel.packId.replace(/Back$/, 'Front')];
    if (wanted.includes(curPack)) return '';
    return Object.keys(templates).find((name) => wanted.includes(packOf(name))) || '';
  }

  // After the user picks a Group/Template in a layer's browser: if the layer's current component
  // is not in the new selection, switch it to the matching one there (same name, colour, or the first).
  // "All" (no group) leaves the layer as it is.
  _applyCatalogSelection(card, key) {
    if (!card || !this.layerCatalogSel?.[key]?.groupId) return false;
    // Picking a sibling template's pack for the Frame (e.g. Tokens & Markers › Tall while on
    // TokenRegular) switches Layout (Geometry) to that template, whose layout change then also
    // applies the matching frame.
    const tplName = key === 'background' ? this._siblingTemplateForSel(this.layerCatalogSel[key]) : '';
    if (tplName && this.onLayoutRequest) {
      this.onLayoutRequest(card, tplName);
      return true;
    }
    const pick = this._matchingPackItem(card.frame_components?.[key] || '', this._getLayerItems(key));
    if (!pick) return false;
    this._applyComponentItem(card, key, pick);
    return true;
  }

  setSelected(key) {
    this.selectedKey = key || null;
    if (!this.listEl) return;
    this.listEl.querySelectorAll('.layer-item').forEach((el) => {
      const isMatch = Boolean(this.selectedKey && el.dataset.layerKey === this.selectedKey);
      el.classList.toggle('is-selected', isMatch);
      if (isMatch) {
        el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    });
  }

  _getLayerItems(key) {
    const cat = getSymbolsCatalog();
    const slotKey = key === 'textbox' ? 'background' : key;
    // A template pack selected for this layer (setLayoutFilter / the drawer's Template select)
    // limits the components to that pack; "All" in the drawer clears it.
    const sel = this.layerCatalogSel?.[key];
    if (sel?.groupId) {
      const group = (cat.frame_catalog?.groups || []).find((g) => g.id === sel.groupId);
      const packs = (group?.packs || []).filter((pk) => !sel.packId || pk.id === sel.packId);
      const packItems = packs.flatMap((pk) => (pk.items || []).filter((it) => it.slot === slotKey && it.url));
      if (packItems.length) return packItems;
    }
    const all = (cat.frames_by_role && cat.frames_by_role[slotKey]) || [];
    if (slotKey !== 'background') return all;
    const tf = this.taxonomyFilters || {};
    if (!tf.frame_era && !tf.layout && !tf.material && !tf.showcase_style) return all;
    return all.filter((it) => {
      if (tf.frame_era && it.frame_era !== tf.frame_era) return false;
      if (tf.layout && it.layout !== tf.layout && it.structural !== tf.layout) return false;
      if (tf.material && it.material !== tf.material) return false;
      if (tf.showcase_style && it.showcase_style !== tf.showcase_style) return false;
      return true;
    });
  }

  _applyComponentItem(card, key, item) {
    if (!card || !item) return;
    card.frame_components = card.frame_components || {};
    const prevBg = card.frame_components.background || '';
    card.frame_components[key] = item.url;
    // Keep Bottom Textbox synced with Top Frame unless, in pop-out mode, the user chose a different one
    if (key === 'background' && (!isSplitFrame(card) || !card.frame_components.textbox || card.frame_components.textbox === prevBg)) {
      card.frame_components.textbox = item.url;
    }
    // Frame image selection is intentionally decoupled from card text/art Layout.
    card.hidden_layers = normalizeHiddenLayers(card.hidden_layers);
    delete card.hidden_layers[key];
    this.render(card);
    this.onChange?.(card);
  }

  _stepComponent(card, key, delta) {
    const items = this._getLayerItems(key);
    if (!items.length) return;
    const curUrl = card.frame_components?.[key] || '';
    let idx = items.findIndex((it) => it.url === curUrl);
    if (idx < 0) idx = delta > 0 ? 0 : items.length - 1;
    else idx = (idx + delta + items.length) % items.length;
    this._applyComponentItem(card, key, items[idx]);
  }

  render(card) {
    if (!this.listEl || !card) return;
    const shapes = Array.isArray(card.shapes) ? card.shapes : [];
    const shapeMap = new Map(shapes.map((s) => [`shape:${s.id}`, s]));
    const validKeys = new Set([...DEFAULT_LAYER_ORDER, ...shapeMap.keys()]);

    const order = Array.isArray(card.layer_order) && card.layer_order.length
      ? card.layer_order.filter((k) => validKeys.has(k))
      : [...DEFAULT_LAYER_ORDER];
    DEFAULT_LAYER_ORDER.forEach((k) => { if (!order.includes(k)) order.push(k); });
    shapeMap.forEach((_, sk) => { if (!order.includes(sk)) order.push(sk); });
    card.layer_order = order;
    card.hidden_layers = normalizeHiddenLayers(card.hidden_layers);
    card.layer_opacities = card.layer_opacities || {};

    this.listEl.innerHTML = '';
    const splitFrame = isSplitFrame(card);
    const displayOrder = [...order].reverse();

    displayOrder.forEach((key) => {
      if (key === 'textbox' && !splitFrame) return;
      const wrapLi = document.createElement('li');
      wrapLi.className = 'layer-item-wrap';
      wrapLi.style.listStyle = 'none';

      const li = document.createElement('div');
      const isShape = key.startsWith('shape:');
      const shape = isShape ? shapeMap.get(key) : null;
      const carouselItems = (!isShape && key !== 'art') ? this._getLayerItems(key) : [];
      const hasCarousel = carouselItems.length > 0;
      const resolvedUrl = key === 'textbox'
        ? (card.frame_components?.textbox || card.frame_components?.background || '')
        : (card.frame_components?.[key] || '');
      const isEmptyFrame = !isShape && key !== 'art' && !resolvedUrl;
      const isHidden = Boolean(card.hidden_layers[key]) || isEmptyFrame;
      const isSelected = Boolean(this.selectedKey && this.selectedKey === key);
      const isExpanded = Boolean(hasCarousel && this.expandedKey === key);
      li.className = 'layer-item' + (isHidden ? ' is-hidden-layer' : '') + (isSelected ? ' is-selected' : '');
      li.draggable = true;
      li.dataset.layerKey = key;

      const opacity = isShape
        ? (shape?.opacity ?? card.layer_opacities[key] ?? 0.55)
        : (card.layer_opacities[key] ?? 1.0);

      if (isShape && shape) {
        const shapeIdx = shapes.findIndex((s) => s.id === shape.id) + 1;
        const iconName = SHAPE_ICONS[shape.type] || 'rect';
        const label = shape.type === 'circle' ? 'Circle' : (shape.type === 'rounded' ? 'Rounded' : 'Box');
        li.innerHTML = `
          <span title="Arrastrar para reordenar" style="cursor:grab; opacity:0.6; display:inline-flex;">${iconSvg('grip', 12)}</span>
          <button type="button" class="btn btn-sm" data-act="toggle" title="${isHidden ? 'Mostrar capa' : 'Ocultar capa'}">${iconSvg(isHidden ? 'eye-off' : 'eye', 13)}</button>
          <span class="layer-name">${iconSvg(iconName, 12)} ${label} #${shapeIdx}</span>
          <input type="color" data-act="color" value="${shape.color || '#000000'}" title="Color" style="width:20px; height:18px; padding:0; border:none; background:none; cursor:pointer; flex-shrink:0;">
          <input type="range" min="0" max="1" step="0.05" value="${opacity}" data-act="opacity" style="width:44px;" title="Opacidad">
          <button type="button" class="btn btn-sm" data-act="dup" title="Duplicar" style="padding:2px 4px;">${iconSvg('copy', 12)}</button>
          <button type="button" class="btn btn-sm" data-act="del" title="Eliminar" style="padding:2px 4px;">${iconSvg('x', 12)}</button>
        `;
      } else {
        const canColor = COLORABLE_FRAME_KEYS.has(key);
        const curColor = canColor ? ((card.layer_colors && card.layer_colors[key]) || '') : '';
        const hasColor = Boolean(curColor && curColor !== 'no-color');
        const colorCtrlHtml = canColor
          ? `<input type="color" data-act="layer-color" value="${hasColor ? curColor : '#1e293b'}" title="${hasColor ? `Tinte: ${curColor}` : 'Aplicar tinte de color'}" style="width:16px; height:16px; padding:0; border:1px solid ${hasColor ? 'var(--accent)' : 'var(--border)'}; border-radius:3px; background:none; cursor:pointer; opacity:${hasColor ? '1' : '0.45'}; flex-shrink:0;">`
            + (hasColor ? `<button type="button" class="btn btn-sm" data-act="layer-color-clear" title="Quitar tinte" style="padding:1px 3px;">${iconSvg('x', 10)}</button>` : '')
          : '';
        const navArrowsHtml = hasCarousel
          ? `<button type="button" class="btn btn-sm layer-nav-btn" data-act="prev" title="Variante anterior">‹</button>`
            + `<button type="button" class="btn btn-sm layer-nav-btn" data-act="next" title="Siguiente variante">›</button>`
          : '';
        const caretHtml = hasCarousel ? `<span style="font-size:10px; opacity:0.65; margin-left:2px;">${isExpanded ? '▾' : '▸'}</span>` : '';
        li.innerHTML = `
          <span title="Arrastrar para reordenar" style="cursor:grab; opacity:0.6; display:inline-flex;">${iconSvg('grip', 12)}</span>
          <button type="button" class="btn btn-sm" data-act="toggle" title="${isHidden ? 'Mostrar capa' : 'Ocultar capa'}" aria-pressed="${isHidden ? 'true' : 'false'}">${iconSvg(isHidden ? 'eye-off' : 'eye', 13)}</button>
          <span class="layer-name" style="cursor:${hasCarousel ? 'pointer' : 'default'};" title="${hasCarousel ? 'Clic para desplegar carrusel de variantes' : ''}">${layerLabel(key, card)}${caretHtml}</span>
          ${navArrowsHtml}
          ${colorCtrlHtml}
          <input type="range" min="0" max="1" step="0.05" value="${opacity}" data-act="opacity" style="width:40px;" title="Opacidad">
        `;
      }

      const toggleBtn = li.querySelector('[data-act="toggle"]');
      const prevBtn = li.querySelector('[data-act="prev"]');
      const nextBtn = li.querySelector('[data-act="next"]');
      const opacityInput = li.querySelector('[data-act="opacity"]');
      const colorInput = li.querySelector('[data-act="color"]');
      const layerColorInput = li.querySelector('[data-act="layer-color"]');
      const layerColorClearBtn = li.querySelector('[data-act="layer-color-clear"]');
      const dupBtn = li.querySelector('[data-act="dup"]');
      const delBtn = li.querySelector('[data-act="del"]');

      [toggleBtn, prevBtn, nextBtn, opacityInput, colorInput, layerColorInput, layerColorClearBtn, dupBtn, delBtn].filter(Boolean).forEach((ctrl) => {
        ctrl.addEventListener('pointerdown', (e) => {
          e.stopPropagation();
          li.draggable = false;
          const restore = () => { li.draggable = true; };
          window.addEventListener('pointerup', restore, { once: true });
          window.addEventListener('pointercancel', restore, { once: true });
        });
      });

      if (prevBtn) {
        prevBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          this._stepComponent(card, key, -1);
        });
      }
      if (nextBtn) {
        nextBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          this._stepComponent(card, key, 1);
        });
      }

      if (layerColorInput) {
        layerColorInput.addEventListener('input', (e) => {
          card.layer_colors = card.layer_colors || {};
          card.layer_colors[key] = e.target.value;
          layerColorInput.style.opacity = '1';
          layerColorInput.style.borderColor = 'var(--accent)';
          this.onChange?.(card);
        });
        layerColorInput.addEventListener('change', () => this.render(card));
      }

      if (layerColorClearBtn) {
        layerColorClearBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          if (card.layer_colors) delete card.layer_colors[key];
          this.render(card);
          this.onChange?.(card);
        });
      }

      li.addEventListener('click', (e) => {
        if (e.target && e.target.closest('button, input')) return;
        this.setSelected(key);
        this.onSelect?.(key, card);
        if (hasCarousel) {
          this.expandedKey = (this.expandedKey === key) ? null : key;
          this.filterText = '';
          this.render(card);
        }
      });

      if (!isShape && key !== 'art') {
        li.addEventListener('contextmenu', (e) => {
          const url = key === 'textbox'
            ? (card.frame_components?.textbox || card.frame_components?.background)
            : card.frame_components?.[key];
          if (url) showComponentContextMenu(e, url, layerLabel(key, card));
        });
      }

      toggleBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        card.hidden_layers = normalizeHiddenLayers(card.hidden_layers);
        card.hidden_layers[key] = !card.hidden_layers[key];
        this.render(card);
        this.onChange?.(card);
      });

      opacityInput.addEventListener('input', (e) => {
        const val = parseFloat(e.target.value);
        card.layer_opacities[key] = val;
        if (isShape && shape) shape.opacity = val;
        this.onChange?.(card);
      });

      if (colorInput && shape) {
        colorInput.addEventListener('input', (e) => {
          shape.color = e.target.value;
          this.onChange?.(card);
        });
      }

      if (dupBtn && shape) {
        dupBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          const newId = 's_' + Date.now() + '_' + Math.floor(Math.random() * 1000);
          const copy = { ...shape, id: newId, x: (shape.x || 70) + 18, y: (shape.y || 640) + 18 };
          card.shapes.push(copy);
          const copyKey = `shape:${newId}`;
          const curIdx = card.layer_order.indexOf(key);
          if (curIdx >= 0) card.layer_order.splice(curIdx + 1, 0, copyKey);
          else card.layer_order.push(copyKey);
          card.layer_opacities[copyKey] = copy.opacity ?? 0.55;
          this.selectedKey = copyKey;
          this.render(card);
          this.onSelect?.(copyKey, card);
          this.onChange?.(card);
        });
      }

      if (delBtn && shape) {
        delBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          card.shapes = (card.shapes || []).filter((s) => s.id !== shape.id);
          card.layer_order = (card.layer_order || []).filter((k) => k !== key);
          delete card.layer_opacities[key];
          if (card.hidden_layers) delete card.hidden_layers[key];
          if (this.selectedKey === key) this.selectedKey = null;
          this.render(card);
          this.onSelect?.(null, card);
          this.onChange?.(card);
        });
      }

      li.addEventListener('dragstart', (e) => {
        if (e.target && e.target.closest('button, input')) {
          e.preventDefault();
          return;
        }
        this.dragKey = key;
        li.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', key);
      });

      li.addEventListener('dragend', () => {
        this.dragKey = null;
        this.listEl.querySelectorAll('.layer-item').forEach((el) => {
          el.classList.remove('dragging', 'drop-above', 'drop-below');
        });
      });

      const handleDragOver = (e) => {
        e.preventDefault();
        if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
        const dragged = this.dragKey;
        if (!dragged || dragged === key) return;
        const rect = li.getBoundingClientRect();
        const isAbove = e.clientY < rect.top + rect.height / 2;
        this.listEl.querySelectorAll('.layer-item').forEach((el) => el.classList.remove('drop-above', 'drop-below'));
        li.classList.add(isAbove ? 'drop-above' : 'drop-below');
      };

      const handleDrop = (e) => {
        e.preventDefault();
        e.stopPropagation();
        const dragged = this.dragKey || (e.dataTransfer && e.dataTransfer.getData('text/plain'));
        this.dragKey = null;
        if (!dragged || dragged === key) return;
        const rect = li.getBoundingClientRect();
        const dropAboveInUI = e.clientY < rect.top + rect.height / 2;

        const nextDisplay = displayOrder.filter((k) => k !== dragged);
        let targetIdx = nextDisplay.indexOf(key);
        if (targetIdx < 0) return;
        if (!dropAboveInUI) targetIdx += 1;
        nextDisplay.splice(targetIdx, 0, dragged);
        card.layer_order = [...nextDisplay].reverse();
        const artIdx = card.layer_order.indexOf('art');
        const bgIdx = card.layer_order.indexOf('background');
        if (artIdx >= 0 && bgIdx >= 0) {
          card.art_over_top = artIdx > bgIdx;
        }
        this.render(card);
        this.onChange?.(card);
      };

      wrapLi.addEventListener('dragover', handleDragOver);
      wrapLi.addEventListener('dragleave', (e) => {
        if (!wrapLi.contains(e.relatedTarget)) {
          li.classList.remove('drop-above', 'drop-below');
        }
      });
      wrapLi.addEventListener('drop', handleDrop);

      wrapLi.appendChild(li);

      // Collapsible Carousel Drawer when this layer is expanded (Card Conjurer Group -> Template -> Component hierarchy)
      if (isExpanded && hasCarousel) {
        const cat = getSymbolsCatalog();
        const catalogSlot = key === 'textbox' ? 'background' : key;
        const rawGroups = cat.frame_catalog?.groups || [];
        const fallbackRoleItems = (cat.frames_by_role && cat.frames_by_role[catalogSlot]) || [];

        // Build structured groups -> packs filtered to this layer slot (catalogSlot)
        const slotGroups = [];
        const allSlotItems = [];
        const seenUrlInSlot = new Set();
        for (const g of rawGroups) {
          const matchingPacks = [];
          for (const p of (g.packs || [])) {
            const pItems = (p.items || []).filter((it) => it.slot === catalogSlot);
            if (!pItems.length) continue;
            matchingPacks.push({ id: p.id, name: p.name, section: p.section || 'Main', items: pItems });
            for (const it of pItems) {
              if (!seenUrlInSlot.has(it.url)) {
                seenUrlInSlot.add(it.url);
                allSlotItems.push(it);
              }
            }
          }
          if (matchingPacks.length) {
            slotGroups.push({ id: g.id, name: g.name, packs: matchingPacks });
          }
        }
        // Fallback if frame_catalog has no items for this slot
        const effectiveAll = allSlotItems.length ? allSlotItems : fallbackRoleItems.map((it) => ({
          ...it,
          name: it.label,
          group: 'Otros',
          group_id: 'Other',
          pack: it.template || 'Estándar',
          pack_id: it.template || 'default',
        }));

        const curUrl = card.frame_components?.[key] || '';
        const origUrl = card._original_frame_components?.[key] || '';
        const findMeta = (u) => {
          if (!u) return null;
          const exact = effectiveAll.find((it) => it.url === u);
          if (exact) return exact;
          const fb = fallbackRoleItems.find((it) => it.url === u);
          return fb ? { ...fb, name: fb.label, group: '', pack: fb.template || '' } : null;
        };
        const curItem = findMeta(curUrl);
        const origItem = findMeta(origUrl);
        const isModifiedFromOrig = Boolean(origUrl && origUrl !== curUrl);

        this.layerCatalogSel = this.layerCatalogSel || {};
        if (!this.layerCatalogSel[key]) {
          this.layerCatalogSel[key] = {
            groupId: curItem?.group_id || '',
            packId: curItem?.pack_id || '',
          };
        }
        const sel = this.layerCatalogSel[key];
        // Validate saved group/pack still exist
        if (sel.groupId && !slotGroups.some((g) => g.id === sel.groupId)) sel.groupId = '';
        const activeGroupObj = sel.groupId ? slotGroups.find((g) => g.id === sel.groupId) : null;
        const availablePacks = activeGroupObj
          ? activeGroupObj.packs
          : slotGroups.flatMap((g) => g.packs.map((p) => ({ ...p, _groupName: g.name })));
        if (sel.packId && !availablePacks.some((p) => p.id === sel.packId)) sel.packId = '';

        const fmtRef = (it) => {
          if (!it) return 'Unassigned';
          const parts = [it.pack, it.name].filter(Boolean);
          return parts.join(' · ');
        };

        const pinHtml = `
          <div style="display:flex; flex-direction:column; gap:2px; padding:5px 6px; margin-bottom:5px; border-radius:4px; background:var(--surface); border:1px solid var(--border); font-size:10px;">
            <div class="row-between" style="gap:4px;">
              <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${fmtRef(curItem)}">📌 <strong>Current:</strong> ${fmtRef(curItem)}</span>
              <div class="row" style="gap:4px; flex-shrink:0; align-items:center;">
                <span style="color:var(--text-muted);" data-el="car-count"></span>
                <button type="button" class="btn btn-sm" data-act="maximize-drawer" style="padding:1px 5px; font-size:10px;" title="Maximize component browser">⤢</button>
              </div>
            </div>
            ${isModifiedFromOrig ? `
              <div class="row-between" style="gap:4px; color:var(--text-muted);">
                <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${fmtRef(origItem)}">Initial: ${fmtRef(origItem)}</span>
                <button type="button" class="btn btn-sm" data-act="restore-orig-comp" style="padding:0 5px; font-size:9.5px; flex-shrink:0;" title="Restore initial component">↩ Original</button>
              </div>` : ''}
          </div>`;

        const groupOptsHtml = `<option value="">Group: All (${slotGroups.length})</option>` +
          slotGroups.map((g) => `<option value="${g.id}" ${g.id === sel.groupId ? 'selected' : ''}>${g.name}</option>`).join('');
        const packOptsHtml = `<option value="">Template: All (${availablePacks.length})</option>` +
          availablePacks.map((p) => {
            const lbl = p._groupName ? `${p.name} (${p._groupName})` : p.name;
            return `<option value="${p.id}" ${p.id === sel.packId ? 'selected' : ''}>${lbl}</option>`;
          }).join('');

        const drawer = document.createElement('div');
        drawer.className = 'layer-carousel';
        drawer.innerHTML = `
          ${pinHtml}
          ${slotGroups.length ? `
            <div style="display:flex; flex-direction:column; gap:4px; margin-bottom:5px;">
              <select class="select" data-cat="group" style="font-size:10.5px; padding:3px 5px; width:100%;" title="Frame group">${groupOptsHtml}</select>
              <select class="select" data-cat="pack" style="font-size:10.5px; padding:3px 5px; width:100%;" title="Template / Pack">${packOptsHtml}</select>
            </div>` : ''}
          <div class="row" style="gap:4px; margin-bottom:4px;">
            <input type="text" class="input" data-act="carousel-filter" placeholder="Search template or color..." value="${this.filterText}" style="padding:3px 6px; font-size:10.5px; flex:1;">
            <button type="button" class="btn btn-sm" data-act="clear-cat" style="padding:2px 6px; font-size:10px;" title="Show all groups and templates">All</button>
          </div>
          <div class="layer-carousel-track-row">
            <button type="button" class="btn btn-sm layer-nav-btn" data-act="car-prev" title="Previous">‹</button>
            <div class="layer-carousel-track"></div>
            <button type="button" class="btn btn-sm layer-nav-btn" data-act="car-next" title="Next">›</button>
          </div>
        `;

        const trackEl = drawer.querySelector('.layer-carousel-track');
        const countEl = drawer.querySelector('[data-el="car-count"]');
        const groupSel = drawer.querySelector('select[data-cat="group"]');
        const packSel = drawer.querySelector('select[data-cat="pack"]');
        const filterIn = drawer.querySelector('[data-act="carousel-filter"]');
        const clearCatBtn = drawer.querySelector('[data-act="clear-cat"]');
        const restoreOrigBtn = drawer.querySelector('[data-act="restore-orig-comp"]');
        const maxDrawerBtn = drawer.querySelector('[data-act="maximize-drawer"]');
        const carPrev = drawer.querySelector('[data-act="car-prev"]');
        const carNext = drawer.querySelector('[data-act="car-next"]');

        maxDrawerBtn?.addEventListener('click', (e) => {
          e.stopPropagation();
          this._openMaximizedComponentModal(card, key, slotGroups, effectiveAll, sel, findMeta, fmtRef);
        });

        const getVisibleList = (q = '') => {
          const ql = q.trim().toLowerCase();
          let list = effectiveAll;
          if (sel.groupId) {
            const gObj = slotGroups.find((g) => g.id === sel.groupId);
            if (gObj) {
              if (sel.packId) {
                const pObj = gObj.packs.find((p) => p.id === sel.packId);
                list = pObj ? pObj.items : [];
              } else {
                list = gObj.packs.flatMap((p) => p.items);
              }
            }
          } else if (sel.packId) {
            for (const g of slotGroups) {
              const pObj = g.packs.find((p) => p.id === sel.packId);
              if (pObj) { list = pObj.items; break; }
            }
          }
          if (ql) {
            list = list.filter((it) =>
              `${it.name || ''} ${it.pack || ''} ${it.group || ''}`.toLowerCase().includes(ql)
            );
          }
          return list;
        };

        const renderTrack = (q = '') => {
          trackEl.innerHTML = '';
          const filtered = getVisibleList(q);
          if (countEl) countEl.textContent = `${filtered.length}`;
          if (!filtered.length) {
            trackEl.innerHTML = '<span style="font-size:10.5px; color:var(--text-muted); padding:6px;">No matches</span>';
            return;
          }
          const visibleItems = filtered.slice(0, 120);
          const showPackTag = !sel.packId;
          visibleItems.forEach((it) => {
            const isActive = it.url === curUrl;
            const isOrig = Boolean(origUrl && it.url === origUrl);
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'layer-carousel-card' + (isActive ? ' is-active' : '');
            btn.title = `${it.group ? it.group + ' › ' : ''}${it.pack ? it.pack + ' › ' : ''}${it.name}${isOrig ? ' (Initial)' : ''}`;
            btn.style.position = 'relative';
            const subTag = showPackTag && it.pack
              ? `<span style="font-size:8.5px; opacity:0.7; display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${it.pack}</span>`
              : '';
            btn.innerHTML = `${isOrig ? '<span style="position:absolute; top:2px; right:2px; font-size:10px; line-height:1; background:rgba(0,0,0,0.75); padding:1px 3px; border-radius:3px;" title="Initial component">📌</span>' : ''}<img src="${it.url}" loading="lazy" alt="${it.name}"><span>${it.name}</span>${subTag}`;
            btn.addEventListener('click', (e) => {
              e.stopPropagation();
              this._applyComponentItem(card, key, it);
            });
            btn.addEventListener('contextmenu', (e) => {
              showComponentContextMenu(e, it.url, it.name);
            });
            trackEl.appendChild(btn);
          });
          if (filtered.length > visibleItems.length) {
            const more = document.createElement('span');
            more.style.cssText = 'font-size:10px; color:var(--text-muted); padding:6px; align-self:center; white-space:nowrap;';
            more.textContent = `+${filtered.length - visibleItems.length} more (select a Template)`;
            trackEl.appendChild(more);
          }
          const activeCard = trackEl.querySelector('.is-active');
          if (activeCard) activeCard.scrollIntoView({ inline: 'center', block: 'nearest' });
        };

        renderTrack(this.filterText);
        groupSel?.addEventListener('change', (e) => {
          e.stopPropagation();
          sel.groupId = groupSel.value;
          sel.packId = '';
          if (!this._applyCatalogSelection(card, key)) this.render(card);
        });
        packSel?.addEventListener('change', (e) => {
          e.stopPropagation();
          sel.packId = packSel.value;
          if (!this._applyCatalogSelection(card, key)) renderTrack(this.filterText);
        });
        clearCatBtn?.addEventListener('click', (e) => {
          e.stopPropagation();
          sel.groupId = '';
          sel.packId = '';
          this.filterText = '';
          this.render(card);
        });
        restoreOrigBtn?.addEventListener('click', (e) => {
          e.stopPropagation();
          if (origItem) {
            sel.groupId = origItem.group_id || '';
            sel.packId = origItem.pack_id || '';
            this._applyComponentItem(card, key, origItem);
          } else if (origUrl) {
            this._applyComponentItem(card, key, { url: origUrl, label: 'Original' });
          }
        });
        filterIn.addEventListener('input', (e) => {
          this.filterText = e.target.value;
          renderTrack(this.filterText);
        });
        carPrev.addEventListener('click', (e) => {
          e.stopPropagation();
          const list = getVisibleList(this.filterText);
          if (!list.length) return;
          const idx = list.findIndex((it) => it.url === curUrl);
          const next = list[(idx < 0 ? list.length - 1 : (idx - 1 + list.length) % list.length)];
          this._applyComponentItem(card, key, next);
        });
        carNext.addEventListener('click', (e) => {
          e.stopPropagation();
          const list = getVisibleList(this.filterText);
          if (!list.length) return;
          const idx = list.findIndex((it) => it.url === curUrl);
          const next = list[(idx < 0 ? 0 : (idx + 1) % list.length)];
          this._applyComponentItem(card, key, next);
        });

        wrapLi.appendChild(drawer);
      }

      this.listEl.appendChild(wrapLi);
    });
  }

  _openMaximizedComponentModal(card, key, slotGroups, effectiveAll, sel, findMeta, fmtRef) {
    let overlay = document.getElementById('dg-comp-maximize-modal');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'dg-comp-maximize-modal';
      overlay.className = 'modal-overlay';
      overlay.innerHTML = `
        <div class="modal-content" style="width:980px; max-width:95vw; max-height:88vh; display:flex; flex-direction:column;">
          <div class="modal-header">
            <span data-el="title">Browse Components</span>
            <button type="button" class="modal-close" data-act="close">&times;</button>
          </div>
          <div class="modal-body" style="display:flex; flex-direction:column; gap:10px; overflow:hidden; flex:1;">
            <div data-el="pin-bar" style="padding:6px 10px; border-radius:6px; background:var(--surface-2); border:1px solid var(--border); font-size:11.5px; display:flex; align-items:center; justify-content:space-between; gap:8px; flex-wrap:wrap;"></div>
            <div class="row" style="gap:8px; flex-wrap:wrap; align-items:center;">
              <select class="select" data-el="group" style="width:220px;"></select>
              <select class="select" data-el="pack" style="width:260px;"></select>
              <input type="text" class="input" data-el="search" placeholder="Search template or color..." style="flex:1; min-width:180px;">
              <button type="button" class="btn btn-sm" data-act="all">All</button>
              <span data-el="count" style="font-size:11.5px; color:var(--text-muted); white-space:nowrap;"></span>
            </div>
            <div style="font-size:11px; color:var(--text-muted); margin-top:-4px;">Click any component to apply it. Hold <strong>Shift + Click</strong> to keep this window open while comparing.</div>
            <div data-el="grid" class="art-results-grid" style="overflow-y:auto; flex:1; grid-template-columns:repeat(auto-fill, minmax(140px, 1fr)); padding-right:4px;"></div>
          </div>
        </div>`;
      document.body.appendChild(overlay);
    }

    const titleEl = overlay.querySelector('[data-el="title"]');
    const pinBarEl = overlay.querySelector('[data-el="pin-bar"]');
    const groupSel = overlay.querySelector('[data-el="group"]');
    const packSel = overlay.querySelector('[data-el="pack"]');
    const searchIn = overlay.querySelector('[data-el="search"]');
    const countEl = overlay.querySelector('[data-el="count"]');
    const gridEl = overlay.querySelector('[data-el="grid"]');

    titleEl.textContent = `Browse ${layerLabel(key, card)} Components`;
    searchIn.value = this.filterText || '';

    const close = () => {
      overlay.classList.remove('open');
      overlay.onclick = null;
      this.render(card);
    };

    const populateDropdowns = () => {
      groupSel.innerHTML = `<option value="">Group: All (${slotGroups.length})</option>` +
        slotGroups.map((g) => `<option value="${g.id}" ${g.id === sel.groupId ? 'selected' : ''}>${g.name}</option>`).join('');
      const activeGroupObj = sel.groupId ? slotGroups.find((g) => g.id === sel.groupId) : null;
      const availPacks = activeGroupObj
        ? activeGroupObj.packs
        : slotGroups.flatMap((g) => g.packs.map((p) => ({ ...p, _groupName: g.name })));
      if (sel.packId && !availPacks.some((p) => p.id === sel.packId)) sel.packId = '';
      packSel.innerHTML = `<option value="">Template: All (${availPacks.length})</option>` +
        availPacks.map((p) => `<option value="${p.id}" ${p.id === sel.packId ? 'selected' : ''}>${p._groupName ? `${p.name} (${p._groupName})` : p.name}</option>`).join('');
    };

    const renderGrid = () => {
      const curUrl = card.frame_components?.[key] || '';
      const origUrl = card._original_frame_components?.[key] || '';
      const curItem = findMeta(curUrl);
      const origItem = findMeta(origUrl);
      const isMod = Boolean(origUrl && origUrl !== curUrl);

      pinBarEl.innerHTML = `
        <span>📌 <strong>Current:</strong> ${fmtRef(curItem)}</span>
        ${isMod ? `<span class="row" style="gap:6px; color:var(--text-muted);"><span>Initial: ${fmtRef(origItem)}</span><button type="button" class="btn btn-sm" data-act="restore-orig">↩ Original</button></span>` : ''}
      `;
      pinBarEl.querySelector('[data-act="restore-orig"]')?.addEventListener('click', () => {
        if (origItem) {
          sel.groupId = origItem.group_id || '';
          sel.packId = origItem.pack_id || '';
          this._applyComponentItem(card, key, origItem);
        } else if (origUrl) {
          this._applyComponentItem(card, key, { url: origUrl, label: 'Original' });
        }
        populateDropdowns();
        renderGrid();
      });

      const ql = (searchIn.value || '').trim().toLowerCase();
      let list = effectiveAll;
      if (sel.groupId) {
        const gObj = slotGroups.find((g) => g.id === sel.groupId);
        if (gObj) {
          if (sel.packId) {
            const pObj = gObj.packs.find((p) => p.id === sel.packId);
            list = pObj ? pObj.items : [];
          } else {
            list = gObj.packs.flatMap((p) => p.items);
          }
        }
      } else if (sel.packId) {
        for (const g of slotGroups) {
          const pObj = g.packs.find((p) => p.id === sel.packId);
          if (pObj) { list = pObj.items; break; }
        }
      }
      if (ql) {
        list = list.filter((it) => `${it.name || ''} ${it.pack || ''} ${it.group || ''}`.toLowerCase().includes(ql));
      }

      countEl.textContent = `${list.length} items`;
      gridEl.innerHTML = '';
      if (!list.length) {
        gridEl.innerHTML = '<p style="color:var(--text-muted); grid-column:1/-1; padding:12px;">No matching components.</p>';
        return;
      }

      const maxShow = 300;
      list.slice(0, maxShow).forEach((it) => {
        const isActive = it.url === curUrl;
        const isOrig = Boolean(origUrl && it.url === origUrl);
        const tile = document.createElement('div');
        tile.className = 'art-result-card';
        tile.style.cssText = `cursor:pointer; position:relative; ${isActive ? 'outline:2px solid var(--accent);' : ''}`;
        tile.title = `${it.group ? it.group + ' › ' : ''}${it.pack ? it.pack + ' › ' : ''}${it.name}`;
        tile.innerHTML = `
          ${isOrig ? '<span style="position:absolute; top:6px; right:6px; font-size:11px; background:rgba(0,0,0,0.78); padding:1px 4px; border-radius:4px; z-index:2;" title="Initial component">📌</span>' : ''}
          <img src="${it.url}" loading="lazy" alt="${it.name}" style="width:100%; aspect-ratio:5/7; object-fit:contain; background:#111; border-radius:4px;">
          <div style="font-size:11px; font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${it.name}</div>
          <div style="font-size:9.5px; color:var(--text-muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${it.pack || ''}</div>
        `;
        tile.addEventListener('click', (evt) => {
          this._applyComponentItem(card, key, it);
          if (!evt.shiftKey) close();
          else renderGrid();
        });
        tile.addEventListener('contextmenu', (evt) => {
          showComponentContextMenu(evt, it.url, it.name);
        });
        gridEl.appendChild(tile);
      });
      if (list.length > maxShow) {
        const note = document.createElement('p');
        note.style.cssText = 'grid-column:1/-1; font-size:11px; color:var(--text-muted); text-align:center; padding:6px;';
        note.textContent = `Showing first ${maxShow} of ${list.length} components — filter by Group, Template, or search to narrow down.`;
        gridEl.appendChild(note);
      }
    };

    groupSel.onchange = () => {
      sel.groupId = groupSel.value;
      sel.packId = '';
      this._applyCatalogSelection(card, key);
      populateDropdowns();
      renderGrid();
    };
    packSel.onchange = () => {
      sel.packId = packSel.value;
      this._applyCatalogSelection(card, key);
      renderGrid();
    };
    searchIn.oninput = () => {
      this.filterText = searchIn.value;
      renderGrid();
    };
    overlay.onclick = (e) => {
      if (e.target === overlay || e.target?.getAttribute?.('data-act') === 'close') return close();
      if (e.target?.getAttribute?.('data-act') === 'all') {
        sel.groupId = '';
        sel.packId = '';
        searchIn.value = '';
        this.filterText = '';
        populateDropdowns();
        renderGrid();
      }
    };

    populateDropdowns();
    renderGrid();
    overlay.classList.add('open');
    searchIn.focus();
  }
}

function drawPlaneswalkerBackdrop(ctx, face, width, height) {
  const tax = face?.taxonomy || {};
  if (tax.structural_type_override !== 'planeswalker') return;
  const isTall = tax.box_variant === 'tall' || face?.template === 'PlaneswalkerTall';
  const sx = width / 1500;
  const sy = height / 2100;
  const x0 = Math.round(112 * sx);
  const x1 = Math.round(1388 * sx);
  const y0 = Math.round((isTall ? 1148 : 1285) * sy);
  const y1 = Math.round(1906 * sy);

  ctx.save();
  ctx.fillStyle = 'rgba(235, 238, 244, 0.84)';
  ctx.beginPath();
  ctx.roundRect(x0, y0, x1 - x0, y1 - y0, Math.round(22 * sx));
  ctx.fill();

  const bands = isTall ? 4 : 3;
  const bandH = (y1 - y0) / bands;
  ctx.fillStyle = 'rgba(210, 216, 226, 0.45)';
  for (let i = 0; i < bands; i++) {
    if (i % 2 === 1) {
      const by0 = Math.round(y0 + i * bandH);
      const by1 = Math.round(y0 + (i + 1) * bandH);
      ctx.fillRect(x0 + 6, by0, x1 - x0 - 12, Math.min(y1 - 6, by1) - by0);
    }
  }
  ctx.restore();
}

function drawSingleComponentImage(ctx, source, img, role, width, height) {
  const iw = img.naturalWidth || img.width || width;
  const ih = img.naturalHeight || img.height || height;
  const aspect = ih ? iw / ih : 1;
  const cardAspect = width / height;
  if (Math.abs(aspect - cardAspect) <= 0.04) {
    ctx.drawImage(source, 0, 0, width, height);
  } else if (role === 'crown') {
    const scale = iw > width ? width / 2010 : 1;
    const tw = Math.round(iw * scale);
    const th = Math.round(ih * scale);
    const x = Math.round((width - tw) / 2);
    const y = Math.round(45 * (height / 2100));
    ctx.drawImage(source, x, y, tw, th);
  } else if (role === 'pt_box') {
    const scale = iw > 320 ? width / 2010 : 1;
    const tw = Math.round(iw * scale);
    const th = Math.round(ih * scale);
    const x = Math.round(1152 * (width / 1500));
    const y = Math.round(1862 * (height / 2100));
    ctx.drawImage(source, x, y, tw, th);
  } else if (role === 'stamp' || role === 'name_box') {
    if (iw < width * 0.4) {
      const tw = Math.round(iw * (width / 1500));
      const th = Math.round(ih * (height / 2100));
      const x = Math.round((width - tw) / 2);
      const y = Math.round(1885 * (height / 2100));
      ctx.drawImage(source, x, y, tw, th);
    } else {
      ctx.drawImage(source, 0, 0, width, height);
    }
  } else {
    ctx.drawImage(source, 0, 0, width, height);
  }
}

function tintImageElement(img, colorHex) {
  const w = img.naturalWidth || img.width || 1500;
  const h = img.naturalHeight || img.height || 2100;
  const off = document.createElement('canvas');
  off.width = w;
  off.height = h;
  const octx = off.getContext('2d');
  octx.drawImage(img, 0, 0, w, h);
  octx.globalCompositeOperation = 'source-atop';
  octx.fillStyle = colorHex;
  octx.fillRect(0, 0, w, h);
  octx.globalCompositeOperation = 'source-over';
  return off;
}

function drawShapeScaled(ctx, s, scale, opOverride = undefined) {
  if (!s) return;
  const op = opOverride !== undefined
    ? Math.max(0, Math.min(1, Number(opOverride)))
    : (s.opacity !== undefined ? Math.max(0, Math.min(1, Number(s.opacity))) : 0.55);
  if (op <= 0.001) return;
  const x = (s.x || 0) * scale;
  const y = (s.y || 0) * scale;
  const w = (s.w || 0) * scale;
  const h = (s.h || 0) * scale;
  ctx.save();
  ctx.globalAlpha = op;
  ctx.fillStyle = s.color || '#000000';
  if (s.type === 'circle') {
    ctx.beginPath();
    ctx.ellipse(x + w / 2, y + h / 2, Math.max(1, w / 2), Math.max(1, h / 2), 0, 0, Math.PI * 2);
    ctx.fill();
  } else if (s.type === 'rounded') {
    const r = Math.min(Math.max(0, Number(s.radius ?? 14) * scale), w / 2, h / 2);
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, r);
    ctx.fill();
  } else {
    ctx.fillRect(x, y, w, h);
  }
  ctx.restore();
}

function defaultTextColorForFace(face) {
  const tax = face?.taxonomy || {};
  const effects = Array.isArray(tax.frame_effects) ? tax.frame_effects : [];
  if (effects.includes('inverted') || tax.border_color === 'borderless' || face?.template === 'M15Borderless') {
    return '#f2f2f2';
  }
  return '#111111';
}

function isLightHex(hex) {
  const clean = String(hex || '').replace('#', '');
  if (clean.length < 6) return false;
  const r = parseInt(clean.slice(0, 2), 16);
  const g = parseInt(clean.slice(2, 4), 16);
  const b = parseInt(clean.slice(4, 6), 16);
  return (r * 299 + g * 587 + b * 114) / 1000 > 145;
}

function applyShadowIfLight(ctx, hex) {
  if (isLightHex(hex)) {
    ctx.shadowColor = 'rgba(0, 0, 0, 0.85)';
    ctx.shadowBlur = 4;
    ctx.shadowOffsetX = 2;
    ctx.shadowOffsetY = 2;
  } else {
    ctx.shadowColor = 'transparent';
    ctx.shadowBlur = 0;
    ctx.shadowOffsetX = 0;
    ctx.shadowOffsetY = 0;
  }
}

async function preloadManaSymbolsFromTexts(...texts) {
  const codes = new Set();
  for (const t of texts) {
    if (!t) continue;
    const matches = String(t).match(/\{([^{}]+)\}/g) || [];
    matches.forEach((m) => codes.add(m));
  }
  const map = new Map();
  await Promise.all(
    [...codes].map(async (raw) => {
      const url = resolveManaSymbolUrl(raw);
      if (url) {
        const img = await loadImageElement(url);
        if (img) map.set(normalizeManaCode(raw), img);
      }
    })
  );
  return map;
}

function drawSymbolWithShadow(ctx, img, x, y, size) {
  ctx.save();
  ctx.beginPath();
  ctx.arc(x + size / 2 - Math.max(1, size / 28), y + size / 2 + Math.max(2, size / 18), size * 0.48, 0, Math.PI * 2);
  ctx.fillStyle = 'rgba(0, 0, 0, 0.58)';
  ctx.fill();
  ctx.drawImage(img, x, y, size, size);
  ctx.restore();
}

function drawManaCostRow(ctx, manaStr, rightX, topY, size, symbolImgMap) {
  if (!manaStr) return 0;
  const tokens = String(manaStr).match(/\{([^{}]+)\}/g) || [];
  if (!tokens.length) return 0;
  const gap = Math.max(3, Math.round(size / 14));
  const step = size + gap;
  const totalW = tokens.length * step;
  let curX = rightX - totalW;

  for (const raw of tokens) {
    const norm = normalizeManaCode(raw);
    const img = symbolImgMap.get(norm);
    if (img) {
      drawSymbolWithShadow(ctx, img, curX, topY, size);
    } else {
      ctx.save();
      ctx.beginPath();
      ctx.arc(curX + size / 2, topY + size / 2, size * 0.48, 0, Math.PI * 2);
      ctx.fillStyle = '#cbc2bf';
      ctx.fill();
      ctx.fillStyle = '#111111';
      ctx.font = `bold ${Math.round(size * 0.6)}px "BelerenLocal", sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(raw.replace(/[{}]/g, ''), curX + size / 2, topY + size / 2);
      ctx.restore();
    }
    curX += step;
  }
  return totalW;
}

function drawSingleLineShrunk(ctx, text, fontFamily, targetSize, geometry, defaultW, colorHex) {
  if (!text) return;
  const x = Number(geometry?.x || 0);
  const y = Number(geometry?.y || 0);
  const maxW = Number(geometry?.max_w || geometry?.width || geometry?.w || defaultW);
  const align = geometry?.align || 'left';
  let size = Number(targetSize || 64);

  ctx.save();
  ctx.font = `bold ${size}px ${fontFamily}`;
  while (size > 20 && ctx.measureText(String(text)).width > maxW) {
    size -= 2;
    ctx.font = `bold ${size}px ${fontFamily}`;
  }
  const lineW = ctx.measureText(String(text)).width;
  let drawX = x;
  if (align === 'center') drawX = x + (maxW - lineW) / 2;
  else if (align === 'right') drawX = x + maxW - lineW;

  ctx.fillStyle = colorHex;
  applyShadowIfLight(ctx, colorHex);
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';
  ctx.fillText(String(text), drawX, y);
  ctx.restore();
}

function parseLoyaltyLine(para) {
  const m = String(para || '').trim().match(/^\[?([+\-\u2212\u2013\u2014](?:\d+|X)|0)\]?\s*:\s*(.*)$/i);
  if (!m) return null;
  const raw = m[1].toUpperCase();
  let dir = 'zero';
  let label = raw;
  if (raw.startsWith('+')) dir = 'up';
  else if (/^[-\u2212\u2013\u2014]/.test(raw)) {
    dir = 'down';
    label = `\u2212${raw.slice(1)}`;
  }
  return { label, dir, rest: m[2] || '' };
}

const _PW_ICON_URLS = {
  up: '/assets/resources/frames/planeswalker/planeswalkerPlus.png',
  down: '/assets/resources/frames/planeswalker/planeswalkerMinus.png',
  zero: '/assets/resources/frames/planeswalker/planeswalkerNeutral.png',
};
const _pwIconCache = {};
async function preloadPlaneswalkerLoyaltyIcons() {
  await Promise.all(Object.entries(_PW_ICON_URLS).map(async ([dir, url]) => {
    if (_pwIconCache[dir]) return;
    const im = await loadImageElement(url);
    if (im) _pwIconCache[dir] = im;
  }));
}

function drawLoyaltyIcon(ctx, cx, cy, w, h, dir, label) {
  const ccImg = dir !== 'start' ? _pwIconCache[dir] : null;
  if (ccImg) {
    ctx.save();
    // Official Card Conjurer dimensions: plus 210x152, minus 212x148, neutral 212x128 at x=42..44, text center x=154
    const drawW = dir === 'up' ? 210 : 212;
    const drawH = dir === 'up' ? 152 : (dir === 'down' ? 148 : 128);
    const drawX = dir === 'up' ? 44 : 42;
    const drawY = Math.round(cy - drawH / 2);
    ctx.drawImage(ccImg, drawX, drawY, drawW, drawH);
    ctx.font = `bold 56px "BelerenLocal", Georgia, serif`;
    ctx.fillStyle = '#ffffff';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    const yOff = dir === 'up' ? 10 : (dir === 'down' ? -10 : 0);
    ctx.fillText(label, 154, cy + yOff, 145);
    ctx.restore();
    return;
  }
  ctx.save();
  const hw = w / 2;
  const hh = h / 2;
  ctx.beginPath();
  if (dir === 'up') {
    ctx.moveTo(cx, cy - hh);
    ctx.lineTo(cx + hw, cy - hh * 0.22);
    ctx.lineTo(cx + hw * 0.88, cy + hh);
    ctx.lineTo(cx - hw * 0.88, cy + hh);
    ctx.lineTo(cx - hw, cy - hh * 0.22);
    ctx.closePath();
  } else if (dir === 'down') {
    ctx.moveTo(cx - hw * 0.88, cy - hh);
    ctx.lineTo(cx + hw * 0.88, cy - hh);
    ctx.lineTo(cx + hw, cy + hh * 0.22);
    ctx.lineTo(cx, cy + hh);
    ctx.lineTo(cx - hw, cy + hh * 0.22);
    ctx.closePath();
  } else if (dir === 'start') {
    ctx.moveTo(cx - hw * 0.92, cy - hh * 0.72);
    ctx.quadraticCurveTo(cx, cy - hh * 1.08, cx + hw * 0.92, cy - hh * 0.72);
    ctx.lineTo(cx + hw, cy + hh * 0.12);
    ctx.quadraticCurveTo(cx + hw * 0.6, cy + hh * 0.88, cx, cy + hh);
    ctx.quadraticCurveTo(cx - hw * 0.6, cy + hh * 0.88, cx - hw, cy + hh * 0.12);
    ctx.closePath();
  } else {
    ctx.moveTo(cx - hw * 0.82, cy - hh * 0.86);
    ctx.lineTo(cx + hw * 0.82, cy - hh * 0.86);
    ctx.lineTo(cx + hw, cy);
    ctx.lineTo(cx + hw * 0.82, cy + hh * 0.86);
    ctx.lineTo(cx - hw * 0.82, cy + hh * 0.86);
    ctx.lineTo(cx - hw, cy);
    ctx.closePath();
  }
  ctx.fillStyle = '#111317';
  ctx.fill();
  ctx.lineWidth = Math.max(2.5, h * 0.065);
  ctx.strokeStyle = '#d4dae3';
  ctx.stroke();

  const fPx = Math.round(h * (label.length >= 3 ? 0.44 : 0.52));
  ctx.font = `bold ${fPx}px "BelerenLocal", Georgia, serif`;
  ctx.fillStyle = '#ffffff';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  const yNudge = dir === 'up' ? hh * 0.14 : (dir === 'down' ? -hh * 0.12 : 0);
  ctx.fillText(label, cx, cy + yNudge, w * 0.86);
  ctx.restore();
}

function layoutRichRulesBlocks(ctx, oracleText, flavorText, maxW, fontSize, symbolImgMap) {
  const symSize = Math.max(14, Math.round(fontSize * 0.88));
  const lineH = Math.round(fontSize * 1.22);
  const paraGap = Math.round(fontSize * 0.28);
  const italicSize = Math.max(14, Math.round(fontSize * 0.94));
  const fLineH = Math.round(italicSize * 1.18);

  ctx.font = `${fontSize}px "MPlantinLocal", Georgia, serif`;
  const spaceW = ctx.measureText(' ').width;

  const blocks = [];
  let totalH = 0;

  const tokenizeWord = (word) => {
    const parts = word.split(/(\{[^{}]+\})/g).filter(Boolean);
    const tokens = [];
    let wTotal = 0;
    for (const part of parts) {
      if (part.startsWith('{') && part.endsWith('}')) {
        const norm = normalizeManaCode(part);
        const img = symbolImgMap.get(norm);
        const w = symSize + Math.max(2, Math.round(symSize / 16));
        tokens.push({ kind: 'sym', img, raw: part, width: w, size: symSize });
        wTotal += w;
      } else {
        ctx.font = `${fontSize}px "MPlantinLocal", Georgia, serif`;
        const w = ctx.measureText(part).width;
        tokens.push({ kind: 'text', text: part, width: w });
        wTotal += w;
      }
    }
    return { tokens, width: wTotal };
  };

  if (oracleText && String(oracleText).trim()) {
    const paragraphs = String(oracleText).split('\n').map((p) => p.trim()).filter(Boolean);
    // Card Conjurer ability text starts at x=270 (0.18 * 1500), icons sit at x=42..254
    const badgeIndent = Math.max(120, Math.round(fontSize * 2.25));
    paragraphs.forEach((para, pIdx) => {
      const loy = parseLoyaltyLine(para);
      const effMaxW = loy ? Math.max(160, maxW - badgeIndent) : maxW;
      const xOffset = loy ? badgeIndent : 0;
      const body = loy ? loy.rest : para;
      const words = body.split(/\s+/).filter(Boolean);
      const paraLines = [];
      let curLine = [];
      let curW = 0;
      words.forEach((word) => {
        const { tokens, width } = tokenizeWord(word);
        if (curLine.length > 0 && curW + spaceW + width > effMaxW) {
          paraLines.push(curLine);
          curLine = [...tokens];
          curW = width;
        } else {
          if (curLine.length > 0) {
            curLine.push({ kind: 'text', text: ' ', width: spaceW });
            curW += spaceW;
          }
          curLine.push(...tokens);
          curW += width;
        }
      });
      if (curLine.length > 0) paraLines.push(curLine);
      if (loy) {
        const minH = Math.round(fontSize * 1.55);
        const h = Math.max(paraLines.length * lineH, minH);
        blocks.push({ kind: 'loyalty_para', loy, lines: paraLines, lineH, height: h, xOffset, badgeIndent, fontSize });
        totalH += h;
      } else {
        paraLines.forEach((ln) => {
          blocks.push({ kind: 'oracle_line', tokens: ln, height: lineH });
          totalH += lineH;
        });
      }
      if (pIdx < paragraphs.length - 1) {
        blocks.push({ kind: 'gap', height: paraGap });
        totalH += paraGap;
      }
    });
  }

  const normOracle = String(oracleText || '').replace(/\s+/g, ' ').trim();
  const normFlavor = String(flavorText || '').replace(/\s+/g, ' ').trim();
  if (normFlavor && (!normOracle || !normOracle.includes(normFlavor))) {
    if (blocks.length > 0) {
      const sepH = Math.round(fontSize * 0.45);
      blocks.push({ kind: 'divider', height: sepH });
      totalH += sepH;
    }
    ctx.font = `italic ${italicSize}px "MPlantinLocal", Georgia, serif`;
    String(flavorText).split('\n').forEach((para) => {
      const words = para.trim().split(/\s+/).filter(Boolean);
      if (!words.length) return;
      let line = words[0];
      for (let i = 1; i < words.length; i++) {
        const probe = `${line} ${words[i]}`;
        if (ctx.measureText(probe).width <= maxW) {
          line = probe;
        } else {
          blocks.push({ kind: 'flavor_line', text: line, height: fLineH, size: italicSize });
          totalH += fLineH;
          line = words[i];
        }
      }
      blocks.push({ kind: 'flavor_line', text: line, height: fLineH, size: italicSize });
      totalH += fLineH;
    });
  }

  return { blocks, totalH, fontSize, italicSize };
}

function drawRichRulesBox(ctx, oracleText, flavorText, geometry, colorHex, symbolImgMap) {
  const x = Number(geometry?.x || 129);
  const y = Number(geometry?.y || 1328);
  const maxW = Number(geometry?.max_w || geometry?.width || geometry?.w || 1242);
  const maxH = Number(geometry?.height || geometry?.h || 604);
  let chosenSize = Math.min(Number(geometry?.size || geometry?.font_size || 62), 64);
  const minSize = 24;

  let layout = layoutRichRulesBlocks(ctx, oracleText, flavorText, maxW, chosenSize, symbolImgMap);
  while (chosenSize > minSize && layout.totalH > maxH) {
    chosenSize -= 2;
    layout = layoutRichRulesBlocks(ctx, oracleText, flavorText, maxW, chosenSize, symbolImgMap);
  }

  let curY = y + Math.max(0, Math.floor((maxH - layout.totalH) / 2));
  const bottomLimit = y + maxH;

  ctx.save();
  ctx.beginPath();
  ctx.rect(0, y - 16, 1500, maxH + 32);
  ctx.clip();

  let prevWasLoyalty = false;
  for (const blk of layout.blocks) {
    if (curY + Math.floor(blk.height * 0.75) > bottomLimit) break;
    if (blk.kind === 'gap') {
      curY += blk.height;
    } else if (blk.kind === 'divider') {
      prevWasLoyalty = false;
      const midY = curY + Math.floor(blk.height / 2);
      ctx.save();
      ctx.strokeStyle = isLightHex(colorHex) ? 'rgba(255,255,255,0.32)' : 'rgba(17,17,17,0.28)';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x + 40, midY);
      ctx.lineTo(x + maxW - 40, midY);
      ctx.stroke();
      ctx.restore();
      curY += blk.height;
    } else if (blk.kind === 'flavor_line') {
      prevWasLoyalty = false;
      ctx.save();
      ctx.font = `italic ${blk.size}px "MPlantinLocal", Georgia, serif`;
      ctx.fillStyle = colorHex;
      applyShadowIfLight(ctx, colorHex);
      ctx.textAlign = 'left';
      ctx.textBaseline = 'top';
      ctx.fillText(blk.text, x, curY);
      ctx.restore();
      curY += blk.height;
    } else if (blk.kind === 'loyalty_para') {
      if (prevWasLoyalty) {
        ctx.save();
        ctx.strokeStyle = isLightHex(colorHex) ? 'rgba(255,255,255,0.22)' : 'rgba(17,17,17,0.18)';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x - 12, curY - Math.round(chosenSize * 0.14));
        ctx.lineTo(x + maxW - 8, curY - Math.round(chosenSize * 0.14));
        ctx.stroke();
        ctx.restore();
      }
      prevWasLoyalty = true;
      const badgeW = Math.round(chosenSize * 1.95);
      const badgeH = Math.round(chosenSize * 1.42);
      // Straddle the left border of the Planeswalker textbox (official MTG alignment)
      const badgeCx = x + Math.round(chosenSize * 0.12);
      const badgeCy = curY + Math.round(blk.height / 2);
      drawLoyaltyIcon(ctx, badgeCx, badgeCy, badgeW, badgeH, blk.loy.dir, blk.loy.label);
      const textBlockH = blk.lines.length * blk.lineH;
      let lineY = curY + Math.max(0, Math.floor((blk.height - textBlockH) / 2));
      for (const tokens of blk.lines) {
        let curX = x + blk.xOffset;
        for (const tok of tokens) {
          if (tok.kind === 'text') {
            ctx.save();
            ctx.font = `${chosenSize}px "MPlantinLocal", Georgia, serif`;
            ctx.fillStyle = colorHex;
            applyShadowIfLight(ctx, colorHex);
            ctx.textAlign = 'left';
            ctx.textBaseline = 'top';
            ctx.fillText(tok.text, curX, lineY);
            ctx.restore();
            curX += tok.width;
          } else if (tok.kind === 'sym') {
            const symY = Math.round(lineY + (chosenSize - tok.size) * 0.55);
            if (tok.img) {
              drawSymbolWithShadow(ctx, tok.img, Math.round(curX), Math.max(0, symY), tok.size);
            } else {
              ctx.save();
              ctx.beginPath();
              ctx.arc(curX + tok.size / 2, symY + tok.size / 2, tok.size * 0.46, 0, Math.PI * 2);
              ctx.fillStyle = '#cbc2bf';
              ctx.fill();
              ctx.fillStyle = '#111111';
              ctx.font = `bold ${Math.round(tok.size * 0.58)}px "BelerenLocal", sans-serif`;
              ctx.textAlign = 'center';
              ctx.textBaseline = 'middle';
              ctx.fillText(tok.raw.replace(/[{}]/g, ''), curX + tok.size / 2, symY + tok.size / 2);
              ctx.restore();
            }
            curX += tok.width;
          }
        }
        lineY += blk.lineH;
      }
      curY += blk.height;
    } else if (blk.kind === 'oracle_line') {
      let curX = x;
      for (const tok of blk.tokens) {
        if (tok.kind === 'text') {
          ctx.save();
          ctx.font = `${chosenSize}px "MPlantinLocal", Georgia, serif`;
          ctx.fillStyle = colorHex;
          applyShadowIfLight(ctx, colorHex);
          ctx.textAlign = 'left';
          ctx.textBaseline = 'top';
          ctx.fillText(tok.text, curX, curY);
          ctx.restore();
          curX += tok.width;
        } else if (tok.kind === 'sym') {
          const symY = Math.round(curY + (chosenSize - tok.size) * 0.55);
          if (tok.img) {
            drawSymbolWithShadow(ctx, tok.img, Math.round(curX), Math.max(0, symY), tok.size);
          } else {
            ctx.save();
            ctx.beginPath();
            ctx.arc(curX + tok.size / 2, symY + tok.size / 2, tok.size * 0.46, 0, Math.PI * 2);
            ctx.fillStyle = '#cbc2bf';
            ctx.fill();
            ctx.fillStyle = '#111111';
            ctx.font = `bold ${Math.round(tok.size * 0.58)}px "BelerenLocal", sans-serif`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(tok.raw.replace(/[{}]/g, ''), curX + tok.size / 2, symY + tok.size / 2);
            ctx.restore();
          }
          curX += tok.width;
        }
      }
      curY += blk.height;
    }
  }

  ctx.restore();
}

function splitFromFace(face) {
  const rawTypeY = Number(face?.text_layers?.type_line?.bounds?.y);
  return Number.isFinite(rawTypeY) && rawTypeY > 400 && rawTypeY < 1950;
}

function computeFrameSplitY(face, card, height) {
  const sy = height / 2100;
  const rawTypeY = Number(face?.text_layers?.type_line?.bounds?.y);
  if (splitFromFace(face)) {
    return Math.round(Math.max(0, rawTypeY - 22) * sy);
  }
  const layTypeY = Number(card?.layout?.type_line?.y);
  if (Number.isFinite(layTypeY) && layTypeY > 200 && layTypeY < 975) {
    return Math.round(Math.max(0, layTypeY * 2 - 70) * sy);
  }
  return Math.round(1167 * sy);
}

const DEFAULT_ART_BOUNDS = { x: 115, y: 237, w: 1271, h: 930 };

// The planeswalker ability-box backdrop as recorded canvas calls (empty for other cards), so the
// export reproduces the preview's geometry (which depends on the client-side template) exactly.
function recordPlaneswalkerBackdrop(face, width, height) {
  const scratch = document.createElement('canvas');
  scratch.width = 1;
  scratch.height = 1;
  const recorder = createRecordingContext(scratch.getContext('2d'));
  drawPlaneswalkerBackdrop(recorder.ctx, face, width, height);
  return recorder.ops.some((op) => op.op === 'fill' || op.op === 'fillRect') ? recorder.ops : [];
}

// Art zone (canvas px) and transform ({x, y} offsets from the zone centre, scale, rotation).
// Returns null when neither the card layout nor the face says where the art goes.
function computeArtPlacement(face, card, width, height) {
  const art = face?.art_layer;
  const layArt = card?.layout?.art;
  if (!layArt && !art) return null;
  const sx = width / 750;
  const sy = height / 1050;
  const bounds = layArt
    ? {
        x: Math.round(Number(layArt.x || 0) * sx),
        y: Math.round(Number(layArt.y || 0) * sy),
        w: Math.round(Number(layArt.w || 635) * sx),
        h: Math.round(Number(layArt.h || 465) * sy),
      }
    : (art?.bounds || { ...DEFAULT_ART_BOUNDS });
  const rawTx = Number(art?.transform?.x || 0);
  const rawTy = Number(art?.transform?.y || 0);
  const baseOx = (rawTx === Number(art?.bounds?.x || 0)) ? 0 : rawTx;
  const baseOy = (rawTy === Number(art?.bounds?.y || 0)) ? 0 : rawTy;
  const transform = {
    ...(art?.transform || {}),
    x: layArt ? Number(layArt.offset_x || 0) * sx : baseOx,
    y: layArt ? Number(layArt.offset_y || 0) * sy : baseOy,
    scale: Number(layArt?.scale ?? art?.transform?.scale ?? 1.0) || 1.0,
  };
  return { bounds, transform };
}

// Describes the frame layers exactly as renderProjectFace draws them, so the server-side
// export (recipe_renderer.draw_frame_spec) can reproduce the preview: layer order, the
// Top/Bottom split for pop-out cards, visibility, opacity and tint.
export function buildFrameExportSpec(card, face = null, size = { width: 1500, height: 2100 }) {
  if (!card || !card.frame_components) return null;
  const width = Number(size.width) || 1500;
  const height = Number(size.height) || 2100;
  const fc = card.frame_components;
  const hidden = normalizeHiddenLayers(card.hidden_layers);
  const opacities = card.layer_opacities || {};
  const colors = card.layer_colors || {};
  const validHex = (v) => (/^#[0-9a-fA-F]{6}$/.test(String(v || '').trim()) ? String(v).trim() : '');
  const order = Array.isArray(card.layer_order) && card.layer_order.length
    ? [...card.layer_order]
    : [...DEFAULT_LAYER_ORDER];
  if (!order.includes('textbox')) {
    const insertAt = Math.max(order.indexOf('crown'), order.indexOf('background'));
    order.splice(insertAt >= 0 ? insertAt + 1 : order.length, 0, 'textbox');
  }
  const split = isSplitFrame(card);
  const artIdx = order.indexOf('art');
  const bgIdx = order.indexOf('background');
  const crownIdx = order.indexOf('crown');
  const artUnclipped = artIdx >= 0 && ((bgIdx >= 0 && artIdx > bgIdx) || (crownIdx >= 0 && artIdx > crownIdx));
  const shapeScale = width / 750;
  const shapes = new Map((card.shapes || []).map((sh) => [`shape:${sh.id}`, sh]));
  const layers = [];
  for (const key of order) {
    if (key === 'art') {
      const opacity = opacities.art ?? 1.0;
      if (hidden.art || opacity <= 0.01) continue;
      layers.push({
        key: 'art',
        url: card.custom_art_data || card.art_crop_url || face?.art_layer?.url || null,
        placement: computeArtPlacement(face, card, width, height),
        unclipped: artUnclipped,
        opacity,
        brightness: Number(card.brightness ?? 1.0),
      });
      continue;
    }
    if (key.startsWith('shape:')) {
      const shape = shapes.get(key);
      if (!shape || hidden[key]) continue;
      layers.push({
        key: 'shape',
        type: shape.type || 'rect',
        x: (shape.x || 0) * shapeScale,
        y: (shape.y || 0) * shapeScale,
        w: (shape.w || 0) * shapeScale,
        h: (shape.h || 0) * shapeScale,
        radius: Number(shape.radius ?? 14) * shapeScale,
        color: validHex(shape.color) || '#000000',
        opacity: Number(opacities[key] ?? shape.opacity ?? 0.55),
      });
      continue;
    }
    if (key === 'textbox' && (!split || hidden.textbox)) continue;
    if (key === 'textbox' || (key === 'background' && !split)) layers.push({ key: 'pw_backdrop', ops: recordPlaneswalkerBackdrop(face, width, height) });
    if (key !== 'textbox' && hidden[key]) continue;
    const isTextbox = key === 'textbox';
    const url = isTextbox ? (fc.textbox || fc.background) : fc[key];
    const opacity = isTextbox ? (opacities.textbox ?? opacities.background ?? 1.0) : (opacities[key] ?? 1.0);
    if (!url || opacity <= 0.01) continue;
    let clip = null;
    if (isTextbox) clip = 'bottom';
    else if (key === 'background' && split) clip = 'top';
    layers.push({
      key,
      url,
      role: FRAME_SLOT_ROLES[key] || key,
      opacity,
      tint: validHex(isTextbox ? (colors.textbox || colors.background) : colors[key]),
      clip,
    });
  }
  return {
    canvas_width: width,
    canvas_height: height,
    bg_color: validHex(card.bg_color) || '#111111',
    hide_text: Boolean(card.hide_card_text),
    split,
    split_y: computeFrameSplitY(face, card, height),
    split_y_from_face: splitFromFace(face),
    layers,
  };
}

// Full export description of a card face: frame/art/shape layers (buildFrameExportSpec)
// plus the recorded set-symbol and text drawing calls, so the PNG matches the preview.
export async function buildCardExportSpec(card, face, opts = {}) {
  const size = opts.canvas || { width: 1500, height: 2100 };
  const spec = buildFrameExportSpec(card, face, size);
  if (!spec || !face) return spec;
  if (document.fonts?.ready) await document.fonts.ready;
  const scratch = document.createElement('canvas');
  const result = await renderProjectFace(face, scratch, { ...opts, card, canvas: size, recordText: true });
  spec.text_ops = result.text_ops || null;
  return spec;
}

export async function renderProjectFace(face, canvasEl, opts = {}) {
  await ensureSymbolsCatalog();
  const size = opts.canvas || { width: 1500, height: 2100 };
  const width = Number(size.width) || 1500;
  const height = Number(size.height) || 2100;
  let ctx = canvasEl.getContext('2d');
  const card = opts.card || null;

  canvasEl.width = width;
  canvasEl.height = height;
  canvasEl.style.maxWidth = '100%';
  canvasEl.style.height = 'auto';
  canvasEl.style.transform = '';

  const bgColor = (card?.bg_color && /^#[0-9a-fA-F]{6}$/.test(card.bg_color.trim()))
    ? card.bg_color.trim()
    : '#111111';
  ctx.fillStyle = bgColor;
  ctx.fillRect(0, 0, width, height);

  const result = { layers: 0, skipped: [] };
  const hidden = normalizeHiddenLayers(card?.hidden_layers);
  const opacities = card?.layer_opacities || {};
  const layerColors = card?.layer_colors || {};

  const drawArt = async (unclipped = false) => {
    if (hidden.art) return;
    const op = opacities.art ?? 1.0;
    if (op <= 0.01) return;
    const art = face?.art_layer;
    const rawArtUrl = card?.custom_art_data || card?.art_crop_url || art?.url;
    if (!rawArtUrl) return;
    const artUrl = /^https?:\/\//i.test(rawArtUrl)
      ? `/api/art/proxy?url=${encodeURIComponent(rawArtUrl)}`
      : rawArtUrl;
    const artImg = await loadImageElement(artUrl);
    if (!artImg) {
      result.skipped.push(artUrl);
      return;
    }
    const { bounds: baseBounds, transform } = computeArtPlacement(face, card, width, height)
      || { bounds: { ...DEFAULT_ART_BOUNDS }, transform: { x: 0, y: 0, scale: 1.0 } };
    const bright = Number(card?.brightness ?? 1.0);
    ctx.save();
    ctx.globalAlpha = op;
    if (Math.abs(bright - 1.0) > 0.01) ctx.filter = `brightness(${bright})`;
    drawArtInto(ctx, artImg, baseBounds, transform, { unclipped });
    ctx.filter = 'none';
    ctx.restore();
    result.layers += 1;
  };

  if (card && card.frame_components) {
    const slotToRole = FRAME_SLOT_ROLES;
    const rawOrder = Array.isArray(card.layer_order) && card.layer_order.length
      ? [...card.layer_order]
      : [...DEFAULT_LAYER_ORDER];
    // Backwards-compatibility: if saved layer_order didn't have 'textbox' yet, place it right above crown/background
    if (!rawOrder.includes('textbox')) {
      const crownIdx = rawOrder.indexOf('crown');
      const bgIdx = rawOrder.indexOf('background');
      const insertAt = Math.max(crownIdx, bgIdx);
      rawOrder.splice(insertAt >= 0 ? insertAt + 1 : rawOrder.length, 0, 'textbox');
    }
    const order = rawOrder;
    const scaleFactor = width / 750;
    const splitFrame = isSplitFrame(card);
    const splitY = computeFrameSplitY(face, card, height);
    const artIdx = order.indexOf('art');
    const bgIdx = order.indexOf('background');
    const crownIdx = order.indexOf('crown');
    const artUnclipped = (artIdx >= 0 && ((bgIdx >= 0 && artIdx > bgIdx) || (crownIdx >= 0 && artIdx > crownIdx)));

    for (const key of order) {
      if (key === 'art') {
        await drawArt(artUnclipped);
        continue;
      }
      if (key.startsWith('shape:')) {
        if (hidden[key]) continue;
        const sid = key.slice(6);
        const shape = (card.shapes || []).find((s) => s.id === sid);
        if (shape) drawShapeScaled(ctx, shape, scaleFactor, opacities[key] ?? shape.opacity ?? 0.55);
        continue;
      }
      if (key === 'textbox') {
        // Non pop-out: the single Frame layer (background) already covers the whole card.
        if (!splitFrame) continue;
        if (hidden.textbox) continue;
        drawPlaneswalkerBackdrop(ctx, face, width, height);
        const op = opacities.textbox ?? opacities.background ?? 1.0;
        const url = card.frame_components.textbox || card.frame_components.background;
        if (op <= 0.01 || !url) continue;
        const img = await loadImageElement(url);
        if (!img) {
          result.skipped.push(url);
          continue;
        }
        const rawTint = layerColors.textbox || layerColors.background || '';
        const tintHex = /^#[0-9a-fA-F]{6}$/.test(rawTint.trim()) ? rawTint.trim() : '';
        const source = tintHex ? tintImageElement(img, tintHex) : img;
        ctx.save();
        ctx.beginPath();
        ctx.rect(0, splitY, width, height - splitY);
        ctx.clip();
        ctx.globalAlpha = op;
        drawSingleComponentImage(ctx, source, img, 'base_frame', width, height);
        ctx.restore();
        result.layers += 1;
        continue;
      }
      if (key === 'background' && !splitFrame) drawPlaneswalkerBackdrop(ctx, face, width, height);
      if (hidden[key]) continue;
      const op = opacities[key] ?? 1.0;
      const url = card.frame_components[key];
      if (op <= 0.01 || !url) continue;
      const img = await loadImageElement(url);
      if (!img) {
        result.skipped.push(url);
        continue;
      }
      const tintHex = layerColors[key] && /^#[0-9a-fA-F]{6}$/.test(layerColors[key].trim())
        ? layerColors[key].trim()
        : '';
      const source = tintHex ? tintImageElement(img, tintHex) : img;
      ctx.save();
      if (key === 'background' && splitFrame) {
        ctx.beginPath();
        ctx.rect(0, 0, width, splitY);
        ctx.clip();
      }
      ctx.globalAlpha = op;
      drawSingleComponentImage(ctx, source, img, slotToRole[key] || key, width, height);
      ctx.restore();
      result.layers += 1;
    }
  } else {
    await drawArt();
    drawPlaneswalkerBackdrop(ctx, face, width, height);
    const stack = [...(face?.frame_stack || [])].sort((a, b) => (Number(a.z_index) || 0) - (Number(b.z_index) || 0));
    for (const layer of stack) {
      if (!layer?.url) continue;
      if (layer.asset_role === 'mask' || layer.asset_role === 'pinline') continue;
      if (layer.asset_role === 'stamp' || layer.asset_role === 'other') continue;
      const img = await loadImageElement(layer.url);
      if (!img) {
        result.skipped.push(layer.url);
        continue;
      }
      const maskSrc = layer.mask_url || layer.mask_id;
      let source = img;
      if (maskSrc) {
        const resolvedMaskUrl = maskSrc.startsWith('/') ? maskSrc : `/assets/resources/frames/${maskSrc}`;
        const maskImg = await loadImageElement(resolvedMaskUrl);
        if (!maskImg) {
          result.skipped.push(layer.url);
          continue;
        }
        const scratch = document.createElement('canvas');
        scratch.width = width;
        scratch.height = height;
        const scratchCtx = scratch.getContext('2d');
        scratchCtx.drawImage(img, 0, 0, width, height);
        applyMaskToCanvas(scratch, maskImg);
        source = scratch;
      }
      ctx.save();
      ctx.globalAlpha = layer.opacity ?? 1;
      if (layer.blend) ctx.globalCompositeOperation = layer.blend;
      drawSingleComponentImage(ctx, source, img, layer.asset_role, width, height);
      ctx.restore();
      result.layers += 1;
    }
  }

  // From here on (set symbol + text) the export replays these exact calls server-side.
  let recorder = null;
  if (opts.recordText) {
    recorder = createRecordingContext(ctx);
    ctx = recorder.ctx;
  }

  // Set Symbol (Rune)
  const sx = width / 750;
  const sy = height / 1050;
  const L = card?.layout || null;
  const colInfo = face?.text_layers?.collector_info || {};
  const setCode = (card?.set || colInfo.set || 'mtg').toLowerCase();
  const rarity = (card?.rarity || colInfo.rarity || 'common').toLowerCase();
  const origSet = (colInfo.set || '').toLowerCase();
  const customSetChosen = card?.set && origSet && card.set.toLowerCase() !== origSet;
  // Prefer the set's own rarity-coloured symbol from _shared/set_symbols; Scryfall's is a plain
  // black silhouette, which gets the rarity colours and outline applied (styledSetSymbol).
  const localRaritySymbol = exactSetSymbolUrl(setCode, rarity);
  const scryfallSymbol = face?.set_symbol?.url || opts?.set_symbol?.url || '';
  const symUrl = customSetChosen
    ? (resolveSetSymbolUrl(setCode, rarity) || scryfallSymbol)
    : (localRaritySymbol || scryfallSymbol || resolveSetSymbolUrl(setCode, rarity));
  const symIsSilhouette = Boolean(symUrl && symUrl === scryfallSymbol);
  const symBounds = L?.set_symbol
    ? {
        x: Math.round(Number(L.set_symbol.x || 692) * sx),
        y: Math.round(Number(L.set_symbol.y || 620) * sy),
        width: Math.round(Number(L.set_symbol.size || 40) * sx * 2.2),
        height: Math.round(Number(L.set_symbol.size || 40) * sy),
      }
    : (face?.set_symbol_bounds || { x: 1384, y: 1241, width: 120, height: 80 });
  if (symUrl && symBounds && Number(symBounds.width || 0) > 0 && Number(symBounds.x || 0) > 2) {
    const symImg = await loadImageElement(symUrl);
    if (symImg) {
      const bw = Number(symBounds.width) || 120;
      const bh = Number(symBounds.height) || 80;
      const scale = Math.min(bw / (symImg.naturalWidth || symImg.width || bw), bh / (symImg.naturalHeight || symImg.height || bh));
      const dw = Math.round((symImg.naturalWidth || symImg.width || bw) * scale);
      const dh = Math.round((symImg.naturalHeight || symImg.height || bh) * scale);
      const rx = Number(symBounds.x) || 1384;
      const ry = Number(symBounds.y) || 1241;
      const dx = rx > 1100 ? rx - dw : rx;
      const dy = ry - Math.round(dh / 2);
      if (symIsSilhouette) {
        const styled = styledSetSymbol(symImg, dw, dh, rarity);
        ctx.drawImage(styled.canvas, Math.max(0, dx) - styled.pad, Math.max(0, dy) - styled.pad, dw + 2 * styled.pad, dh + 2 * styled.pad);
      } else {
        ctx.drawImage(symImg, Math.max(0, dx), Math.max(0, dy), dw, dh);
      }
      result.layers += 1;
    }
  }

  // Text Layers & Mana Symbols
  if (!card?.hide_card_text) {
    const tl = face?.text_layers || {};
    const defColor = defaultTextColorForFace(face);

    const titleText = card ? card.name : tl.title?.text;
    const manaText = card ? card.mana_cost : tl.mana_cost?.text;
    const typeText = card ? card.type_line : tl.type_line?.text;
    const oracleText = card ? card.oracle_text : tl.oracle_text?.text;
    const flavorText = card ? card.flavor_text : tl.flavor_text?.text;

    const advTitleText = card?.adventure?.name ?? tl.adventure_title?.text ?? '';
    const advManaText = card?.adventure?.mana_cost ?? tl.adventure_mana_cost?.text ?? '';
    const advTypeText = card?.adventure?.type_line ?? tl.adventure_type_line?.text ?? '';
    const advOracleText = card?.adventure?.oracle_text ?? tl.adventure_oracle_text?.text ?? '';

    const symbolImgMap = await preloadManaSymbolsFromTexts(manaText, oracleText, advManaText, advOracleText);
    if (oracleText && /^[+\-\u2212\u2013\u20140\[]/m.test(oracleText)) {
      await preloadPlaneswalkerLoyaltyIcons();
    }

    const manaTokens = String(manaText || '').match(/\{([^{}]+)\}/g) || [];
    const manaBounds = tl.mana_cost?.bounds || { x: 0, y: 118, width: 1394, size: 74 };
    const manaSize = L?.mana_cost?.size
      ? Math.round(Number(L.mana_cost.size) * sx)
      : Math.min(Number(manaBounds.size || 68), 76);
    const manaRightX = L?.mana_cost?.x
      ? Math.round(Number(L.mana_cost.x) * sx)
      : (Number(manaBounds.width || manaBounds.w)
        ? Number(manaBounds.x || 0) + Number(manaBounds.width || manaBounds.w)
        : (Number(manaBounds.x || 0) > 500 ? Number(manaBounds.x) : width - 106));
    const manaY = L?.mana_cost?.y
      ? Math.round(Number(L.mana_cost.y) * sy - manaSize * 0.82)
      : Number(manaBounds.y || 118);

    if (manaTokens.length > 0) {
      drawManaCostRow(ctx, manaText, manaRightX, manaY, manaSize, symbolImgMap);
    }

    if (titleText) {
      const titleSize = L?.title?.font_size
        ? Math.round(Number(L.title.font_size) * sx)
        : Number(tl.title?.bounds?.size || 74);
      const titleBounds = L?.title
        ? {
            x: Math.round(Number(L.title.x || 62) * sx),
            y: Math.round(Number(L.title.y || 90) * sy - titleSize * 0.85),
            max_w: Math.round(Number(L.title.max_w || 490) * sx),
            size: titleSize,
          }
        : { ...(tl.title?.bounds || { x: 125, y: 110, w: 980, size: 74 }) };
      if (manaTokens.length > 0) {
        const availW = Math.max(300, manaRightX - manaTokens.length * (manaSize + 6) - Number(titleBounds.x || 125) - 20);
        titleBounds.max_w = Math.min(Number(titleBounds.max_w || titleBounds.width || titleBounds.w || 980), availW);
      }
      const titleColor = L?.title?.color || defColor;
      drawSingleLineShrunk(ctx, titleText, '"BelerenLocal", Georgia, serif', titleSize, titleBounds, 980, titleColor);
    }

    const officialTitle = (card?.official_name || '').trim();
    if (officialTitle) {
      const otSize = L?.official_title?.font_size ? Math.round(Number(L.official_title.font_size) * sx) : 44;
      const otBounds = L?.official_title
        ? {
            x: Math.round(Number(L.official_title.x || 62) * sx),
            y: Math.round(Number(L.official_title.y || 114) * sy - otSize * 0.85),
            max_w: Math.round(Number(L.official_title.max_w || 490) * sx),
          }
        : { x: Number(tl.title?.bounds?.x || 125), y: Number(tl.title?.bounds?.y || 110) + 92, max_w: 980 };
      const otColor = L?.official_title?.color || '#f2f2f2';
      drawSingleLineShrunk(ctx, `(${officialTitle})`, '"MPlantinLocal", Georgia, serif', otSize, otBounds, 980, otColor);
    }

    if (typeText) {
      const typeSize = L?.type_line?.font_size
        ? Math.round(Number(L.type_line.font_size) * sx)
        : Number(tl.type_line?.bounds?.size || 64);
      const typeBounds = L?.type_line
        ? {
            x: Math.round(Number(L.type_line.x || 64) * sx),
            y: Math.round(Number(L.type_line.y || 629) * sy - typeSize * 0.85),
            max_w: Math.round(Number(L.type_line.max_w || 550) * sx),
            size: typeSize,
          }
        : { ...(tl.type_line?.bounds || { x: 128, y: 1189, w: 1100, size: 64 }) };
      const symRightX = Number(symBounds?.x || 1384);
      const symW = Number(symBounds?.width || 120);
      const availTypeW = Math.max(300, symRightX - symW - Number(typeBounds.x || 128) - 16);
      typeBounds.max_w = Math.min(Number(typeBounds.max_w || typeBounds.width || typeBounds.w || 1100), availTypeW);
      const typeColor = L?.type_line?.color || defColor;
      drawSingleLineShrunk(ctx, typeText, '"BelerenLocal", Georgia, serif', typeSize, typeBounds, 1100, typeColor);
    }

    if ((oracleText || flavorText) && !L?.oracle_box?.hidden) {
      const rulesBounds = L?.oracle_box
        ? {
            x: Math.round(Number(L.oracle_box.x || 64) * sx),
            y: Math.round(Number(L.oracle_box.y || 662) * sy),
            w: Math.round(Number(L.oracle_box.w || 621) * sx),
            h: Math.round(Number(L.oracle_box.h || 302) * sy),
            size: Math.round(Number(L.oracle_box.font_size || 30) * sx),
          }
        : (tl.oracle_text?.bounds || tl.flavor_text?.bounds || { x: 129, y: 1324, w: 1242, h: 604, size: 62 });
      const oracleColor = L?.oracle_box?.color || defColor;
      drawRichRulesBox(ctx, oracleText || '', flavorText || '', rulesBounds, oracleColor, symbolImgMap);
    }

    // Adventure spell (card_face 1): left page below main type_line
    if (advTitleText || advManaText || advTypeText || advOracleText) {
      const advManaTokens = String(advManaText || '').match(/\{([^{}]+)\}/g) || [];
      const advManaSize = L?.adventure_mana_cost?.size
        ? Math.round(Number(L.adventure_mana_cost.size) * sx)
        : Number(tl.adventure_mana_cost?.bounds?.size || 52);
      const advManaRightX = L?.adventure_mana_cost?.x
        ? Math.round(Number(L.adventure_mana_cost.x) * sx)
        : 724;
      const advManaY = L?.adventure_mana_cost?.y
        ? Math.round(Number(L.adventure_mana_cost.y) * sy - advManaSize * 0.82)
        : Number(tl.adventure_mana_cost?.bounds?.y || 1340);

      if (advManaTokens.length > 0) {
        drawManaCostRow(ctx, advManaText, advManaRightX, advManaY, advManaSize, symbolImgMap);
      }

      if (advTitleText) {
        const advTitleSize = L?.adventure_title?.font_size
          ? Math.round(Number(L.adventure_title.font_size) * sx)
          : Number(tl.adventure_title?.bounds?.size || 54);
        const advTitleBounds = L?.adventure_title
          ? {
              x: Math.round(Number(L.adventure_title.x || 62) * sx),
              y: Math.round(Number(L.adventure_title.y || 696) * sy - advTitleSize * 0.85),
              max_w: Math.round(Number(L.adventure_title.max_w || 235) * sx),
              size: advTitleSize,
            }
          : { x: 120, y: 1330, max_w: 470, size: advTitleSize };
        if (advManaTokens.length > 0) {
          const availAdvW = Math.max(180, advManaRightX - advManaTokens.length * (advManaSize + 4) - advTitleBounds.x - 12);
          advTitleBounds.max_w = Math.min(advTitleBounds.max_w, availAdvW);
        }
        drawSingleLineShrunk(ctx, advTitleText, '"BelerenLocal", Georgia, serif', advTitleSize, advTitleBounds, 470, L?.adventure_title?.color || '#ffffff');
      }

      if (advTypeText) {
        const advTypeSize = L?.adventure_type_line?.font_size
          ? Math.round(Number(L.adventure_type_line.font_size) * sx)
          : Number(tl.adventure_type_line?.bounds?.size || 46);
        const advTypeBounds = L?.adventure_type_line
          ? {
              x: Math.round(Number(L.adventure_type_line.x || 62) * sx),
              y: Math.round(Number(L.adventure_type_line.y || 741) * sy - advTypeSize * 0.85),
              max_w: Math.round(Number(L.adventure_type_line.max_w || 290) * sx),
              size: advTypeSize,
            }
          : { x: 120, y: 1424, max_w: 584, size: advTypeSize };
        drawSingleLineShrunk(ctx, advTypeText, '"BelerenLocal", Georgia, serif', advTypeSize, advTypeBounds, 584, L?.adventure_type_line?.color || '#ffffff');
      }

      if (advOracleText) {
        const advRulesBounds = L?.adventure_oracle_box
          ? {
              x: Math.round(Number(L.adventure_oracle_box.x || 64) * sx),
              y: Math.round(Number(L.adventure_oracle_box.y || 767) * sy),
              w: Math.round(Number(L.adventure_oracle_box.w || 292) * sx),
              h: Math.round(Number(L.adventure_oracle_box.h || 192) * sy),
              size: Math.round(Number(L.adventure_oracle_box.font_size || 26) * sx),
            }
          : { x: 118, y: 1516, w: 602, h: 400, size: 52 };
        drawRichRulesBox(ctx, advOracleText, '', advRulesBounds, L?.adventure_oracle_box?.color || defColor, symbolImgMap);
      }
    }

    const power = card ? card.power : tl.pt?.power;
    const toughness = card ? card.toughness : tl.pt?.toughness;
    if (power !== null && power !== undefined && String(power).trim() !== '') {
      const ptSize = L?.pt_text?.font_size ? Math.round(Number(L.pt_text.font_size) * sx) : Number(tl.pt?.bounds?.size || 74);
      const ptBounds = L?.pt_text
        ? {
            x: Math.round(Number(L.pt_text.x || 648) * sx - 102),
            y: Math.round(Number(L.pt_text.y || 970) * sy - ptSize * 0.5),
            w: 205,
            h: 78,
            size: ptSize,
            align: 'center',
          }
        : (tl.pt?.bounds || { x: 1189, y: 1894, w: 205, h: 78, size: 74, align: 'center' });
      const ptColor = L?.pt_text?.color || defColor;
      drawSingleLineShrunk(ctx, `${power}/${toughness ?? ''}`, '"BelerenLocal", Georgia, serif', ptSize, ptBounds, 205, ptColor);
    }

    for (const k of ['loyalty', 'defense']) {
      const val = (k === 'loyalty' && card?.loyalty != null && String(card.loyalty).trim() !== '')
        ? String(card.loyalty).trim()
        : tl[k]?.text;
      if (val) {
        const b = tl[k]?.bounds || { x: 1189, y: 1894, w: 205, h: 78, size: 74, align: 'center' };
        const bx = Number(b.x || 1189) + Number(b.w || b.width || 205) / 2;
        const by = Number(b.y || 1894) + Number(b.h || b.height || 78) / 2;
        if (k === 'loyalty') {
          drawLoyaltyIcon(ctx, bx, by, 185, 138, 'start', val);
        } else {
          drawSingleLineShrunk(ctx, val, '"BelerenLocal", Georgia, serif', Number(b.size || 74), b, 205, '#f2f2f2');
        }
      }
    }

    // Official 2-line MTG collector footer (top: collector_number + rarity; bottom: SET • LANG + brush + Artist)
    const artistText = String(card?.artist ?? tl.collector_info?.artist ?? '').trim();
    const colNum = String(tl.collector_info?.collector_number || '').trim();
    const rarityChar = String(rarity || 'common').trim().charAt(0).toUpperCase() || 'C';
    const setUpper = String(setCode || 'mtg').trim().toUpperCase();
    const langUpper = String(tl.collector_info?.lang || 'en').trim().toUpperCase();
    if (artistText || colNum || setUpper) {
      const baseSize = L?.artist?.font_size ? Math.round(Number(L.artist.font_size) * sx) : 30;
      const fSize = Math.max(22, Math.min(34, baseSize));
      const baseX = L?.artist?.x ? Math.round(Number(L.artist.x) * sx) : 94;
      const line2Y = 1998;
      const line1Y = line2Y - Math.round(fSize * 1.24);
      const col2X = baseX + Math.round(fSize * 6.4);
      const colColor = L?.artist?.color || '#f2f2f2';

      ctx.save();
      ctx.fillStyle = colColor;
      ctx.textAlign = 'left';
      ctx.textBaseline = 'top';
      // Line 1: collector number (left) + rarity initial (right col)
      ctx.font = `600 ${fSize}px "BelerenLocal", sans-serif`;
      if (colNum) ctx.fillText(colNum, baseX, line1Y);
      ctx.fillText(rarityChar, col2X, line1Y);
      // Line 2: SET • LANG (left) + paintbrush icon + Artist (right col)
      ctx.fillText(`${setUpper} \u2022 ${langUpper}`, baseX, line2Y);
      if (artistText) {
        // Draw crisp MTG paintbrush nib icon
        const bx = col2X;
        const by = line2Y + Math.round(fSize * 0.52);
        const bw = Math.round(fSize * 1.15);
        const bh = Math.round(fSize * 0.62);
        ctx.beginPath();
        ctx.moveTo(bx, by - bh * 0.5);
        ctx.lineTo(bx + bw * 0.35, by - bh * 0.25);
        ctx.quadraticCurveTo(bx + bw * 0.78, by - bh * 0.52, bx + bw, by);
        ctx.quadraticCurveTo(bx + bw * 0.78, by + bh * 0.52, bx + bw * 0.35, by + bh * 0.25);
        ctx.lineTo(bx, by + bh * 0.5);
        ctx.closePath();
        ctx.fill();
        ctx.font = `600 ${Math.round(fSize * 1.05)}px "BelerenLocal", Georgia, serif`;
        ctx.fillText(artistText, bx + bw + Math.round(fSize * 0.35), line2Y - 1, 760);
      }
      ctx.restore();
    }
  }

  if (recorder) result.text_ops = recorder.ops;

  if (opts.draftShape) {
    drawShapeScaled(ctx, opts.draftShape, width / 750);
  }

  return result;
}
