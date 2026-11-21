export const CROP_MASKS = {
  free: { label: 'Free / Rectangular', aspect: null },
  classic_box: { label: 'Classic Art Box (682×477)', aspect: 682 / 477 },
  borderless_bottom_curve: { label: 'Borderless Full-Art (Bottom Curve)', aspect: 750 / 970 },
  extended_angled: { label: 'Extended Art / Borderless (Angled)', aspect: 700 / 560 },
  circular: { label: 'Circular / Oval Vignette', aspect: 1.0 },
  full_art: { label: 'Full Art / Saga (Vertical)', aspect: 700 / 940 },
};

export function drawMaskPath(ctx, maskType, x, y, w, h) {
  ctx.beginPath();
  if (maskType === 'circular') {
    ctx.ellipse(x + w / 2, y + h / 2, w / 2, h / 2, 0, 0, Math.PI * 2);
  } else if (maskType === 'borderless_bottom_curve') {
    const rx = w * 0.22;
    const ry = h * 0.21;
    ctx.moveTo(x, y);
    ctx.lineTo(x + w, y);
    ctx.lineTo(x + w, y + h - ry);
    ctx.quadraticCurveTo(x + w, y + h, x + w - rx, y + h);
    ctx.lineTo(x + rx, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - ry);
    ctx.closePath();
  } else if (maskType === 'extended_angled') {
    const bevel = Math.min(w, h) * 0.14;
    ctx.moveTo(x, y);
    ctx.lineTo(x + w, y);
    ctx.lineTo(x + w, y + h - bevel);
    ctx.lineTo(x + w - bevel, y + h);
    ctx.lineTo(x + bevel, y + h);
    ctx.lineTo(x, y + h - bevel);
    ctx.closePath();
  } else {
    ctx.rect(x, y, w, h);
  }
}

export class CropMaskModal {
  constructor(modalEl, onApply) {
    this.modal = modalEl;
    this.onApply = onApply;
    this.canvas = modalEl.querySelector('#cb-crop-canvas');
    this.ctx = this.canvas.getContext('2d');
    this.maskSelect = modalEl.querySelector('#cb-crop-mask-select');
    this.zoomInput = modalEl.querySelector('#cb-crop-zoom');
    this.img = null;
    this.maskType = 'classic_box';
    this.zoom = 1.0;
    this.box = { x: 40, y: 40, w: 300, h: 210 };
    this.dragState = null;

    this._bindEvents();
  }

  _bindEvents() {
    this.modal.querySelector('#cb-crop-close-btn')?.addEventListener('click', () => this.close());
    this.modal.querySelector('#cb-crop-cancel-btn')?.addEventListener('click', () => this.close());
    this.modal.querySelector('#cb-crop-reset-btn')?.addEventListener('click', () => this.resetBox());
    this.modal.querySelector('#cb-crop-apply-btn')?.addEventListener('click', () => this.apply());

    this.maskSelect?.addEventListener('change', () => {
      this.maskType = this.maskSelect.value;
      this.resetBox();
    });
    this.zoomInput?.addEventListener('input', () => {
      this.zoom = parseFloat(this.zoomInput.value) || 1.0;
      this.render();
    });

    this.canvas.addEventListener('pointerdown', (e) => {
      const rect = this.canvas.getBoundingClientRect();
      const px = (e.clientX - rect.left) * (this.canvas.width / rect.width);
      const py = (e.clientY - rect.top) * (this.canvas.height / rect.height);
      const b = this.box;
      const nearRight = Math.abs(px - (b.x + b.w)) < 18 && Math.abs(py - (b.y + b.h)) < 18;
      if (nearRight) {
        this.dragState = { mode: 'resize', startX: px, startY: py, orig: { ...b } };
      } else if (px >= b.x && px <= b.x + b.w && py >= b.y && py <= b.y + b.h) {
        this.dragState = { mode: 'move', startX: px, startY: py, orig: { ...b } };
      }
      this.canvas.setPointerCapture(e.pointerId);
    });

    this.canvas.addEventListener('pointermove', (e) => {
      if (!this.dragState) return;
      const rect = this.canvas.getBoundingClientRect();
      const px = (e.clientX - rect.left) * (this.canvas.width / rect.width);
      const py = (e.clientY - rect.top) * (this.canvas.height / rect.height);
      const dx = px - this.dragState.startX;
      const dy = py - this.dragState.startY;
      const orig = this.dragState.orig;
      const aspect = CROP_MASKS[this.maskType]?.aspect;

      if (this.dragState.mode === 'move') {
        this.box.x = Math.max(0, Math.min(this.canvas.width - orig.w, orig.x + dx));
        this.box.y = Math.max(0, Math.min(this.canvas.height - orig.h, orig.y + dy));
      } else {
        let nw = Math.max(40, Math.min(this.canvas.width - orig.x, orig.w + dx));
        let nh = aspect ? nw / aspect : Math.max(40, Math.min(this.canvas.height - orig.y, orig.h + dy));
        if (orig.y + nh > this.canvas.height) {
          nh = this.canvas.height - orig.y;
          if (aspect) nw = nh * aspect;
        }
        this.box.w = nw;
        this.box.h = nh;
      }
      this.render();
    });

    this.canvas.addEventListener('pointerup', () => { this.dragState = null; });
  }

