import React from 'react';
import {AbsoluteFill, interpolate, random, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {C, clamp, gradientText} from './theme';

export const useVertical = () => {
  const {width, height} = useVideoConfig();
  return height > width;
};

type SpringConfig = Parameters<typeof spring>[0]['config'];

export const useSpring = (delay = 0, config: SpringConfig = {damping: 200}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return spring({frame: frame - delay, fps, config});
};

// Fond commun à toute la vidéo : halos de couleur, grille et symboles de code qui flottent.
const SYMBOLS = ['{ }', '</>', '( )', '=>', '#', '[ ]', 'def', 'if', '01', 'IA', ';', 'py', 'SQL', '< />'];
export const Background: React.FC = () => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const a = frame / 90;
  const span = height + 200;
  return (
    <AbsoluteFill style={{background: C.bg, overflow: 'hidden'}}>
      <AbsoluteFill
        style={{
          background: `radial-gradient(circle at ${25 + 12 * Math.sin(a)}% ${30 + 10 * Math.cos(a)}%, rgba(59,139,255,0.32), transparent 45%),
            radial-gradient(circle at ${75 + 10 * Math.cos(a * 0.8)}% ${72 + 8 * Math.sin(a)}%, rgba(43,184,104,0.26), transparent 45%)`,
        }}
      />
      <AbsoluteFill
        style={{
          backgroundImage:
            'linear-gradient(rgba(255,255,255,0.045) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.045) 1px, transparent 1px)',
          backgroundSize: '80px 80px',
          backgroundPosition: `0 ${-frame * 0.4}px`,
        }}
      />
      {SYMBOLS.map((s, i) => {
        const x = random(`x${i}`) * width;
        const speed = 0.4 + random(`s${i}`) * 0.8;
        const y = ((((random(`y${i}`) * span - frame * speed) % span) + span) % span) - 100;
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: x,
              top: y,
              fontFamily: 'monospace',
              fontSize: 26 + random(`f${i}`) * 30,
              color: i % 2 ? C.blue : C.green,
              opacity: 0.16,
            }}
          >
            {s}
          </div>
        );
      })}
    </AbsoluteFill>
  );
};

export const Appear: React.FC<{delay?: number; y?: number; style?: React.CSSProperties; children: React.ReactNode}> = ({
  delay = 0,
  y = 40,
  style,
  children,
}) => {
  const p = useSpring(delay);
  return <div style={{opacity: p, transform: `translateY(${(1 - p) * y}px)`, ...style}}>{children}</div>;
};

const Word: React.FC<{delay: number; hl: boolean; children: React.ReactNode}> = ({delay, hl, children}) => {
  const p = useSpring(delay, {damping: 14, stiffness: 120});
  return (
    <span
      style={{
        display: 'inline-block',
        margin: '0 0.13em',
        opacity: interpolate(p, [0, 0.6], [0, 1], clamp),
        transform: `translateY(${(1 - p) * 50}px)`,
        ...(hl ? gradientText : {}),
      }}
    >
      {children}
    </span>
  );
};

// Phrase qui apparaît mot par mot ; les mots de `highlight` sont en dégradé bleu-vert.
export const Words: React.FC<{
  text: string;
  size: number;
  delay?: number;
  stagger?: number;
  highlight?: string[];
  style?: React.CSSProperties;
}> = ({text, size, delay = 0, stagger = 4, highlight = [], style}) => (
  <div style={{fontFamily: 'Poppins', fontWeight: 800, fontSize: size, lineHeight: 1.15, letterSpacing: -1, textAlign: 'center', ...style}}>
    {text.split(' ').map((w, i) => (
      <Word key={i} delay={delay + i * stagger} hl={highlight.includes(w.replace(/[.,!?]/g, ''))}>
        {w}
      </Word>
    ))}
  </div>
);

export const Kicker: React.FC<{children: React.ReactNode; delay?: number}> = ({children, delay = 0}) => (
  <Appear delay={delay} y={20}>
    <div
      style={{
        display: 'inline-block',
        padding: '10px 26px',
        borderRadius: 999,
        border: `2px solid ${C.green}`,
        color: C.greenLight,
        fontFamily: 'Inter',
        fontWeight: 600,
        fontSize: 26,
        letterSpacing: 2,
        textTransform: 'uppercase',
        background: 'rgba(43,184,104,0.1)',
      }}
    >
      {children}
    </div>
  </Appear>
);

