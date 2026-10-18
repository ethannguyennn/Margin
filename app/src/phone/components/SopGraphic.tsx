import { graphicAsset, type SopGraphic as Graphic } from '../../ui/sop-graphics';

/** The same bundled image and crop used by the glasses, at phone reading size. */
export function SopGraphic({ graphic }: { graphic: Graphic | null }) {
  if (!graphic) return null;
  const [x, y, width, height] = graphic.crop;
  return (
    <figure className="sop-graphic">
      <svg role="img" aria-label={graphic.alt}
        viewBox={`${x * 1000} ${y * 500} ${width * 1000} ${height * 500}`}>
        <image href={graphicAsset(graphic)} width="1000" height="500" />
      </svg>
      <figcaption><strong>{graphic.title}</strong><span>Synthetic training reference · not to scale</span></figcaption>
    </figure>
  );
}
