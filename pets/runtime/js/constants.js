// Canonical vocabulary shared by every pack, renderer and the host. Keep in sync with
// agent_meter/pet.py (STATES, MOODS, REACTIONS) and pets/SPEC.md.

export const BASE_STATES = ['offline', 'exhausted', 'alarm', 'waiting', 'busy', 'working', 'painting', 'tired',
  'alert', 'focus', 'excited', 'confused', 'sleeping', 'idle'];
export const REACTIONS = ['celebrate', 'eating', 'startle', 'wave', 'painting'];
export const INTERACTIONS = ['poke', 'pet', 'drag', 'drop', 'refresh', 'photo'];
export const MOODS = ['neutral', 'happy', 'excited', 'worried', 'sad', 'sleepy', 'surprised', 'confused', 'determined'];
export const EXPRESSIONS = ['neutral', 'happy', 'excited', 'determined', 'worried', 'sad', 'sleepy', 'surprised',
  'confused', 'dizzy', 'yawn', 'love'];

// Every animation name a pack may implement.
export const ANIMATIONS = Array.from(new Set([...BASE_STATES, ...REACTIONS, ...INTERACTIONS]));

// A valid pack implements at least these; everything else falls back along FALLBACKS to the first
// implemented name and finally to `idle`.
export const REQUIRED_STATES = ['idle', 'working', 'tired', 'alarm', 'sleeping', 'celebrate', 'offline', 'waiting'];

export const FALLBACKS = {
  busy: ['working'],
  painting: ['working'],
  exhausted: ['tired'],
  alarm: ['tired'],
  alert: ['waiting'],
  focus: ['working'],
  excited: ['celebrate'],
  confused: ['idle'],
  eating: ['working'],
  startle: ['alarm'],
  wave: ['celebrate'],
  poke: ['wave'],
  pet: ['celebrate'],
  drag: ['startle'],
  drop: ['idle'],
  refresh: ['working'],
  photo: ['celebrate'],
  tired: ['idle'],
  waiting: ['idle'],
  working: ['idle'],
  celebrate: ['idle'],
  sleeping: ['idle'],
  offline: ['idle'],
};

export const EXPRESSION_FALLBACKS = {
  excited: ['happy', 'neutral'],
  determined: ['neutral'],
  worried: ['sad', 'neutral'],
  sad: ['worried', 'neutral'],
  sleepy: ['neutral'],
  surprised: ['neutral'],
  confused: ['neutral'],
  dizzy: ['confused', 'sad', 'neutral'],
  yawn: ['sleepy', 'neutral'],
  love: ['happy', 'neutral'],
  happy: ['neutral'],
};

export const STATE_LABELS = {
  offline: '失联', exhausted: '电量耗尽', alarm: '告急', waiting: '等你确认', busy: '忙翻了', working: '干活中',
  painting: '创作中', tired: '没力气', alert: '有提醒', focus: '专注', excited: '期待', confused: '拿不准',
  sleeping: '睡觉', idle: '待机', celebrate: '庆祝', eating: '吃 token', startle: '受惊', wave: '打招呼',
  poke: '被戳', pet: '被摸', drag: '被拎起', drop: '落地', refresh: '刷新', photo: '拍照',
};

/** First implemented name along the fallback chain; `idle` always terminates it. */
export function resolveAnimation(name, has) {
  const seen = new Set();
  const queue = [name];
  while (queue.length) {
    const next = queue.shift();
    if (seen.has(next)) continue;
    seen.add(next);
    if (has(next)) return next;
    queue.push(...(FALLBACKS[next] || []));
  }
  return 'idle';
}

export function resolveExpression(name, has) {
  const seen = new Set();
  const queue = [name];
  while (queue.length) {
    const next = queue.shift();
    if (seen.has(next)) continue;
    seen.add(next);
    if (has(next)) return next;
    queue.push(...(EXPRESSION_FALLBACKS[next] || []));
  }
  return has('neutral') ? 'neutral' : null;
}

/** Tone of a remaining percentage, mirrors agent_meter.pet.tone_of. */
export function toneOf(remaining, threshold = 20) {
  if (remaining == null || Number.isNaN(remaining)) return 'unknown';
  if (remaining <= 0) return 'empty';
  if (remaining <= Math.min(5, threshold)) return 'critical';
  if (remaining <= threshold) return 'low';
  return 'ok';
}
