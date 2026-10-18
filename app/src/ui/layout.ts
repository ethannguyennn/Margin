import { TextContainerProperty, TextContainerUpgrade, CreateStartUpPageContainer, RebuildPageContainer,
  ImageContainerProperty, ImageRawDataUpdate, ImageRawDataUpdateResult, type EvenAppBridge } from '@evenrealities/even_hub_sdk';
import type { ScreenText } from './screens';
import { getGraphic, graphicPixels, GRAPHIC_WIDTH, GRAPHIC_HEIGHT } from './sop-graphics';

export const CONTAINERS = [
  { containerID: 1, containerName: 'header', yPosition: 0, height: 40, textColor: 2, isEventCapture: 0, paddingLength: 4 },
  { containerID: 2, containerName: 'main', yPosition: 48, height: 184, textColor: 4, isEventCapture: 1, paddingLength: 8 },
  { containerID: 3, containerName: 'footer', yPosition: 240, height: 48, textColor: 2, isEventCapture: 0, paddingLength: 4 },
] as const;

export const GRAPHIC_CONTAINER = { containerID: 4, containerName: 'sop-reference',
  xPosition: 288, yPosition: 68, width: GRAPHIC_WIDTH, height: GRAPHIC_HEIGHT } as const;

export function createLayout(text: ScreenText): CreateStartUpPageContainer {
  const illustrated = getGraphic(text.graphic_id) !== null;
  return new CreateStartUpPageContainer({ containerTotalNum: CONTAINERS.length + Number(illustrated),
    textObject: CONTAINERS.map(c => new TextContainerProperty({ ...c, xPosition: 0,
      width: illustrated && c.containerName === 'main' ? 280 : 576,
      borderWidth: 0, borderColor: 0, borderRadius: 0, content: text[c.containerName] || ' ' })),
    ...(illustrated ? { imageObject: [new ImageContainerProperty(GRAPHIC_CONTAINER)] } : {}) });
}

export type DisplayBridge = Pick<EvenAppBridge, 'createStartUpPageContainer' | 'textContainerUpgrade'> &
  Partial<Pick<EvenAppBridge, 'rebuildPageContainer' | 'updateImageRawData'>>;
/** Rebuild only when adding/removing the picture; text and image updates otherwise stay local. */
export class LensDisplay {
  private previous: ScreenText | null = null;
  constructor(private readonly bridge: DisplayBridge, private readonly rasterize = graphicPixels) {}
  async render(text: ScreenText): Promise<void> {
    const graphic = getGraphic(text.graphic_id);
    const previousGraphic = getGraphic(this.previous?.graphic_id);
    const changedLayout = Boolean(graphic) !== Boolean(previousGraphic);
    const pixels = graphic && (graphic.id !== previousGraphic?.id || !this.previous) ?
      await this.rasterize(graphic.id) : null;
    if (graphic && previousGraphic && graphic.id !== previousGraphic.id) {
      // Clear the old reference before new instructions; a failed upload must never pair them.
      const cleared = await this.bridge.updateImageRawData?.(new ImageRawDataUpdate({
        containerID: GRAPHIC_CONTAINER.containerID, containerName: GRAPHIC_CONTAINER.containerName,
        imageData: new Uint8Array(GRAPHIC_WIDTH * GRAPHIC_HEIGHT),
      }));
      if (cleared === undefined || !ImageRawDataUpdateResult.isSuccess(cleared)) {
        throw new Error('SOP reference image clear failed');
      }
    }
    if (!this.previous) {
      const result = await this.bridge.createStartUpPageContainer(createLayout(text));
      if (result !== 0) throw new Error(`Startup page failed: ${result}`);
    } else if (changedLayout) {
      const layout = createLayout(text);
      if (!this.bridge.rebuildPageContainer || !await this.bridge.rebuildPageContainer(new RebuildPageContainer({
        containerTotalNum: layout.containerTotalNum, textObject: layout.textObject, imageObject: layout.imageObject,
      }))) throw new Error('SOP reference layout update failed');
    } else {
      for (const c of CONTAINERS) {
        if (this.previous[c.containerName] === text[c.containerName]) continue;
        const ok = await this.bridge.textContainerUpgrade(new TextContainerUpgrade({
          containerID: c.containerID, containerName: c.containerName,
          content: text[c.containerName] || ' ', contentOffset: 0, contentLength: 0,
        }));
        if (!ok) throw new Error(`Text update failed: ${c.containerName}`);
      }
    }
    if (pixels) {
      if (!this.bridge.updateImageRawData) throw new Error('SOP reference image bridge unavailable');
      const result = await this.bridge.updateImageRawData(new ImageRawDataUpdate({
        containerID: GRAPHIC_CONTAINER.containerID, containerName: GRAPHIC_CONTAINER.containerName,
        imageData: pixels,
      }));
      if (!ImageRawDataUpdateResult.isSuccess(result)) throw new Error(`SOP reference image update failed: ${result}`);
    }
    this.previous = { ...text };
  }
}
