// Avatar DSL -> three.js scene graph. The DSL is plain JSON (see pets/SPEC.md); this file is the only
// place that turns it into meshes, so the Python validator and this builder must agree on its vocabulary.

import * as THREE from '../vendor/three.pet.min.js';
import { buildProp } from './props.js';
import { DEG, TAU, clamp, desaturateHex } from './util.js';
import { identity } from './anim.js';

const OUTLINE_VERT = `
uniform float thickness;
void main() {
  vec3 p = position + normal * thickness;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
}`;
const OUTLINE_FRAG = `
uniform vec3 color;
uniform float opacity;
void main() {
  gl_FragColor = vec4(color, opacity);
  #include <colorspace_fragment>
}`;

const NO_OUTLINE = new Set(['group', 'disc', 'ring', 'plane', 'arc', 'screen']);

const gradientCache = new Map();
function gradient(steps) {
  if (!gradientCache.has(steps)) {
    const data = new Uint8Array(steps);
    for (let i = 0; i < steps; i++) data[i] = Math.round(70 + (185 * i) / Math.max(steps - 1, 1));
    const tex = new THREE.DataTexture(data, steps, 1, THREE.RedFormat, THREE.UnsignedByteType);
    tex.minFilter = tex.magFilter = THREE.NearestFilter;
    tex.needsUpdate = true;
    gradientCache.set(steps, tex);
  }
  return gradientCache.get(steps);
}

let softDot = null;
function softDotTexture() {
  if (softDot) return softDot;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 64;
  const g = canvas.getContext('2d');
  const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, 'rgba(255,255,255,1)');
  grad.addColorStop(0.55, 'rgba(255,255,255,.55)');
  grad.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grad;
  g.fillRect(0, 0, 64, 64);
  softDot = new THREE.CanvasTexture(canvas);
  softDot.colorSpace = THREE.SRGBColorSpace;
  return softDot;
}

function sideOf(name) {
  return name === 'back' ? THREE.BackSide : name === 'double' ? THREE.DoubleSide : THREE.FrontSide;
}

