// What a loaded pack can do, independent of how it draws. The Director only talks to this interface.

import { RECIPES, applyOverride } from './recipes.js';

const SPRITE_ANTICS = ['antic_hop', 'antic_wiggle', 'antic_spin'];

export class PackModel {
  constructor(manifest, avatar = null) {
    this.manifest = manifest;
    this.id = manifest.id;
    this.name = manifest.name;
    this.renderer = manifest.renderer;
    this.voice = manifest.voice || {};
    this.avatar = avatar;
    this.sprite = manifest.sprite || null;
    this.expressions = new Set(avatar && avatar.face && avatar.face.expressions ? Object.keys(avatar.face.expressions) : []);
  }

  /** Whether the pack implements this animation itself (otherwise the caller follows the fallback chain). */
  has(name) {
    if (this.renderer === 'sprite') return Boolean(this.sprite && this.sprite.states && this.sprite.states[name]);
    return name in RECIPES && !name.startsWith('antic_');
  }

  hasExpression(name) {
    return this.expressions.has(name);
  }

  antics() {
    if (this.renderer === 'three') return Object.keys(RECIPES).filter((n) => n.startsWith('antic_'));
    return this.sprite && this.sprite.motion !== false ? SPRITE_ANTICS : [];
  }

  /** Merged, ready-to-play spec: recipe + the pack's override (three) or its strip (sprite). */
  spec(name) {
    if (this.renderer === 'three') {
      const base = RECIPES[name] || RECIPES.idle;
      return applyOverride(base, this.manifest.states && this.manifest.states[name]);
    }
    const recipe = RECIPES[name] || RECIPES.idle;
    const strip = (this.sprite && this.sprite.states && this.sprite.states[name]) || {};
    const motion = this.sprite && this.sprite.motion !== false;
    const rootOnly = (c) => c.t === 'root' || (c.t === 'body' && c.k === 'squash');
    return {
      fps: strip.fps ?? 8,
      loop: strip.loop !== false,
      dur: strip.dur ?? recipe.dur,
      fx: strip.fx ?? recipe.fx,
      desaturate: recipe.desaturate,
      pose: motion && recipe.pose && recipe.pose.root ? { root: recipe.pose.root } : {},
      channels: motion ? (recipe.channels || []).filter(rootOnly).map((c) => (c.t === 'body' ? { ...c, t: 'root' } : c)) : [],
      show: [],
    };
  }
}
