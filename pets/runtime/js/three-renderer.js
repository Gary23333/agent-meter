// three.js renderer: scene, camera, lights, and the glue between a Rig and the Director's view.

import * as THREE from '../vendor/three.pet.min.js';
import { Rig } from './avatar-builder.js';
import { Blender } from './anim.js';
import { clamp, damp, mulberry32 } from './util.js';

function lightsFor(kind, tokens, scene) {
  const color = (key) => (key.startsWith('$') ? tokens[key.slice(1)] : key);
  if (kind === 'neon') {
    scene.add(new THREE.AmbientLight(0x7a6cff, 0.9));
    const key = new THREE.DirectionalLight(0xffffff, 1.4);
    key.position.set(1.5, 3, 4.5);
    const right = new THREE.DirectionalLight(color('$accent2'), 2.2);
    right.position.set(4, 1.5, 1.5);
    const left = new THREE.DirectionalLight(color('$accent1'), 2.0);
    left.position.set(-4, 1.2, 1);
    scene.add(key, right, left);
  } else if (kind === 'studio') {
    scene.add(new THREE.AmbientLight(0xffffff, 0.75));
    const key = new THREE.DirectionalLight(0xffffff, 2.4);
    key.position.set(2.5, 4, 4.5);
    const rim = new THREE.DirectionalLight(0xbfd4ff, 1.2);
    rim.position.set(-3, 2, -3);
    scene.add(key, rim);
  } else {
    scene.add(new THREE.HemisphereLight(0xffffff, 0xcfc8ee, 1.25));
    const key = new THREE.DirectionalLight(0xffffff, 2.0);
    key.position.set(2.5, 3.5, 4.5);
    scene.add(key);
  }
}

export class ThreeRenderer {
  constructor(container, model, { width, height, dpr = 2, tokens, preserve = false, seed = 11 }) {
    this.container = container;
    this.model = model;
    this.width = width;
    this.height = height;
    this.dpr = Math.min(dpr, 2);
    this.tokens = tokens;
    this.preserve = preserve;
    this.t = 0;
    this.layerKey = null;
    this.view = { animation: 'idle', intensity: 0.5, expression: 'neutral', look: null, show: [], energy: null, energyTone: 'unknown', desaturate: 0 };
    this.lookX = 0;
    this.lookY = 0;
    this.rng = mulberry32(seed);
    this.nextBlink = 2 + this.rng() * 3;
    this.blinking = false;
    this.frozen = false;
  }

  async init() {
    const cfg = this.model.manifest.three || {};
    this.renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, premultipliedAlpha: true,
      powerPreference: 'low-power', preserveDrawingBuffer: this.preserve });
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.setPixelRatio(this.dpr);
    this.renderer.setSize(this.width, this.height, false);
    const canvas = this.renderer.domElement;
    Object.assign(canvas.style, { position: 'absolute', left: '0', top: '0', width: '100%', height: '100%', display: 'block' });
    this.container.prepend(canvas);
    this.canvas = canvas;

    this.scene = new THREE.Scene();
    const cam = cfg.camera || {};
    this.camera = new THREE.PerspectiveCamera(cam.fov ?? 28, this.width / this.height, 0.1, 60);
    this.camera.position.set(...(cam.position || [0, 0.95, 6.2]));
    this.camera.lookAt(...(cam.target || [0, 0.78, 0]));
    lightsFor(cfg.lights || 'soft', this.tokens, this.scene);

    this.rig = new Rig(this.model.avatar, this.tokens);
    this.scene.add(this.rig.root);
    this.blender = new Blender(0.28);
    this.rig.setExpression('neutral');
    this.apply(0);
    this.computeBounds();
  }

  setTokens(tokens) {
    this.tokens = tokens;
    this.rig.setTokens(tokens);
    this.rig.setMeter(this.view.energy, this.view.energyTone, true);
  }

  setView(view) {
    this.view = view;
    if (view.layerKey !== this.layerKey) {
      this.layerKey = view.layerKey;
      this.blender.set(view.animation, this.model.spec(view.animation), true);
    }
    this.rig.setExpression(view.expression);
    this.rig.setProps(view.show || []);
    this.rig.setDesaturate(view.desaturate || 0);
    this.rig.setMeter(view.energy, view.energyTone);
  }

  /** Advances animation by dt seconds. */
  advance(dt) {
    this.t += dt;
    this.blender.step(dt);
    this.apply(dt);
  }

  apply(dt) {
    const pose = this.blender.evaluate(this.view.intensity);
    this.rig.applyPose(pose);
    const look = this.view.look || { x: 0, y: 0 };
    this.lookX = dt > 0 ? damp(this.lookX, look.x, 9, dt) : look.x;
    this.lookY = dt > 0 ? damp(this.lookY, look.y, 9, dt) : look.y;
    this.rig.setLook(clamp(this.lookX, -1, 1), clamp(this.lookY, -1, 1));
    if (!this.frozen) {
      if (!this.blinking && this.t >= this.nextBlink) { this.blinking = true; this.blinkStart = this.t; }
      let k = 0;
      if (this.blinking) {
        const u = (this.t - this.blinkStart) / 0.16;
        k = u >= 1 ? 0 : 1 - Math.abs(u * 2 - 1);
        if (u >= 1) { this.blinking = false; this.nextBlink = this.t + 2.2 + this.rng() * 3.6; }
      }
      this.rig.setBlink(k);
    }
  }

  /** Deterministic pose for contact sheets: settles the blender at time t with no blinking. */
  seek(t) {
    this.frozen = true;
    this.blender.seek(t);
    this.t = t;
    this.rig.setBlink(0);
    this.apply(0);
  }

  render() {
    this.renderer.render(this.scene, this.camera);
  }

  project(vector) {
    const v = vector.clone().project(this.camera);
    return { x: (v.x * 0.5 + 0.5) * this.width, y: (1 - (v.y * 0.5 + 0.5)) * this.height };
  }

  anchor(name) {
    return this.project(this.rig.anchorWorld(name));
  }

  computeBounds() {
    this.rig.root.updateMatrixWorld(true);
    const box = new THREE.Box3();
    this.rig.root.traverse((o) => {
      if (o.isMesh && o.visible && !o.name.endsWith(':outline') && o.userData.prop !== true) box.expandByObject(o);
    });
    if (box.isEmpty()) { this.bbox = { x: 0, y: 0, w: this.width, h: this.height }; return; }
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) {
      const p = this.project(new THREE.Vector3(x, y, z));
      minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x); minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
    }
    const padX = (maxX - minX) * 0.08, padY = (maxY - minY) * 0.08;
    this.bbox = { x: Math.max(0, minX - padX), y: Math.max(0, minY - padY),
      w: Math.min(this.width, maxX + padX) - Math.max(0, minX - padX), h: Math.min(this.height, maxY + padY) - Math.max(0, minY - padY) };
  }

  bounds() {
    return this.bbox;
  }

  resize(width, height, dpr = this.dpr) {
    this.width = width;
    this.height = height;
    this.dpr = Math.min(dpr, 2);
    this.renderer.setPixelRatio(this.dpr);
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.computeBounds();
  }

  dispose() {
    this.rig.dispose();
    this.renderer.dispose();
    this.canvas.remove();
  }
}
