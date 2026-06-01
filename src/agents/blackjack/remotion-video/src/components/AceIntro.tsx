import React from "react";
import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
} from "remotion";

const COLORS = {
  void: "#050505",
  gold: "#d4a853",
  goldDim: "#a68a3f",
  goldBright: "#f0d48a",
  textPrimary: "#f5f5f0",
};

// Large dramatic Ace of Spades
const AceOfSpades: React.FC<{ scale: number; rotation: number; opacity: number }> = ({
  scale,
  rotation,
  opacity,
}) => {
  return (
    <div
      style={{
        width: 220,
        height: 320,
        background: "linear-gradient(145deg, #ffffff 0%, #f0f0f0 100%)",
        borderRadius: 16,
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        alignItems: "center",
        boxShadow: `
          0 25px 80px rgba(0,0,0,0.6),
          0 0 100px rgba(212, 168, 83, 0.3),
          inset 0 0 30px rgba(255,255,255,0.5)
        `,
        transform: `scale(${scale}) rotate(${rotation}deg)`,
        opacity,
        position: "relative",
        border: "3px solid #1a1a1a",
      }}
    >
      {/* Top corner */}
      <div
        style={{
          position: "absolute",
          top: 12,
          left: 14,
          textAlign: "center",
        }}
      >
        <div style={{ fontSize: 28, fontWeight: 700, color: "#1a1a1a", fontFamily: "serif" }}>A</div>
        <div style={{ fontSize: 22, color: "#1a1a1a", marginTop: -6 }}>♠</div>
      </div>

      {/* Center spade - BIG */}
      <div
        style={{
          fontSize: 140,
          color: "#1a1a1a",
          textShadow: "2px 2px 4px rgba(0,0,0,0.2)",
        }}
      >
        ♠
      </div>

      {/* Bottom corner (inverted) */}
      <div
        style={{
          position: "absolute",
          bottom: 12,
          right: 14,
          textAlign: "center",
          transform: "rotate(180deg)",
        }}
      >
        <div style={{ fontSize: 28, fontWeight: 700, color: "#1a1a1a", fontFamily: "serif" }}>A</div>
        <div style={{ fontSize: 22, color: "#1a1a1a", marginTop: -6 }}>♠</div>
      </div>
    </div>
  );
};

export const AceIntro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Ace card dramatic entrance - flies in and lands
  const aceEntrance = spring({
    frame,
    fps,
    config: { damping: 10, stiffness: 80, mass: 1.2 },
    durationInFrames: 25,
  });

  const aceScale = interpolate(aceEntrance, [0, 1], [0.3, 1]);
  const aceRotation = interpolate(aceEntrance, [0, 1], [-45, 0]);
  const aceOpacity = interpolate(aceEntrance, [0, 0.3, 1], [0, 1, 1]);

  // Logo text slam in
  const logoProgress = spring({
    frame: frame - 12,
    fps,
    config: { damping: 8, stiffness: 150 },
    durationInFrames: 18,
  });

  const logoScale = interpolate(logoProgress, [0, 1], [2, 1]);
  const logoOpacity = interpolate(logoProgress, [0, 0.5, 1], [0, 1, 1]);

  // Tagline slide up
  const taglineProgress = spring({
    frame: frame - 25,
    fps,
    config: { damping: 12, stiffness: 100 },
    durationInFrames: 20,
  });

  const taglineY = interpolate(taglineProgress, [0, 1], [40, 0]);
  const taglineOpacity = interpolate(taglineProgress, [0, 1], [0, 1]);

  // Background pulse
  const pulse = interpolate(
    Math.sin((frame / fps) * Math.PI * 4),
    [-1, 1],
    [0.15, 0.4]
  );

  // Particle/sparkle effect
  const sparkleOpacity = interpolate(frame, [20, 30], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        background: COLORS.void,
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        alignItems: "center",
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* Dramatic gold burst behind card */}
      <div
        style={{
          position: "absolute",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: 800,
          height: 800,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${COLORS.gold}60 0%, transparent 50%)`,
          opacity: pulse,
        }}
      />

      {/* Secondary glow */}
      <div
        style={{
          position: "absolute",
          top: "30%",
          left: "20%",
          width: 400,
          height: 400,
          borderRadius: "50%",
          background: COLORS.gold,
          filter: "blur(100px)",
          opacity: pulse * 0.5,
        }}
      />

      {/* Sparkle particles */}
      {[...Array(8)].map((_, i) => (
        <div
          key={i}
          style={{
            position: "absolute",
            top: `${30 + Math.sin(i * 0.8) * 25}%`,
            left: `${20 + i * 10}%`,
            width: 4,
            height: 4,
            borderRadius: "50%",
            background: COLORS.goldBright,
            opacity: sparkleOpacity * (0.5 + Math.sin((frame + i * 10) / 8) * 0.5),
            transform: `scale(${1 + Math.sin((frame + i * 5) / 10) * 0.5})`,
          }}
        />
      ))}

      {/* Main content */}
      <div style={{ display: "flex", alignItems: "center", gap: 60 }}>
        {/* Ace of Spades */}
        <AceOfSpades scale={aceScale} rotation={aceRotation} opacity={aceOpacity} />

        {/* Text content */}
        <div style={{ textAlign: "left" }}>
          {/* Logo */}
          <div
            style={{
              fontFamily: "Cinzel, serif",
              fontSize: 72,
              fontWeight: 700,
              letterSpacing: 6,
              background: `linear-gradient(135deg, ${COLORS.goldBright} 0%, ${COLORS.gold} 50%, ${COLORS.goldDim} 100%)`,
              backgroundClip: "text",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              transform: `scale(${logoScale})`,
              opacity: logoOpacity,
              textShadow: "0 0 60px rgba(212, 168, 83, 0.5)",
            }}
          >
            BLACKJACK
            <br />
            GOD
          </div>

          {/* Tagline */}
          <div
            style={{
              fontFamily: "Outfit, sans-serif",
              fontSize: 28,
              color: COLORS.textPrimary,
              marginTop: 20,
              transform: `translateY(${taglineY}px)`,
              opacity: taglineOpacity,
            }}
          >
            Beat the Casino — <span style={{ color: COLORS.gold }}>Legally</span>
          </div>
        </div>
      </div>
    </div>
  );
};
