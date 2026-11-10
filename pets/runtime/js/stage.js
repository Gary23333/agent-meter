// The stage ties a renderer, the Director, the particle layer, the bubble and the HUD together and runs
// the frame loop with a per-state frame-rate governor.

import { Director } from './director.js';
import { BubbleUI } from './bubble.js';
import { HudUI } from './hud.js';
import { FxLayer } from './fx.js';
import { applyThemeVars, DEFAULT_THEME } from './theme.js';
import { fitStage } from './util.js';

const RECT_INTERVAL = 0.4;
const HUD_HEIGHT = 34;

export class Stage {
  constructor({ root, petEl, fxCanvas, bubbleEl, hudEl, host, model, renderer, params }) {
    this.root = root;
    this.petEl = petEl;
    this.host = host;
    this.model = model;
    this.renderer = renderer;
    this.scale = params.scale || 1;
    this.mode = params.still ? 'fill' : params.embed ? 'embed' : 'window';
    this.themeId = params.theme || DEFAULT_THEME;
    this.scheme = params.scheme || 'light';
    this.visible = true;
    this.t0 = performance.now();
    this.lastTs = 0;
    this.lastRects = '';
    this.lastRectAt = 0;
    this.hoverSince = 0;
    this.fps = 20;
    this.director = new Director(model, { seed: params.seed || 7, now: 0 });
    this.fx = new FxLayer(fxCanvas, params.seed || 5);
    this.bubble = new BubbleUI(bubbleEl, {
      onAction: (b) => this.host.post({ type: 'action', id: b.id, action: b.action }),
      onShown: (b) => this.host.post({ type: 'bubble-shown', id: b.id }),
    });
    this.hud = new HudUI(hudEl);
    this.hud.setMode(params.hud || 'pill');
    this.view = null;
    this.setTheme(this.themeId, this.scheme);
    this.director.setPrefs({ reduceMotion: Boolean(params.reduceMotion), calm: Boolean(params.calm) });
    this.layout();
    window.addEventListener('resize', () => this.layout());
    this.loop = this.loop.bind(this);
  }

  get now() {
    return (performance.now() - this.t0) / 1000;
  }

  start() {
    requestAnimationFrame(this.loop);
  }

  setTheme(id, scheme = this.scheme) {
    this.themeId = id;
    this.scheme = scheme;
    this.tokens = applyThemeVars(this.root, id, scheme);
    this.fx.setTokens(this.tokens);
    if (this.renderer.setTokens) this.renderer.setTokens(this.tokens);
  }

  layout() {
    const W = this.root.clientWidth || window.innerWidth;
    const H = this.root.clientHeight || window.innerHeight;
    const dpr = window.devicePixelRatio || 2;
    const st = this.model.manifest.stage || { width: 240, height: 260 };
    const hudH = this.hud.mode === 'off' ? 0 : HUD_HEIGHT;
    let w = st.width * this.scale, h = st.height * this.scale;
    const fit = fitStage({ W, H, w, h, hudH, mode: this.mode });
    w *= fit; h *= fit;
    this.petRect = { x: (W - w) / 2, y: H - hudH - h, w, h };
    Object.assign(this.petEl.style, { left: `${this.petRect.x}px`, top: `${this.petRect.y}px`, width: `${w}px`, height: `${h}px` });
    this.renderer.resize(w, h, dpr);
    this.fx.resize(W, H, Math.min(dpr, 2));
    this.rootSize = { w: W, h: H };
  }

  setPrefs(p) {
    if (p.hud) { this.hud.setMode(p.hud); this.layout(); }
    if (p.scale && p.scale !== this.scale) { this.scale = p.scale; this.layout(); }
    if ('effects' in p) this.fx.setEnabled(p.effects !== false);
    const dp = {};
    for (const k of ['calm', 'reduceMotion', 'chatter', 'followCursor', 'lowPower']) if (k in p) dp[k] = p[k];
    this.director.setPrefs(dp);
    if (p.reduceMotion) this.fx.setEnabled(false);
  }

  receive(msg) {
    const now = this.now;
    switch (msg.type) {
      case 'frame': this.director.setFrame(msg.frame, now); break;
      case 'say': this.director.say(msg.bubble); break;
      case 'prefs': this.setPrefs(msg.prefs || {}); break;
      case 'theme': this.setTheme(msg.id, msg.scheme || this.scheme); break;
      case 'pointer': this.pointer(msg, now); break;
      case 'cursor': this.cursor(msg); break;
      case 'drag': if (msg.phase === 'start') this.director.dragStart(); else this.director.dragEnd(now); break;
      case 'local': if (msg.kind === 'refresh') this.director.refresh(now); else if (msg.kind === 'photo') this.director.photo(now); break;
      case 'visibility': this.visible = msg.visible !== false; break;
      default: break;
    }
  }

  // ---- input (already hit-tested by the host when native)

  hit(x, y) {
    if (this.bubble.hit(x, y)) return 'bubble';
    const hud = this.hud.rect();
    if (hud && x >= hud.x && x <= hud.x + hud.w && y >= hud.y && y <= hud.y + hud.h) return 'hud';
    const b = this.renderer.bounds();
    const px = this.petRect.x + b.x, py = this.petRect.y + b.y;
    if (x >= px && x <= px + b.w && y >= py && y <= py + b.h) return 'pet';
    return null;
  }

