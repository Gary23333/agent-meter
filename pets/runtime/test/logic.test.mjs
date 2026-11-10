import test from 'node:test';
import assert from 'node:assert/strict';

import { ANIMATIONS, FALLBACKS, REQUIRED_STATES, resolveAnimation, resolveExpression, toneOf } from '../js/constants.js';
import { Blender, evaluate, mirrorChannel, mirrorPose } from '../js/anim.js';
import { ANTICS, RECIPES, applyOverride } from '../js/recipes.js';
import { PackModel } from '../js/pack-model.js';
import { Director } from '../js/director.js';
import { fitStage } from '../js/util.js';

const threePack = (extra = {}) => new PackModel({ id: 't', name: 'T', renderer: 'three', ...extra },
  { face: { expressions: { neutral: {}, happy: {}, sad: {}, worried: {} } } });
const spritePack = (states) => new PackModel({ id: 's', name: 'S', renderer: 'sprite', sprite: { states, motion: true } });

test('every animation name resolves along a terminating chain, even for a minimal sprite pack', () => {
  const minimal = Object.fromEntries(REQUIRED_STATES.map((n) => [n, { image: `${n}.png`, frames: 1 }]));
  const pack = spritePack(minimal);
  for (const name of ANIMATIONS) {
    const resolved = resolveAnimation(name, (n) => pack.has(n));
    assert.ok(pack.has(resolved), `${name} -> ${resolved}`);
  }
  assert.equal(resolveAnimation('busy', (n) => pack.has(n)), 'working');
  assert.equal(resolveAnimation('exhausted', (n) => pack.has(n)), 'tired');
  assert.equal(resolveAnimation('nonsense', () => false), 'idle');
});

test('fallback chains never loop and only name known animations', () => {
  for (const [from, chain] of Object.entries(FALLBACKS)) {
    assert.ok(ANIMATIONS.includes(from), from);
    for (const to of chain) assert.ok(ANIMATIONS.includes(to), `${from}->${to}`);
    assert.notEqual(resolveAnimation(from, () => false), undefined);
  }
});

test('expression fallbacks end at neutral', () => {
  const only = (...names) => (n) => names.includes(n);
  assert.equal(resolveExpression('excited', only('happy', 'neutral')), 'happy');
  assert.equal(resolveExpression('dizzy', only('sad', 'neutral')), 'sad');
  assert.equal(resolveExpression('yawn', only('neutral')), 'neutral');
  assert.equal(resolveExpression('happy', () => false), null);
});

test('tone thresholds match agent_meter.pet.tone_of', () => {
  assert.deepEqual([null, 0, 3, 5, 5.1, 20, 20.1].map((v) => toneOf(v, 20)),
    ['unknown', 'empty', 'critical', 'critical', 'low', 'low', 'ok']);
  assert.equal(toneOf(8, 10), 'low');
});

test('every recipe evaluates to finite numbers across time and intensity', () => {
  for (const [name, spec] of Object.entries(RECIPES)) {
    for (const intensity of [0, 0.5, 1]) {
      for (let t = 0; t < 6; t += 0.37) {
        const out = evaluate(spec, t, intensity, {});
        for (const [slot, v] of Object.entries(out)) {
          for (const part of [v.pos, v.rot, v.scl]) {
            for (const n of part) assert.ok(Number.isFinite(n), `${name}.${slot} t=${t} -> ${n}`);
          }
          assert.ok(Number.isFinite(v.glow));
        }
      }
    }
  }
});

test('every required state and every antic has a recipe, and a pack that overrides nothing still plays', () => {
  for (const name of REQUIRED_STATES) assert.ok(RECIPES[name], name);
  for (const name of ANTICS) assert.ok(RECIPES[name] && RECIPES[name].dur > 0, name);
  const pack = threePack();
  for (const name of ANIMATIONS) assert.ok(pack.has(name), name);
});

test('squash keeps volume close to constant', () => {
  const out = evaluate({ channels: [{ t: 'body', k: 'squash', a: 0.08, f: 1 }] }, 0.25, 0.5, {});
  const [x, y, z] = out.body.scl;
  assert.ok(y > 1 && x < 1 && z < 1);
  assert.ok(Math.abs(x * y * z - 1) < 0.01);
});

