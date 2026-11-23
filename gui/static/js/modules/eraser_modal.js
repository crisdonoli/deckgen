// Canva-style Freehand, Straight-Line & Shape Eraser / Restore Modal for any Card Builder layer.
// Displays the target component at 100% opacity over a translucent preview of all other layers
// so you can erase or restore exact regions using Brush, Straight Line, Rectangle, or Ellipse tools.

import { loadImageElement } from './crop_masks.js?v=3';

export class LayerEraserModal {
  constructor(modalEl, onApply) {
    this.modal = modalEl;
    this.onApply = onApply;
    this.canvas = modalEl?.querySelector('#cb-eraser-canvas') || null;
    this.ctx = this.canvas ? this.canvas.getContext('2d') : null;
    this.titleEl = modalEl?.querySelector('#cb-eraser-title') || null;
    this.modeEraseBtn = modalEl?.querySelector('#cb-eraser-mode-erase') || null;
    this.modeRestoreBtn = modalEl?.querySelector('#cb-eraser-mode-restore') || null;
    this.toolButtons = modalEl ? [...modalEl.querySelectorAll('[data-eraser-tool]')] : [];
    this.sizeInput = modalEl?.querySelector('#cb-eraser-size') || null;
    this.sizeValEl = modalEl?.querySelector('#cb-eraser-size-val') || null;
    this.softInput = modalEl?.querySelector('#cb-eraser-softness') || null;
    this.softValEl = modalEl?.querySelector('#cb-eraser-softness-val') || null;
    this.refOpInput = modalEl?.querySelector('#cb-eraser-ref-opacity') || null;
    this.refOpValEl = modalEl?.querySelector('#cb-eraser-ref-opacity-val') || null;
    this.zoomValEl = modalEl?.querySelector('#cb-eraser-zoom-val') || null;
    this.undoBtn = modalEl?.querySelector('#cb-eraser-undo-btn') || null;
    this.resetBtn = modalEl?.querySelector('#cb-eraser-reset-btn') || null;
    this.applyBtn = modalEl?.querySelector('#cb-eraser-apply-btn') || null;
    this.cancelBtn = modalEl?.querySelector('#cb-eraser-cancel-btn') || null;
    this.closeBtn = modalEl?.querySelector('#cb-eraser-close-btn') || null;
    this.zoomInBtn = modalEl?.querySelector('#cb-eraser-zoom-in') || null;
    this.zoomOutBtn = modalEl?.querySelector('#cb-eraser-zoom-out') || null;
    this.zoomResetBtn = modalEl?.querySelector('#cb-eraser-zoom-reset') || null;
    this.stageWrap = modalEl?.querySelector('#cb-eraser-stage') || null;

    this.W = 750;
    this.H = 1050;
    this.layerKey = null;
    this.mode = 'erase'; // 'erase' | 'restore'
    this.tool = 'brush'; // 'brush' | 'line' | 'rect' | 'circle'
    this.brushSize = 28;
    this.softness = 0.15;
    this.refOpacity = 0.4;
    this.zoom = 1.0;

    this.refCanvas = null;
    this.targetCanvas = null;
    this.maskCanvas = document.createElement('canvas');
    this.maskCanvas.width = this.W;
    this.maskCanvas.height = this.H;
    this.maskCtx = this.maskCanvas.getContext('2d', { willReadFrequently: true });

    this.workCanvas = document.createElement('canvas');
    this.workCanvas.width = this.W;
    this.workCanvas.height = this.H;
    this.workCtx = this.workCanvas.getContext('2d');

    this.undoStack = [];
    this.isDrawing = false;
    this.startPt = null;
    this.lastPt = null;
    this.cursorPt = null;
    this.shiftHeld = false;
    this._checkerPattern = null;

    if (this.modal && this.canvas) this._bindEvents();
  }