  pointer(m, now) {
    const hit = m.x == null ? null : this.hit(m.x, m.y);
    switch (m.ev) {
      case 'move':
        this.bubble.setHovered(hit === 'bubble');
        this.hud.setExpanded(hit === 'hud');
        if (hit === 'pet') {
          if (!this.hoverSince) this.hoverSince = now;
          if (now - this.hoverSince > 1.1) this.director.petStart();
        } else { this.hoverSince = 0; this.director.petEnd(); }
        break;
      case 'leave':
        this.hoverSince = 0;
        this.director.petEnd();
        this.bubble.setHovered(false);
        this.hud.setExpanded(false);
        break;
      case 'click':
        if (hit === 'bubble') {
          const b = this.bubble.click(now);
          this.host.post({ type: 'bubble-click', id: b && b.id, action: b && b.action });
        } else if (hit === 'hud') {
          this.host.post({ type: 'hud-click' });
        } else if (hit === 'pet') {
          this.director.poke(now);
          this.host.post({ type: 'pet-click' });
        }
        break;
      case 'dblclick':
        if (hit === 'pet') { this.director.refresh(now); this.host.post({ type: 'refresh-request' }); }
        break;
      case 'right':
        this.host.post({ type: 'context', x: m.x, y: m.y, hit });
        break;
      default: break;
    }
  }

  cursor(m) {
    if (m.x == null) { this.director.setCursor(null); return; }
    const head = this.renderer.anchor('head');
    const dx = (m.x - (this.petRect.x + head.x)) / 220, dy = (m.y - (this.petRect.y + head.y)) / 220;
    this.director.setCursor(Math.max(-1, Math.min(1, dx)), Math.max(-1, Math.min(1, -dy)));
  }

  // ---- loop

  loop(ts) {
    requestAnimationFrame(this.loop);
    if (!this.visible) return;
    const interval = 1000 / this.fps;
    if (this.lastTs && ts - this.lastTs < interval - 2) return;
    const dt = this.lastTs ? Math.min(0.1, (ts - this.lastTs) / 1000) : 0.016;
    this.lastTs = ts;
    this.step(dt, this.now);
  }

  /** One pass of the loop body. It also runs without an animation frame: a hidden window gets none. */
  step(dt, now) {
    const view = this.director.update(dt, now);
    this.view = view;
    this.fps = view.fps;
    for (const b of this.director.drainBubbles()) this.bubble.push(b);
    this.renderer.setView(view);
    this.renderer.advance(dt);
    this.renderer.render();

    this.fx.setEmitters(view.fx, view.layerKey);
    const anchor = (name) => { const a = this.renderer.anchor(name); return { x: a.x + this.petRect.x, y: a.y + this.petRect.y }; };
    this.fx.update(dt, anchor);
    if (this.fx.active() || this.fxWasActive) this.fx.draw();
    this.fxWasActive = this.fx.active();

    this.bubble.update(now);
    if (this.bubble.current) {
      const b = this.renderer.bounds();
      this.bubble.place(this.rootSize.w, this.petRect.y + b.y, this.petRect.x + b.x + b.w / 2);
    }
    const hudModel = this.director.hud(now);
    hudModel.baseTime = this.director.frame ? this.director.frame.generated_at + (now - this.director.frameLocal) : 0;
    this.hud.update(hudModel, now);
    this.reportRects(now);
  }

  /**
   * The pet and its particles as a PNG data URL, for screenshots of a window that is not on screen (and so gets
   * no animation frames). `settle` seconds of animation are played first so a state change has finished blending.
   */
  capture({ settle = 0.8 } = {}) {
    // A hidden page never hears "resize": measure again, so the picture matches the stage as it is now.
    this.layout();
    const steps = Math.max(1, Math.round(settle * 30));
    for (let i = 0; i < steps; i++) this.step(1 / 30, this.now);
    const dpr = Math.min(window.devicePixelRatio || 2, 2);
    const out = document.createElement('canvas');
    out.width = Math.max(1, Math.round(this.rootSize.w * dpr));
    out.height = Math.max(1, Math.round(this.rootSize.h * dpr));
    const g = out.getContext('2d');
    const r = this.petRect;
    g.drawImage(this.renderer.canvas, r.x * dpr, r.y * dpr, r.w * dpr, r.h * dpr);
    g.drawImage(this.fx.canvas, 0, 0, out.width, out.height);
    return out.toDataURL('image/png');
  }

  reportRects(now) {
    if (now - this.lastRectAt < RECT_INTERVAL) return;
    this.lastRectAt = now;
    const b = this.renderer.bounds();
    const rects = [{ kind: 'pet', x: this.petRect.x + b.x, y: this.petRect.y + b.y, w: b.w, h: b.h }];
    const bubble = this.bubble.rect();
    if (bubble) rects.push({ kind: 'bubble', ...bubble });
    const hud = this.hud.rect();
    if (hud) rects.push({ kind: 'hud', ...hud });
    const round = (r) => ({ ...r, x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.w), h: Math.round(r.h) });
    const payload = JSON.stringify(rects.map(round));
    if (payload !== this.lastRects) {
      this.lastRects = payload;
      this.host.post({ type: 'rects', rects: JSON.parse(payload), size: this.rootSize });
    }
  }
}