test('mirroring flips the outward axes for the left side only', () => {
  const ch = { t: 'arm', p: 'rot.z', a: 10, o: 4 };
  assert.deepEqual([mirrorChannel(ch, 'R').a, mirrorChannel(ch, 'L').a, mirrorChannel(ch, 'L').o], [10, -10, -4]);
  assert.equal(mirrorChannel({ t: 'arm', p: 'rot.x', a: 5 }, 'L').a, 5);
  assert.deepEqual(mirrorChannel({ t: 'arm', p: 'rot.x', a: 5 }, 'R', true).ph, Math.PI);
  assert.deepEqual(mirrorPose({ rot: [-52, 3, 12], pos: [0.1, 0, 0] }), { rot: [-52, -3, -12], pos: [-0.1, 0, 0] });
});

test('right and left arms of a recipe are mirror images', () => {
  const out = evaluate(RECIPES.celebrate, 0.3, 0.5, {});
  assert.ok(out.armR.rot[2] > 100 && out.armL.rot[2] < -100);
});

test('blender cross-fades and then drops the old layer', () => {
  const blender = new Blender(0.5);
  blender.set('a', { pose: { root: { pos: [1, 0, 0] } } });
  assert.equal(blender.evaluate(0.5).root.pos[0], 1);
  blender.set('b', { pose: { root: { pos: [3, 0, 0] } } });
  blender.step(0.25);
  const mid = blender.evaluate(0.5).root.pos[0];
  assert.ok(mid > 1 && mid < 3, `mid=${mid}`);
  blender.step(0.5);
  assert.equal(blender.layers.length, 1);
  assert.equal(blender.evaluate(0.5).root.pos[0], 3);
});

test('a slot only one layer touches fades from and to the rest transform', () => {
  const blender = new Blender(1);
  blender.set('a', { pose: { head: { scl: [2, 2, 2] } } });
  blender.set('b', {});
  blender.step(0.5);
  const mixed = blender.evaluate(0.5).head;
  assert.ok(mixed.scl[0] > 1 && mixed.scl[0] < 2);
});

test('seek settles on the top layer at an exact time', () => {
  const blender = new Blender(1);
  blender.set('a', { channels: [{ t: 'root', p: 'pos.y', k: 'sine', a: 1, f: 1 }] });
  blender.set('b', { channels: [{ t: 'root', p: 'pos.y', k: 'sine', a: 1, f: 1 }] });
  blender.seek(0.25);
  assert.equal(blender.layers.length, 1);
  assert.ok(Math.abs(blender.evaluate(0.5).root.pos[1] - Math.sin(Math.PI / 2) * (0.55 + 0.45)) < 1e-9);
});

test('overrides merge poses by slot, append channels and scale speed', () => {
  const merged = applyOverride(RECIPES.working, {
    pose: { head: { rot: [30, 0, 0] } }, channels: [{ t: 'tail', p: 'rot.y', k: 'sine', a: 5, f: 1 }],
    drop: ['antenna'], scale: { amp: 2, speed: 2 }, expression: 'happy',
  });
  assert.deepEqual(merged.pose.head.rot, [30, 0, 0]);
  assert.ok(merged.pose.armR);
  assert.ok(!merged.channels.some((c) => c.t === 'antenna'));
  assert.equal(merged.expression, 'happy');
  const appended = merged.channels.find((c) => c.t === 'tail' && c.a === 10);     // 5 * amp 2
  assert.ok(appended && appended.f === 2);                                         // 1 * speed 2
  const original = RECIPES.working.channels.find((c) => c.t === 'tail');
  const scaled = merged.channels.find((c) => c.t === 'tail' && c.a === original.a * 2);
  assert.equal(scaled.f, original.f * 2);
});

const frame = (over = {}) => ({
  schema_version: 1, generated_at: 1000, state: 'idle', mood: 'happy', intensity: 0.5, reaction: null,
  energy: { known: true, remaining: 82, tone: 'ok', label: 'Codex · 5 小时', resets_at: 1000 + 9060, stale: false, drives_state: true },
  meters: [], activity: { running: 0, apps: [] }, focus: { active: false }, reminders: [], ...over,
});

test('director follows the frame state and lets the mood choose the face only where it should', () => {
  const d = new Director(threePack(), { seed: 1 });
  d.setFrame(frame({ state: 'working', mood: 'worried' }), 0);
  let v = d.update(0.016, 0.1);
  assert.equal(v.animation, 'working');
  assert.equal(v.expression, 'worried');
  d.setFrame(frame({ state: 'alarm', mood: 'happy' }), 1);
  v = d.update(0.016, 1.1);
  assert.equal(v.animation, 'alarm');
  assert.equal(v.expression, 'neutral');     // surprised is missing from this avatar -> neutral
});

