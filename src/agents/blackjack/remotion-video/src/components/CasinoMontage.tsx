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
  goldBright: "#f0d48a",
  emerald: "#2dd881",
  ruby: "#e85454",
  textPrimary: "#f5f5f0",
  feltGreen: "#1a5c3a",
};

// Mini playing card component
const MiniCard: React.FC<{
  value: string;
  suit: string;
  color: string;
  x: number;
  y: number;
  rotation: number;
  delay: number;
  scale?: number;
}> = ({ value, suit, color, x, y, rotation, delay, scale = 1 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const entrance = spring({
    frame: frame - delay,
    fps,
    config: { damping: 10, stiffness: 120 },
    durationInFrames: 15,
  });

  const cardScale = interpolate(entrance, [0, 1], [0, scale]);
  const cardOpacity = interpolate(entrance, [0, 0.5, 1], [0, 1, 1]);

  return (
    <div
      style={{
        position: "absolute",
        left: `${x}%`,
        top: `${y}%`,
        transform: `translate(-50%, -50%) rotate(${rotation}deg) scale(${cardScale})`,
        opacity: cardOpacity,
      }}
    >
      <div
        style={{
          width: 70,
          height: 100,
          background: "white",
          borderRadius: 8,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          boxShadow: "0 8px 25px rgba(0,0,0,0.4)",
          border: "2px solid #ddd",
        }}
      >
        <div style={{ fontSize: 24, fontWeight: 700, color, fontFamily: "serif" }}>{value}</div>
        <div style={{ fontSize: 20, color }}>{suit}</div>
      </div>
    </div>
  );
};

// Chip stack component
const ChipStack: React.FC<{
  x: number;
  y: number;
  colors: string[];
  delay: number;
}> = ({ x, y, colors, delay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const entrance = spring({
    frame: frame - delay,
    fps,
    config: { damping: 12, stiffness: 100 },
    durationInFrames: 18,
  });

  const stackScale = interpolate(entrance, [0, 1], [0, 1]);
  const stackOpacity = interpolate(entrance, [0, 0.5, 1], [0, 1, 1]);

  return (
    <div
      style={{
        position: "absolute",
        left: `${x}%`,
        top: `${y}%`,
        transform: `translate(-50%, -50%) scale(${stackScale})`,
        opacity: stackOpacity,
      }}
    >
      {colors.map((color, i) => (
        <div
          key={i}
          style={{
            width: 50,
            height: 12,
            background: `linear-gradient(180deg, ${color} 0%, ${color}dd 100%)`,
            borderRadius: 25,
            marginTop: i === 0 ? 0 : -4,
            border: "2px solid rgba(255,255,255,0.3)",
            boxShadow: "0 2px 4px rgba(0,0,0,0.3)",
          }}
        />
      ))}
    </div>
  );
};

// Winning text flash
const WinFlash: React.FC<{ delay: number }> = ({ delay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const progress = spring({
    frame: frame - delay,
    fps,
    config: { damping: 8, stiffness: 200 },
    durationInFrames: 15,
  });

  const scale = interpolate(progress, [0, 1], [0.5, 1]);
  const opacity = interpolate(progress, [0, 0.3, 1], [0, 1, 1]);

  const glow = interpolate(
    Math.sin(((frame - delay) / fps) * Math.PI * 6),
    [-1, 1],
    [0.5, 1]
  );

  return (
    <div
      style={{
        position: "absolute",
        top: "15%",
        left: "50%",
        transform: `translateX(-50%) scale(${scale})`,
        opacity,
        textAlign: "center",
      }}
    >
      <div
        style={{
          fontFamily: "Cinzel, serif",
          fontSize: 64,
          fontWeight: 700,
          color: COLORS.emerald,
          textShadow: `0 0 40px rgba(45, 216, 129, ${glow})`,
        }}
      >
        BLACKJACK!
      </div>
      <div
        style={{
          fontFamily: "Outfit, sans-serif",
          fontSize: 28,
          color: COLORS.gold,
          marginTop: 8,
        }}
      >
        21 — YOU WIN
      </div>
    </div>
  );
};

export const CasinoMontage: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Background felt table effect
  const feltOpacity = interpolate(frame, [0, 10], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Pulsing ambient light
  const ambientPulse = interpolate(
    Math.sin((frame / fps) * Math.PI * 3),
    [-1, 1],
    [0.1, 0.25]
  );

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        background: `linear-gradient(180deg, ${COLORS.void} 0%, #0a1f12 50%, ${COLORS.void} 100%)`,
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* Felt table texture overlay */}
      <div
        style={{
          position: "absolute",
          top: "30%",
          left: "10%",
          right: "10%",
          bottom: "20%",
          background: `radial-gradient(ellipse at center, ${COLORS.feltGreen} 0%, #0d3320 100%)`,
          borderRadius: "50%",
          opacity: feltOpacity * 0.6,
          filter: "blur(2px)",
        }}
      />

      {/* Gold ambient glow */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: "50%",
          transform: "translateX(-50%)",
          width: 600,
          height: 300,
          background: `radial-gradient(ellipse at center, ${COLORS.gold}40 0%, transparent 70%)`,
          opacity: ambientPulse,
        }}
      />

      {/* Winning hand - Ace + King = 21 */}
      <MiniCard value="A" suit="♠" color="#1a1a1a" x={42} y={55} rotation={-8} delay={0} scale={1.2} />
      <MiniCard value="K" suit="♥" color={COLORS.ruby} x={52} y={52} rotation={5} delay={5} scale={1.2} />

      {/* Dealer's bust hand */}
      <MiniCard value="10" suit="♦" color={COLORS.ruby} x={45} y={25} rotation={-3} delay={10} scale={0.9} />
      <MiniCard value="6" suit="♣" color="#1a1a1a" x={52} y={23} rotation={4} delay={12} scale={0.9} />
      <MiniCard value="J" suit="♠" color="#1a1a1a" x={59} y={26} rotation={8} delay={14} scale={0.9} />

      {/* Chip stacks - winnings */}
      <ChipStack x={25} y={65} colors={[COLORS.gold, COLORS.gold, "#c0c0c0", COLORS.gold]} delay={8} />
      <ChipStack x={75} y={60} colors={["#c0c0c0", COLORS.gold, COLORS.gold, "#c0c0c0", COLORS.gold]} delay={12} />
      <ChipStack x={20} y={45} colors={[COLORS.ruby, COLORS.ruby, COLORS.gold]} delay={16} />
      <ChipStack x={80} y={70} colors={[COLORS.gold, "#c0c0c0", COLORS.gold, COLORS.gold]} delay={20} />

      {/* Extra scattered cards for depth */}
      <MiniCard value="7" suit="♥" color={COLORS.ruby} x={15} y={35} rotation={-25} delay={18} scale={0.7} />
      <MiniCard value="3" suit="♣" color="#1a1a1a" x={85} y={40} rotation={20} delay={22} scale={0.7} />

      {/* WIN flash */}
      <WinFlash delay={25} />

      {/* Bottom text */}
      <div
        style={{
          position: "absolute",
          bottom: 50,
          left: "50%",
          transform: "translateX(-50%)",
          fontFamily: "Outfit, sans-serif",
          fontSize: 24,
          color: COLORS.textPrimary,
          opacity: interpolate(frame - 35, [0, 15], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
          textAlign: "center",
        }}
      >
        Turn the odds in <span style={{ color: COLORS.gold }}>YOUR</span> favor
      </div>
    </div>
  );
};
