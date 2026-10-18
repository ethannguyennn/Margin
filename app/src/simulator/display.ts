import type { DiagramImage } from '../types';
import { CONTAINERS, GRAPHIC_CONTAINER, TILES } from '../ui/geometry';
import { graphicPng } from '../ui/sop-graphics';
import type { ScreenText } from '../ui/screens';

function png(bytes: Uint8Array): string {
  return `data:image/png;base64,${btoa(Array.from(bytes, b => String.fromCharCode(b)).join(''))}`;
}

/** Encoded PNG and the legacy raw grey formats accepted by the lens client. */
export function tileSource(base64: string): string {
  const bytes = Uint8Array.from(atob(base64), c => c.charCodeAt(0));
  if (bytes[0] === 137 && bytes[1] === 80 && bytes[2] === 78 && bytes[3] === 71) return png(bytes);
  if (![288 * 144, 288 * 144 / 2].includes(bytes.length)) throw new Error('Unsupported diagram format');
  const canvas = document.createElement('canvas'); canvas.width = 288; canvas.height = 144;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('Diagram preview unavailable');
  const image = context.createImageData(288, 144);
  for (let i = 0; i < 288 * 144; i++) {
    const value = bytes.length === 288 * 144 ? bytes[i] : ((bytes[i >> 1] >> (i % 2 ? 0 : 4)) & 15) * 17;
    image.data.set([value, value, value, 255], i * 4);
  }
  context.putImageData(image, 0, 0);
  return canvas.toDataURL('image/png');
}

/** A responsive logical 576x288 canvas. Firmware font metrics are approximate. */
export class BrowserLensDisplay {
  readonly element = document.createElement('div');
  private plane = document.createElement('div');
  private texts = new Map<string, HTMLElement>();
  private pictures = document.createElement('div');
  private observer?: ResizeObserver;
  private epoch = 0;

  constructor() {
    this.element.className = 'lens-sim-display';
    this.element.setAttribute('role', 'img');
    this.plane.className = 'lens-sim-plane';
    for (const container of CONTAINERS) {
      const node = document.createElement('div');
      node.className = `lens-sim-text lens-sim-${container.containerName}`;
      Object.assign(node.style, { top: `${container.yPosition}px`, height: `${container.height}px`,
        padding: `${container.paddingLength}px`, opacity: container.textColor === 4 ? '1' : '0.65' });
      this.texts.set(container.containerName, node); this.plane.append(node);
    }
    this.plane.append(this.pictures); this.element.append(this.plane);
    if (typeof ResizeObserver !== 'undefined') {
      this.observer = new ResizeObserver(entries => {
        this.plane.style.transform = `scale(${entries[0].contentRect.width / 576})`;
      });
      this.observer.observe(this.element);
    }
  }

  async render(text: ScreenText, screen: string, diagram?: DiagramImage): Promise<void> {
    const epoch = ++this.epoch;
    this.element.dataset.screen = screen;
    this.element.setAttribute('aria-label', [screen.replaceAll('_', ' '), text.header, text.main, text.footer].filter(Boolean).join('. '));
    this.pictures.replaceChildren();
    for (const [name, node] of this.texts) {
      node.textContent = text[name as 'header' | 'main' | 'footer'];
      node.hidden = screen === 'DIAGRAM' && name === 'main';
      node.style.width = name === 'main' && text.graphic_id ? '280px' : '576px';
    }
    if (screen === 'DIAGRAM' && diagram) {
      for (const tile of diagram.tiles) {
        if (tile.slot !== 0 && tile.slot !== 1) continue;
        this.image(tileSource(tile.image), TILES[tile.slot].xPosition, 48, 'Diagram tile');
      }
    } else if (text.graphic_id) {
      const bytes = await graphicPng(text.graphic_id);
      if (epoch !== this.epoch) return; // late images never outlive their step
      this.image(png(bytes), GRAPHIC_CONTAINER.xPosition, GRAPHIC_CONTAINER.yPosition, 'SOP reference');
    }
  }

  private image(src: string, x: number, y: number, alt: string) {
    const image = document.createElement('img'); image.src = src; image.alt = alt;
    image.width = 288; image.height = 144; image.className = 'lens-sim-image';
    image.style.left = `${x}px`; image.style.top = `${y}px`; this.pictures.append(image);
  }

  dispose() { this.epoch++; this.observer?.disconnect(); }
}
