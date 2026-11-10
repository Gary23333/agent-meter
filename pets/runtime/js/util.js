// Small numeric helpers. No DOM, no three.js: usable from Node tests.

export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
export const lerp = (a, b, t) => a + (b - a) * t;
export const smoothstep = (t) => { t = clamp(t, 0, 1); return t * t * (3 - 2 * t); };
export const fract = (v) => v - Math.floor(v);
export const TAU = Math.PI * 2;
export const DEG = Math.PI / 180;

/** Exponential smoothing that is frame-rate independent. */
export const damp = (current, target, lambda, dt) => lerp(current, target, 1 - Math.exp(-lambda * dt));

function hash(n) {
  const s = Math.sin(n * 127.1 + 311.7) * 43758.5453123;
  return s - Math.floor(s);
}

/** Smooth 1-D value noise in [-1, 1]. */
export function noise1(x) {
  const i = Math.floor(x);
  const f = x - i;
  const u = f * f * (3 - 2 * f);
  return lerp(hash(i), hash(i + 1), u) * 2 - 1;
}

/** Deterministic PRNG so contact sheets and tests are reproducible. */
export function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function hexToRgb(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(String(hex).trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function rgbToHex([r, g, b]) {
  const h = (v) => Math.round(clamp(v, 0, 255)).toString(16).padStart(2, '0');
  return `#${h(r)}${h(g)}${h(b)}`;
}

export function mixHex(a, b, t) {
  const x = hexToRgb(a), y = hexToRgb(b);
  if (!x || !y) return a;
  return rgbToHex([lerp(x[0], y[0], t), lerp(x[1], y[1], t), lerp(x[2], y[2], t)]);
}

/** Pulls a colour toward its own grey; used for the offline look. */
export function desaturateHex(hex, amount) {
  const c = hexToRgb(hex);
  if (!c) return hex;
  const g = 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2];
  return rgbToHex([lerp(c[0], g, amount), lerp(c[1], g, amount), lerp(c[2], g, amount)]);
}

export function deepClone(value) {
  return value == null ? value : JSON.parse(JSON.stringify(value));
}

export const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

export function formatCountdown(seconds) {
  const s = Math.floor(seconds);
  if (s <= 0) return '待刷新';
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  if (d >= 3) return `${d}天`;
  if (d >= 1) return h > 0 ? `${d}天${h}时` : `${d}天`;
  if (h >= 1) return `${h}时${m}分`;
  return `${Math.max(m, 1)}分`;
}

/**
 * How much the pet is shrunk (never enlarged) to fit its stage. Modes:
 *   window  the floating desktop window: the top fifth stays free for the speech bubble, the HUD sits underneath
 *   embed   the stage inside the app's tab: a fifth of the height stays free for the bubble, no HUD
 *   fill    a thumbnail: the pet takes the whole stage
 */
export function fitStage({ W, H, w, h, hudH = 0, mode = 'window' }) {
  const room = mode === 'fill' ? H * 0.98 : mode === 'embed' ? H * 0.8 : H * 0.82 - hudH;
  return Math.max(0.05, Math.min(1, W / w, room / h));
}
