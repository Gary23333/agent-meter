// Motion channels and state blending. A "motion spec" is plain data:
//   { pose: {slot: {pos, rot, scl, glow}}, channels: [{t, p, k, a, f, ph, o, fixed}], ... }
// Rotations are degrees, `scl` multiplies, everything else adds on top of the node's rest transform.

import { TAU, clamp, fract, noise1, smoothstep } from './util.js';

export const identity = () => ({ pos: [0, 0, 0], rot: [0, 0, 0], scl: [1, 1, 1], glow: 1 });

const AXIS = { x: 0, y: 1, z: 2 };

function wave(kind, f, t, ph) {
  switch (kind) {
    case 'abs': return Math.abs(Math.sin(Math.PI * f * t + ph));
    case 'saw': return fract(f * t + ph / TAU) * 2 - 1;
    case 'pulse': return Math.pow(0.5 + 0.5 * Math.sin(TAU * f * t + ph), 3);
    case 'noise': return noise1(t * f + ph);
    case 'once': return smoothstep(clamp(t * f, 0, 1));
    case 'sine':
    case 'squash':
    default: return Math.sin(TAU * f * t + ph);
  }
}

/** How strongly intensity (0..1) scales amplitude: 0.5 is neutral, 1 is about 45 % more. */
export const amplitudeScale = (intensity) => 0.55 + 0.9 * clamp(intensity ?? 0.5, 0, 1);

function slotOf(out, name) {
  return out[name] || (out[name] = identity());
}

/** Adds the spec's pose and channels at time `t` into `out` (slot -> transform). */
export function evaluate(spec, t, intensity, out = {}) {
  if (!spec) return out;
  for (const [slot, pose] of Object.entries(spec.pose || {})) {
    const o = slotOf(out, slot);
    if (pose.pos) for (let i = 0; i < 3; i++) o.pos[i] += pose.pos[i] || 0;
    if (pose.rot) for (let i = 0; i < 3; i++) o.rot[i] += pose.rot[i] || 0;
    if (pose.scl) for (let i = 0; i < 3; i++) o.scl[i] *= pose.scl[i] ?? 1;
    if (pose.glow != null) o.glow *= pose.glow;
  }
  const k = amplitudeScale(intensity);
  for (const ch of spec.channels || []) {
    const o = slotOf(out, ch.t);
    const amp = (ch.a ?? 1) * (ch.fixed ? 1 : k);
    const v = (ch.o ?? 0) + amp * wave(ch.k || 'sine', ch.f ?? 1, t, ch.ph ?? 0);
    if (ch.k === 'squash') {
      // Volume-preserving squash and stretch: taller means thinner.
      const s = amp * wave('sine', ch.f ?? 1, t, ch.ph ?? 0);
      o.scl[0] *= 1 - 0.5 * s;
      o.scl[1] *= 1 + s;
      o.scl[2] *= 1 - 0.5 * s;
      continue;
    }
    const p = ch.p || 'pos.y';
    if (p === 'glow') { o.glow *= 1 + v; continue; }
    if (p === 'scl') { for (let i = 0; i < 3; i++) o.scl[i] *= 1 + v; continue; }
    const [group, axis] = p.split('.');
    const index = AXIS[axis];
    if (index == null) continue;
    if (group === 'scl') o.scl[index] *= 1 + v;
    else if (group === 'pos' || group === 'rot') o[group][index] += v;
  }
  return out;
}

/** Cross-fades between the specs of consecutive animations; every layer runs on its own clock. */
export class Blender {
  constructor(fade = 0.3) {
    this.fade = fade;
    this.layers = [];
  }

  get current() {
    return this.layers.length ? this.layers[this.layers.length - 1].name : null;
  }

  /** Makes `name` the top layer. Re-setting the same name only swaps its spec unless `restart`. */
  set(name, spec, restart = false) {
    const top = this.layers[this.layers.length - 1];
    if (top && top.name === name && !restart) { top.spec = spec; return; }
    for (const layer of this.layers) layer.target = 0;
    this.layers.push({ name, spec, w: this.layers.length ? 0 : 1, target: 1, clock: 0 });
  }

  step(dt) {
    const rate = dt / Math.max(this.fade, 1e-3);
    for (const layer of this.layers) {
      layer.w += clamp(layer.target - layer.w, -rate, rate);
      layer.clock += dt;
    }
    this.layers = this.layers.filter((l) => l.target > 0 || l.w > 1e-3);
  }

  /** Jumps to a settled state at time `t` (contact sheets, tests). */
  seek(t) {
    this.layers = this.layers.filter((l) => l.target > 0);
    for (const layer of this.layers) { layer.w = 1; layer.clock = t; }
  }

  /** Weighted mean of every live layer; a layer that does not touch a slot counts as identity there. */
  evaluate(intensity) {
    const total = this.layers.reduce((sum, l) => sum + l.w, 0);
    if (total <= 0) return {};
    const parts = this.layers.map((l) => ({ w: l.w / total, part: evaluate(l.spec, l.clock, intensity, {}) }));
    const rest = identity();
    const slots = new Set(parts.flatMap((p) => Object.keys(p.part)));
    const mixed = {};
    for (const slot of slots) {
      const m = { pos: [0, 0, 0], rot: [0, 0, 0], scl: [0, 0, 0], glow: 0 };
      for (const { w, part } of parts) {
        const v = part[slot] || rest;
        for (let i = 0; i < 3; i++) { m.pos[i] += v.pos[i] * w; m.rot[i] += v.rot[i] * w; m.scl[i] += v.scl[i] * w; }
        m.glow += v.glow * w;
      }
      mixed[slot] = m;
    }
    return mixed;
  }
}

/** Mirror helpers for authoring symmetric limbs: right is authored, left is derived. */
const MIRROR_PROPS = new Set(['rot.y', 'rot.z', 'pos.x']);

export function mirrorChannel(ch, side, alt = false) {
  const out = { ...ch, t: ch.t + side };
  if (side === 'L' && MIRROR_PROPS.has(ch.p)) {
    out.a = -(ch.a ?? 1);
    if (ch.o != null) out.o = -ch.o;
  }
  if (side === 'R' && alt) out.ph = (ch.ph ?? 0) + Math.PI;
  return out;
}

export function mirrorPose(pose) {
  const out = { ...pose };
  if (pose.rot) out.rot = [pose.rot[0], -pose.rot[1], -pose.rot[2]];
  if (pose.pos) out.pos = [-pose.pos[0], pose.pos[1], pose.pos[2]];
  return out;
}
