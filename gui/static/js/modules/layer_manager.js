import { iconSvg } from './icons.js?v=1';

const LAYER_LABELS = {
  background: 'Frame',
  art: 'Artwork',
  pinlines: 'Pinlines / Textbox',
  name_box: 'Name Box',
  crown: 'Crown',
  border: 'Border',
  pt_box: 'PT Box',
};

const SHAPE_ICONS = {
  rect: 'rect',
  rounded: 'rounded-rect',
  circle: 'circle',
};

const COLORABLE_FRAME_KEYS = new Set(['background', 'pinlines', 'name_box', 'crown', 'border', 'pt_box']);

export const DEFAULT_LAYER_ORDER = [
  'background',
  'art',
  'pinlines',
  'name_box',
  'crown',
  'border',
  'pt_box',
];

function normalizeHiddenLayers(raw) {
  if (Array.isArray(raw)) {
    const obj = {};
    raw.forEach((k) => { obj[k] = true; });
    return obj;
  }
  if (raw && typeof raw === 'object') return raw;
  return {};
}

export class LayerManager {
  constructor(listEl, onChange, onSelect = null, onDelete = null) {
    this.listEl = listEl;
    this.onChange = onChange;
    this.onSelect = onSelect;
    this.onDelete = onDelete;
    this.dragKey = null;
    this.selectedKey = null;
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
    // Render top-most layer first in UI (reverse of bottom-to-top render order)
    const displayOrder = [...order].reverse();

    displayOrder.forEach((key) => {
      const li = document.createElement('li');
      const isShape = key.startsWith('shape:');
      const shape = isShape ? shapeMap.get(key) : null;
      const isEmptyFrame = !isShape && key !== 'art' && !(card.frame_components && card.frame_components[key]);
      const isHidden = Boolean(card.hidden_layers[key]) || isEmptyFrame;
      const isSelected = Boolean(this.selectedKey && this.selectedKey === key);
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
          <span title="Drag to reorder" style="cursor:grab; opacity:0.6; display:inline-flex;">${iconSvg('grip', 12)}</span>
          <button type="button" class="btn btn-sm" data-act="toggle" title="${isHidden ? 'Show layer' : 'Hide layer'}">${iconSvg(isHidden ? 'eye-off' : 'eye', 13)}</button>
          <span class="layer-name">${iconSvg(iconName, 12)} ${label} #${shapeIdx}</span>
          <input type="color" data-act="color" value="${shape.color || '#000000'}" title="Shape color" style="width:20px; height:18px; padding:0; border:none; background:none; cursor:pointer; flex-shrink:0;">
          <input type="range" min="0" max="1" step="0.05" value="${opacity}" data-act="opacity" style="width:44px;" title="Opacity">
          <button type="button" class="btn btn-sm" data-act="dup" title="Duplicate shape" style="padding:2px 4px;">${iconSvg('copy', 12)}</button>
          <button type="button" class="btn btn-sm" data-act="del" title="Delete shape" style="padding:2px 4px;">${iconSvg('x', 12)}</button>
        `;
      } else {
        const canColor = COLORABLE_FRAME_KEYS.has(key);
        const curColor = canColor ? ((card.layer_colors && card.layer_colors[key]) || '') : '';
        const hasColor = Boolean(curColor && curColor !== 'no-color');
        const tr = card.layer_transforms && card.layer_transforms[key];
        const hasTransform = Boolean(tr && (tr.dx || tr.dy || tr.crop_l || tr.crop_t || tr.crop_r || tr.crop_b));
        const colorCtrlHtml = canColor
          ? `<input type="color" data-act="layer-color" value="${hasColor ? curColor : '#1e293b'}" title="${hasColor ? `Color overlay: ${curColor}` : 'Set solid color overlay (no-color)'}" style="width:18px; height:18px; padding:0; border:1px solid ${hasColor ? 'var(--accent)' : 'var(--border)'}; border-radius:3px; background:none; cursor:pointer; opacity:${hasColor ? '1' : '0.45'}; flex-shrink:0;">`
            + (hasColor ? `<button type="button" class="btn btn-sm" data-act="layer-color-clear" title="Clear color (restore texture)" style="padding:1px 3px;">${iconSvg('x', 11)}</button>` : '')
          : '';
        const resetTrHtml = (canColor && hasTransform)
          ? `<button type="button" class="btn btn-sm" data-act="reset-tr" title="Reset move &amp; crop" style="padding:2px 4px;">${iconSvg('rotate-ccw', 11)}</button>`
          : '';
        const delCompHtml = (canColor && !isEmptyFrame)
          ? `<button type="button" class="btn btn-sm" data-act="del-comp" title="Delete component (Del)" style="padding:2px 4px;">${iconSvg('trash', 11)}</button>`
          : '';
        li.innerHTML = `
          <span title="Drag to reorder" style="cursor:grab; opacity:0.6; display:inline-flex;">${iconSvg('grip', 12)}</span>
          <button type="button" class="btn btn-sm" data-act="toggle" title="${isHidden ? 'Show layer' : 'Hide layer'}" aria-pressed="${isHidden ? 'true' : 'false'}">${iconSvg(isHidden ? 'eye-off' : 'eye', 13)}</button>
          <span class="layer-name">${LAYER_LABELS[key] || key}${isEmptyFrame ? ' <small style="opacity:0.6;">(empty)</small>' : ''}</span>
          ${colorCtrlHtml}
          <input type="range" min="0" max="1" step="0.05" value="${opacity}" data-act="opacity" style="width:42px;" title="Opacity">
          ${resetTrHtml}
          ${delCompHtml}
        `;
      }

      const toggleBtn = li.querySelector('[data-act="toggle"]');
      const opacityInput = li.querySelector('[data-act="opacity"]');
      const colorInput = li.querySelector('[data-act="color"]');
      const layerColorInput = li.querySelector('[data-act="layer-color"]');
      const layerColorClearBtn = li.querySelector('[data-act="layer-color-clear"]');
      const resetTrBtn = li.querySelector('[data-act="reset-tr"]');
      const delCompBtn = li.querySelector('[data-act="del-comp"]');
      const dupBtn = li.querySelector('[data-act="dup"]');
      const delBtn = li.querySelector('[data-act="del"]');

      // Prevent draggable <li> from hijacking clicks/drags on interactive controls
      [toggleBtn, opacityInput, colorInput, layerColorInput, layerColorClearBtn, resetTrBtn, delCompBtn, dupBtn, delBtn].filter(Boolean).forEach((ctrl) => {
        ctrl.addEventListener('pointerdown', (e) => {
          e.stopPropagation();
          li.draggable = false;
        });
        ctrl.addEventListener('pointerup', () => { li.draggable = true; });
        ctrl.addEventListener('pointercancel', () => { li.draggable = true; });
      });

      if (resetTrBtn) {
        resetTrBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          if (card.layer_transforms) delete card.layer_transforms[key];
          this.render(card);
          this.onChange?.(card);
        });
      }

      if (delCompBtn) {
        delCompBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          if (this.onDelete) {
            this.onDelete(key, card);
          } else {
            if (card.frame_components) card.frame_components[key] = '';
            if (card.layer_transforms) delete card.layer_transforms[key];
            if (card.layer_colors) delete card.layer_colors[key];
            card.hidden_layers = normalizeHiddenLayers(card.hidden_layers);
            card.hidden_layers[key] = true;
            if (this.selectedKey === key) this.selectedKey = null;
            this.render(card);
            this.onSelect?.(null, card);
            this.onChange?.(card);
          }
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
      });

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

      li.addEventListener('dragover', (e) => {
        e.preventDefault();
        if (!this.dragKey || this.dragKey === key) return;
        const rect = li.getBoundingClientRect();
        const isAbove = e.clientY < rect.top + rect.height / 2;
        this.listEl.querySelectorAll('.layer-item').forEach((el) => el.classList.remove('drop-above', 'drop-below'));
        li.classList.add(isAbove ? 'drop-above' : 'drop-below');
      });

      li.addEventListener('dragleave', () => {
        li.classList.remove('drop-above', 'drop-below');
      });

      li.addEventListener('drop', (e) => {
        e.preventDefault();
        const dragged = this.dragKey || e.dataTransfer.getData('text/plain');
        if (!dragged || dragged === key) return;
        const rect = li.getBoundingClientRect();
        const dropAboveInUI = e.clientY < rect.top + rect.height / 2;

        const nextDisplay = displayOrder.filter((k) => k !== dragged);
        let targetIdx = nextDisplay.indexOf(key);
        if (!dropAboveInUI) targetIdx += 1;
        nextDisplay.splice(targetIdx, 0, dragged);
        card.layer_order = [...nextDisplay].reverse();
        this.render(card);
        this.onChange?.(card);
      });

      this.listEl.appendChild(li);
    });
  }
}
