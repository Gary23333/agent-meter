// Sprite-sheet renderer: each state is a strip of frames (typically produced by an image model or drawn
// as pixel art). The recipe library's root-level motion is layered on top so short strips still feel alive.

import { Blender } from './anim.js';
import { DEG } from './util.js';

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.decoding = 'async';
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error(`cannot load ${url}`));
    image.src = url;
  });
}

export class SpriteRenderer {
  constructor(container, model, { width, height, dpr = 2, baseUrl, seed = 3 }) {
    this.container = container;
    this.model = model;
    this.sprite = model.sprite;
    this.width = width;
    this.height = height;
    this.dpr = Math.min(dpr, 2);
    this.baseUrl = baseUrl;
    this.images = new Map();
    this.clock = 0;
    this.layerKey = null;
    this.view = { animation: 'idle', intensity: 0.5, desaturate: 0 };
    this.stripName = 'idle';
    this.blender = new Blender(0.22);
  }

  async init() {
    const canvas = document.createElement('canvas');
    Object.assign(canvas.style, { position: 'absolute', left: '0', top: '0', width: '100%', height: '100%', display: 'block' });
    if (this.sprite.pixelated) canvas.style.imageRendering = 'pixelated';
    this.container.prepend(canvas);
    this.canvas = canvas;
    this.g = canvas.getContext('2d');
    this.resize(this.width, this.height, this.dpr);
    const urls = new Set(Object.values(this.sprite.states).map((s) => s.image));
    const loaded = await Promise.all([...urls].map(async (url) => [url, await loadImage(new URL(url, this.baseUrl).href).catch(() => null)]));
    for (const [url, image] of loaded) if (image) this.images.set(url, image);
    if (!this.images.size) throw new Error('no sprite images could be loaded');
  }

  setTokens() {}

  setView(view) {
    this.view = view;
    if (view.layerKey !== this.layerKey) {
      this.layerKey = view.layerKey;
      this.stripName = this.model.has(view.animation) ? view.animation : 'idle';
      this.clock = 0;
      this.blender.set(view.animation, this.model.spec(this.stripName), true);
    }
    this.canvas.style.filter = view.desaturate ? `grayscale(${view.desaturate})` : '';
  }

  advance(dt) {
    this.clock += dt;
    this.blender.step(dt);
  }

  seek(t) {
    this.clock = t;
    this.blender.seek(t);
  }

  frameIndex() {
    const strip = this.sprite.states[this.stripName] || this.sprite.states.idle;
    const n = Math.max(1, strip.frames || 1);
    const raw = Math.floor(this.clock * (strip.fps ?? 8));
    return strip.loop === false ? Math.min(n - 1, raw) : raw % n;
  }

  layout() {
    const f = this.sprite.frame;
    // Leave headroom above the sprite: hops and celebrations lift it by up to a fifth of its height.
    let scale = Math.min(this.width / f.width, (this.height * 0.78) / f.height);
    if (this.sprite.pixelated) scale = Math.max(1, Math.floor(scale * this.dpr)) / this.dpr;
    const ground = (this.model.manifest.stage && this.model.manifest.stage.ground) ?? 0.95;
    return { scale, px: this.width / 2, py: this.height * ground, w: f.width * scale, h: f.height * scale };
  }

  render() {
    const g = this.g;
    g.clearRect(0, 0, this.width, this.height);
    const strip = this.sprite.states[this.stripName] || this.sprite.states.idle;
    const image = this.images.get(strip.image) || [...this.images.values()][0];
    if (!image) return;
    const f = this.sprite.frame;
    const cols = strip.cols || strip.frames || 1;
    const index = (strip.start || 0) + this.frameIndex();
    const sx = (index % cols) * f.width, sy = (strip.row || 0) * f.height + Math.floor(index / cols) * f.height;
    const lay = this.layout();
    const pose = this.blender.evaluate(this.view.intensity);
    const root = pose.root || { pos: [0, 0, 0], rot: [0, 0, 0], scl: [1, 1, 1] };
    const unit = lay.h / 1.5;
    g.imageSmoothingEnabled = !this.sprite.pixelated;
    g.imageSmoothingQuality = 'high';
    g.save();
    g.translate(lay.px + root.pos[0] * unit, lay.py - root.pos[1] * unit);
    g.rotate(-root.rot[2] * DEG);
    g.scale(root.scl[0], root.scl[1]);
    const pivot = this.sprite.pivot || { x: 0.5, y: 1 };
    g.drawImage(image, sx, sy, f.width, f.height, -lay.w * pivot.x, -lay.h * pivot.y, lay.w, lay.h);
    g.restore();
  }

  anchor(name) {
    const lay = this.layout();
    const a = (this.sprite.anchors || {})[name] || { head: { x: 0.5, y: 0.2 }, body: { x: 0.5, y: 0.55 }, prop: { x: 0.8, y: 0.6 }, root: { x: 0.5, y: 1 } }[name] || { x: 0.5, y: 0.5 };
    return { x: lay.px - lay.w / 2 + a.x * lay.w, y: lay.py - lay.h + a.y * lay.h };
  }

  bounds() {
    const lay = this.layout();
    return { x: lay.px - lay.w / 2, y: lay.py - lay.h, w: lay.w, h: lay.h };
  }

  resize(width, height, dpr = this.dpr) {
    this.width = width;
    this.height = height;
    this.dpr = Math.min(dpr, 2);
    this.canvas.width = Math.round(width * this.dpr);
    this.canvas.height = Math.round(height * this.dpr);
    this.g.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
  }

  dispose() {
    this.canvas.remove();
  }
}
