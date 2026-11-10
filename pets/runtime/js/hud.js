// HUD under the pet: a capsule with the tightest relevant quota, an expandable list of every window
// (never summed), and chips for running sessions. Modes: off | pill | full.

import { formatCountdown } from './util.js';

const TONE_VAR = { ok: '--ok', low: '--low', critical: '--crit', empty: '--crit', unknown: '--unknown' };

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export class HudUI {
  constructor(el) {
    this.el = el;
    this.mode = 'pill';
    this.expanded = false;
    this.cache = '';
    el.innerHTML = '<div class="list"></div><div class="chips"></div><div class="pill"><i class="dot"></i><b></b><span class="sub"></span></div>';
    this.list = el.querySelector('.list');
    this.chips = el.querySelector('.chips');
    this.pill = el.querySelector('.pill');
    this.value = this.pill.querySelector('b');
    this.sub = this.pill.querySelector('.sub');
    this.dot = this.pill.querySelector('.dot');
  }

  setMode(mode) {
    this.mode = mode;
    this.el.dataset.mode = mode;
    this.el.hidden = mode === 'off';
    this.cache = '';
  }

  setExpanded(on) {
    if (this.expanded === on) return;
    this.expanded = on;
    this.el.classList.toggle('open', on);
  }

  /** Cheap to call every tick: the DOM is only touched when the rendered text changes. */
  update(model, now, frameAge = 0) {
    if (this.mode === 'off') return;
    const { pill, meters, chips } = model;
    const sig = JSON.stringify([pill, meters.map((m) => [m.id, Math.round(m.remaining), m.stale, m.resets_at && Math.floor((m.resets_at - frameAge) / 60)]), chips, this.mode]);
    if (sig === this.cache) return;
    this.cache = sig;
    this.pill.hidden = !pill;
    if (pill) {
      this.value.textContent = pill.text;
      this.sub.textContent = pill.sub || '';
      this.sub.hidden = !pill.sub;
      this.dot.style.background = `var(${TONE_VAR[pill.tone] || '--unknown'})`;
      this.pill.title = pill.label || '';
      this.pill.classList.toggle('stale', Boolean(pill.stale));
    }
    this.list.innerHTML = meters.map((m) => {
      const pct = Math.max(0, Math.min(100, m.remaining));
      const when = m.resets_at ? formatCountdown(m.resets_at - (model.baseTime || 0)) : '';
      return `<div class="row${m.stale ? ' stale' : ''}"><span class="name">${esc(m.name)} · ${esc(m.window)}</span>` +
        `<span class="bar"><i style="width:${pct}%;background:var(${TONE_VAR[m.tone] || '--unknown'})"></i></span>` +
        `<span class="val">${Math.round(m.remaining)}%</span><span class="when">${esc(when)}</span></div>`;
    }).join('');
    const shown = this.mode === 'full' ? chips : [];
    this.chips.innerHTML = shown.slice(0, 3).map((c) => `<span class="chip">${esc(c.label)}${c.count > 1 ? ` ×${c.count}` : ''}${c.project ? ` · ${esc(c.project)}` : ''}</span>`).join('');
  }

  rect() {
    if (this.mode === 'off' || this.el.hidden) return null;
    const target = this.expanded ? this.el : this.pill.hidden ? this.el : this.pill;
    const box = target.getBoundingClientRect();
    return { x: box.left, y: box.top, w: box.width, h: box.height };
  }
}
