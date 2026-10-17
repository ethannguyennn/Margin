// Bootstrap derived from even-realities/evenhub-templates/asr.
// Provider-specific audio/STT wiring belongs to Part 2, not this scaffold.
import {
  waitForEvenAppBridge, TextContainerProperty, CreateStartUpPageContainer,
  TextContainerUpgrade, OsEventTypeList,
} from '@evenrealities/even_hub_sdk';

const bridge = await waitForEvenAppBridge();
const created = await bridge.createStartUpPageContainer(new CreateStartUpPageContainer({
  containerTotalNum: 1,
  textObject: [new TextContainerProperty({
    xPosition: 0, yPosition: 0, width: 576, height: 288,
    borderWidth: 0, borderColor: 0, borderRadius: 0, paddingLength: 8, textColor: 4,
    containerID: 1, containerName: 'main', isEventCapture: 1,
    content: 'Margin\nPress to ask\nDouble press to exit',
  })],
}));
if (created !== 0) throw new Error(`Startup failed: ${created}`);
console.info('[Margin] Scaffold page created', created);
const unsubscribe = bridge.onEvenHubEvent(event => {
  const envelope = event.sysEvent ?? event.textEvent;
  if (!envelope) return;
  const type = envelope.eventType ?? OsEventTypeList.CLICK_EVENT;
  if (type === OsEventTypeList.DOUBLE_CLICK_EVENT) void bridge.shutDownPageContainer(1);
  if (type === OsEventTypeList.CLICK_EVENT) void bridge.textContainerUpgrade(new TextContainerUpgrade({
    containerID: 1, containerName: 'main', content: 'Margin scaffold ready.\nShared contracts published.',
  }));
});
window.addEventListener('beforeunload', unsubscribe);
