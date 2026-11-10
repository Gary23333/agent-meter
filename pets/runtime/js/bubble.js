// Speech bubble: one at a time, by priority, themed through CSS variables. DOM only; the Director decides
// what to say, this decides when and where it appears.

const MAX_QUEUE = 8;
const GAP_AFTER = 0.5;
const SWAP_MARGIN = 20;

export class BubbleUI {
  constructor(el, { onAction = () => {}, onShown = () => {} } = {}) {
    this.el = el;
    this.text = el.querySelector('.b-text');
    this.onAction = onAction;
    this.onShown = onShown;
    this.queue = [];
    this.current = null;
    this.until = 0;
    this.nextAt = 0;
    this.hovered = false;
    this.seen = new Set();
  }

  push(bubble) {
    if (!bubble || !bubble.text) return;
    if (bubble.id && (this.seen.has(bubble.id) || (this.current && this.current.id === bubble.id) || this.queue.some((q) => q.id === bubble.id))) return;
    if (bubble.id) {
      this.seen.add(bubble.id);
      if (this.seen.size > 300) this.seen = new Set([...this.seen].slice(-150));
    }
    // Idle chatter never queues behind real news.
    if (bubble.tone === 'chat' && (this.current && this.current.tone !== 'chat' || this.queue.length)) return;
    this.queue.push(bubble);
    this.queue.sort((a, b) => (b.priority ?? 30) - (a.priority ?? 30));
    if (this.queue.length > MAX_QUEUE) this.queue.length = MAX_QUEUE;
  }

  update(now) {
    if (this.current) {
      const urgent = this.queue[0] && (this.queue[0].priority ?? 30) >= (this.current.priority ?? 30) + SWAP_MARGIN;
      if ((now >= this.until && !this.hovered) || urgent) this.hide(now);
    }
    if (!this.current && this.queue.length && now >= this.nextAt) this.show(this.queue.shift(), now);
  }

  show(bubble, now) {
    this.current = bubble;
    this.until = now + (bubble.ttl ?? 8);
    this.text.textContent = bubble.text;
    this.el.dataset.tone = bubble.tone || 'info';
    this.el.classList.toggle('clickable', Boolean(bubble.action));
    this.el.hidden = false;
    // Restart the entrance transition.
    this.el.classList.remove('in');
    void this.el.offsetWidth;
    this.el.classList.add('in');
    if (bubble.id) this.onShown(bubble);
  }

  hide(now) {
    this.current = null;
    this.nextAt = now + GAP_AFTER;
    this.el.classList.remove('in');
    this.el.hidden = true;
  }

  /** Puts the bubble above the pet's silhouette; `cx` is where the tail should point. */
  place(rootWidth, top, cx) {
    if (!this.current) return;
    const w = this.el.offsetWidth, h = this.el.offsetHeight;
    const left = Math.max(8, Math.min(rootWidth - w - 8, cx - w / 2));
    this.el.style.left = `${left}px`;
    this.el.style.top = `${Math.max(4, top - h - 12)}px`;
    this.el.style.setProperty('--tail-x', `${Math.max(14, Math.min(w - 14, cx - left))}px`);
  }

  rect() {
    if (!this.current) return null;
    return { x: this.el.offsetLeft, y: this.el.offsetTop, w: this.el.offsetWidth, h: this.el.offsetHeight };
  }

  hit(x, y) {
    const r = this.rect();
    return Boolean(r && x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h);
  }

  setHovered(on) {
    this.hovered = on;
  }

  /** Click: runs the action, if any, and dismisses. Returns the bubble that was clicked. */
  click(now) {
    const clicked = this.current;
    if (!clicked) return null;
    if (clicked.action) this.onAction(clicked);
    this.hide(now);
    return clicked;
  }
}