test('a reaction plays once per key, for its window, then the base state returns', () => {
  const d = new Director(threePack(), { seed: 1 });
  d.setPrefs({ calm: true });                                  // no idle antics muddying the timeline
  const reaction = { id: 'celebrate', key: 'k1', until: 1008, reason: 'x' };
  d.setFrame(frame({ reaction }), 10);
  assert.equal(d.update(0.016, 10.1).animation, 'celebrate');
  assert.equal(d.update(0.016, 17).animation, 'celebrate');
  assert.equal(d.update(0.016, 18.5).animation, 'idle');
  d.setFrame(frame({ reaction }), 19);                       // same key again: ignored
  assert.equal(d.update(0.016, 19.1).animation, 'idle');
  d.setFrame(frame({ reaction: { ...reaction, key: 'k2', until: 1008 } }), 20);
  assert.equal(d.update(0.016, 20.1).animation, 'celebrate');
});

test('a weaker reaction never interrupts a stronger one', () => {
  const d = new Director(threePack(), { seed: 1 });
  d.setFrame(frame({ reaction: { id: 'startle', key: 's', until: 1006 } }), 0);
  d.setFrame(frame({ reaction: { id: 'wave', key: 'w', until: 1005 } }), 1);
  assert.equal(d.update(0.016, 1.1).animation, 'startle');
});

test('sprite packs fall back through the chain for reactions they lack', () => {
  const states = Object.fromEntries(REQUIRED_STATES.map((n) => [n, { image: `${n}.png`, frames: 1 }]));
  const d = new Director(spritePack(states), { seed: 1 });
  d.setFrame(frame({ reaction: { id: 'eating', key: 'e', until: 1005 } }), 0);
  assert.equal(d.update(0.016, 0.1).animation, 'working');
});

test('dragging beats everything, and dropping lands with an overlay', () => {
  const d = new Director(threePack(), { seed: 1 });
  d.setFrame(frame({ state: 'working' }), 0);
  d.dragStart();
  assert.equal(d.update(0.016, 1).animation, 'drag');
  d.dragEnd(2);
  assert.equal(d.update(0.016, 2.1).animation, 'drop');
  assert.equal(d.update(0.016, 3.5).animation, 'working');
});

test('an interaction that falls back to a longer animation keeps its own short duration', () => {
  const states = Object.fromEntries(REQUIRED_STATES.map((n) => [n, { image: `${n}.png`, frames: 1 }]));
  const d = new Director(spritePack(states), { seed: 1 });
  d.setPrefs({ calm: true });
  d.setFrame(frame(), 0);
  d.poke(5);
  assert.equal(d.update(0.016, 5.1).animation, 'celebrate');      // poke -> wave -> celebrate for this pack
  assert.equal(d.update(0.016, 6.0).animation, 'celebrate');
  assert.equal(d.update(0.016, 6.3).animation, 'idle');           // gone after the poke's own 1.1 s, not celebrate's 8 s
  d.refresh(10);
  assert.equal(d.update(0.016, 10.5).animation, 'working');       // refresh -> working
  assert.equal(d.update(0.016, 11.6).animation, 'idle');
});

test('poke plays an overlay and answers with an honest one-line summary', () => {
  const d = new Director(threePack(), { seed: 1 });
  d.setFrame(frame({ activity: { running: 2, apps: [] } }), 0);
  d.poke(5);
  assert.equal(d.update(0.016, 5.1).animation, 'poke');
  const bubble = d.drainBubbles().pop();
  assert.match(bubble.text, /Codex · 5 小时 还剩 82%/);
  assert.match(bubble.text, /2 个会话进行中/);
  const unknown = new Director(threePack(), { seed: 1 });
  unknown.setFrame(frame({ energy: { known: false, stale: false } }), 0);
  assert.match(unknown.summaryLine(), /还没读到百分比额度/);
  unknown.setFrame(frame({ energy: { known: false, stale: true } }), 0);
  assert.match(unknown.summaryLine(), /已过期/);
});

