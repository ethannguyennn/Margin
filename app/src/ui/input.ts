import { OsEventTypeList, type EvenHubEvent } from '@evenrealities/even_hub_sdk';
import type { Gesture } from '../state';

export function gestureFromEvent(event: EvenHubEvent | 'NOD' | 'SHAKE', captureID = 2): Gesture | null {
  if (typeof event === 'string') return event;
  const envelopes = [event.sysEvent, event.textEvent].filter(e => e !== undefined);
  const types = envelopes.map(e => e!.eventType ?? OsEventTypeList.CLICK_EVENT);
  if (types.includes(OsEventTypeList.DOUBLE_CLICK_EVENT)) return 'DOUBLE_PRESS';
  if (event.textEvent?.containerID !== undefined && event.textEvent.containerID !== captureID) return null;
  if (types.includes(OsEventTypeList.SCROLL_TOP_EVENT)) return 'UP';
  if (types.includes(OsEventTypeList.SCROLL_BOTTOM_EVENT)) return 'DOWN';
  if (types.includes(OsEventTypeList.LONG_PRESS_EVENT) || types.includes(OsEventTypeList.LONG_PRESS_RELEASE_EVENT)) return 'LONG_PRESS';
  if (types.includes(OsEventTypeList.CLICK_EVENT)) return 'PRESS';
  return null;
}