// En-tête de scène : petite étiquette, grand titre, sous-titre.
export const SceneHeader: React.FC<{kicker: string; title: string; highlight?: string[]; subtitle?: string; align?: 'center' | 'left'}> = ({
  kicker,
  title,
  highlight,
  subtitle,
  align = 'center',
}) => {
  const v = useVertical();
  return (
    <div style={{display: 'flex', flexDirection: 'column', alignItems: align === 'center' ? 'center' : 'flex-start', gap: 22}}>
      <Kicker>{kicker}</Kicker>
      <Words
        text={title}
        size={v ? 72 : 68}
        delay={6}
        highlight={highlight}
        style={{textAlign: align, marginLeft: align === 'left' ? '-0.13em' : 0}}
      />
      {subtitle ? (
        <Appear delay={22}>
          <p style={{margin: 0, fontFamily: 'Inter', fontSize: v ? 34 : 30, color: C.muted, textAlign: align, maxWidth: 1200, lineHeight: 1.4}}>
            {subtitle}
          </p>
        </Appear>
      ) : null}
    </div>
  );
};

export const Card: React.FC<{style?: React.CSSProperties; children: React.ReactNode}> = ({style, children}) => (
  <div
    style={{
      background: C.card,
      border: `1.5px solid ${C.border}`,
      borderRadius: 28,
      padding: 36,
      boxShadow: '0 30px 80px rgba(0,0,0,0.35)',
      ...style,
    }}
  >
    {children}
  </div>
);

// Fenêtre façon application (trois points en haut).
export const Window: React.FC<{title: string; style?: React.CSSProperties; children: React.ReactNode}> = ({title, style, children}) => (
  <div
    style={{
      background: '#0d1326',
      border: `1.5px solid ${C.border}`,
      borderRadius: 24,
      overflow: 'hidden',
      boxShadow: '0 40px 100px rgba(0,0,0,0.5)',
      ...style,
    }}
  >
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '18px 24px',
        background: 'rgba(255,255,255,0.05)',
        borderBottom: `1px solid ${C.border}`,
      }}
    >
      {['#ff5f57', '#febc2e', '#28c840'].map((c) => (
        <div key={c} style={{width: 16, height: 16, borderRadius: 8, background: c}} />
      ))}
      <div style={{marginLeft: 16, fontFamily: 'Inter', fontWeight: 600, fontSize: 22, color: C.muted}}>{title}</div>
    </div>
    {children}
  </div>
);

export const Check: React.FC<{delay: number; children: React.ReactNode; size?: number}> = ({delay, children, size = 30}) => {
  const p = useSpring(delay);
  return (
    <div style={{display: 'flex', alignItems: 'center', gap: 18, opacity: p, transform: `translateX(${(1 - p) * -40}px)`}}>
      <div
        style={{
          flex: 'none',
          width: size * 1.4,
          height: size * 1.4,
          borderRadius: 999,
          background: `linear-gradient(135deg, ${C.green}, ${C.greenLight})`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#06210f',
          fontWeight: 800,
          fontSize: size * 0.8,
          transform: `scale(${p})`,
        }}
      >
        ✓
      </div>
      <div style={{fontFamily: 'Inter', fontWeight: 500, fontSize: size, color: C.text, lineHeight: 1.3}}>{children}</div>
    </div>
  );
};

export const Scene: React.FC<{style?: React.CSSProperties; children: React.ReactNode}> = ({style, children}) => {
  const v = useVertical();
  return (
    <AbsoluteFill
      style={{
        padding: v ? '150px 70px' : '80px 120px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: v ? 60 : 50,
        color: C.text,
        ...style,
      }}
    >
      {children}
    </AbsoluteFill>
  );
};

// Petite icône carrée avec un texte (ex. « Py », « </> »).
export const Badge: React.FC<{label: string; color: string; size?: number; emoji?: boolean}> = ({label, color, size = 84, emoji}) => (
  <div
    style={{
      flex: 'none',
      width: size,
      height: size,
      borderRadius: size * 0.28,
      background: `${color}22`,
      border: `2px solid ${color}`,
      color,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: 'Poppins',
      fontWeight: 800,
      fontSize: size * (emoji ? 0.6 : 0.36),
    }}
  >
    {label}
  </div>
);

// Fenêtre de navigateur claire (maquettes de sites).
export const Browser: React.FC<{url: string; children: React.ReactNode; height: number}> = ({url, children, height}) => (
  <div style={{width: '100%', background: '#f6f8fc', borderRadius: 24, overflow: 'hidden', boxShadow: '0 40px 100px rgba(0,0,0,0.5)', color: '#16203a'}}>
    <div style={{display: 'flex', alignItems: 'center', gap: 10, padding: '16px 22px', background: '#e4e9f3'}}>
      {['#ff5f57', '#febc2e', '#28c840'].map((c) => (
        <div key={c} style={{width: 15, height: 15, borderRadius: 8, background: c}} />
      ))}
      <div style={{marginLeft: 18, flex: 1, padding: '8px 20px', borderRadius: 999, background: '#fff', fontFamily: 'Inter', fontSize: 22, color: '#4a5272'}}>
        🔒 {url}
      </div>
    </div>
    <div style={{position: 'relative', height}}>{children}</div>
  </div>
);
