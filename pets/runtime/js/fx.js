// Particle overlay shared by every renderer: a transparent 2-D canvas above the avatar. Glyphs are drawn
// as vector paths (not emoji) so they look the same on every machine and tint with the theme.

import { TAU, clamp, mulberry32 } from './util.js';

const MAX_PARTICLES = 140;
const GRAVITY = 240;

const star = (g, r, inner = 0.38) => {
  g.beginPath();
  for (let i = 0; i < 8; i++) {
    const rad = i % 2 ? r * inner : r, a = (Math.PI * i) / 4 - Math.PI / 2;
    g.lineTo(Math.cos(a) * rad, Math.sin(a) * rad);
  }
  g.closePath();
};

const heart = (g, s) => {
  g.beginPath();
  g.moveTo(0, s * 0.9);
  g.bezierCurveTo(-s * 1.4, -s * 0.1, -s * 0.9, -s * 1.0, 0, -s * 0.4);
  g.bezierCurveTo(s * 0.9, -s * 1.0, s * 1.4, -s * 0.1, 0, s * 0.9);
  g.closePath();
};

const drop = (g, s) => {
  g.beginPath();
  g.moveTo(0, -s * 1.3);
  g.bezierCurveTo(s * 1.0, -s * 0.1, s * 0.9, s * 0.9, 0, s * 0.9);
  g.bezierCurveTo(-s * 0.9, s * 0.9, -s * 1.0, -s * 0.1, 0, -s * 1.3);
  g.closePath();
};

const glyph = (g, text, size, color, stroke) => {
  g.font = `800 ${size}px ui-rounded, "SF Pro Rounded", system-ui, sans-serif`;
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  if (stroke) { g.lineWidth = 3; g.strokeStyle = stroke; g.strokeText(text, 0, 0); }
  g.fillStyle = color;
  g.fillText(text, 0, 0);
};

const range = (r, lo, hi) => lo + r() * (hi - lo);
const easeOutBack = (t) => { const c = 1.70158; return 1 + (c + 1) * Math.pow(t - 1, 3) + c * Math.pow(t - 1, 2); };

