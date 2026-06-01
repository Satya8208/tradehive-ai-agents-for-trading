import React from "react";
import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  Sequence,
  AbsoluteFill,
} from "remotion";
import { AceIntro } from "./components/AceIntro";
import { CasinoMontage } from "./components/CasinoMontage";
import { CardCountingTeaser } from "./components/CardCountingTeaser";
import { StatsFlash } from "./components/StatsFlash";
import { CTAScene } from "./components/CTAScene";

const COLORS = {
  void: "#050505",
  gold: "#d4a853",
};

// PUNCHY fade transition
const PunchyFade: React.FC<{
  children: React.ReactNode;
  fadeInDuration?: number;
  fadeOutStart: number;
  fadeOutDuration?: number;
}> = ({ children, fadeInDuration = 8, fadeOutStart, fadeOutDuration = 10 }) => {
  const frame = useCurrentFrame();

  const fadeIn = interpolate(frame, [0, fadeInDuration], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const fadeOut = interpolate(
    frame,
    [fadeOutStart, fadeOutStart + fadeOutDuration],
    [1, 0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    }
  );

  return <AbsoluteFill style={{ opacity: Math.min(fadeIn, fadeOut) }}>{children}</AbsoluteFill>;
};

// Simple fade in
const FadeIn: React.FC<{ children: React.ReactNode; duration?: number }> = ({
  children,
  duration = 10,
}) => {
  const frame = useCurrentFrame();

  const opacity = interpolate(frame, [0, duration], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return <AbsoluteFill style={{ opacity }}>{children}</AbsoluteFill>;
};

// FAST gold wipe transition
const GoldWipe: React.FC<{ progress: number }> = ({ progress }) => {
  const width = interpolate(progress, [0, 0.5, 1], [0, 100, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const x = interpolate(progress, [0, 0.5, 1], [0, 0, 100], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  if (width === 0) return null;

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: `${x}%`,
        width: `${width}%`,
        height: "100%",
        background: `linear-gradient(90deg, transparent 0%, ${COLORS.gold} 30%, ${COLORS.gold} 70%, transparent 100%)`,
        zIndex: 100,
      }}
    />
  );
};

export const BlackjackPromo: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  // ===== SCENE TIMING (12 seconds = 360 frames @ 30fps) =====
  // Scene 1: Ace Intro (0-2s = 0-60 frames)
  // Scene 2: Casino Montage (1.8-4.3s = 54-130 frames)
  // Scene 3: Card Counting (4-7s = 120-210 frames)
  // Scene 4: Stats Flash (6.7-9.3s = 200-280 frames)
  // Scene 5: CTA (9-12s = 270-360 frames)

  const SCENE1_START = 0;
  const SCENE1_DURATION = 65;

  const SCENE2_START = 50;
  const SCENE2_DURATION = 85;

  const SCENE3_START = 115;
  const SCENE3_DURATION = 100;

  const SCENE4_START = 195;
  const SCENE4_DURATION = 90;

  const SCENE5_START = 265;
  const SCENE5_DURATION = 95;

  // Transition wipes - FAST (8 frames each)
  const wipe1 = interpolate(frame, [50, 58], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const wipe2 = interpolate(frame, [115, 123], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const wipe3 = interpolate(frame, [195, 203], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const wipe4 = interpolate(frame, [265, 273], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ background: COLORS.void }}>
      {/* Scene 1: Ace of Spades Intro */}
      <Sequence from={SCENE1_START} durationInFrames={SCENE1_DURATION}>
        <PunchyFade fadeOutStart={50} fadeOutDuration={12}>
          <AceIntro />
        </PunchyFade>
      </Sequence>

      {/* Scene 2: Casino/Winning Montage */}
      <Sequence from={SCENE2_START} durationInFrames={SCENE2_DURATION}>
        <PunchyFade fadeInDuration={8} fadeOutStart={70} fadeOutDuration={12}>
          <CasinoMontage />
        </PunchyFade>
      </Sequence>

      {/* Scene 3: Card Counting Demo */}
      <Sequence from={SCENE3_START} durationInFrames={SCENE3_DURATION}>
        <PunchyFade fadeInDuration={8} fadeOutStart={85} fadeOutDuration={12}>
          <CardCountingTeaser />
        </PunchyFade>
      </Sequence>

      {/* Scene 4: Stats Flash */}
      <Sequence from={SCENE4_START} durationInFrames={SCENE4_DURATION}>
        <PunchyFade fadeInDuration={8} fadeOutStart={75} fadeOutDuration={12}>
          <StatsFlash />
        </PunchyFade>
      </Sequence>

      {/* Scene 5: CTA */}
      <Sequence from={SCENE5_START} durationInFrames={SCENE5_DURATION}>
        <FadeIn duration={10}>
          <CTAScene />
        </FadeIn>
      </Sequence>

      {/* Gold wipe transitions */}
      <GoldWipe progress={wipe1} />
      <GoldWipe progress={wipe2} />
      <GoldWipe progress={wipe3} />
      <GoldWipe progress={wipe4} />

      {/* Final fade to black */}
      <AbsoluteFill
        style={{
          background: COLORS.void,
          opacity: interpolate(
            frame,
            [durationInFrames - 12, durationInFrames],
            [0, 1],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
          ),
        }}
      />
    </AbsoluteFill>
  );
};
