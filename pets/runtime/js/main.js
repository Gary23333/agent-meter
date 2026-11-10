// Entry point of the pet page. URL parameters (all optional, set by the native host):
//   pack=<id>  packRoot=<url ending in />  theme=<id>  scheme=light|dark  scale=<n>  hud=off|pill|full
//   reduceMotion=1  calm=1  dev=1 (browser harness)
//   embed=1  the page lives inside the app's panel (real DOM pointer events, bubble room on top)
//   still=1  thumbnail: pet fills the stage, no chatter or antics, body[data-settled] once drawn

import { createHost, installDomPointer } from './host.js';
import { loadPack } from './packs.js';
import { PackModel } from './pack-model.js';
import { Stage } from './stage.js';
import { DEFAULT_THEME, themeTokens } from './theme.js';
import { FallbackRenderer } from './fallback-renderer.js';

const q = new URLSearchParams(location.search);
export const params = {
  pack: q.get('pack') || 'gauge',
  packRoot: q.get('packRoot') || '../presets/',
  theme: q.get('theme') || DEFAULT_THEME,
  scheme: q.get('scheme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'),
  scale: parseFloat(q.get('scale') || '1') || 1,
  hud: q.get('hud') || 'pill',
  reduceMotion: q.get('reduceMotion') === '1',
  calm: q.get('calm') === '1' || q.get('still') === '1',
  embed: q.get('embed') === '1' || q.get('still') === '1',
  still: q.get('still') === '1',
  seed: parseInt(q.get('seed') || '7', 10),
};

const EMERGENCY = new PackModel({ id: 'fallback', name: '备用', renderer: 'three', stage: { width: 240, height: 260 } });

async function makeRenderer(model, base, container, size, tokens) {
  // A thumbnail reads the canvas back, which needs the drawing buffer to be kept.
  const opts = { width: size.width, height: size.height, dpr: window.devicePixelRatio || 2, tokens, baseUrl: base, preserve: params.still };
  if (model.renderer === 'sprite') {
    const { SpriteRenderer } = await import('./sprite-renderer.js');
    const r = new SpriteRenderer(container, model, opts);
    await r.init();
    return r;
  }
  const { ThreeRenderer } = await import('./three-renderer.js');
  const r = new ThreeRenderer(container, model, opts);
  await r.init();
  return r;
}

export async function boot() {
  const root = document.getElementById('stage');
  const host = createHost();
  const tokens = themeTokens(params.theme, params.scheme);
  const petEl = document.getElementById('pet');
  let model, base, renderer, problem = null;
  try {
    ({ model, base } = await loadPack(params.packRoot, params.pack));
  } catch (error) {
    problem = `pack ${params.pack}: ${error.message}`;
    try {
      ({ model, base } = await loadPack(params.packRoot, 'gauge'));
    } catch {
      model = EMERGENCY;
    }
  }
  const st = model.manifest.stage || { width: 240, height: 260 };
  try {
    renderer = await makeRenderer(model, base, petEl, st, tokens);
  } catch (error) {
    problem = problem || `renderer: ${error.message}`;
    renderer = new FallbackRenderer(petEl, model, { width: st.width, height: st.height, dpr: window.devicePixelRatio || 2, tokens });
    await renderer.init();
  }
  const stage = new Stage({
    root, petEl, fxCanvas: document.getElementById('fx'), bubbleEl: document.getElementById('bubble'),
    hudEl: document.getElementById('hud'), host, model, renderer, params,
  });
  host.subscribe((m) => stage.receive(m));
  // A browser has no native overlay, and neither has a stage embedded in the panel: both use DOM pointer events.
  if (!host.native || params.embed) installDomPointer(root, (m) => stage.receive(m));
  if (params.still) {
    // A thumbnail shows the pet at its best (idle, content, a healthy ring) and is drawn in one go: a window that is
    // not on screen gets no animation frames, and none are needed. The picture is left in window.__petStill.
    stage.director.setPrefs({ calm: true, chatter: false, followCursor: false });
    stage.receive({ type: 'frame', frame: { schema_version: 1, generated_at: Date.now() / 1000, state: 'idle', mood: 'happy', intensity: 0.6,
      energy: { known: true, remaining: 78, tone: 'ok', drives_state: true, scope: 'auto', label: '', resets_at: null, stale: false },
      meters: [], activity: { known: true, running: 0, apps: [] }, focus: { active: false }, reminders: [] } });
    renderer.setView(stage.director.update(0, stage.now));
    renderer.seek(0.5);
    renderer.render();
    const still = document.createElement('canvas');
    still.width = renderer.canvas.width;
    still.height = renderer.canvas.height;
    still.getContext('2d').drawImage(renderer.canvas, 0, 0);
    window.__petStill = still.toDataURL('image/png');
    document.body.dataset.settled = '1';
  } else {
    stage.start();
  }
  window.__pet = { stage, host, model, renderer };
  host.post({ type: 'ready', pack: model.id, name: model.name, renderer: model.renderer, stage: st, problem });
  if (problem) host.post({ type: 'error', message: problem });
  return stage;
}

if (!window.__PET_NO_BOOT__) {
  boot().catch((error) => {
    document.body.dataset.error = String(error && error.message || error);
    createHost().post({ type: 'error', message: String(error && error.message || error) });
  });
}
