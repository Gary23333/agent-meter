// The client-side "mind": turns the latest PetFrame plus local interaction into what to show right now.
// Pure logic, no DOM, so it runs in Node tests and in the contact-sheet generator alike.

import { resolveAnimation, resolveExpression, toneOf } from './constants.js';
import { formatCountdown, mulberry32 } from './util.js';

export const DEFAULT_VOICE = {
  idle: ['今天也要好好用量～', '我在这儿看着额度呢。', '有需要就戳我一下。', '额度充足，心情不错！'],
  working: ['Agent 在干活，我给它加油！', '噼里啪啦～敲代码中。', '专注模式，别打扰我哦。'],
  busy: ['好多会话同时在跑，忙翻啦！', '手速拉满！', '冷静冷静，一个一个来。'],
  waiting: ['有 Agent 在等你确认哦！', '需要你看一眼～', '它在等你的回复。'],
  tired: ['额度有点见底了……', '能量不足，省着点用吧。', '我有点饿了。'],
  alarm: ['额度告急！！', '快没有了！要不要换个账号？', '红灯了红灯了！'],
  exhausted: ['额度用完了……躺平。', '电量耗尽，等重置吧。', '晕晕的……'],
  sleeping: ['Zzz……', '（呼呼）', '梦里额度满满。'],
  alert: ['有东西快到期啦！', '记得处理一下提醒～', '别让重置卡过期哦。'],
  focus: ['专注中，加油！', '我陪你一起专注。', '放下手机哦。'],
  excited: ['听说要重置了！', '期待期待～', '水晶球说有戏！'],
  confused: ['咦？数据好像过期了。', '额度读不到，我也不确定。', '这是怎么回事？'],
  offline: ['和后端失联了……', '线被拔掉了吗？', '等我重连一下。'],
  celebrate: ['耶！', '太棒了！', '撒花～'],
  eating: ['好吃好吃！', '吃 token 中～', '嚼嚼嚼。'],
  startle: ['哎呀！出错了？', '吓我一跳！'],
  wave: ['嗨～', '我回来啦！'],
  poke: ['嘿！', '别戳啦～', '怎么啦？'],
};

const REACTION_RANK = { startle: 4, celebrate: 3, painting: 2, eating: 1, wave: 0 };
// Only these states let the brain's mood choose the face; the others have a face that *is* the state.
const MOOD_DRIVEN = new Set(['idle', 'working', 'busy', 'focus']);
const BUBBLE_TTL = { danger: 14, warn: 12, good: 9, info: 9, chat: 5 };

export class Director {
  constructor(pack, { seed = 7, now = 0 } = {}) {
    this.pack = pack;
    this.rng = mulberry32(seed);
    this.frame = null;
    this.frameLocal = now;
    this.prefs = { calm: false, reduceMotion: false, chatter: true, followCursor: true, lowPower: false };
    this.overlay = null;          // timed reaction or interaction: {anim, until, key, kind}
    this.antic = null;
    this.held = false;
    this.petting = false;
    this.cursor = null;
    this.seenReactions = new Set();
    this.bubbles = [];
    this.lastState = null;
    this.lastChatter = -1e9;
    this.chatterN = 0;
    this.nextAnticAt = now + 6 + this.rng() * 8;
  }

  setPrefs(p) {
    Object.assign(this.prefs, p);
  }

  resolve(name) {
    return resolveAnimation(name, (n) => this.pack.has(n));
  }

  setCursor(x, y) {
    this.cursor = x == null ? null : { x, y };
  }

  /** Called with each PetFrame from the host. `now` is the local monotonic clock in seconds. */
  setFrame(frame, now) {
    this.frame = frame;
    this.frameLocal = now;
    for (const r of frame.reminders || []) {
      this.bubbles.push({ id: r.id, text: r.text || r.title, tone: r.tone || 'info', ttl: BUBBLE_TTL[r.tone] || 9,
        priority: r.priority ?? 30, action: r.action || null, source: r.source || null });
    }
    const reaction = frame.reaction;
    if (reaction && !this.seenReactions.has(reaction.key)) {
      this.seenReactions.add(reaction.key);
      if (this.seenReactions.size > 200) this.seenReactions = new Set([...this.seenReactions].slice(-100));
      const current = this.overlay && this.overlay.kind === 'reaction' ? REACTION_RANK[this.overlay.id] : -1;
      if ((REACTION_RANK[reaction.id] ?? 0) >= current) {
        const anim = this.resolve(reaction.id);
        const spec = this.pack.spec(anim);
        const remaining = Math.max(1.5, Math.min(12, (reaction.until ?? 0) - (frame.generated_at ?? 0)));
        this.overlay = { anim, id: reaction.id, kind: 'reaction', key: reaction.key, until: now + Math.min(remaining, spec.dur ?? remaining) };
      }
    }
  }

  say(bubble) {
    this.bubbles.push({ tone: 'info', ttl: 8, priority: 40, ...bubble });
  }

  drainBubbles() {
    const out = this.bubbles;
    this.bubbles = [];
    return out;
  }

  // ---- local interaction (called by the host bridge)

  poke(now) {
    this.playOverlay('poke', 'interaction', now);
    this.say({ id: `poke:${Math.floor(now * 10)}`, text: this.summaryLine(), tone: 'chat', ttl: 6, priority: 35 });
  }

  refresh(now) { this.playOverlay('refresh', 'interaction', now); }
  photo(now) { this.playOverlay('photo', 'interaction', now); }
  petStart() { this.petting = true; }
  petEnd() { this.petting = false; }
  dragStart() { this.held = true; this.antic = null; }
  dragEnd(now) { this.held = false; this.playOverlay('drop', 'interaction', now); }

