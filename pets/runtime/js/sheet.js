// Contact sheet: every animation of a pack (several time samples each), every expression, and the idle
// pose under all seven interface styles, drawn onto one canvas. Deterministic, so two renders of an
// unchanged pack are identical and a screenshot can be diffed or reviewed by a model.
//
// ?pack=gauge[,blob]  states=all|core|a,b  frames=1|3  size=150  cols=6  theme=aurora  scheme=light
//  fx=1  expr=1  themes=1  bg=checker|paper|clear  packRoot=../presets/

import { loadPack } from './packs.js';
import { ANIMATIONS, EXPRESSIONS, REQUIRED_STATES, STATE_LABELS, resolveAnimation, resolveExpression } from './constants.js';
import { FxLayer } from './fx.js';
import { THEMES, themeTokens } from './theme.js';

const q = new URLSearchParams(location.search);
const opt = {
  packs: (q.get('pack') || 'gauge').split(',').filter(Boolean),
  states: q.get('states') || 'all',
  frames: Math.max(1, Math.min(4, parseInt(q.get('frames') || '3', 10))),
  size: parseInt(q.get('size') || '150', 10),
  cols: parseInt(q.get('cols') || '0', 10),
  theme: q.get('theme') || 'aurora',
  scheme: q.get('scheme') || 'light',
  fx: q.get('fx') !== '0',
  expr: q.get('expr') !== '0',
  themes: q.get('themes') !== '0',
  bg: q.get('bg') || 'paper',
  packRoot: q.get('packRoot') || '../presets/',
};

const ENERGY = { alarm: [0.04, 'critical'], exhausted: [0, 'empty'], tired: [0.15, 'low'], busy: [0.5, 'ok'], offline: [null, 'unknown'], confused: [null, 'unknown'] };
const TIMES = { 1: [0.5], 2: [0.3, 0.8], 3: [0.25, 0.6, 1.0], 4: [0.2, 0.5, 0.8, 1.1] };

function viewFor(model, name, expressionOverride) {
  const resolved = resolveAnimation(name, (n) => model.has(n));
  const spec = model.spec(resolved);
  const wanted = expressionOverride || spec.expression || 'neutral';
  const [energy, tone] = ENERGY[name] || [0.78, 'ok'];
  return {
    animation: resolved, layerKey: `sheet:${name}:${expressionOverride || ''}`, kind: 'base', intensity: 0.6,
    expression: resolveExpression(wanted, (e) => model.hasExpression(e)) || 'neutral', look: spec.look || null,
    show: spec.show || [], fx: spec.fx || [], energy, energyTone: tone, desaturate: spec.desaturate || 0, fps: 30,
  };
}

function checker(g, x, y, w, h, dark) {
  g.fillStyle = dark ? '#2a2a31' : '#f4f4f6';
  g.fillRect(x, y, w, h);
  g.fillStyle = dark ? '#33333b' : '#e8e8ec';
  const s = 10;
  for (let j = 0; j < h; j += s) for (let i = 0; i < w; i += s) if (((i / s) + (j / s)) % 2 === 0) g.fillRect(x + i, y + j, Math.min(s, w - i), Math.min(s, h - j));
}

async function makeRenderer(model, base, size, tokens) {
  const holder = document.createElement('div');
  Object.assign(holder.style, { position: 'fixed', left: '-9999px', top: '0', width: `${size.w}px`, height: `${size.h}px` });
  document.body.append(holder);
  const dpr = 2;
  const common = { width: size.w, height: size.h, dpr, tokens, baseUrl: base, preserve: true };
  if (model.renderer === 'sprite') {
    const { SpriteRenderer } = await import('./sprite-renderer.js');
    const r = new SpriteRenderer(holder, model, common);
    await r.init();
    return r;
  }
  const { ThreeRenderer } = await import('./three-renderer.js');
  const r = new ThreeRenderer(holder, model, common);
  await r.init();
  return r;
}