  _buildCheckerPattern() {
    if (this._checkerPattern) return this._checkerPattern;
    const tile = document.createElement('canvas');
    tile.width = 20;
    tile.height = 20;
    const tctx = tile.getContext('2d');
    tctx.fillStyle = '#1e293b';
    tctx.fillRect(0, 0, 20, 20);
    tctx.fillStyle = '#334155';
    tctx.fillRect(0, 0, 10, 10);
    tctx.fillRect(10, 10, 10, 10);
    this._checkerPattern = this.ctx.createPattern(tile, 'repeat');
    return this._checkerPattern;
  }

  _setTool(toolName) {
    this.tool = toolName || 'brush';
    this.toolButtons.forEach((btn) => {
      btn.classList.toggle('btn-primary', btn.dataset.eraserTool === this.tool);
    });
    this.render();
  }

  _constrainEndPt(a, b, shift) {
    if (!shift || !a || !b) return b;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    if (this.tool === 'line') {
      // Snap line to 0° / 45° / 90° angles
      const angle = Math.atan2(dy, dx);
      const snapped = Math.round(angle / (Math.PI / 4)) * (Math.PI / 4);
      const dist = Math.hypot(dx, dy);
      return { x: a.x + Math.cos(snapped) * dist, y: a.y + Math.sin(snapped) * dist };
    }
    if (this.tool === 'rect' || this.tool === 'circle') {
      // Snap to square / perfect circle
      const side = Math.max(Math.abs(dx), Math.abs(dy));
      return { x: a.x + Math.sign(dx || 1) * side, y: a.y + Math.sign(dy || 1) * side };
    }
    return b;
  }

  _bindEvents() {
    this.closeBtn?.addEventListener('click', () => this.close());
    this.cancelBtn?.addEventListener('click', () => this.close());
    this.applyBtn?.addEventListener('click', () => this.apply());
    this.undoBtn?.addEventListener('click', () => this.undoStroke());
    this.resetBtn?.addEventListener('click', () => {
      this._pushUndo();
      this.maskCtx.clearRect(0, 0, this.W, this.H);
      this.render();
    });

    const setMode = (m) => {
      this.mode = m;
      this.modeEraseBtn?.classList.toggle('btn-primary', m === 'erase');
      this.modeRestoreBtn?.classList.toggle('btn-primary', m === 'restore');
      this.render();
    };
    this.modeEraseBtn?.addEventListener('click', () => setMode('erase'));
    this.modeRestoreBtn?.addEventListener('click', () => setMode('restore'));
    this.toolButtons.forEach((btn) => {
      btn.addEventListener('click', () => this._setTool(btn.dataset.eraserTool));
    });

    this.sizeInput?.addEventListener('input', () => {
      this.brushSize = Math.max(4, Math.min(140, parseInt(this.sizeInput.value, 10) || 28));
      if (this.sizeValEl) this.sizeValEl.textContent = `${this.brushSize}px`;
      this.render();
    });
    this.softInput?.addEventListener('input', () => {
      this.softness = Math.max(0, Math.min(1, parseFloat(this.softInput.value) || 0));
      if (this.softValEl) this.softValEl.textContent = `${Math.round(this.softness * 100)}%`;
    });
    this.refOpInput?.addEventListener('input', () => {
      this.refOpacity = Math.max(0, Math.min(1, parseFloat(this.refOpInput.value) || 0));
      if (this.refOpValEl) this.refOpValEl.textContent = `${Math.round(this.refOpacity * 100)}%`;
      this.render();
    });

    this.zoomInBtn?.addEventListener('click', () => this._setZoom(this.zoom + 0.25));
    this.zoomOutBtn?.addEventListener('click', () => this._setZoom(this.zoom - 0.25));
    this.zoomResetBtn?.addEventListener('click', () => this._setZoom(1.0));
    this.stageWrap?.addEventListener('wheel', (e) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      this._setZoom(this.zoom + (e.deltaY < 0 ? 0.15 : -0.15));
    }, { passive: false });

