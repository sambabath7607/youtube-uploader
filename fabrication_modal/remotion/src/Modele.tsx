import React from 'react';
import {AbsoluteFill, interpolate, Sequence, useCurrentFrame} from 'remotion';
import {Background} from './components';
import {SceneVue} from './scenes';
import {C, clamp} from './theme';
import type {Donnees} from './types';

// Pas de son ici : les images sont rendues muettes, en morceaux parallèles, et la piste son
// (voix + musique) est ajoutée une seule fois par ffmpeg (aucun « clic » aux raccords).
const FONDU = 8; // images

const Fondu: React.FC<{duree: number; children: React.ReactNode}> = ({duree, children}) => {
  const frame = useCurrentFrame();
  const f = Math.max(1, Math.min(FONDU, Math.floor(duree / 3)));
  const opacite = interpolate(frame, [0, f, duree - f, duree], [0, 1, 1, 0], clamp);
  return <AbsoluteFill style={{opacity: opacite}}>{children}</AbsoluteFill>;
};

export const Modele: React.FC<Donnees> = (d) => (
  <AbsoluteFill style={{color: C.text, fontFamily: 'Inter'}}>
    <Background />
    {d.scenes.map((s, i) => (
      <Sequence key={i} from={s.debut} durationInFrames={Math.max(1, s.duree)}>
        <Fondu duree={Math.max(3, s.duree)}>
          <SceneVue d={d} s={s} />
        </Fondu>
      </Sequence>
    ))}
  </AbsoluteFill>
);
