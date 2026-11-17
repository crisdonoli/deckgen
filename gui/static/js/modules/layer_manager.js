const LAYER_LABELS = {
  background: 'Background',
  art: 'Artwork',
  pinlines: 'Pinlines / Textbox',
  name_box: 'Name Box',
  crown: 'Crown',
  border: 'Border',
  pt_box: 'PT Box',
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
  constructor(listEl, onChange) {
    this.listEl = listEl;
    this.onChange = onChange;
    this.dragKey = null;
  }

  render(card) {
    if (!this.listEl || !card) return;
    const order = Array.isArray(card.layer_order) && card.layer_order.length
      ? card.layer_order.filter((k) => DEFAULT_LAYER_ORDER.includes(k))
      : [...DEFAULT_LAYER_ORDER];
    DEFAULT_LAYER_ORDER.forEach((k) => { if (!order.includes(k)) order.push(k); });
    card.layer_order = order;
    card.hidden_layers = normalizeHiddenLayers(card.hidden_layers);
    card.layer_opacities = card.layer_opacities || {};

    this.listEl.innerHTML = '';
    // Render top-most layer first in UI (reverse of bottom-to-top render order)
    const displayOrder = [...order].reverse();

    displayOrder.forEach((key) => {
      const li = document.createElement('li');
      const isEmptyFrame = key !== 'art' && !(card.frame_components && card.frame_components[key]);
      const isHidden = Boolean(card.hidden_layers[key]) || isEmptyFrame;
      li.className = 'layer-item' + (isHidden ? ' is-hidden-layer' : '');
      li.draggable = true;
      li.dataset.layerKey = key;

      const opacity = card.layer_opacities[key] ?? 1.0;

      li.innerHTML = `
        <span title="Drag to reorder" style="cursor:grab; opacity:0.65;">⠿</span>
        <button type="button" class="btn btn-sm" data-act="toggle" title="${isHidden ? 'Show layer' : 'Hide layer'}" aria-pressed="${isHidden ? 'true' : 'false'}">${isHidden ? '🚫' : '👁'}</button>
        <span class="layer-name">${LAYER_LABELS[key] || key}${isEmptyFrame ? ' <small style="opacity:0.6;">(empty)</small>' : ''}</span>
        <input type="range" min="0" max="1" step="0.05" value="${opacity}" data-act="opacity" style="width:58px;" title="Opacity">
      `;

      const toggleBtn = li.querySelector('[data-act="toggle"]');
      const opacityInput = li.querySelector('[data-act="opacity"]');

      // Prevent draggable <li> from hijacking clicks/drags on interactive controls
      [toggleBtn, opacityInput].forEach((ctrl) => {
        ctrl.addEventListener('pointerdown', (e) => {
          e.stopPropagation();
          li.draggable = false;
        });
        ctrl.addEventListener('pointerup', () => { li.draggable = true; });
        ctrl.addEventListener('pointercancel', () => { li.draggable = true; });
      });

      toggleBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        card.hidden_layers = normalizeHiddenLayers(card.hidden_layers);
        card.hidden_layers[key] = !card.hidden_layers[key];
        this.render(card);
        this.onChange?.(card);
      });

      opacityInput.addEventListener('input', (e) => {
        card.layer_opacities[key] = parseFloat(e.target.value);
        this.onChange?.(card);
      });

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