  open(imageSrc, initialMask = 'classic_box') {
    this.maskType = initialMask || 'classic_box';
    if (this.maskSelect) this.maskSelect.value = this.maskType;
    this.zoom = 1.0;
    if (this.zoomInput) this.zoomInput.value = '1';

    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      this.img = img;
      const maxW = 700;
      const maxH = 480;
      const scale = Math.min(maxW / img.width, maxH / img.height, 1.0);
      this.canvas.width = Math.round(img.width * scale);
      this.canvas.height = Math.round(img.height * scale);
      this.resetBox();
      this.modal.classList.add('open');
    };
    img.src = /^https?:\/\//i.test(imageSrc) ? `/api/art/proxy?url=${encodeURIComponent(imageSrc)}` : imageSrc;
  }

  close() {
    this.modal.classList.remove('open');
  }

  resetBox() {
    if (!this.canvas.width) return;
    const aspect = CROP_MASKS[this.maskType]?.aspect;
    let w = this.canvas.width * 0.72;
    let h = aspect ? w / aspect : this.canvas.height * 0.72;
    if (h > this.canvas.height * 0.85) {
      h = this.canvas.height * 0.85;
      if (aspect) w = h * aspect;
    }
    this.box = {
      x: (this.canvas.width - w) / 2,
      y: (this.canvas.height - h) / 2,
      w,
      h,
    };
    this.render();
  }

  render() {
    if (!this.img) return;
    const { ctx, canvas, box } = this;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Draw zoomed image centered
    const zw = canvas.width * this.zoom;
    const zh = canvas.height * this.zoom;
    const zx = (canvas.width - zw) / 2;
    const zy = (canvas.height - zh) / 2;
    ctx.drawImage(this.img, zx, zy, zw, zh);

    // Dim outside mask
    ctx.save();
    ctx.fillStyle = 'rgba(0, 0, 0, 0.58)';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.globalCompositeOperation = 'destination-out';
    drawMaskPath(ctx, this.maskType, box.x, box.y, box.w, box.h);
    ctx.fill();
    ctx.restore();

    // Redraw crisp image inside mask
    ctx.save();
    drawMaskPath(ctx, this.maskType, box.x, box.y, box.w, box.h);
    ctx.clip();
    ctx.drawImage(this.img, zx, zy, zw, zh);
    ctx.restore();

    // Mask outline + resize handle
    ctx.save();
    ctx.strokeStyle = '#3b82f6';
    ctx.lineWidth = 2;
    drawMaskPath(ctx, this.maskType, box.x, box.y, box.w, box.h);
    ctx.stroke();
    ctx.fillStyle = '#3b82f6';
    ctx.fillRect(box.x + box.w - 7, box.y + box.h - 7, 14, 14);
    ctx.restore();
  }

  apply() {
    if (!this.img) return;
    const { canvas, box } = this;
    const outCanvas = document.createElement('canvas');
    const scaleToNat = this.img.naturalWidth / (canvas.width * this.zoom);
    const outW = Math.max(64, Math.round(box.w * scaleToNat));
    const outH = Math.max(64, Math.round(box.h * scaleToNat));
    outCanvas.width = outW;
    outCanvas.height = outH;
    const octx = outCanvas.getContext('2d');

    // Clip to exact template mask geometry with transparent alpha
    drawMaskPath(octx, this.maskType, 0, 0, outW, outH);
    octx.clip();

    const zx = (canvas.width - canvas.width * this.zoom) / 2;
    const zy = (canvas.height - canvas.height * this.zoom) / 2;
    const sx = (box.x - zx) * scaleToNat;
    const sy = (box.y - zy) * scaleToNat;
    octx.drawImage(this.img, sx, sy, outW, outH, 0, 0, outW, outH);

    const dataUrl = outCanvas.toDataURL('image/png');
    this.close();
    if (this.onApply) this.onApply(dataUrl, this.maskType);
  }
}

export function loadImageElement(src) {
  return new Promise((resolve) => {
    if (!src) return resolve(null);
    const img = new Image();
    if (!/^data:/i.test(src)) img.crossOrigin = 'anonymous';
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
}

export function applyMaskToCanvas(canvas, maskImage) {
  if (!canvas || !maskImage) return canvas;
  const aux = document.createElement('canvas');
  aux.width = canvas.width;
  aux.height = canvas.height;
  const auxCtx = aux.getContext('2d');
  auxCtx.drawImage(maskImage, 0, 0, canvas.width, canvas.height);
  const ctx = canvas.getContext('2d');
  ctx.save();
  ctx.globalCompositeOperation = 'destination-in';
  ctx.drawImage(aux, 0, 0);
  ctx.restore();
  return canvas;
}

// zone: {x,y,w,h} in absolute canvas coordinates; transform: {x,y,scale,rotation}
export function drawArtInto(targetCtx, artImage, zone, transform = {}) {
  if (!artImage || !zone) return;
  const scale = Math.max(zone.w / artImage.width, zone.h / artImage.height) * (transform.scale || 1);
  const dw = artImage.width * scale;
  const dh = artImage.height * scale;
  targetCtx.save();
  targetCtx.beginPath();
  targetCtx.rect(zone.x, zone.y, zone.w, zone.h);
  targetCtx.clip();
  if (transform.rotation) {
    targetCtx.translate(zone.x + zone.w / 2 + (transform.x || 0), zone.y + zone.h / 2 + (transform.y || 0));
    targetCtx.rotate((transform.rotation * Math.PI) / 180);
    targetCtx.drawImage(artImage, -dw / 2, -dh / 2, dw, dh);
  } else {
    targetCtx.drawImage(
      artImage,
      zone.x + (zone.w - dw) / 2 + (transform.x || 0),
      zone.y + (zone.h - dh) / 2 + (transform.y || 0),
      dw,
      dh
    );
  }
  targetCtx.restore();
}

