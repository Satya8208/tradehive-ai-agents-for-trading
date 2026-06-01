import { Composition } from "remotion";
import { BlackjackPromo } from "./BlackjackPromo";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="BlackjackPromo"
        component={BlackjackPromo}
        durationInFrames={360} // 12 seconds at 30fps - PUNCHY ebook promo
        fps={30}
        width={1920}
        height={1080}
      />
    </>
  );
};
