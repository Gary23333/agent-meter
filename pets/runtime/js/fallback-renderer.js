// Last-resort renderer (no WebGL, or a broken pack): a round face on a 2-D canvas. It exists so the pet
// never shows an empty window; it makes no attempt to be pretty.

import { TAU } from './util.js';

const FACES = {
  happy: { eye: 'arc', mouth: 'smile' }, excited: { eye: 'arc', mouth: 'open' }, sad: { eye: 'dot', mouth: 'frown' },
  worried: { eye: 'dot', mouth: 'frown' }, sleepy: { eye: 'line', mouth: 'flat' }, surprised: { eye: 'big', mouth: 'open' },
  confused: { eye: 'dot', mouth: 'flat' }, dizzy: { eye: 'x', mouth: 'frown' }, determined: { eye: 'dot', mouth: 'flat' },
  neutral: { eye: 'dot', mouth: 'smile' }, yawn: { eye: 'line', mouth: 'open' }, love: { eye: 'arc', mouth: 'smile' },
};

export class FallbackRenderer {
  constructor(container, model, { width, height, dpr = 2, tokens }) {
    this.container = container;
    this.width = width;
    this.height = height;
    this.dpr = Math.min(dpr, 2);
    this.tokens = tokens || { accent1: '#7c6cff', ink: '#2b2260' };
    this.t = 0;
    this.view = { expression: 'neutral', animation: 'idle', intensity: 0.5 };
  }

  async init() {
    const canvas = document.createElement('canvas');
    Object.assign(canvas.style, { position: 'absolute', left: '0', top: '0', width: '100%', height: '100%' });
    this.container.prepend(canvas);
    this.canvas = canvas;
    this.g = canvas.getContext('2d');
    this.resize(this.width, this.height, this.dpr);
  }

  setTokens(tokens) { this.tokens = tokens; }
  setView(view) { this.view = view; }
  advance(dt) { this.t += dt; }
  seek(t) { this.t = t; }

  render() {
    const g = this.g, { width: w, height: h } = this;
    g.clearRect(0, 0, w, h);
    const speed = this.view.animation === 'sleeping' ? 0.5 : this.view.animation === 'alarm' ? 8 : 2;
    const bob = Math.sin(this.t * speed) * 4;
    const r = Math.min(w, h) * 0.3;
    const cx = w / 2, cy = h * 0.6 + bob;
    g.fillStyle = this.tokens.accent1;
    g.beginPath(); g.arc(cx, cy, r, 0, TAU); g.fill();
    g.strokeStyle = this.tokens.ink; g.fillStyle = this.tokens.ink; g.lineWidth = 3; g.lineCap = 'round';
    const face = FACES[this.view.expression] || FACES.neutral;
    for (const s of [-1, 1]) {
      const x = cx + s * r * 0.38, y = cy - r * 0.1;
      g.beginPath();
      if (face.eye === 'dot') g.arc(x, y, r * 0.09, 0, TAU), g.fill();
      else if (face.eye === 'big') g.arc(x, y, r * 0.14, 0, TAU), g.fill();
      else if (face.eye === 'arc') g.arc(x, y + r * 0.05, r * 0.12, Math.PI, 0), g.stroke();
      else if (face.eye === 'line') g.moveTo(x - r * 0.1, y), g.lineTo(x + r * 0.1, y), g.stroke();
      else g.moveTo(x - 6, y - 6), g.lineTo(x + 6, y + 6), g.moveTo(x + 6, y - 6), g.lineTo(x - 6, y + 6), g.stroke();
    }
    g.beginPath();
    if (face.mouth === 'smile') g.arc(cx, cy + r * 0.12, r * 0.28, 0.15 * Math.PI, 0.85 * Math.PI), g.stroke();
    else if (face.mouth === 'frown') g.arc(cx, cy + r * 0.5, r * 0.22, 1.15 * Math.PI, 1.85 * Math.PI), g.stroke();
    else if (face.mouth === 'open') g.ellipse(cx, cy + r * 0.38, r * 0.12, r * 0.16, 0, 0, TAU), g.fill();
    else g.moveTo(cx - r * 0.18, cy + r * 0.38), g.lineTo(cx + r * 0.18, cy + r * 0.38), g.stroke();
  }

  anchor(name) {
    const r = Math.min(this.width, this.height) * 0.3;
    return { x: this.width / 2, y: this.height * 0.6 - (name === 'head' ? r : 0) };
  }

  bounds() {
    const r = Math.min(this.width, this.height) * 0.3;
    return { x: this.width / 2 - r, y: this.height * 0.6 - r, w: r * 2, h: r * 2 };
  }

  resize(width, height, dpr = this.dpr) {
    this.width = width;
    this.height = height;
    this.dpr = Math.min(dpr, 2);
    this.canvas.width = Math.round(width * this.dpr);
    this.canvas.height = Math.round(height * this.dpr);
    this.g.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
  }

  dispose() { this.canvas.remove(); }
}
