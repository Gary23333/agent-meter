// HUD under the pet: a capsule with the tightest relevant quota, an expandable list of every window
// (never summed), and chips for running sessions. Modes: off | pill | full.

import { formatCountdown, unionRects, chipUnder } from './util.js';

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
    this.chips.innerHTML = shown.slice(0, 3).map((c) => {
      const app = c.app ? ` class="chip app" data-app="${esc(c.app)}" title="点击打开应用"` : ' class="chip"';
      return `<span${app}>${esc(c.label)}${c.count > 1 ? ` ×${c.count}` : ''}${c.project ? ` · ${esc(c.project)}` : ''}</span>`;
    }).join('');
  }

  chipRects() {
    return Array.from(this.chips.querySelectorAll('.chip')).map((el) => {
      const b = el.getBoundingClientRect();
      return { app: el.dataset.app || null, x: b.left, y: b.top, w: b.width, h: b.height };
    });
  }

  chipAt(x, y) {
    return chipUnder(this.chipRects(), x, y);
  }

  rect() {
    if (this.mode === 'off' || this.el.hidden) return null;
    const box = (el) => { const b = el.getBoundingClientRect(); return { x: b.left, y: b.top, w: b.width, h: b.height }; };
    if (this.expanded) return box(this.el);
    // The chips are clickable too, so the native overlay must not let clicks on them fall through.
    return unionRects([this.pill.hidden ? null : box(this.pill), this.chips.childElementCount ? box(this.chips) : null]);
  }
}