/** A tube bent into an arc whose index buffer runs along the arc, so a draw range shortens it. */
function arcGeometry({ radius = 0.8, tube = 0.05, start = 225, sweep = 270, segments = [8, 96] } = {}) {
  const [radial, tubular] = segments;
  const positions = [], normals = [], indices = [];
  for (let i = 0; i <= tubular; i++) {
    const a = (start - (sweep * i) / tubular) * DEG;
    const cx = Math.cos(a), cy = Math.sin(a);
    for (let j = 0; j <= radial; j++) {
      const v = (j / radial) * TAU;
      const r = radius + tube * Math.cos(v);
      positions.push(r * cx, r * cy, tube * Math.sin(v));
      normals.push(Math.cos(v) * cx, Math.cos(v) * cy, Math.sin(v));
    }
  }
  const stride = radial + 1;
  for (let i = 0; i < tubular; i++) {
    for (let j = 0; j < radial; j++) {
      const a = i * stride + j, b = (i + 1) * stride + j, c = (i + 1) * stride + j + 1, d = i * stride + j + 1;
      indices.push(a, d, b, b, d, c);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
  g.setIndex(indices);
  g.userData = { tubular, perSegment: radial * 6 };
  return g;
}

function shapeFor(spec) {
  const s = new THREE.Shape();
  const kind = typeof spec === 'string' ? spec : spec.kind || 'star';
  if (kind === 'heart') {
    s.moveTo(0, -0.9);
    s.bezierCurveTo(-1.3, 0.1, -0.9, 0.95, 0, 0.45);
    s.bezierCurveTo(0.9, 0.95, 1.3, 0.1, 0, -0.9);
  } else if (kind === 'drop') {
    s.moveTo(0, 1);
    s.bezierCurveTo(0.9, -0.1, 0.8, -1, 0, -1);
    s.bezierCurveTo(-0.8, -1, -0.9, -0.1, 0, 1);
  } else if (kind === 'bolt') {
    [[0.2, 1], [-0.7, -0.1], [-0.05, -0.1], [-0.3, -1], [0.7, 0.2], [0.05, 0.2]].forEach(([x, y], i) => (i ? s.lineTo(x, y) : s.moveTo(x, y)));
    s.closePath();
  } else if (spec && Array.isArray(spec.points)) {
    spec.points.forEach(([x, y], i) => (i ? s.lineTo(x, y) : s.moveTo(x, y)));
    s.closePath();
  } else {
    const points = (spec && spec.points) || 5, inner = (spec && spec.inner) || 0.45;
    for (let i = 0; i < points * 2; i++) {
      const r = i % 2 ? inner : 1, a = (Math.PI * i) / points + Math.PI / 2;
      const x = Math.cos(a) * r, y = Math.sin(a) * r;
      if (i) s.lineTo(x, y); else s.moveTo(x, y);
    }
    s.closePath();
  }
  return s;
}

function geometryFor(n) {
  const [a, b] = n.segments || [];
  switch (n.type) {
    case 'sphere': return new THREE.SphereGeometry(n.radius ?? 0.5, a ?? 28, b ?? 20);
    case 'capsule': return new THREE.CapsuleGeometry(n.radius ?? 0.12, n.length ?? 0.3, a ?? 6, b ?? 12);
    case 'box': {
      const [x, y, z] = n.size || [0.5, 0.5, 0.5];
      return n.round ? new THREE.RoundedBoxGeometry(x, y, z, 4, n.round) : new THREE.BoxGeometry(x, y, z);
    }
    case 'cylinder': return new THREE.CylinderGeometry(n.radiusTop ?? 0.2, n.radiusBottom ?? 0.2, n.height ?? 0.4, a ?? 20);
    case 'cone': return new THREE.ConeGeometry(n.radius ?? 0.2, n.height ?? 0.4, a ?? 20);
    case 'torus': return new THREE.TorusGeometry(n.radius ?? 0.5, n.tube ?? 0.05, a ?? 10, b ?? 40, (n.arc ?? 360) * DEG);
    case 'disc': return new THREE.CircleGeometry(n.radius ?? 0.1, a ?? 28);
    case 'ring': return new THREE.RingGeometry(n.inner ?? 0.08, n.outer ?? 0.1, a ?? 32, 1, (n.start ?? 0) * DEG, (n.arc ?? 360) * DEG);
    case 'plane': return new THREE.PlaneGeometry(...(n.size || [0.5, 0.5]));
    case 'lathe': return new THREE.LatheGeometry((n.points || [[0.1, 0], [0.3, 0.2], [0.1, 0.5]]).map(([r, y]) => new THREE.Vector2(r, y)), a ?? 24);
    case 'tube': return new THREE.TubeGeometry(new THREE.CatmullRomCurve3((n.path || [[0, 0, 0], [0, 0.3, 0]]).map((p) => new THREE.Vector3(...p))),
      b ?? 24, n.radius ?? 0.03, a ?? 8, Boolean(n.closed));
    case 'extrude': {
      const geometry = new THREE.ExtrudeGeometry(shapeFor(n.shape || 'star'), {
        depth: n.depth ?? 0.12, bevelEnabled: true, bevelThickness: n.bevel ?? 0.02, bevelSize: n.bevel ?? 0.02, bevelSegments: 2, curveSegments: 10,
      });
      geometry.center();
      const k = n.size ?? 0.2;
      geometry.scale(k, k, k);
      return geometry;
    }
    case 'arc': return arcGeometry({ radius: n.radius, tube: n.tube, start: n.start, sweep: n.sweep, segments: n.segments });
    case 'screen': return new THREE.PlaneGeometry(...(n.size || [0.4, 0.3]));
    default: return null;
  }
}

function vec3(v, fallback) {
  if (v == null) return fallback.slice();
  return Array.isArray(v) ? [v[0] ?? 0, v[1] ?? 0, v[2] ?? 0] : [v, v, v];
}

export class Rig {
  constructor(def, tokens) {
    this.def = def;
    this.tokens = tokens;
    this.desaturate = 0;
    this.root = new THREE.Group();
    this.nodes = new Map();
    this.rest = new Map();
    this.materials = new Map();
    this.slots = {};
    this.props = new Map();
    this.expression = null;
    this.glowBase = 1;
    this.meter = null;
    this.build();
  }

  resolve(key, depth = 0) {
    if (key == null || depth > 6) return null;
    if (key.startsWith('#')) return key;
    if (key.startsWith('$')) return this.tokens[key.slice(1)] || '#ff00ff';
    const palette = this.def.palette || {};
    return key in palette ? this.resolve(palette[key], depth + 1) : '#ff00ff';
  }

  paint(color) {
    return this.desaturate > 0 ? desaturateHex(color, this.desaturate) : color;
  }

  makeMaterial(name, d) {
    const common = {
      color: this.paint(this.resolve(d.color ?? '#ffffff')), side: sideOf(d.side),
      transparent: (d.opacity ?? 1) < 1 || d.texture === 'softdot', opacity: d.opacity ?? 1,
    };
    let m;
    switch (d.kind || 'toon') {
      case 'basic': m = new THREE.MeshBasicMaterial(common); break;
      case 'standard': m = new THREE.MeshStandardMaterial({ ...common, roughness: d.roughness ?? 0.55, metalness: d.metalness ?? 0 }); break;
      case 'lambert': m = new THREE.MeshLambertMaterial(common); break;
      default: m = new THREE.MeshToonMaterial({ ...common, gradientMap: gradient(d.steps ?? 3) });
    }
    if (d.emissive && 'emissive' in m) {
      m.emissive = new THREE.Color(this.paint(this.resolve(d.emissive)));
      m.emissiveIntensity = d.emissiveIntensity ?? 1;
    }
    if (d.texture === 'softdot') { m.map = softDotTexture(); m.depthWrite = false; }
    if (d.blend === 'add') m.blending = THREE.AdditiveBlending;
    if (d.decal) { m.polygonOffset = true; m.polygonOffsetFactor = -2; m.polygonOffsetUnits = -2; }
    m.userData = { color: d.color ?? '#ffffff', emissive: d.emissive || null, baseEmissive: d.emissiveIntensity ?? 1, baseOpacity: d.opacity ?? 1, glow: d.glow === true };
    this.materials.set(name, m);
    return m;
  }

  build() {
    const def = this.def;
    for (const [name, d] of Object.entries(def.materials || {})) this.makeMaterial(name, d);
    const fallback = new THREE.MeshToonMaterial({ color: '#ff00ff', gradientMap: gradient(3) });
    const outlineDefault = def.outline && def.outline.enabled !== false ? def.outline : null;
    const outlineColor = outlineDefault ? this.paint(this.resolve(outlineDefault.color || '$ink')) : null;
    this.outlineMaterials = [];

    for (const n of def.nodes || []) {
      let object;
      if (n.type === 'group') {
        object = new THREE.Group();
      } else {
        const geometry = geometryFor(n);
        if (!geometry) continue;
        const material = (n.material && this.materials.get(n.material)) || fallback;
        object = new THREE.Mesh(geometry, material);
        const want = n.outline ?? (outlineDefault && !NO_OUTLINE.has(n.type));
        if (want && outlineDefault) {
          const m = new THREE.ShaderMaterial({
            vertexShader: OUTLINE_VERT, fragmentShader: OUTLINE_FRAG, side: THREE.BackSide,
            uniforms: {
              thickness: { value: typeof want === 'number' ? want : outlineDefault.thickness ?? 0.014 },
              color: { value: new THREE.Color(outlineColor) }, opacity: { value: 1 },
            },
          });
          m.userData = { colorKey: outlineDefault.color || '$ink' };
          this.outlineMaterials.push(m);
          const shell = new THREE.Mesh(geometry, m);
          shell.name = `${n.id}:outline`;
          object.add(shell);
        }
        if (n.type === 'arc' || n.type === 'screen') object.material.side = THREE.DoubleSide;
      }
      object.name = n.id;
      const pos = vec3(n.position, [0, 0, 0]), rot = vec3(n.rotation, [0, 0, 0]), scl = vec3(n.scale, [1, 1, 1]);
      object.position.set(...pos);
      object.rotation.set(rot[0] * DEG, rot[1] * DEG, rot[2] * DEG);
      object.scale.set(...scl);
      if (n.visible === false) object.visible = false;
      this.rest.set(n.id, { pos, rot, scl });
      this.nodes.set(n.id, object);
      (n.parent ? this.nodes.get(n.parent) || this.root : this.root).add(object);
    }

    for (const [slot, id] of Object.entries(def.slots || {})) {
      if (this.nodes.has(id)) this.slots[slot] = this.nodes.get(id);
    }
    if (!this.slots.root) this.slots.root = this.root;

    const face = def.face || {};
    this.expressions = face.expressions || {};
    this.managed = new Set(face.managed || Object.values(this.expressions).flatMap((e) => [...(e.show || []), ...(e.hide || [])]));
    this.blinkNodes = (face.blink || []).filter((id) => this.nodes.has(id));
    this.lookNodes = (face.look || []).filter((l) => this.nodes.has(l.node));

    if (def.meter && this.nodes.has(def.meter.node)) {
      const node = this.nodes.get(def.meter.node);
      this.meter = { node, geometry: node.geometry, colors: def.meter.colors || {}, material: node.material };
      node.geometry.setDrawRange(0, 0);
    }
    this.buildProps();
  }

  buildProps() {
    for (const group of this.props.values()) group.parent && group.parent.remove(group);
    this.props.clear();
    for (const [name, p] of Object.entries(this.def.props || {})) {
      const group = buildProp(name, this.tokens);
      if (!group) continue;
      const pos = vec3(p.position, [0, 0, 0]), rot = vec3(p.rotation, [0, 0, 0]), scl = vec3(p.scale, [1, 1, 1]);
      group.position.set(...pos);
      group.rotation.set(rot[0] * DEG, rot[1] * DEG, rot[2] * DEG);
      group.scale.set(...scl);
      group.visible = false;
      (this.nodes.get(p.parent || 'root') || this.root).add(group);
      this.props.set(name, group);
    }
  }

  // ---- runtime controls

  setTokens(tokens) {
    this.tokens = tokens;
    this.refreshColors();
    this.buildProps();
  }

  setDesaturate(amount) {
    if (Math.abs(amount - this.desaturate) < 0.01) return;
    this.desaturate = amount;
    this.refreshColors();
  }

  refreshColors() {
    for (const m of this.materials.values()) {
      m.color.set(this.paint(this.resolve(m.userData.color)));
      if (m.userData.emissive) m.emissive.set(this.paint(this.resolve(m.userData.emissive)));
    }
    for (const m of this.outlineMaterials) m.uniforms.color.value.set(this.paint(this.resolve(m.userData.colorKey)));
    if (this.meterTone) this.setMeter(this.meterFrac, this.meterTone, true);
  }

  setExpression(name) {
    if (!name || name === this.expression) return;
    const e = this.expressions[name];
    if (!e) return;
    this.expression = name;
    const show = new Set(e.show || []);
    for (const id of this.managed) {
      const node = this.nodes.get(id);
      if (node) node.visible = show.has(id);
    }
  }

  hasExpression(name) {
    return name in this.expressions;
  }

  setBlink(k) {
    for (const id of this.blinkNodes) {
      const node = this.nodes.get(id);
      if (node) node.scale.y = this.rest.get(id).scl[1] * (1 - 0.92 * k);
    }
  }

  setLook(x, y) {
    for (const l of this.lookNodes) {
      const node = this.nodes.get(l.node);
      const rest = this.rest.get(l.node);
      node.position.x = rest.pos[0] + x * (l.range ? l.range[0] : 0.03);
      node.position.y = rest.pos[1] + y * (l.range ? l.range[1] : 0.02);
    }
  }

  setProps(show) {
    for (const [name, group] of this.props) group.visible = show.includes(name);
  }

  setGlow(v) {
    for (const m of this.materials.values()) {
      if (m.userData.glow && 'emissiveIntensity' in m) m.emissiveIntensity = m.userData.baseEmissive * v;
    }
  }

  /** frac in 0..1 or null (unknown). */
  setMeter(frac, tone, force = false) {
    if (!this.meter) return;
    this.meterFrac = frac;
    this.meterTone = tone;
    const g = this.meter.geometry;
    const { tubular, perSegment } = g.userData;
    const segments = frac == null ? 0 : frac <= 0 ? 0 : Math.max(1, Math.round(clamp(frac, 0, 1) * tubular));
    g.setDrawRange(0, segments * perSegment);
    const key = this.meter.colors[tone] || this.meter.colors.ok || '$accent1';
    const color = this.paint(this.resolve(tone === 'unknown' || frac == null ? this.meter.colors.unknown || '$unknown' : key));
    this.meter.material.color.set(color);
    if ('emissive' in this.meter.material) this.meter.material.emissive.set(color);
  }

  /** Applies a blended pose (slot -> offsets) on top of every slot node's rest transform. */
  applyPose(pose) {
    const rest = identity();
    for (const [slot, node] of Object.entries(this.slots)) {
      const r = this.rest.get(node.name) || { pos: [0, 0, 0], rot: [0, 0, 0], scl: [1, 1, 1] };
      const p = pose[slot] || rest;
      node.position.set(r.pos[0] + p.pos[0], r.pos[1] + p.pos[1], r.pos[2] + p.pos[2]);
      node.rotation.set((r.rot[0] + p.rot[0]) * DEG, (r.rot[1] + p.rot[1]) * DEG, (r.rot[2] + p.rot[2]) * DEG);
      node.scale.set(r.scl[0] * p.scl[0], r.scl[1] * p.scl[1], r.scl[2] * p.scl[2]);
    }
    const glow = pose.gauge ? pose.gauge.glow : 1;
    this.setGlow(glow);
    const shadow = this.slots.shadow;
    if (shadow) {
      const lift = pose.root ? clamp(pose.root.pos[1], 0, 0.6) : 0;
      const r = this.rest.get(shadow.name);
      const k = 1 - lift * 0.9;
      shadow.scale.set(r.scl[0] * k, r.scl[1] * k, r.scl[2] * k);
      if (shadow.material && shadow.material.userData) shadow.material.opacity = shadow.material.userData.baseOpacity * k;
    }
  }

  anchorWorld(name, out = new THREE.Vector3()) {
    const a = (this.def.anchors || {})[name];
    const node = a ? this.nodes.get(a.node) : this.slots[name === 'prop' ? 'armR' : name] || this.slots.root;
    const offset = a && a.offset ? a.offset : name === 'head' ? [0, 0.4, 0] : name === 'prop' ? [0, -0.3, 0.3] : [0, 0, 0];
    node.updateWorldMatrix(true, false);
    return node.localToWorld(out.set(...offset));
  }

  dispose() {
    this.root.traverse((o) => { if (o.geometry) o.geometry.dispose(); });
    for (const m of this.materials.values()) m.dispose();
    for (const m of this.outlineMaterials) m.dispose();
  }
}
