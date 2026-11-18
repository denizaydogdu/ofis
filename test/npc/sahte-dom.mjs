// Test support (test/test_npc.py): a minimal fake DOM and renderer so web/scene.js can build the office in node (no
// WebGL) and the test can count what one frame would draw.
const noop = () => {};
function el(tag = 'div') {
  const e = { tagName: tag.toUpperCase(), style: {}, children: [], className: '', title: '', textContent: '', hidden: false,
    clientWidth: 1440, clientHeight: 820, offsetWidth: 90, offsetHeight: 20, width: 300, height: 150, parentElement: null,
    addEventListener: noop, removeEventListener: noop, dispatchEvent: noop, setPointerCapture: noop, releasePointerCapture: noop,
    appendChild(c) { this.children.push(c); c.parentElement = this; return c; }, append(...c) { this.children.push(...c); },
    remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter((x) => x !== this); },
    replaceChildren(...c) { this.children = c; }, setAttribute: noop, getAttribute: () => null, getRootNode() { return el(); },
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 1440, height: 820 }), classList: { add: noop, remove: noop, toggle: noop },
    getContext: () => new Proxy({}, { get: (t, k) => (k === 'measureText' ? () => ({ width: 50 }) : k === 'canvas' ? e : typeof k === 'string' && /^create/.test(k) ? () => ({ addColorStop: noop }) : typeof k === 'string' && /^(fillStyle|strokeStyle|font|lineWidth|textAlign|textBaseline|globalAlpha)$/.test(k) ? '' : noop), set: () => true }),
    ownerDocument: null };
  return e;
}
globalThis.document = { createElement: el, documentElement: el('html'), hidden: false, body: el('body'), addEventListener: noop };
globalThis.window = { devicePixelRatio: 2, innerWidth: 1440, innerHeight: 900, addEventListener: noop, removeEventListener: noop };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '360' });
globalThis.ResizeObserver = class { observe() {} };
globalThis.requestAnimationFrame = () => 0;
globalThis.PointerEvent = class {};
globalThis.Image = class { set src(v) {} addEventListener() {} };
globalThis.fetch = async () => ({ ok: false });
export class FakeRenderer {
  constructor() { this.domElement = el('canvas'); this.shadowMap = {}; this.calls = 0; }
  setPixelRatio() {} setSize() {} dispose() {}
  render(scene) { this.calls++; }
}
export { el };