  playOverlay(name, kind, now) {
    const anim = this.resolve(name);
    // An interaction lasts as long as *it* does, even when the pack only has a longer fallback to show
    // (a poke that falls back to celebrate must not turn into an 8 second party).
    const dur = this.pack.spec(name).dur ?? this.pack.spec(anim).dur ?? 1.2;
    this.overlay = { anim, id: name, kind, key: `${name}:${now}`, until: now + dur };
  }

  /** "Codex · 5 小时 还剩 82% · 2时31分 · 2 个会话进行中" without inventing anything unknown. */
  summaryLine() {
    const f = this.frame;
    if (!f) return '还没读到数据，稍等一下～';
    const parts = [];
    const e = f.energy || {};
    if (e.known) {
      parts.push(`${e.label || '额度'} 还剩 ${Math.round(e.remaining)}%`);
      if (e.resets_at && f.generated_at) parts.push(formatCountdown(e.resets_at - f.generated_at));
    } else if (e.stale) {
      parts.push('额度数据已过期，我也不确定');
    } else {
      parts.push('还没读到百分比额度');
    }
    const running = f.activity && f.activity.running;
    if (running) parts.push(`${running} 个会话进行中`);
    return parts.join(' · ');
  }

  // ---- per-tick decision

  update(dt, now) {
    const f = this.frame;
    const baseName = this.resolve(f ? f.state : 'idle');
    if (baseName !== this.lastState) {
      if (this.lastState !== null) this.onStateChange(baseName, now);
      this.lastState = baseName;
    }
    if (this.overlay && now >= this.overlay.until) this.overlay = null;
    if (this.antic && now >= this.antic.until) {
      this.antic = null;
      this.nextAnticAt = now + 10 + this.rng() * 15;
    }

    let anim = baseName;
    let layerKey = baseName;
    let kind = 'base';
    if (this.held) { anim = this.resolve('drag'); layerKey = 'drag'; kind = 'interaction'; }
    else if (this.overlay) { anim = this.overlay.anim; layerKey = `${this.overlay.kind}:${this.overlay.key}`; kind = this.overlay.kind; }
    else if (this.petting) { anim = this.resolve('pet'); layerKey = 'pet'; kind = 'interaction'; }
    else if (this.antic) { anim = this.antic.anim; layerKey = `antic:${this.antic.key}`; kind = 'antic'; }
    else if (baseName === 'idle' && !this.prefs.calm && !this.prefs.reduceMotion && now >= this.nextAnticAt) {
      const options = this.pack.antics();
      if (options.length) {
        const name = options[Math.floor(this.rng() * options.length)];
        const spec = this.pack.spec(name);
        this.antic = { anim: name, key: Math.floor(now * 10), until: now + (spec.dur ?? 1.5) };
        anim = name; layerKey = `antic:${this.antic.key}`; kind = 'antic';
      } else {
        this.nextAnticAt = now + 20;
      }
    }

    const spec = this.pack.spec(anim);
    let expression = spec.expression || 'neutral';
    if (kind === 'base' && MOOD_DRIVEN.has(baseName) && f && f.mood) expression = f.mood;
    expression = resolveExpression(expression, (n) => this.pack.hasExpression(n)) || 'neutral';

    const energy = f && f.energy && f.energy.known ? Math.max(0, Math.min(1, f.energy.remaining / 100)) : null;
    let fps = spec.fps ?? 20;
    if (this.prefs.reduceMotion) fps = Math.min(fps, 10);
    else if (this.prefs.lowPower) fps = Math.min(fps, 15);
    const look = spec.look || (this.prefs.followCursor && this.cursor ? this.cursor : null);
    return {
      animation: anim, layerKey, kind, base: baseName,
      intensity: kind === 'base' && f ? f.intensity ?? 0.5 : 0.7,
      expression, look, show: spec.show || [], fx: this.prefs.reduceMotion ? [] : spec.fx || [],
      energy, energyTone: f && f.energy ? f.energy.tone : 'unknown', drivesState: !!(f && f.energy && f.energy.drives_state),
      desaturate: spec.desaturate || 0, fps,
    };
  }

  onStateChange(state, now) {
    if (!this.prefs.chatter || this.prefs.calm || now - this.lastChatter < 90 || this.rng() > 0.6) return;
    const lines = (this.pack.voice && this.pack.voice[state]) || DEFAULT_VOICE[state];
    if (!lines || !lines.length) return;
    this.lastChatter = now;
    this.chatterN += 1;
    this.say({ id: `chat:${state}:${this.chatterN}`, text: lines[Math.floor(this.rng() * lines.length)], tone: 'chat', ttl: 5, priority: 5 });
  }

  /** Data for the HUD pill and the hover list. */
  hud(now) {
    const f = this.frame;
    if (!f) return { pill: null, meters: [], chips: [] };
    const e = f.energy || {};
    let pill = null;
    if (e.known) {
      pill = { text: `${Math.round(e.remaining)}%`, sub: e.resets_at && f.generated_at ? formatCountdown(e.resets_at - f.generated_at - (now - this.frameLocal)) : null,
        label: e.label, tone: e.tone, stale: e.stale };
    } else if (e.stale) {
      pill = { text: '过期', sub: null, label: '额度数据已过期', tone: 'unknown', stale: true };
    }
    const chips = ((f.activity && f.activity.apps) || []).map((a) => ({ label: a.label, count: a.count, project: a.project, app: a.app }));
    if (f.focus && f.focus.active) {
      chips.unshift({ label: '专注', count: 1, project: formatCountdown(f.focus.ends_at - f.generated_at - (now - this.frameLocal)) });
    }
    const threshold = 20;
    const meters = (f.meters || []).map((m) => ({ ...m, tone: m.tone || toneOf(m.remaining, threshold) }));
    return { pill, meters, chips };
  }
}
