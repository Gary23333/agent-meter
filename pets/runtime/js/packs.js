// Loads a pack's manifest (and avatar) over fetch. The same code runs against the native agentpet:// scheme
// and a plain static server during development.

import { PackModel } from './pack-model.js';

async function getJson(url) {
  const response = await fetch(url, { cache: 'no-store' });
  if (!response.ok) throw new Error(`${response.status} ${url}`);
  return response.json();
}

export function packBase(packRoot, id) {
  return new URL(`${id}/`, new URL(packRoot, location.href));
}

export async function loadPack(packRoot, id) {
  if (!/^[a-z0-9][a-z0-9-]{1,30}$/.test(id)) throw new Error(`bad pack id ${id}`);
  const base = packBase(packRoot, id);
  const manifest = await getJson(new URL('pet.json', base));
  if (manifest.format !== 'agentmeter-pet/1') throw new Error('unsupported pack format');
  if (manifest.id !== id) throw new Error('pack id does not match its folder');
  if (manifest.renderer !== 'three' && manifest.renderer !== 'sprite') throw new Error('unknown renderer');
  let avatar = null;
  if (manifest.renderer === 'three') {
    const file = (manifest.three && manifest.three.avatar) || 'avatar.json';
    if (/(^|\/)\.\.(\/|$)|^\//.test(file)) throw new Error('avatar path escapes the pack');
    avatar = await getJson(new URL(file, base));
    if (avatar.format !== 'agentmeter-avatar/1') throw new Error('unsupported avatar format');
  }
  return { model: new PackModel(manifest, avatar), base };
}

/** The pack list the host provides (agentpet://app/packs.json) or, in development, a static index. */
export async function listPacks(packRoot) {
  try {
    return await getJson(new URL('index.json', new URL(packRoot, location.href)));
  } catch {
    return [];
  }
}
