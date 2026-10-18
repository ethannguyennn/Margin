import { TextContainerProperty, TextContainerUpgrade, CreateStartUpPageContainer, RebuildPageContainer, ImageContainerProperty, ImageRawDataUpdate, type EvenAppBridge } from '@evenrealities/even_hub_sdk';
import { graphicPixels, GRAPHIC_WIDTH, GRAPHIC_HEIGHT } from './sop-graphics';
import type { DiagramImage } from '../types';
import type { ScreenText } from './screens';
export type Layout = 'TEXT' | 'DIAGRAM' | 'REFERENCE';
export const CONTAINERS = [
    { containerID: 1, containerName: 'header', yPosition: 0, height: 40, textColor: 2, isEventCapture: 0, paddingLength: 4 },
    { containerID: 2, containerName: 'main', yPosition: 48, height: 184, textColor: 4, isEventCapture: 1, paddingLength: 8 },
    { containerID: 3, containerName: 'footer', yPosition: 240, height: 48, textColor: 2, isEventCapture: 0, paddingLength: 4 },
] as const;
export const TILES = [{ containerID: 4, containerName: 'tile-0', xPosition: 0 }, { containerID: 5, containerName: 'tile-1', xPosition: 288 }] as const;
export const GRAPHIC_CONTAINER = { containerID: 6, containerName: "reference", xPosition: 288, yPosition: 68, width: GRAPHIC_WIDTH, height: GRAPHIC_HEIGHT };
export function createLayout(text: ScreenText, layout: Layout = 'TEXT'): CreateStartUpPageContainer {
    const texts = CONTAINERS.filter(c => layout !== 'DIAGRAM' || c.containerName !== 'main');
    return new CreateStartUpPageContainer({ containerTotalNum: layout === 'TEXT' ? 3 : 4,
        textObject: texts.map(c => new TextContainerProperty({ ...c, xPosition: 0, width: layout === 'REFERENCE' && c.containerName === 'main' ? 280 : 576, borderWidth: 0, borderColor: 0, borderRadius: 0,
            ...(layout === 'DIAGRAM' && c.containerName === 'footer' ? { isEventCapture: 1, textColor: 3 } : {}),
            content: text[c.containerName] || ' ' })),
        ...(layout === 'REFERENCE' ? { imageObject: [new ImageContainerProperty(GRAPHIC_CONTAINER)] } : {}),
        ...(layout === 'DIAGRAM' ? { imageObject: TILES.map(c => new ImageContainerProperty({ ...c, yPosition: 48, width: 288, height: 144 })) } : {}) });
}
export type DisplayBridge = Pick<EvenAppBridge, 'createStartUpPageContainer' | 'textContainerUpgrade'> & Partial<Pick<EvenAppBridge, 'rebuildPageContainer' | 'updateImageRawData'>>;
export class DiagramRenderError extends Error {
}
export class LensDisplay {
    private previous: ScreenText | null = null;
    private layout: Layout = 'TEXT';
    private image: DiagramImage | undefined;
    private graphicId: string | undefined;
    rebuildCount = 0;
    constructor(private readonly bridge: DisplayBridge, private readonly rasterize = graphicPixels) { }
    async render(text: ScreenText, layout: Layout = 'TEXT', image?: DiagramImage): Promise<void> {
        if (layout === 'TEXT' && text.graphic_id) layout = 'REFERENCE';
        if (!this.previous) {
            const result = await this.bridge.createStartUpPageContainer(createLayout(text, layout));
            if (result !== 0)
                throw new Error(`Startup page failed: ${result}`);
            this.previous = { ...text };
            this.layout = layout;
        }
        else if (layout !== this.layout) {
            if (!this.bridge.rebuildPageContainer)
                throw new Error('Rebuild bridge unavailable');
            const starting = layout === 'DIAGRAM' ? { ...text, footer: 'loading diagram' } : text;
            if (!await this.bridge.rebuildPageContainer(new RebuildPageContainer(createLayout(starting, layout))))
                throw new Error('Layout switch failed');
            this.rebuildCount++;
            console.info(`[Specs] layout=${layout} rebuilds=${this.rebuildCount}`);
            this.layout = layout;
            this.previous = { ...starting };
            this.image = undefined;
            this.graphicId = undefined;
        }
        if (layout === 'REFERENCE' && text.graphic_id !== this.graphicId) {
            if (!this.bridge.updateImageRawData) throw new Error('Reference image bridge unavailable');
            const send = async (pixels: Uint8Array) => {
                const status = await this.bridge.updateImageRawData!(new ImageRawDataUpdate({
                    containerID: GRAPHIC_CONTAINER.containerID, containerName: GRAPHIC_CONTAINER.containerName, imageData: pixels }));
                if (status !== 'success') throw new Error(`Reference image update failed: ${status}`);
            };
            // Clear the old reference before changing the instruction, even if decoding fails.
            if (this.graphicId) { await send(new Uint8Array(GRAPHIC_WIDTH * GRAPHIC_HEIGHT)); this.graphicId = undefined; }
            await send(await this.rasterize(text.graphic_id!));
            this.graphicId = text.graphic_id;
            console.info(`[Specs] reference=${text.graphic_id} status=success`);
        }
        // Raw image sends are awaited one at a time. Callers use the shared BridgeQueue.
        if (layout === 'DIAGRAM' && image && image !== this.image) {
            if (!this.bridge.updateImageRawData)
                throw new DiagramRenderError('Image bridge unavailable');
            for (const tile of [...image.tiles].sort((a, b) => a.slot - b.slot)) {
                const c = TILES[tile.slot];
                const status = await this.bridge.updateImageRawData(new ImageRawDataUpdate({ containerID: c.containerID, containerName: c.containerName, imageData: tile.image }));
                if (status !== 'success')
                    throw new DiagramRenderError(`Diagram tile ${tile.slot} failed: ${status}`);
                console.info(`[Specs] diagram=${image.diagram_id} tile=${tile.slot} status=success`);
            }
            this.image = image;
        }
        for (const c of CONTAINERS) {
            if (layout === 'DIAGRAM' && c.containerName === 'main')
                continue;
            if (this.previous[c.containerName] === text[c.containerName])
                continue;
            if (!await this.bridge.textContainerUpgrade(new TextContainerUpgrade({ containerID: c.containerID, containerName: c.containerName,
                content: text[c.containerName] || ' ', contentOffset: 0, contentLength: 0 })))
                throw new Error(`Text update failed: ${c.containerName}`);
            this.previous[c.containerName] = text[c.containerName];
        }
    }
}
