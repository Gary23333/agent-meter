// Built-in props. A pack opts in by naming them in avatar.json "props" and states reveal them with "show".
// Everything here is plain three.js primitives so a prop costs a few hundred triangles at most.

import * as THREE from '../vendor/three.pet.min.js';

function mesh(geometry, color, { emissive = null, emissiveIntensity = 0, roughness = 0.6, metalness = 0, opacity = 1 } = {}) {
  const material = new THREE.MeshStandardMaterial({ color, roughness, metalness, opacity, transparent: opacity < 1 });
  if (emissive) { material.emissive = new THREE.Color(emissive); material.emissiveIntensity = emissiveIntensity; }
  const m = new THREE.Mesh(geometry, material);
  m.userData.prop = true;
  return m;
}

export const PROP_BUILDERS = {
  laptop(c) {
    const g = new THREE.Group();
    const base = mesh(new THREE.BoxGeometry(0.62, 0.035, 0.42), c.silver, { metalness: 0.5, roughness: 0.4 });
    const keys = mesh(new THREE.PlaneGeometry(0.5, 0.26), '#4a4a63');
    keys.rotation.x = -Math.PI / 2;
    keys.position.set(0, 0.019, 0.04);
    const lid = new THREE.Group();
    lid.position.set(0, 0.21, -0.2);
    lid.rotation.x = -0.18;
    const shell = mesh(new THREE.BoxGeometry(0.62, 0.4, 0.03), c.silver, { metalness: 0.5, roughness: 0.4 });
    const bezel = mesh(new THREE.PlaneGeometry(0.58, 0.36), '#1c1c2e');
    bezel.position.z = 0.0165;
    const screen = mesh(new THREE.PlaneGeometry(0.52, 0.3), '#2b2b4a', { emissive: c.screen, emissiveIntensity: 0.18 });
    screen.position.z = 0.017;
    lid.add(shell, bezel, screen);
    [[0.34, 0.095, c.accent], [0.22, 0.045, '#ffffff'], [0.4, -0.005, c.screen], [0.16, -0.055, '#ffffff'], [0.3, -0.105, c.accent]].forEach(([w, y, color], i) => {
      const line = mesh(new THREE.PlaneGeometry(w, 0.022), color, { emissive: color, emissiveIntensity: 0.6 });
      line.position.set(-0.24 + w / 2 + (i % 2 ? 0.05 : 0), y, 0.018);
      lid.add(line);
    });
    g.add(base, keys, lid);
    g.userData.screen = screen;
    return g;
  },
  brush(c) {
    const g = new THREE.Group();
    const handle = mesh(new THREE.CylinderGeometry(0.018, 0.026, 0.46, 10), c.wood);
    const ferrule = mesh(new THREE.CylinderGeometry(0.03, 0.022, 0.07, 10), c.silver, { metalness: 0.6 });
    ferrule.position.y = 0.26;
    const tip = mesh(new THREE.ConeGeometry(0.032, 0.11, 10), c.accent, { emissive: c.accent, emissiveIntensity: 0.4 });
    tip.position.y = 0.345;
    g.add(handle, ferrule, tip);
    return g;
  },
  sign(c) {
    const g = new THREE.Group();
    const pole = mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.5, 8), c.silver, { metalness: 0.5 });
    pole.position.y = 0.0;
    const board = mesh(new THREE.CylinderGeometry(0.2, 0.2, 0.03, 28), c.accent, { emissive: c.accent, emissiveIntensity: 0.35 });
    board.rotation.x = Math.PI / 2;
    board.position.y = 0.32;
    const bar = mesh(new THREE.BoxGeometry(0.05, 0.16, 0.02), '#ffffff');
    bar.position.set(0, 0.35, 0.02);
    const dot = mesh(new THREE.SphereGeometry(0.03, 12, 10), '#ffffff');
    dot.position.set(0, 0.23, 0.02);
    g.add(pole, board, bar, dot);
    return g;
  },
  plug(c) {
    const g = new THREE.Group();
    const cable = new THREE.TubeGeometry(new THREE.CatmullRomCurve3([
      new THREE.Vector3(-0.55, 0.02, 0.1), new THREE.Vector3(-0.35, 0.02, 0.28), new THREE.Vector3(-0.12, 0.02, 0.2),
      new THREE.Vector3(0.1, 0.02, 0.32), new THREE.Vector3(0.3, 0.07, 0.24)]), 24, 0.018, 8, false);
    const wire = mesh(cable, c.ink);
    const head = mesh(new THREE.BoxGeometry(0.1, 0.07, 0.07), c.ink);
    head.position.set(0.34, 0.09, 0.22);
    head.rotation.z = 0.5;
    const pinA = mesh(new THREE.BoxGeometry(0.05, 0.012, 0.012), c.silver, { metalness: 0.8 });
    pinA.position.set(0.4, 0.13, 0.2);
    pinA.rotation.z = 0.5;
    const pinB = pinA.clone();
    pinB.position.z = 0.24;
    g.add(wire, head, pinA, pinB);
    return g;
  },
  headphones(c) {
    const g = new THREE.Group();
    const band = mesh(new THREE.TorusGeometry(0.34, 0.03, 10, 36, Math.PI), c.ink);
    band.rotation.z = 0;
    const cupL = mesh(new THREE.CylinderGeometry(0.11, 0.11, 0.1, 18), c.accent, { emissive: c.accent, emissiveIntensity: 0.25 });
    cupL.rotation.z = Math.PI / 2;
    cupL.position.set(-0.36, 0.0, 0);
    const cupR = cupL.clone();
    cupR.position.x = 0.36;
    g.add(band, cupL, cupR);
    return g;
  },
  crystal(c) {
    const g = new THREE.Group();
    const base = mesh(new THREE.CylinderGeometry(0.1, 0.13, 0.07, 16), c.wood);
    const ball = mesh(new THREE.SphereGeometry(0.15, 24, 18), c.glass, { emissive: c.glass, emissiveIntensity: 0.55, opacity: 0.85, roughness: 0.1 });
    ball.position.y = 0.17;
    const glint = mesh(new THREE.SphereGeometry(0.03, 8, 6), '#ffffff', { emissive: '#ffffff', emissiveIntensity: 1 });
    glint.position.set(-0.06, 0.24, 0.1);
    g.add(base, ball, glint);
    g.userData.ball = ball;
    return g;
  },
  resetter(c) {
    const g = new THREE.Group();
    const body = mesh(new THREE.BoxGeometry(0.46, 0.3, 0.26), '#dfe4f2', { metalness: 0.2, roughness: 0.5 });
    body.position.y = 0.15;
    const screen = mesh(new THREE.PlaneGeometry(0.3, 0.1), '#10162a', { emissive: c.accent, emissiveIntensity: 0.5 });
    screen.position.set(0, 0.22, 0.131);
    const led = [c.accent, '#5eead4', '#ffd04a'].map((color, i) => {
      const dot = mesh(new THREE.SphereGeometry(0.014, 8, 6), color, { emissive: color, emissiveIntensity: 1 });
      dot.position.set(-0.07 + i * 0.07, 0.29, 0.131);
      return dot;
    });
    const button = mesh(new THREE.CylinderGeometry(0.06, 0.07, 0.05, 20), '#ff4d5e', { emissive: '#ff4d5e', emissiveIntensity: 0.35, roughness: 0.35 });
    button.position.set(0, 0.075, 0.131);
    button.rotation.x = Math.PI / 2;
    g.add(body, screen, button, ...led);
    return g;
  },
  fish(c) {
    const g = new THREE.Group();
    const body = mesh(new THREE.SphereGeometry(0.12, 16, 12), c.accent, { roughness: 0.4 });
    body.scale.set(1.6, 0.8, 0.6);
    const tail = mesh(new THREE.ConeGeometry(0.09, 0.14, 4), c.accent);
    tail.rotation.z = -Math.PI / 2;
    tail.position.x = -0.26;
    const eye = mesh(new THREE.SphereGeometry(0.018, 8, 6), c.ink);
    eye.position.set(0.14, 0.03, 0.07);
    g.add(body, tail, eye);
    return g;
  },
};

export function propColors(tokens) {
  return {
    silver: '#cfd3dc', screen: tokens.accent2, wood: '#b98a5a', accent: tokens.accent1, ink: '#2a2540',
    glass: tokens.accent2,
  };
}

export function buildProp(name, tokens) {
  const make = PROP_BUILDERS[name];
  return make ? make(propColors(tokens)) : null;
}
