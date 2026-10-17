import { TextContainerProperty, TextContainerUpgrade, CreateStartUpPageContainer, type EvenAppBridge } from '@evenrealities/even_hub_sdk';
import type { ScreenText } from './screens';

export const CONTAINERS = [
  { containerID: 1, containerName: 'header', yPosition: 0, height: 40, textColor: 2, isEventCapture: 0, paddingLength: 4 },
  { containerID: 2, containerName: 'main', yPosition: 48, height: 184, textColor: 4, isEventCapture: 1, paddingLength: 8 },
  { containerID: 3, containerName: 'footer', yPosition: 240, height: 48, textColor: 2, isEventCapture: 0, paddingLength: 4 },
] as const;

export function createLayout(text: ScreenText): CreateStartUpPageContainer {
  return new CreateStartUpPageContainer({ containerTotalNum: CONTAINERS.length,
    textObject: CONTAINERS.map(c => new TextContainerProperty({ ...c, xPosition: 0, width: 576,
      borderWidth: 0, borderColor: 0, borderRadius: 0, content: text[c.containerName] || ' ' })) });
}

export type DisplayBridge = Pick<EvenAppBridge, 'createStartUpPageContainer' | 'textContainerUpgrade'>;
/** Fixed container set for every screen; all later changes are text upgrades. */
export class LensDisplay {
  private previous: ScreenText | null = null;
  constructor(private readonly bridge: DisplayBridge) {}
  async render(text: ScreenText): Promise<void> {
    if (!this.previous) {
      const result = await this.bridge.createStartUpPageContainer(createLayout(text));
      if (result !== 0) throw new Error(`Startup page failed: ${result}`);
      this.previous = { ...text };
      return;
    }
    for (const c of CONTAINERS) {
      if (this.previous[c.containerName] === text[c.containerName]) continue;
      const ok = await this.bridge.textContainerUpgrade(new TextContainerUpgrade({
        containerID: c.containerID, containerName: c.containerName,
        content: text[c.containerName] || ' ', contentOffset: 0, contentLength: 0,
      }));
      if (!ok) throw new Error(`Text update failed: ${c.containerName}`);
      this.previous[c.containerName] = text[c.containerName];
    }
  }
}