test('reminders become bubbles carrying tone, priority and action', () => {
  const d = new Director(threePack(), { seed: 1 });
  d.setFrame(frame({ reminders: [{ id: 'low|codex|primary|1|20', text: 'Codex 额度不足', tone: 'warn', priority: 60, action: { kind: 'open_panel', tab: 'accounts' } }] }), 0);
  const [b] = d.drainBubbles();
  assert.equal(b.tone, 'warn');
  assert.equal(b.priority, 60);
  assert.equal(b.action.tab, 'accounts');
  assert.deepEqual(d.drainBubbles(), []);
});

test('idle antics start only when idle, never when calm, and always come back to idle', () => {
  const calm = new Director(threePack(), { seed: 3 });
  calm.setPrefs({ calm: true });
  calm.setFrame(frame(), 0);
  for (let t = 0; t < 120; t += 0.5) assert.equal(calm.update(0.5, t).kind, 'base');

  const d = new Director(threePack(), { seed: 3 });
  d.setFrame(frame(), 0);
  let sawAntic = false;
  for (let t = 0; t < 120; t += 0.25) {
    const v = d.update(0.25, t);
    if (v.kind === 'antic') { sawAntic = true; assert.ok(ANTICS.includes(v.animation)); }
  }
  assert.ok(sawAntic);
  const busy = new Director(threePack(), { seed: 3 });
  busy.setFrame(frame({ state: 'working' }), 0);
  for (let t = 0; t < 120; t += 0.25) assert.notEqual(busy.update(0.25, t).kind, 'antic');
});

test('chatter is rate limited and can be switched off', () => {
  const d = new Director(threePack(), { seed: 2 });
  d.setFrame(frame({ state: 'idle' }), 0);
  d.update(0.1, 0);
  let lines = 0;
  for (let i = 1; i <= 40; i++) {
    d.setFrame(frame({ state: i % 2 ? 'working' : 'idle' }), i);
    d.update(0.1, i);
    lines += d.drainBubbles().filter((b) => b.tone === 'chat').length;
  }
  assert.ok(lines <= 1, `lines=${lines}`);
  const quiet = new Director(threePack(), { seed: 2 });
  quiet.setPrefs({ chatter: false });
  quiet.setFrame(frame(), 0); quiet.update(0.1, 0);
  quiet.setFrame(frame({ state: 'working' }), 200); quiet.update(0.1, 200);
  assert.equal(quiet.drainBubbles().length, 0);
});

test('reduce motion caps the frame rate and removes particles', () => {
  const d = new Director(threePack(), { seed: 1 });
  d.setPrefs({ reduceMotion: true });
  d.setFrame(frame({ state: 'busy' }), 0);
  const v = d.update(0.1, 1);
  assert.ok(v.fps <= 10);
  assert.deepEqual(v.fx, []);
});

test('hud never invents numbers for unknown quota', () => {
  const d = new Director(threePack(), { seed: 1 });
  d.setFrame(frame({ energy: { known: false, stale: false } }), 0);
  assert.equal(d.hud(0).pill, null);
  d.setFrame(frame({ energy: { known: false, stale: true } }), 0);
  assert.equal(d.hud(0).pill.text, '过期');
  d.setFrame(frame(), 0);
  const { pill } = d.hud(30);
  assert.equal(pill.text, '82%');
  assert.match(pill.sub, /时/);
});

test('the pet is only ever shrunk to fit its stage, and each stage mode keeps its own headroom', () => {
  const stage = { W: 392, H: 280, w: 240, h: 260 };
  const [window, embed, fill] = ['window', 'embed', 'fill'].map((mode) => fitStage({ ...stage, mode }));
  assert.ok(embed > 0 && embed < 1, 'the tab stage shrinks the pet to leave room for the bubble');
  assert.ok(fill > embed && fill > window, 'a thumbnail fills the stage');
  assert.ok(fill <= 1);
  // The desktop window keeps its pre-existing formula, HUD included.
  assert.equal(fitStage({ W: 300, H: 400, w: 240, h: 260, hudH: 34 }), Math.min(1, 300 / 240, (400 * 0.82 - 34) / 260));
  // Room never makes it bigger than life, and a degenerate stage never yields zero.
  assert.equal(fitStage({ W: 3000, H: 3000, w: 240, h: 260, mode: 'embed' }), 1);
  assert.ok(fitStage({ W: 0, H: 0, w: 240, h: 260, mode: 'embed' }) > 0);
});
