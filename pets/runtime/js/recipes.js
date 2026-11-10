// Behaviour recipes: how any rig acts in each state, written against rig *slots* (root, body, head,
// armL/armR, legL/legR, tail, earL/earR, antenna, mouth, gauge, prop). A rig that lacks a slot simply
// ignores the motion aimed at it, so one library animates every character.
//
// Conventions (also in pets/SPEC.md):
//   +Y is up, the character faces +Z (toward the viewer). armL/armR/legL/legR/earL/earR are as seen
//   by the viewer (L is on the left of the screen). Rotations are degrees about the slot node's own
//   origin, which sits at its joint. For armR a positive rot.z lifts the arm outwards and a negative
//   rot.x swings it forward; armL is derived by mirroring, so recipes are written once for the right side.
//   `abs` channels bounce (never below the rest height), `squash` is volume preserving.

import { mirrorChannel, mirrorPose } from './anim.js';

const PI = Math.PI;
const pair = (ch, alt = false) => [mirrorChannel(ch, 'L', alt), mirrorChannel(ch, 'R', alt)];
const pairPose = (base, pose) => ({ [`${base}R`]: pose, [`${base}L`]: mirrorPose(pose) });

export const RECIPES = {
  idle: {
    expression: 'neutral', fps: 20,
    channels: [
      { t: 'body', k: 'squash', a: 0.018, f: 0.33 },
      { t: 'root', p: 'pos.y', k: 'sine', a: 0.012, f: 0.33 },
      { t: 'root', p: 'rot.z', k: 'sine', a: 1.4, f: 0.17 },
      { t: 'head', p: 'rot.y', k: 'noise', a: 7, f: 0.22 },
      { t: 'head', p: 'rot.x', k: 'noise', a: 2.5, f: 0.3, ph: 5 },
      ...pair({ t: 'arm', p: 'rot.z', k: 'sine', a: 3, f: 0.33, o: 2 }),
      { t: 'tail', p: 'rot.y', k: 'sine', a: 16, f: 0.6 },
      ...pair({ t: 'ear', p: 'rot.z', k: 'noise', a: 5, f: 0.4 }),
      { t: 'antenna', p: 'rot.z', k: 'sine', a: 7, f: 0.45 },
      { t: 'gauge', p: 'glow', k: 'sine', a: 0.08, f: 0.4 },
    ],
  },
  working: {
    expression: 'determined', fps: 30, show: ['laptop'], look: { x: 0, y: -0.6 },
    pose: { head: { rot: [16, 0, 0] }, body: { rot: [5, 0, 0] }, ...pairPose('arm', { rot: [-52, 0, 12] }) },
    channels: [
      ...pair({ t: 'arm', p: 'rot.x', k: 'sine', a: 13, f: 3.3 }, true),
      { t: 'head', p: 'rot.x', k: 'sine', a: 2, f: 0.9 },
      { t: 'body', k: 'squash', a: 0.012, f: 1.1 },
      { t: 'tail', p: 'rot.y', k: 'sine', a: 20, f: 1.3 },
      ...pair({ t: 'ear', p: 'rot.z', k: 'noise', a: 6, f: 0.8 }),
      { t: 'antenna', p: 'rot.z', k: 'sine', a: 5, f: 1.2 },
      { t: 'gauge', p: 'glow', k: 'sine', a: 0.1, f: 0.8 },
    ],
    fx: [{ kind: 'sparkles', at: 'prop', rate: 1.1 }],
  },
  busy: {
    expression: 'worried', fps: 30, show: ['laptop'], look: { x: 0, y: -0.6 },
    pose: { head: { rot: [18, 0, 0] }, body: { rot: [7, 0, 0] }, ...pairPose('arm', { rot: [-55, 0, 10] }) },
    channels: [
      ...pair({ t: 'arm', p: 'rot.x', k: 'sine', a: 20, f: 5.4 }, true),
      { t: 'head', p: 'rot.z', k: 'sine', a: 3, f: 4.2 },
      { t: 'head', p: 'rot.x', k: 'sine', a: 3, f: 2.2 },
      { t: 'body', k: 'squash', a: 0.02, f: 2.2 },
      { t: 'root', p: 'pos.x', k: 'noise', a: 0.012, f: 7 },
      { t: 'tail', p: 'rot.y', k: 'sine', a: 28, f: 2.6 },
      { t: 'gauge', p: 'glow', k: 'pulse', a: 0.35, f: 1.6 },
    ],
    fx: [{ kind: 'sweat', at: 'head', rate: 1.3 }, { kind: 'sparkles', at: 'prop', rate: 2.4 }, { kind: 'steam', at: 'head', rate: 0.6 }],
  },
  waiting: {
    expression: 'surprised', fps: 30,
    pose: { armR: { rot: [0, 0, 150] }, armL: { rot: [0, 0, -8] }, head: { rot: [0, 0, 9] } },
    channels: [
      { t: 'armR', p: 'rot.z', k: 'sine', a: 15, f: 2.1 },
      { t: 'root', p: 'rot.z', k: 'sine', a: 2.5, f: 1.05 },
      { t: 'head', p: 'rot.z', k: 'sine', a: 3, f: 1.05 },
      { t: 'root', p: 'pos.y', k: 'abs', a: 0.05, f: 1.05 },
      { t: 'tail', p: 'rot.y', k: 'sine', a: 24, f: 1.8 },
      { t: 'antenna', p: 'rot.z', k: 'sine', a: 12, f: 2.1 },
    ],
    fx: [{ kind: 'exclaim', at: 'head', rate: 0.55 }],
  },
  tired: {
    expression: 'worried', fps: 15,
    pose: {
      root: { pos: [0, -0.03, 0], scl: [1.03, 0.95, 1.03] }, head: { rot: [26, 0, 6] }, body: { rot: [8, 0, 0] },
      ...pairPose('arm', { rot: [0, 0, 9] }), ...pairPose('ear', { rot: [0, 0, -22] }),
      tail: { rot: [0, 0, -20] }, antenna: { rot: [0, 0, -30] }, gauge: { glow: 0.55 },
    },
    channels: [
      { t: 'body', k: 'squash', a: 0.03, f: 0.22 },
      { t: 'head', p: 'rot.x', k: 'sine', a: 3, f: 0.22 },
      { t: 'root', p: 'rot.z', k: 'sine', a: 1.2, f: 0.11 },
      { t: 'tail', p: 'rot.y', k: 'sine', a: 6, f: 0.3 },
    ],
    fx: [{ kind: 'sweat', at: 'head', rate: 0.3 }],
  },
  alarm: {
    expression: 'surprised', fps: 30,
    pose: { ...pairPose('arm', { rot: [0, 0, 155] }), head: { rot: [-6, 0, 0] }, ...pairPose('ear', { rot: [0, 0, 28] }) },
    channels: [
      { t: 'root', p: 'pos.x', k: 'sine', a: 0.025, f: 13 },
      { t: 'root', p: 'pos.y', k: 'abs', a: 0.04, f: 4.5 },
      ...pair({ t: 'arm', p: 'rot.z', k: 'sine', a: 12, f: 8 }, true),
      { t: 'head', p: 'rot.z', k: 'sine', a: 4, f: 11 },
      { t: 'body', k: 'squash', a: 0.04, f: 6 },
      { t: 'gauge', p: 'glow', k: 'pulse', a: 0.9, f: 2.6 },
      { t: 'tail', p: 'rot.y', k: 'sine', a: 30, f: 5 },
    ],
    fx: [{ kind: 'exclaim', at: 'head', rate: 1.6 }, { kind: 'sweat', at: 'head', rate: 1.4 }, { kind: 'bolt', at: 'body', rate: 0.6 }],
  },
  exhausted: {
    expression: 'dizzy', lock: true, fps: 15,
    pose: {
      root: { pos: [0, -0.05, 0], scl: [1.14, 0.78, 1.14] }, head: { rot: [34, 0, 10], pos: [0, -0.04, 0] },
      ...pairPose('arm', { rot: [0, 0, 28] }), ...pairPose('leg', { rot: [0, 0, 18] }),
      tail: { rot: [0, 0, -35] }, ...pairPose('ear', { rot: [0, 0, -38] }), antenna: { rot: [0, 0, -45] }, gauge: { glow: 0 },
    },
    channels: [
      { t: 'body', k: 'squash', a: 0.02, f: 0.2 },
      { t: 'head', p: 'rot.z', k: 'sine', a: 4, f: 0.3 },
    ],
    fx: [{ kind: 'stars', at: 'head', rate: 0.7 }],
  },
  sleeping: {
    expression: 'sleepy', lock: true, fps: 8,
    pose: {
      root: { pos: [0, -0.04, 0], scl: [1.04, 0.94, 1.04] }, head: { rot: [40, 0, 12] }, body: { rot: [10, 0, 0] },
      ...pairPose('arm', { rot: [-8, 0, 6] }), ...pairPose('ear', { rot: [0, 0, -18] }),
      antenna: { rot: [0, 0, -40] }, gauge: { glow: 0.5 },
    },
    channels: [
      { t: 'body', k: 'squash', a: 0.035, f: 0.18 },
      { t: 'head', p: 'rot.x', k: 'sine', a: 2, f: 0.18 },
      { t: 'tail', p: 'rot.y', k: 'sine', a: 4, f: 0.2 },
    ],
    fx: [{ kind: 'zzz', at: 'head', rate: 0.4 }],
  },
  celebrate: {
    expression: 'excited', lock: true, fps: 30, dur: 8,
    pose: { ...pairPose('arm', { rot: [0, 0, 150] }), head: { rot: [-8, 0, 0] } },
    channels: [
      { t: 'root', p: 'pos.y', k: 'abs', a: 0.3, f: 1.1, fixed: true },
      { t: 'body', k: 'squash', a: 0.08, f: 1.1, ph: -PI / 2 },
      { t: 'root', p: 'rot.y', k: 'sine', a: 16, f: 0.55 },
      ...pair({ t: 'arm', p: 'rot.z', k: 'sine', a: 16, f: 2.2 }),
      { t: 'head', p: 'rot.z', k: 'sine', a: 7, f: 1.1 },
      { t: 'tail', p: 'rot.y', k: 'sine', a: 34, f: 3 },
      { t: 'antenna', p: 'rot.z', k: 'sine', a: 14, f: 2.2 },
      { t: 'gauge', p: 'glow', k: 'pulse', a: 0.7, f: 2.2 },
    ],
    fx: [{ kind: 'confetti', at: 'head', rate: 9 }, { kind: 'sparkles', at: 'body', rate: 3 }],
  },
  offline: {
    expression: 'confused', lock: true, fps: 12, show: ['plug'], desaturate: 0.75,
    pose: { head: { rot: [10, 0, 0] }, root: { scl: [1, 0.97, 1] }, ...pairPose('arm', { rot: [0, 0, 10] }), gauge: { glow: 0 } },
    channels: [
      { t: 'head', p: 'rot.z', k: 'sine', a: 9, f: 0.35 },
      { t: 'head', p: 'rot.y', k: 'noise', a: 10, f: 0.3 },
      { t: 'body', k: 'squash', a: 0.015, f: 0.25 },
      { t: 'tail', p: 'rot.y', k: 'sine', a: 5, f: 0.3 },
    ],
    fx: [{ kind: 'question', at: 'head', rate: 0.35 }],
  },
  painting: {
    expression: 'happy', fps: 30, show: ['brush'], look: { x: 0.2, y: -0.2 },
    pose: { armR: { rot: [-66, 0, 26] }, armL: { rot: [0, 0, -8] }, head: { rot: [8, 0, 0] } },
    channels: [
      { t: 'armR', p: 'rot.x', k: 'sine', a: 20, f: 1.5 },
      { t: 'armR', p: 'rot.y', k: 'sine', a: 22, f: 1.0, ph: 1 },
      { t: 'head', p: 'rot.y', k: 'sine', a: 7, f: 0.5 },
      { t: 'body', k: 'squash', a: 0.015, f: 0.9 },
      { t: 'tail', p: 'rot.y', k: 'sine', a: 18, f: 1.1 },
      { t: 'gauge', p: 'glow', k: 'sine', a: 0.1, f: 0.7 },
    ],
    fx: [{ kind: 'paint', at: 'prop', rate: 3 }],
  },
  alert: {
    expression: 'surprised', fps: 24, show: ['sign'],
    pose: { armR: { rot: [-30, 0, 95] }, armL: { rot: [0, 0, -6] }, head: { rot: [0, 0, 6] } },
    channels: [
      { t: 'armR', p: 'rot.z', k: 'sine', a: 9, f: 1.5 },
      { t: 'legR', p: 'rot.x', k: 'abs', a: 16, f: 2.8 },
      { t: 'head', p: 'rot.z', k: 'sine', a: 6, f: 0.75 },
      { t: 'root', p: 'pos.y', k: 'abs', a: 0.03, f: 1.5 },
      { t: 'tail', p: 'rot.y', k: 'sine', a: 20, f: 1.6 },
      { t: 'antenna', p: 'rot.z', k: 'sine', a: 10, f: 1.5 },
      { t: 'gauge', p: 'glow', k: 'pulse', a: 0.5, f: 1.5 },
    ],
    fx: [{ kind: 'exclaim', at: 'head', rate: 0.7 }],
  },
  focus: {
    expression: 'determined', fps: 20, show: ['headphones'],
    pose: { head: { rot: [10, 0, 0] }, ...pairPose('arm', { rot: [-20, 0, 6] }) },
    channels: [
      { t: 'head', p: 'rot.z', k: 'sine', a: 5, f: 0.9 },
      { t: 'body', k: 'squash', a: 0.015, f: 0.9 },
      { t: 'root', p: 'pos.y', k: 'abs', a: 0.014, f: 0.9 },
      { t: 'tail', p: 'rot.y', k: 'sine', a: 10, f: 0.9 },
      ...pair({ t: 'ear', p: 'rot.z', k: 'sine', a: 5, f: 0.9 }),
    ],
    fx: [{ kind: 'notes', at: 'head', rate: 0.8 }],
  },
  excited: {
    expression: 'excited', fps: 30, show: ['crystal'],
    pose: { ...pairPose('arm', { rot: [-10, 0, 60] }) },
    channels: [
      { t: 'root', p: 'pos.y', k: 'abs', a: 0.09, f: 1.7 },
      { t: 'body', k: 'squash', a: 0.05, f: 1.7, ph: -PI / 2 },
      ...pair({ t: 'arm', p: 'rot.z', k: 'sine', a: 14, f: 1.7 }),
      { t: 'head', p: 'rot.z', k: 'sine', a: 5, f: 0.85 },
      { t: 'tail', p: 'rot.y', k: 'sine', a: 28, f: 2.4 },
      { t: 'gauge', p: 'glow', k: 'pulse', a: 0.6, f: 1.7 },
    ],
    fx: [{ kind: 'sparkles', at: 'prop', rate: 2.5 }, { kind: 'sparkles', at: 'head', rate: 1 }],
  },
  confused: {
    expression: 'confused', fps: 20,
    pose: { head: { rot: [0, 0, 14] }, ...pairPose('arm', { rot: [0, 0, 12] }) },
    channels: [
      { t: 'head', p: 'rot.y', k: 'sine', a: 16, f: 0.28 },
      { t: 'head', p: 'rot.z', k: 'sine', a: 5, f: 0.4 },
      { t: 'body', k: 'squash', a: 0.015, f: 0.4 },
      { t: 'tail', p: 'rot.y', k: 'sine', a: 12, f: 0.5 },
      { t: 'antenna', p: 'rot.z', k: 'sine', a: 16, f: 0.8 },
    ],
    fx: [{ kind: 'question', at: 'head', rate: 0.6 }],
  },
  eating: {
    expression: 'happy', fps: 30, dur: 5,
    pose: { head: { rot: [10, 0, 0] }, ...pairPose('arm', { rot: [-40, 0, -6] }) },
    channels: [
      { t: 'mouth', p: 'scl.y', k: 'abs', a: 0.9, f: 3, fixed: true },
      { t: 'body', k: 'squash', a: 0.05, f: 3 },
      { t: 'head', p: 'rot.x', k: 'sine', a: 5, f: 3 },
      ...pair({ t: 'arm', p: 'rot.x', k: 'sine', a: 8, f: 3 }),
      { t: 'tail', p: 'rot.y', k: 'sine', a: 24, f: 2.4 },
    ],
    fx: [{ kind: 'coins', at: 'head', rate: 5 }],
  },
  startle: {
    expression: 'surprised', lock: true, fps: 30, dur: 6,
    pose: { ...pairPose('arm', { rot: [0, 0, 70] }), head: { rot: [-10, 0, 0] }, root: { scl: [0.96, 1.06, 0.96] } },
    channels: [
      { t: 'root', p: 'pos.y', k: 'abs', a: 0.1, f: 2.2 },
      { t: 'root', p: 'pos.x', k: 'sine', a: 0.012, f: 14 },
      { t: 'tail', p: 'rot.y', k: 'sine', a: 20, f: 6 },
      { t: 'antenna', p: 'rot.z', k: 'sine', a: 18, f: 6 },
    ],
    fx: [{ kind: 'exclaim', at: 'head', rate: 1.4 }],
  },
  wave: {
    expression: 'happy', fps: 30, dur: 5,
    pose: { armR: { rot: [0, 0, 140] }, head: { rot: [0, 0, 8] } },
    channels: [
      { t: 'armR', p: 'rot.z', k: 'sine', a: 18, f: 2.4 },
      { t: 'root', p: 'pos.y', k: 'abs', a: 0.04, f: 1.2 },
      { t: 'tail', p: 'rot.y', k: 'sine', a: 26, f: 2.2 },
      { t: 'body', k: 'squash', a: 0.02, f: 1.2 },
    ],
    fx: [{ kind: 'hearts', at: 'head', rate: 0.8 }],
  },
  poke: {
    expression: 'surprised', lock: true, fps: 30, dur: 1.1,
    pose: { ...pairPose('arm', { rot: [0, 0, 40] }) },
    channels: [
      { t: 'root', p: 'pos.y', k: 'abs', a: 0.12, f: 1.6, fixed: true },
      { t: 'body', k: 'squash', a: 0.1, f: 1.6, ph: -PI / 2, fixed: true },
      { t: 'tail', p: 'rot.y', k: 'sine', a: 30, f: 4 },
    ],
    fx: [{ kind: 'sparkles', at: 'head', rate: 5 }],
  },
  pet: {
    expression: 'love', fps: 24,
    pose: { head: { rot: [10, 0, 10] }, root: { scl: [1.02, 0.98, 1.02] } },
    channels: [
      { t: 'body', k: 'squash', a: 0.025, f: 0.8 },
      { t: 'tail', p: 'rot.y', k: 'sine', a: 34, f: 3.2 },
      ...pair({ t: 'ear', p: 'rot.z', k: 'sine', a: 8, f: 1.6 }),
      { t: 'head', p: 'rot.z', k: 'sine', a: 4, f: 0.8 },
      { t: 'antenna', p: 'rot.z', k: 'sine', a: 14, f: 2 },
    ],
    fx: [{ kind: 'hearts', at: 'head', rate: 1.6 }],
  },
  drag: {
    expression: 'surprised', lock: true, fps: 30,
    pose: { ...pairPose('arm', { rot: [0, 0, 150] }), root: { pos: [0, 0.08, 0] } },
    channels: [
      ...pair({ t: 'leg', p: 'rot.x', k: 'sine', a: 14, f: 2.2 }, true),
      { t: 'root', p: 'rot.z', k: 'sine', a: 5, f: 1.5 },
      { t: 'body', k: 'squash', a: 0.03, f: 2.2 },
      { t: 'tail', p: 'rot.y', k: 'sine', a: 20, f: 3 },
    ],
  },
  drop: {
    expression: 'surprised', lock: true, fps: 30, dur: 0.7,
    channels: [
      { t: 'root', p: 'pos.y', k: 'abs', a: 0.08, f: 2, fixed: true },
      { t: 'body', k: 'squash', a: 0.12, f: 2, ph: -PI / 2, fixed: true },
    ],
    fx: [{ kind: 'dust', at: 'root', rate: 8 }],
  },
  refresh: {
    expression: 'excited', lock: true, fps: 30, dur: 1.4,
    pose: { ...pairPose('arm', { rot: [0, 0, 70] }) },
    channels: [
      { t: 'root', p: 'rot.y', k: 'saw', a: 180, f: 0.8, fixed: true },
      { t: 'root', p: 'pos.y', k: 'abs', a: 0.12, f: 0.8, fixed: true },
      { t: 'body', k: 'squash', a: 0.05, f: 1.6 },
    ],
    fx: [{ kind: 'sparkles', at: 'body', rate: 6 }],
  },
  photo: {
    expression: 'happy', lock: true, fps: 30, dur: 2.2,
    pose: { ...pairPose('arm', { rot: [0, 0, 125] }), head: { rot: [0, 0, 10] } },
    channels: [
      { t: 'root', p: 'rot.y', k: 'sine', a: 10, f: 0.4 },
      { t: 'tail', p: 'rot.y', k: 'sine', a: 20, f: 2 },
      { t: 'body', k: 'squash', a: 0.02, f: 1 },
    ],
    fx: [{ kind: 'flash', at: 'root', rate: 1 }, { kind: 'sparkles', at: 'head', rate: 3 }],
  },

  // Idle antics: short, internal, never part of a pack's required set.
  antic_hop: {
    expression: 'happy', fps: 30, dur: 1.4,
    pose: { ...pairPose('arm', { rot: [0, 0, 30] }) },
    channels: [
      { t: 'root', p: 'pos.y', k: 'abs', a: 0.14, f: 1.4, fixed: true },
      { t: 'body', k: 'squash', a: 0.07, f: 1.4, ph: -PI / 2, fixed: true },
      { t: 'tail', p: 'rot.y', k: 'sine', a: 26, f: 3 },
    ],
  },
  antic_stretch: {
    expression: 'happy', fps: 24, dur: 2.2,
    pose: { ...pairPose('arm', { rot: [0, 0, 165] }), root: { scl: [0.96, 1.07, 0.96] }, head: { rot: [-14, 0, 0] } },
    channels: [{ t: 'body', k: 'squash', a: 0.02, f: 0.9 }],
  },
  antic_yawn: {
    expression: 'yawn', fps: 20, dur: 2.4,
    pose: { head: { rot: [-16, 0, 0] }, ...pairPose('arm', { rot: [0, 0, 20] }) },
    channels: [{ t: 'body', k: 'squash', a: 0.04, f: 0.45 }],
  },
  antic_look: {
    expression: 'neutral', fps: 24, dur: 2.6,
    channels: [
      { t: 'head', p: 'rot.y', k: 'sine', a: 34, f: 0.38 },
      { t: 'head', p: 'rot.x', k: 'sine', a: 6, f: 0.76 },
      { t: 'tail', p: 'rot.y', k: 'sine', a: 18, f: 1 },
    ],
  },
  antic_wiggle: {
    expression: 'happy', fps: 30, dur: 1.6,
    channels: [
      { t: 'root', p: 'rot.z', k: 'sine', a: 7, f: 2.8 },
      { t: 'body', k: 'squash', a: 0.03, f: 2.8 },
      { t: 'tail', p: 'rot.y', k: 'sine', a: 30, f: 4 },
    ],
  },
  antic_spin: {
    expression: 'happy', fps: 30, dur: 1.2,
    channels: [{ t: 'root', p: 'rot.y', k: 'once', a: 360, f: 0.85, fixed: true }, { t: 'body', k: 'squash', a: 0.03, f: 1.6 }],
  },
};

export const ANTICS = ['antic_hop', 'antic_stretch', 'antic_yawn', 'antic_look', 'antic_wiggle', 'antic_spin'];

/** Applies a pack's per-state override onto a recipe: pose merges by slot, channels append. */
export function applyOverride(base, override) {
  if (!override) return base;
  const out = { ...base, pose: { ...(base.pose || {}) }, channels: [...(base.channels || [])] };
  for (const [slot, pose] of Object.entries(override.pose || {})) out.pose[slot] = { ...(out.pose[slot] || {}), ...pose };
  if (override.drop) out.channels = out.channels.filter((c) => !override.drop.includes(c.t));
  if (override.channels) out.channels.push(...override.channels);
  for (const key of ['expression', 'show', 'fx', 'fps', 'dur', 'look', 'lock', 'desaturate']) {
    if (override[key] !== undefined) out[key] = override[key];
  }
  if (override.scale) {
    const { amp = 1, speed = 1 } = override.scale;
    out.channels = out.channels.map((c) => (c.fixed ? { ...c, f: (c.f ?? 1) * speed } : { ...c, a: (c.a ?? 1) * amp, f: (c.f ?? 1) * speed }));
  }
  return out;
}
