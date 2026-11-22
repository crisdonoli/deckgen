// Records the Canvas 2D calls used to draw a card's set symbol and text, already resolved
// (final font size, left x, alphabetic baseline y, measured width), so the server-side
// export (core/recipe_renderer.replay_canvas_ops) can paint exactly what the preview drew.
// Calls are forwarded to the real context, so the preview renders normally while recording.

const STATE_PROPS = new Set([
  'font', 'fillStyle', 'strokeStyle', 'lineWidth', 'textAlign', 'textBaseline',
  'shadowColor', 'shadowBlur', 'shadowOffsetX', 'shadowOffsetY',
  'globalAlpha', 'globalCompositeOperation',
]);

const RECORDED_METHODS = new Set([
  'save', 'restore', 'beginPath', 'moveTo', 'lineTo', 'quadraticCurveTo', 'bezierCurveTo',
  'arc', 'ellipse', 'rect', 'roundRect', 'closePath', 'fill', 'stroke', 'clip',
  'fillRect', 'strokeRect', 'translate', 'rotate', 'scale', 'setTransform', 'resetTransform',
]);

function imageSource(img) {
  if (typeof HTMLCanvasElement !== 'undefined' && img instanceof HTMLCanvasElement) {
    return img.toDataURL('image/png');
  }
  return img?.currentSrc || img?.src || '';
}

function textOp(ctx, text, x, y, maxWidth) {
  const str = String(text);
  const baseline = ctx.textBaseline;
  const m = ctx.measureText(str);
  ctx.textBaseline = 'alphabetic';
  const ma = ctx.measureText(str);
  ctx.textBaseline = baseline;
  // Distance between the requested baseline line and the alphabetic baseline.
  const baselineY = Number(y) + ma.fontBoundingBoxAscent - m.fontBoundingBoxAscent;
  let width = m.width;
  if (maxWidth !== undefined && maxWidth !== null && Number.isFinite(Number(maxWidth)) && width > Number(maxWidth)) {
    width = Number(maxWidth);
  }
  const align = ctx.textAlign;
  let left = Number(x);
  if (align === 'center') left -= width / 2;
  else if (align === 'right' || align === 'end') left -= width;
  return { op: 'text', text: str, x: left, y: baselineY, width, font: ctx.font };
}

export function createRecordingContext(ctx) {
  // Start from the context's current state, not the Canvas defaults.
  const ops = [...STATE_PROPS].map((k) => ({ op: 'set', k, v: ctx[k] }));
  const proxy = new Proxy(ctx, {
    get(target, prop) {
      if (prop === 'fillText') {
        return (text, x, y, maxWidth) => {
          ops.push(textOp(target, text, x, y, maxWidth));
          return maxWidth === undefined ? target.fillText(text, x, y) : target.fillText(text, x, y, maxWidth);
        };
      }
      if (prop === 'drawImage') {
        return (img, ...args) => {
          ops.push({ op: 'drawImage', src: imageSource(img), args });
          return target.drawImage(img, ...args);
        };
      }
      if (RECORDED_METHODS.has(prop)) {
        return (...args) => {
          ops.push({ op: prop, args });
          return target[prop](...args);
        };
      }
      const value = Reflect.get(target, prop);
      return typeof value === 'function' ? value.bind(target) : value;
    },
    set(target, prop, value) {
      if (STATE_PROPS.has(prop)) ops.push({ op: 'set', k: prop, v: value });
      target[prop] = value;
      return true;
    },
  });
  return { ctx: proxy, ops };
}