function drawFx(renderer, view, size) {
  if (!opt.fx || !view.fx.length) return null;
  const canvas = document.createElement('canvas');
  const fx = new FxLayer(canvas, 9);
  fx.resize(size.w, size.h, 2);
  fx.setTokens(renderer.tokens || themeTokens(opt.theme, opt.scheme));
  fx.setEmitters(view.fx, view.layerKey);
  const anchor = (name) => renderer.anchor(name);
  for (let i = 0; i < 70; i++) fx.update(1 / 60, anchor);
  fx.draw();
  return canvas;
}

function drawTile(g, renderer, view, t, x, y, size, tokens) {
  const dark = tokens.dark;
  if (opt.bg === 'checker') checker(g, x, y, size.w, size.h, dark);
  else if (opt.bg === 'paper') { g.fillStyle = dark ? '#26262b' : '#fbfbfd'; g.fillRect(x, y, size.w, size.h); }
  renderer.setView(view);
  renderer.seek(t);
  renderer.render();
  g.drawImage(renderer.canvas, x, y, size.w, size.h);
  const fx = drawFx(renderer, view, size);
  if (fx) g.drawImage(fx, x, y, size.w, size.h);
}

async function renderPack(id, g0, offsetY, widthHint) {
  const { model, base } = await loadPack(opt.packRoot, id);
  const tokens = themeTokens(opt.theme, opt.scheme);
  const st = model.manifest.stage || { width: 240, height: 260 };
  const size = { w: opt.size, h: Math.round(opt.size * st.height / st.width) };
  const renderer = await makeRenderer(model, base, size, tokens);

  const wanted = opt.states === 'all' ? ANIMATIONS.filter((n) => !['drop'].includes(n))
    : opt.states === 'core' ? REQUIRED_STATES : opt.states.split(',').filter((n) => ANIMATIONS.includes(n));
  const times = TIMES[opt.frames];
  const gap = 6, cellW = times.length * size.w + (times.length - 1) * 2 + gap, cellH = size.h + 22;
  const cols = opt.cols || Math.max(1, Math.floor(widthHint / cellW));
  const rows = Math.ceil(wanted.length / cols);
  const exprCols = Math.max(1, Math.floor(widthHint / (size.w * 0.75 + gap)));
  const exprRows = opt.expr && model.renderer === 'three' ? Math.ceil(EXPRESSIONS.length / exprCols) : 0;
  const themeIds = Object.keys(THEMES);
  const themeRows = opt.themes && model.renderer === 'three' ? Math.ceil(themeIds.length / exprCols) : 0;
  const head = 54, section = 26;
  const total = head + rows * cellH + (exprRows ? section + exprRows * (size.h * 0.75 + 22) : 0) + (themeRows ? section + themeRows * (size.h * 0.75 + 22) : 0) + 14;

  const canvas = document.createElement('canvas');
  canvas.width = widthHint; canvas.height = Math.ceil(total);
  const g = canvas.getContext('2d');
  const dark = tokens.dark;
  g.fillStyle = dark ? '#1c1c20' : '#ffffff';
  g.fillRect(0, 0, canvas.width, canvas.height);
  const ink = dark ? '#f2f2f7' : '#1d1d1f', sub = dark ? '#a0a0ab' : '#6e6e73';
  g.fillStyle = ink; g.font = '700 20px system-ui, "PingFang SC"'; g.textBaseline = 'alphabetic';
  g.fillText(`${model.name}  ${model.manifest.name_en || ''}  ·  ${model.id}  v${model.manifest.version || '0'}`, 14, 28);
  const own = ANIMATIONS.filter((n) => model.has(n)).length;
  g.fillStyle = sub; g.font = '12px system-ui, "PingFang SC"';
  g.fillText(`${model.renderer} 渲染 · 自带 ${own}/${ANIMATIONS.length} 个动画，其余按回退链降级 · 主题 ${THEMES[opt.theme].label}/${opt.scheme} · 每格采样 ${times.join('s, ')}s`, 14, 46);

  const missing = [];
  wanted.forEach((name, i) => {
    const cx = 14 + (i % cols) * cellW, cy = head + Math.floor(i / cols) * cellH;
    const view = viewFor(model, name);
    times.forEach((t, k) => drawTile(g, renderer, view, t, cx + k * (size.w + 2), cy, size, tokens));
    const resolved = view.animation;
    g.fillStyle = resolved === name ? ink : '#d9822b'; g.font = '600 12px system-ui, "PingFang SC"';
    g.fillText(`${name} ${STATE_LABELS[name] || ''}${resolved === name ? '' : ` → ${resolved}`}`, cx + 2, cy + size.h + 14);
    if (resolved !== name) missing.push(name);
  });

  let y = head + rows * cellH;
  const small = { w: Math.round(size.w * 0.75), h: Math.round(size.h * 0.75) };
  const smallRenderer = (exprRows || themeRows) ? (renderer.resize(small.w, small.h, 2), renderer) : renderer;
  if (exprRows) {
    g.fillStyle = ink; g.font = '700 14px system-ui, "PingFang SC"'; g.fillText('表情（待机姿态）', 14, y + 18);
    y += section;
    EXPRESSIONS.forEach((e, i) => {
      const cx = 14 + (i % exprCols) * (small.w + gap), cy = y + Math.floor(i / exprCols) * (small.h + 22);
      const view = viewFor(model, 'idle', e);
      drawTile(g, smallRenderer, { ...view, fx: [] }, 0.4, cx, cy, small, tokens);
      const ok = model.hasExpression(e) || view.expression === e;
      g.fillStyle = ok ? ink : '#d9822b'; g.font = '600 12px system-ui, "PingFang SC"';
      g.fillText(ok ? e : `${e} → ${view.expression}`, cx + 2, cy + small.h + 14);
    });
    y += exprRows * (small.h + 22);
  }
  if (themeRows) {
    g.fillStyle = ink; g.font = '700 14px system-ui, "PingFang SC"'; g.fillText('七套界面风格下的待机', 14, y + 18);
    y += section;
    for (const [i, themeId] of themeIds.entries()) {
      const scheme = ['titanium', 'neon', 'prism'].includes(themeId) ? 'dark' : opt.scheme;
      const tk = themeTokens(themeId, scheme);
      smallRenderer.setTokens(tk);
      const cx = 14 + (i % exprCols) * (small.w + gap), cy = y + Math.floor(i / exprCols) * (small.h + 22);
      drawTile(g, smallRenderer, { ...viewFor(model, 'idle'), fx: [] }, 0.4, cx, cy, small, tk);
      g.fillStyle = ink; g.font = '600 12px system-ui, "PingFang SC"';
      g.fillText(THEMES[themeId].label, cx + 2, cy + small.h + 14);
    }
  }
  renderer.dispose();
  return { canvas, id, missing, own };
}

async function main() {
  const width = parseInt(q.get('width') || '1480', 10);
  const results = [];
  try {
    for (const id of opt.packs) {
      const r = await renderPack(id, null, 0, width);
      results.push(r);
      document.body.append(r.canvas);
    }
    window.__sheetInfo = results.map(({ id, missing, own, canvas }) => ({ id, missing, own, width: canvas.width, height: canvas.height }));
    window.__sheetPNG = (i = 0) => results[i].canvas.toDataURL('image/png');
    document.body.dataset.ready = '1';
  } catch (error) {
    document.body.dataset.error = String(error && error.message || error);
    document.body.append(Object.assign(document.createElement('pre'), { textContent: String(error && error.stack || error) }));
  }
}

document.body.style.cssText = 'margin:0;background:#ddd;font:12px system-ui';
main();
