// AgentMeter's seven interface styles as tokens for the pet: colours for avatars ($accent1 ...) and CSS
// variables for the bubble and HUD. Values follow menubar/Sources/AgentMeterBar/Theme.swift.

const HEALTH = {
  system: { ok: '#34c759', low: '#ff9f0a', crit: '#ff453a' },
  soft: { ok: '#2fbf8f', low: '#f0a23a', crit: '#e5546a' },
  neon: { ok: '#4dff3d', low: '#ffeb1a', crit: '#ff1f66' },
};

export const THEMES = {
  minimal: {
    label: '极简', accent1: '#1d1d1f', accent2: '#6e6e73', ink: '#1d1d1f', health: HEALTH.system,
    bubble: { bgL: '#ffffff', bgD: '#1c1c1e', fgL: '#1d1d1f', fgD: '#f5f5f7', border: 'currentColor', radius: 10, shadow: 'none', font: 'system-ui, -apple-system, "PingFang SC", sans-serif', blur: 0, borderW: 1.2 },
  },
  native: {
    label: '原生', accent1: '#0a84ff', accent2: '#5e5ce6', ink: '#1d1d1f', health: HEALTH.system,
    bubble: { bgL: '#ffffff', bgD: '#2c2c2e', fgL: '#1d1d1f', fgD: '#f5f5f7', border: 'rgba(128,128,128,.35)', radius: 12, shadow: '0 4px 14px rgba(0,0,0,.18)', font: 'system-ui, -apple-system, "PingFang SC", sans-serif', blur: 0, borderW: 1 },
  },
  porcelain: {
    label: '瓷白', accent1: '#4d6394', accent2: '#7a5c8a', ink: '#172133', health: HEALTH.soft,
    bubble: { bgL: 'rgba(255,255,255,.92)', bgD: 'rgba(255,255,255,.92)', fgL: '#172133', fgD: '#172133', border: 'rgba(77,99,148,.4)', radius: 16, shadow: '0 6px 18px rgba(60,80,130,.22), inset 0 1px 0 #fff', font: 'ui-rounded, system-ui, "PingFang SC", sans-serif', blur: 0, borderW: 1 },
  },
  aurora: {
    label: '极光', accent1: '#525ce0', accent2: '#9447d6', ink: '#1a1f38', health: HEALTH.soft,
    bubble: { bgL: 'rgba(255,255,255,.74)', bgD: 'rgba(255,255,255,.14)', fgL: '#1a1f38', fgD: '#ffffff', border: 'rgba(120,100,230,.45)', radius: 16, shadow: '0 8px 24px rgba(82,92,224,.28)', font: 'ui-rounded, system-ui, "PingFang SC", sans-serif', blur: 14, borderW: 1 },
  },
  titanium: {
    label: '钛影', accent1: '#b8cfe0', accent2: '#708fa8', ink: '#0f1721', health: HEALTH.soft,
    bubble: { bgL: 'rgba(38,48,61,.9)', bgD: 'rgba(38,48,61,.9)', fgL: '#f2f7fc', fgD: '#f2f7fc', border: 'rgba(255,255,255,.2)', radius: 12, shadow: '0 6px 18px rgba(0,0,0,.45), inset 0 1px 0 rgba(255,255,255,.18)', font: 'ui-rounded, system-ui, "PingFang SC", sans-serif', blur: 0, borderW: 1 },
  },
  neon: {
    label: '霓虹', accent1: '#ff29d1', accent2: '#00f0ff', ink: '#08051a', health: HEALTH.neon,
    bubble: { bgL: 'rgba(6,9,19,.88)', bgD: 'rgba(6,9,19,.88)', fgL: '#f0f7ff', fgD: '#f0f7ff', border: 'rgba(255,41,209,.75)', radius: 6, shadow: '0 0 14px rgba(255,41,209,.45), 0 0 26px rgba(0,240,255,.25)', font: 'ui-monospace, "SF Mono", Menlo, monospace', blur: 0, borderW: 1.2 },
  },
  prism: {
    label: '棱镜', accent1: '#00f0ff', accent2: '#ff29d1', ink: '#08051a', health: HEALTH.neon,
    bubble: { bgL: 'rgba(6,9,19,.86)', bgD: 'rgba(6,9,19,.86)', fgL: '#f0f7ff', fgD: '#f0f7ff', border: 'rgba(140,100,255,.55)', radius: 14, shadow: '0 6px 22px rgba(140,100,255,.4)', font: 'ui-monospace, "SF Mono", Menlo, monospace', blur: 8, borderW: 1 },
  },
};

export const DEFAULT_THEME = 'aurora';
const FIXED_DARK = new Set(['titanium', 'neon', 'prism']);

/** Palette tokens that avatar colours may reference as "$name". */
export function themeTokens(id, scheme = 'light') {
  const t = THEMES[id] || THEMES[DEFAULT_THEME];
  const dark = FIXED_DARK.has(id) || scheme === 'dark';
  return {
    accent1: t.accent1, accent2: t.accent2, ink: t.ink,
    ok: t.health.ok, low: t.health.low, crit: t.health.crit,
    paper: dark ? '#26262b' : '#ffffff', unknown: '#9aa0a6', dark,
  };
}

export function toneColor(tokens, tone) {
  switch (tone) {
    case 'ok': return tokens.ok;
    case 'low': return tokens.low;
    case 'critical':
    case 'empty': return tokens.crit;
    default: return tokens.unknown;
  }
}

/** Writes the CSS variables the bubble and HUD styles read. */
export function applyThemeVars(el, id, scheme = 'light') {
  const t = THEMES[id] || THEMES[DEFAULT_THEME];
  const tokens = themeTokens(id, scheme);
  const b = t.bubble;
  const style = el.style;
  style.setProperty('--b-bg', tokens.dark ? b.bgD : b.bgL);
  style.setProperty('--b-fg', tokens.dark ? b.fgD : b.fgL);
  style.setProperty('--b-border', b.border === 'currentColor' ? (tokens.dark ? '#f5f5f7' : '#1d1d1f') : b.border);
  style.setProperty('--b-border-w', `${b.borderW}px`);
  style.setProperty('--b-radius', `${b.radius}px`);
  style.setProperty('--b-shadow', b.shadow);
  style.setProperty('--b-font', b.font);
  style.setProperty('--b-blur', `${b.blur}px`);
  style.setProperty('--accent1', tokens.accent1);
  style.setProperty('--accent2', tokens.accent2);
  style.setProperty('--ok', tokens.ok);
  style.setProperty('--low', tokens.low);
  style.setProperty('--crit', tokens.crit);
  style.setProperty('--unknown', tokens.unknown);
  el.dataset.theme = id;
  el.dataset.scheme = tokens.dark ? 'dark' : 'light';
  return tokens;
}
