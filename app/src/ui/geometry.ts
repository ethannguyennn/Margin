// Shared by the hardware layout and browser lens preview. Coordinates are G2 pixels.
export const CONTAINERS = [
  { containerID: 1, containerName: 'header', yPosition: 0, height: 40, textColor: 2, isEventCapture: 0, paddingLength: 4 },
  { containerID: 2, containerName: 'main', yPosition: 48, height: 184, textColor: 4, isEventCapture: 1, paddingLength: 8 },
  { containerID: 3, containerName: 'footer', yPosition: 240, height: 48, textColor: 2, isEventCapture: 0, paddingLength: 4 },
] as const;
export const TILES = [{ containerID: 4, containerName: 'tile-0', xPosition: 0 }, { containerID: 5, containerName: 'tile-1', xPosition: 288 }] as const;
export const GRAPHIC_CONTAINER = { containerID: 6, containerName: 'reference', xPosition: 288, yPosition: 68, width: 288, height: 144 };