    const ptFromEvent = (e) => {
      const rect = this.canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) return { x: 0, y: 0 };
      return {
        x: (e.clientX - rect.left) * (this.W / rect.width),
        y: (e.clientY - rect.top) * (this.H / rect.height),
      };
    };

    this.canvas.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      this._pushUndo();
      this.isDrawing = true;
      this.shiftHeld = Boolean(e.shiftKey);
      const pt = ptFromEvent(e);
      this.startPt = pt;
      this.lastPt = pt;
      this.cursorPt = pt;
      if (this.tool === 'brush') {
        this._dab(pt.x, pt.y);
      }
      this.render();
      this.canvas.setPointerCapture?.(e.pointerId);
    });

    this.canvas.addEventListener('pointermove', (e) => {
      this.shiftHeld = Boolean(e.shiftKey);
      const pt = ptFromEvent(e);
      this.cursorPt = pt;
      if (this.isDrawing && this.tool === 'brush' && this.lastPt) {
        this._strokeLine(this.lastPt, pt);
        this.lastPt = pt;
      }
      this.render();
    });

    const endStroke = (e) => {
      if (!this.isDrawing) return;
      if (this.tool !== 'brush' && this.startPt && this.cursorPt) {
        const endPt = this._constrainEndPt(this.startPt, this.cursorPt, Boolean(e?.shiftKey || this.shiftHeld));
        this._commitShapeTool(this.startPt, endPt);
      }
      this.isDrawing = false;
      this.startPt = null;
      this.lastPt = null;
      this.render();
    };
    this.canvas.addEventListener('pointerup', endStroke);
    this.canvas.addEventListener('pointercancel', endStroke);
    this.canvas.addEventListener('pointerleave', () => {
      if (!this.isDrawing) {
        this.cursorPt = null;
        this.render();
      }
    });

    window.addEventListener('keydown', (e) => {
      if (!this.modal?.classList.contains('open')) return;
      if (e.key === 'Escape') {
        e.preventDefault();
        this.close();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        this.undoStroke();
      } else if (e.key === '[') {
        this.brushSize = Math.max(4, this.brushSize - 4);
        if (this.sizeInput) this.sizeInput.value = String(this.brushSize);
        if (this.sizeValEl) this.sizeValEl.textContent = `${this.brushSize}px`;
        this.render();
      } else if (e.key === ']') {
        this.brushSize = Math.min(140, this.brushSize + 4);
        if (this.sizeInput) this.sizeInput.value = String(this.brushSize);
        if (this.sizeValEl) this.sizeValEl.textContent = `${this.brushSize}px`;
        this.render();
      }
    });
  }

  _commitShapeTool(a, b) {
    const mctx = this.maskCtx;
    mctx.save();
    mctx.globalCompositeOperation = this.mode === 'erase' ? 'source-over' : 'destination-out';
    if (this.tool === 'line') {
      mctx.strokeStyle = '#ffffff';
      mctx.lineWidth = Math.max(2, this.brushSize);
      mctx.lineCap = 'round';
      mctx.beginPath();
      mctx.moveTo(a.x, a.y);
      mctx.lineTo(b.x, b.y);
      mctx.stroke();
    } else if (this.tool === 'rect') {
      const x = Math.min(a.x, b.x);
      const y = Math.min(a.y, b.y);
      const w = Math.abs(b.x - a.x);
      const h = Math.abs(b.y - a.y);
      if (w >= 1 && h >= 1) {
        mctx.fillStyle = '#ffffff';
        mctx.fillRect(x, y, w, h);
      }
    } else if (this.tool === 'circle') {
      const cx = (a.x + b.x) / 2;
      const cy = (a.y + b.y) / 2;
      const rx = Math.abs(b.x - a.x) / 2;
      const ry = Math.abs(b.y - a.y) / 2;
      if (rx >= 1 && ry >= 1) {
        mctx.fillStyle = '#ffffff';
        mctx.beginPath();
        mctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
        mctx.fill();
      }
    }
    mctx.restore();
  }

  _setZoom(z) {
    this.zoom = Math.max(0.6, Math.min(3.0, Math.round(z * 20) / 20));
    if (this.zoomValEl) this.zoomValEl.textContent = `${Math.round(this.zoom * 100)}%`;
    const baseH = Math.min(window.innerHeight * 0.64, 600);
    const h = Math.round(baseH * this.zoom);
    const w = Math.round(h * (this.W / this.H));
    this.canvas.style.width = `${w}px`;
    this.canvas.style.height = `${h}px`;
  }

  _pushUndo() {
    try {
      const snap = this.maskCtx.getImageData(0, 0, this.W, this.H);
      this.undoStack.push(snap);
      if (this.undoStack.length > 30) this.undoStack.shift();
      if (this.undoBtn) this.undoBtn.disabled = false;
    } catch {}
  }

  undoStroke() {
    if (!this.undoStack.length) return;
    const prev = this.undoStack.pop();
    if (prev) this.maskCtx.putImageData(prev, 0, 0);
    if (this.undoBtn) this.undoBtn.disabled = this.undoStack.length === 0;
    this.render();
  }

  _dab(x, y) {
    const r = Math.max(2, this.brushSize / 2);
    const mctx = this.maskCtx;
    mctx.save();
    mctx.globalCompositeOperation = this.mode === 'erase' ? 'source-over' : 'destination-out';
    if (this.softness > 0.02) {
      const innerR = Math.max(0, r * (1 - this.softness));
      const g = mctx.createRadialGradient(x, y, innerR, x, y, r);
      g.addColorStop(0, 'rgba(255,255,255,1)');
      g.addColorStop(1, 'rgba(255,255,255,0)');
      mctx.fillStyle = g;
    } else {
      mctx.fillStyle = '#ffffff';
    }
    mctx.beginPath();
    mctx.arc(x, y, r, 0, Math.PI * 2);
    mctx.fill();
    mctx.restore();
  }

  _strokeLine(a, b) {
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const dist = Math.hypot(dx, dy);
    const step = Math.max(1.5, this.brushSize * 0.18);
    const steps = Math.max(1, Math.ceil(dist / step));
    for (let i = 1; i <= steps; i += 1) {
      const t = i / steps;
      this._dab(a.x + dx * t, a.y + dy * t);
    }
  }

  async open({ layerKey, layerLabel, refCanvas, targetCanvas, existingMaskDataUrl = null }) {
    if (!this.modal || !this.canvas) return;
    this.layerKey = layerKey;
    this.refCanvas = refCanvas;
    this.targetCanvas = targetCanvas;
    this.undoStack = [];
    if (this.undoBtn) this.undoBtn.disabled = true;
    this.mode = 'erase';
    this.modeEraseBtn?.classList.add('btn-primary');
    this.modeRestoreBtn?.classList.remove('btn-primary');
    this._setTool('brush');
    if (this.titleEl) this.titleEl.textContent = `Eraser — ${layerLabel || layerKey}`;

    this.canvas.width = this.W;
    this.canvas.height = this.H;
    this.maskCtx.clearRect(0, 0, this.W, this.H);

    if (existingMaskDataUrl) {
      const img = await loadImageElement(existingMaskDataUrl);
      if (img) {
        this.maskCtx.drawImage(img, 0, 0, this.W, this.H);
      }
    }

    this._setZoom(1.0);
    this.modal.classList.add('open');
    this.render();
  }

  close() {
    this.isDrawing = false;
    this.startPt = null;
    this.cursorPt = null;
    this.modal?.classList.remove('open');
  }

  render() {
    if (!this.ctx) return;
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.W, this.H);

    // 1. Checkerboard background so erased alpha areas are clear
    ctx.fillStyle = this._buildCheckerPattern() || '#1e293b';
    ctx.fillRect(0, 0, this.W, this.H);

    // 2. All other layers rendered translucently as spatial reference
    if (this.refCanvas && this.refOpacity > 0.01) {
      ctx.save();
      ctx.globalAlpha = this.refOpacity;
      ctx.drawImage(this.refCanvas, 0, 0, this.W, this.H);
      ctx.restore();
    }

    // 3. Target component at 100% opacity minus the erased mask strokes
    if (this.targetCanvas) {
      const wctx = this.workCtx;
      wctx.clearRect(0, 0, this.W, this.H);
      wctx.globalCompositeOperation = 'source-over';
      wctx.drawImage(this.targetCanvas, 0, 0, this.W, this.H);
      wctx.globalCompositeOperation = 'destination-out';
      wctx.drawImage(this.maskCanvas, 0, 0, this.W, this.H);
      wctx.globalCompositeOperation = 'source-over';
      ctx.drawImage(this.workCanvas, 0, 0, this.W, this.H);
    }

    // 4. Live preview of Straight Line / Rect / Circle cut while dragging
    const accent = this.mode === 'erase' ? '#f43f5e' : '#22c55e';
    const accentFill = this.mode === 'erase' ? 'rgba(244, 63, 94, 0.25)' : 'rgba(34, 197, 94, 0.25)';
    if (this.isDrawing && this.tool !== 'brush' && this.startPt && this.cursorPt) {
      const a = this.startPt;
      const b = this._constrainEndPt(a, this.cursorPt, this.shiftHeld);
      ctx.save();
      if (this.tool === 'line') {
        ctx.strokeStyle = accentFill;
        ctx.lineWidth = Math.max(2, this.brushSize);
        ctx.lineCap = 'round';
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
        ctx.strokeStyle = accent;
        ctx.lineWidth = 2;
        ctx.setLineDash([6, 4]);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      } else if (this.tool === 'rect') {
        const x = Math.min(a.x, b.x);
        const y = Math.min(a.y, b.y);
        const w = Math.abs(b.x - a.x);
        const h = Math.abs(b.y - a.y);
        ctx.fillStyle = accentFill;
        ctx.fillRect(x, y, w, h);
        ctx.strokeStyle = accent;
        ctx.lineWidth = 2;
        ctx.setLineDash([6, 4]);
        ctx.strokeRect(x, y, w, h);
      } else if (this.tool === 'circle') {
        const cx = (a.x + b.x) / 2;
        const cy = (a.y + b.y) / 2;
        const rx = Math.abs(b.x - a.x) / 2;
        const ry = Math.abs(b.y - a.y) / 2;
        ctx.fillStyle = accentFill;
        ctx.strokeStyle = accent;
        ctx.lineWidth = 2;
        ctx.setLineDash([6, 4]);
        ctx.beginPath();
        ctx.ellipse(cx, cy, Math.max(1, rx), Math.max(1, ry), 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      }
      ctx.restore();
    }

    // 5. Live brush cursor ring (for Brush & Line width preview)
    if (this.cursorPt && (this.tool === 'brush' || this.tool === 'line')) {
      const r = Math.max(2, this.brushSize / 2);
      ctx.save();
      ctx.strokeStyle = accent;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(this.cursorPt.x, this.cursorPt.y, r, 0, Math.PI * 2);
      ctx.stroke();
      ctx.strokeStyle = 'rgba(255,255,255,0.85)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(this.cursorPt.x, this.cursorPt.y, Math.max(1, r - 1.5), 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    }
  }

  _hasAnyErasedPixels() {
    const data = this.maskCtx.getImageData(0, 0, this.W, this.H).data;
    for (let i = 3; i < data.length; i += 4) {
      if (data[i] > 4) return true;
    }
    return false;
  }

  apply() {
    const dataUrl = this._hasAnyErasedPixels() ? this.maskCanvas.toDataURL('image/png') : null;
    const key = this.layerKey;
    this.close();
    if (this.onApply && key) this.onApply(key, dataUrl);
  }
}
