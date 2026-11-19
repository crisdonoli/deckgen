const LAYER_LABELS = {
  background: 'Background',
  art: 'Artwork',
  pinlines: 'Pinlines / Textbox',
  name_box: 'Name Box',
  crown: 'Crown',
  border: 'Border',
  pt_box: 'PT Box',
};

const SHAPE_ICONS = {
  rect: '▭',
  rounded: '▢',
  circle: '◯',
};

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
  constructor(listEl, onChange, onSelect = null) {
    this.listEl = listEl;
    this.onChange = onChange;
    this.onSelect = onSelect;
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
        const icon = SHAPE_ICONS[shape.type] || '▭';
        const label = shape.type === 'circle' ? 'Circle' : (shape.type === 'rounded' ? 'Rounded' : 'Box');
        li.innerHTML = `
          <span title="Drag to reorder" style="cursor:grab; opacity:0.65;">⠿</span>
          <button type="button" class="btn btn-sm" data-act="toggle" title="${isHidden ? 'Show layer' : 'Hide layer'}">${isHidden ? '🚫' : '👁'}</button>
          <span class="layer-name">${icon} ${label} #${shapeIdx}</span>
          <input type="color" data-act="color" value="${shape.color || '#000000'}" title="Shape color" style="width:20px; height:18px; padding:0; border:none; background:none; cursor:pointer; flex-shrink:0;">
          <input type="range" min="0" max="1" step="0.05" value="${opacity}" data-act="opacity" style="width:46px;" title="Opacity">
          <button type="button" class="btn btn-sm" data-act="dup" title="Duplicate shape" style="padding:1px 4px;">⧉</button>
          <button type="button" class="btn btn-sm" data-act="del" title="Delete shape" style="padding:1px 4px;">✕</button>
        `;
      } else {
        li.innerHTML = `
          <span title="Drag to reorder" style="cursor:grab; opacity:0.65;">⠿</span>
          <button type="button" class="btn btn-sm" data-act="toggle" title="${isHidden ? 'Show layer' : 'Hide layer'}" aria-pressed="${isHidden ? 'true' : 'false'}">${isHidden ? '🚫' : '👁'}</button>
          <span class="layer-name">${LAYER_LABELS[key] || key}${isEmptyFrame ? ' <small style="opacity:0.6;">(empty)</small>' : ''}</span>
          <input type="range" min="0" max="1" step="0.05" value="${opacity}" data-act="opacity" style="width:52px;" title="Opacity">
        `;
      }

      const toggleBtn = li.querySelector('[data-act="toggle"]');
      const opacityInput = li.querySelector('[data-act="opacity"]');
      const colorInput = li.querySelector('[data-act="color"]');
      const dupBtn = li.querySelector('[data-act="dup"]');
      const delBtn = li.querySelector('[data-act="del"]');

      // Prevent draggable <li> from hijacking clicks/drags on interactive controls
      [toggleBtn, opacityInput, colorInput, dupBtn, delBtn].filter(Boolean).forEach((ctrl) => {
        ctrl.addEventListener('pointerdown', (e) => {
          e.stopPropagation();
          li.draggable = false;
        });
        ctrl.addEventListener('pointerup', () => { li.draggable = true; });
        ctrl.addEventListener('pointercancel', () => { li.draggable = true; });
      });

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
