import type React from 'react';

// Couleurs reprises du logo et du site Batch Code IA.
export const C = {
  bg: '#070b18',
  text: '#f4f7ff',
  muted: '#9aa6c4',
  blue: '#3b8bff',
  blueDark: '#1250dc',
  green: '#2bb868',
  greenLight: '#5de596',
  card: 'rgba(255,255,255,0.06)',
  border: 'rgba(255,255,255,0.12)',
  // Couleurs du code (thème Monokai, comme l'atelier du site)
  yellow: '#E6DB74',
  pink: '#F92672',
  purple: '#AE81FF',
  cyan: '#66D9EF',
  red: '#ff4d5e',
};

export const gradientText: React.CSSProperties = {
  backgroundImage: `linear-gradient(90deg, ${C.blue}, ${C.greenLight})`,
  WebkitBackgroundClip: 'text',
  backgroundClip: 'text',
  color: 'transparent',
};

export const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