// spawn(rand, colors) -> particle fields; draw(g, p, u, colors) paints at the particle's origin.
const KINDS = {
  zzz: {
    spawn: (r) => ({ x: range(r, 6, 14), y: -4, vx: range(r, 10, 18), vy: range(r, -30, -22), size: range(r, 12, 17), life: 2.4 }),
    draw: (g, p, u, c) => { g.rotate(Math.sin(u * 5) * 0.15); glyph(g, 'Z', p.size * (0.7 + 0.7 * u), c.accent2, c.paperA); },
  },
  hearts: {
    spawn: (r) => ({ x: range(r, -16, 16), y: range(r, -4, 6), vx: range(r, -6, 6), vy: range(r, -40, -28), size: range(r, 6, 10), life: 1.7 }),
    draw: (g, p, u) => { g.translate(Math.sin(u * 9 + p.seed) * 4, 0); heart(g, p.size); g.fillStyle = '#ff5c8a'; g.fill(); },
  },
  sparkles: {
    spawn: (r) => ({ x: range(r, -22, 22), y: range(r, -18, 18), vx: 0, vy: range(r, -8, 4), size: range(r, 4, 8), life: 0.8 }),
    draw: (g, p, u, c) => { g.rotate(u * 1.5); star(g, p.size * Math.sin(Math.PI * clamp(u, 0, 1)) * 1.3 + 0.5); g.fillStyle = p.seed > 0.5 ? '#ffffff' : c.accent2; g.fill(); },
  },
  confetti: {
    spawn: (r, c) => ({ x: range(r, -34, 34), y: range(r, -20, 0), vx: range(r, -60, 60), vy: range(r, -150, -80), ay: 1, size: range(r, 4, 7),
      life: 1.9, spin: range(r, -8, 8), color: [c.accent1, c.accent2, '#ffd04a', '#5eead4', '#ff5c8a'][Math.floor(r() * 5)] }),
    draw: (g, p, u) => { g.rotate(p.seed * 6 + u * p.spin); g.scale(1, Math.cos(u * 14 + p.seed * 9)); g.fillStyle = p.color; g.fillRect(-p.size / 2, -p.size, p.size, p.size * 2); },
  },
  sweat: {
    spawn: (r) => ({ x: range(r, 16, 26), y: range(r, -14, -4), vx: range(r, 2, 8), vy: range(r, 2, 10), ay: 0.35, size: range(r, 4, 6), life: 1.2 }),
    draw: (g, p) => { drop(g, p.size); g.fillStyle = '#7fd6ff'; g.fill(); g.fillStyle = 'rgba(255,255,255,.7)'; g.beginPath(); g.arc(-p.size * 0.3, 0, p.size * 0.2, 0, TAU); g.fill(); },
  },
  question: {
    spawn: (r) => ({ x: range(r, -6, 18), y: -6, vx: range(r, -4, 8), vy: range(r, -22, -14), size: 20, life: 2.0 }),
    draw: (g, p, u, c) => { g.rotate(Math.sin(u * 6) * 0.2); glyph(g, '?', p.size, c.accent2, c.paperA); },
  },
  exclaim: {
    spawn: (r) => ({ x: range(r, -4, 20), y: -10, vx: range(r, -2, 6), vy: range(r, -16, -8), size: 24, life: 1.3 }),
    draw: (g, p, u, c) => { const s = u < 0.2 ? easeOutBack(u / 0.2) : 1; g.scale(s, s); glyph(g, '!', p.size, c.crit, c.paperA); },
  },
  notes: {
    spawn: (r) => ({ x: range(r, -22, 22), y: range(r, -8, 4), vx: range(r, -8, 8), vy: range(r, -26, -16), size: range(r, 7, 10), life: 2.1 }),
    draw: (g, p, u, c) => {
      g.translate(Math.sin(u * 7 + p.seed) * 4, 0);
      g.fillStyle = g.strokeStyle = c.accent1;
      g.beginPath(); g.ellipse(0, 0, p.size * 0.55, p.size * 0.4, -0.4, 0, TAU); g.fill();
      g.lineWidth = 2; g.beginPath(); g.moveTo(p.size * 0.45, -p.size * 0.1); g.lineTo(p.size * 0.45, -p.size * 1.5); g.quadraticCurveTo(p.size * 1.2, -p.size * 1.2, p.size * 0.9, -p.size * 0.6); g.stroke();
    },
  },
  coins: {
    spawn: (r) => ({ x: range(r, 30, 56), y: range(r, -58, -30), vx: 0, vy: 0, size: range(r, 5, 7), life: 0.85, homing: true }),
    draw: (g, p, u) => { const s = 1 - u * 0.7; g.scale(s, s); g.fillStyle = '#ffd04a'; g.beginPath(); g.arc(0, 0, p.size, 0, TAU); g.fill(); g.strokeStyle = '#d99a1a'; g.lineWidth = 1.5; g.stroke(); },
  },
  stars: {
    spawn: (r) => ({ x: 0, y: -6, vx: 0, vy: 0, size: range(r, 5, 7), life: 1.8, orbit: r() * TAU }),
    draw: (g, p, u) => { const a = p.orbit + u * TAU * 1.4; g.translate(Math.cos(a) * 24, Math.sin(a) * 8); g.rotate(u * 8); star(g, p.size); g.fillStyle = '#ffd04a'; g.fill(); },
  },
  steam: {
    spawn: (r) => ({ x: range(r, -16, 16), y: range(r, -14, -4), vx: range(r, -6, 6), vy: range(r, -30, -18), size: range(r, 5, 8), life: 1.4 }),
    draw: (g, p, u) => { g.globalAlpha *= 0.45; g.fillStyle = '#ffffff'; g.beginPath(); g.arc(0, 0, p.size * (1 + u * 1.4), 0, TAU); g.fill(); },
  },
  bolt: {
    spawn: (r) => ({ x: range(r, -36, 36), y: range(r, -30, 10), vx: 0, vy: 0, size: range(r, 9, 14), life: 0.4 }),
    draw: (g, p) => { g.beginPath(); g.moveTo(p.size * 0.2, -p.size); g.lineTo(-p.size * 0.5, 0.1); g.lineTo(0, 0.1); g.lineTo(-p.size * 0.2, p.size); g.lineTo(p.size * 0.5, -0.2); g.lineTo(0, -0.2); g.closePath(); g.fillStyle = '#ffe14a'; g.fill(); },
  },
  paint: {
    spawn: (r, c) => ({ x: range(r, -6, 6), y: range(r, -6, 6), vx: range(r, -50, 50), vy: range(r, -70, -20), ay: 1, size: range(r, 3, 6), life: 0.9,
      color: [c.accent1, c.accent2, '#ffd04a', '#5eead4', '#ff5c8a'][Math.floor(r() * 5)] }),
    draw: (g, p) => { g.fillStyle = p.color; g.beginPath(); g.arc(0, 0, p.size, 0, TAU); g.fill(); },
  },
  dust: {
    spawn: (r) => ({ x: range(r, -20, 20), y: 0, vx: range(r, -40, 40), vy: range(r, -10, -2), size: range(r, 3, 6), life: 0.6 }),
    draw: (g, p, u) => { g.globalAlpha *= 0.5; g.fillStyle = '#b9b3c9'; g.beginPath(); g.arc(0, 0, p.size * (1 + u), 0, TAU); g.fill(); },
  },
};

export class FxLayer {
  constructor(canvas, seed = 5) {
    this.canvas = canvas;
    this.g = canvas.getContext('2d');
    this.rand = mulberry32(seed);
    this.particles = [];
    this.emitters = [];
    this.acc = new Map();
    this.key = null;
    this.flash = 0;
    this.width = canvas.width;
    this.height = canvas.height;
    this.colors = { accent1: '#7c6cff', accent2: '#9447d6', crit: '#ff453a', paperA: 'rgba(255,255,255,.85)' };
    this.enabled = true;
  }

  resize(width, height, dpr) {
    this.width = width;
    this.height = height;
    this.canvas.width = Math.round(width * dpr);
    this.canvas.height = Math.round(height * dpr);
    this.g.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  setTokens(tokens) {
    this.colors = { accent1: tokens.accent1, accent2: tokens.accent2, crit: tokens.crit, paperA: tokens.dark ? 'rgba(20,20,30,.8)' : 'rgba(255,255,255,.85)' };
  }

  /** Continuous emitters for the active animation. `key` changes whenever the animation restarts. */
  setEmitters(list, key) {
    if (key === this.key) return;
    this.key = key;
    this.emitters = this.enabled ? list : [];
    this.acc.clear();
    for (const e of this.emitters) {
      if (e.kind === 'flash') this.flash = 1;
      if (e.kind === 'confetti') this.pending = { kind: 'confetti', at: e.at, count: 14 };
    }
  }

  setEnabled(on) {
    this.enabled = on;
    if (!on) { this.emitters = []; this.particles.length = 0; }
  }

  spawn(kind, at, anchor) {
    const def = KINDS[kind];
    if (!def || this.particles.length >= MAX_PARTICLES) return;
    const p = def.spawn(this.rand, this.colors);
    p.kind = kind;
    p.ox = anchor.x;
    p.oy = anchor.y;
    p.age = 0;
    p.seed = this.rand();
    p.px = p.x;
    p.py = p.y;
    this.particles.push(p);
  }

  update(dt, anchorFn) {
    if (this.pending) {
      const { kind, at, count } = this.pending;
      this.pending = null;
      const a = anchorFn(at);
      for (let i = 0; i < count; i++) this.spawn(kind, at, a);
    }
    for (const e of this.emitters) {
      if (!KINDS[e.kind]) continue;
      const id = `${e.kind}@${e.at}`;
      const n = (this.acc.get(id) || 0) + (e.rate || 1) * dt;
      const whole = Math.floor(n);
      this.acc.set(id, n - whole);
      if (whole > 0) {
        const a = anchorFn(e.at);
        for (let i = 0; i < Math.min(whole, 4); i++) this.spawn(e.kind, e.at, a);
      }
    }
    for (const p of this.particles) {
      p.age += dt;
      if (p.homing) continue;
      p.vy += (p.ay || 0) * GRAVITY * dt;
      p.px += p.vx * dt;
      p.py += p.vy * dt;
    }
    this.particles = this.particles.filter((p) => p.age < p.life);
    this.flash = Math.max(0, this.flash - dt * 2.4);
  }

  active() {
    return this.particles.length > 0 || this.emitters.length > 0 || this.flash > 0;
  }

  draw() {
    const g = this.g;
    g.clearRect(0, 0, this.width, this.height);
    if (this.flash > 0) {
      g.fillStyle = `rgba(255,255,255,${(this.flash * 0.55).toFixed(3)})`;
      g.fillRect(0, 0, this.width, this.height);
    }
    for (const p of this.particles) {
      const u = p.age / p.life;
      const fadeIn = clamp(u / 0.12, 0, 1), fadeOut = clamp((1 - u) / 0.35, 0, 1);
      g.save();
      g.globalAlpha = Math.min(fadeIn, fadeOut);
      let x = p.ox + p.px, y = p.oy + p.py;
      if (p.homing) { const e = u * u * (3 - 2 * u); x = p.ox + p.x * (1 - e) + 6 * e; y = p.oy + p.y * (1 - e) - 4 * e; }
      g.translate(x, y);
      KINDS[p.kind].draw(g, p, u, this.colors);
      g.restore();
    }
  }
}
