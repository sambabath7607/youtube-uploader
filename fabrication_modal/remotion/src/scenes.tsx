import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Appear, Card, Check, Kicker, Scene, useVertical, Window, Words} from './components';
import {C} from './theme';
import type {Donnees, SceneDonnees} from './types';

// Taille du texte selon sa longueur : un texte long reste lisible sans déborder.
const taille = (texte: string, vertical: boolean) => {
  const n = texte.length;
  if (n < 40) return vertical ? 84 : 88;
  if (n < 90) return vertical ? 66 : 68;
  if (n < 160) return vertical ? 54 : 54;
  return vertical ? 44 : 44;
};

const etiquette = (d: Donnees, s: SceneDonnees) => {
  if (!s.numero) return null;
  if (d.modele === 'astuces') return `Astuce ${s.numero}`;
  if (d.modele === 'lecon') return `Notion ${s.numero}`;
  if (d.modele === 'short') return `#${s.numero}`;
  return d.titre;
};

const Titre: React.FC<{d: Donnees; s: SceneDonnees}> = ({d, s}) => {
  const v = useVertical();
  const nombre = d.scenes.filter((x) => x.numero).length;
  const kicker = {lecon: 'Leçon', astuces: `${nombre} astuces`, presentation: 'Présentation', short: ''}[d.modele];
  return (
    <Scene>
      {kicker ? <Kicker>{kicker}</Kicker> : null}
      <Words text={s.texte} size={taille(s.texte, v) + 8} delay={6} style={{color: C.text}} />
      {s.texte !== d.titre ? (
        <Appear delay={24}>
          <p style={{margin: 0, fontSize: v ? 38 : 34, color: d.accent, fontWeight: 600, textAlign: 'center'}}>{d.titre}</p>
        </Appear>
      ) : null}
    </Scene>
  );
};

const Texte: React.FC<{d: Donnees; s: SceneDonnees}> = ({d, s}) => {
  const v = useVertical();
  const kicker = etiquette(d, s);
  return (
    <Scene>
      {kicker ? <Kicker>{kicker}</Kicker> : null}
      <Words text={s.texte} size={taille(s.texte, v)} delay={4} stagger={3} />
    </Scene>
  );
};

const Points: React.FC<{d: Donnees; s: SceneDonnees}> = ({d, s}) => {
  const v = useVertical();
  const kicker = etiquette(d, s);
  const points = s.points ?? [];
  // Les points apparaissent un par un pendant la première moitié de la scène (pendant que la voix les cite)
  const pas = Math.max(8, Math.min(40, Math.floor((s.duree * 0.5) / Math.max(1, points.length))));
  return (
    <Scene>
      {kicker ? <Kicker>{kicker}</Kicker> : null}
      <Words text={s.texte} size={taille(s.texte, v) - 6} delay={4} stagger={3} />
      <Card style={{display: 'flex', flexDirection: 'column', gap: v ? 34 : 26, minWidth: v ? 0 : 1100, borderColor: d.accent}}>
        {points.map((p, i) => (
          <Check key={i} delay={18 + i * pas} size={v ? 40 : 36}>
            {p}
          </Check>
        ))}
      </Card>
    </Scene>
  );
};

const Code: React.FC<{d: Donnees; s: SceneDonnees}> = ({d, s}) => {
  const v = useVertical();
  const frame = useCurrentFrame();
  const kicker = etiquette(d, s);
  const lignes = (s.code ?? '').replace(/\t/g, '    ').split('\n');
  // Une ligne de plus toutes les « pas » images, sur les 40 % du début de la scène
  const pas = Math.max(2, Math.floor((s.duree * 0.4) / Math.max(1, lignes.length)));
  const visibles = Math.min(lignes.length, Math.floor((frame - 12) / pas) + 1);
  const police = lignes.length > 14 ? (v ? 26 : 28) : v ? 32 : 36;
  return (
    <Scene>
      {kicker ? <Kicker>{kicker}</Kicker> : null}
      <Words text={s.texte} size={taille(s.texte, v) - 10} delay={4} stagger={3} />
      <Appear delay={8} style={{width: v ? '100%' : 1400}}>
        <Window title={s.langage || 'code'} style={{borderColor: d.accent}}>
          <pre
            style={{
              margin: 0,
              padding: '28px 36px',
              fontFamily: '"DejaVu Sans Mono", monospace',
              fontSize: police,
              lineHeight: 1.45,
              color: C.text,
              whiteSpace: 'pre-wrap',
              minHeight: police * 1.45 * Math.min(lignes.length, 6) + 56,
            }}
          >
            {lignes.map((l, i) => (
              <div key={i} style={{opacity: i < visibles ? 1 : 0}}>
                {l.trimStart().startsWith('#') || l.trimStart().startsWith('//') ? <span style={{color: C.muted}}>{l}</span> : l || ' '}
              </div>
            ))}
          </pre>
        </Window>
      </Appear>
    </Scene>
  );
};

const Fin: React.FC<{d: Donnees; s: SceneDonnees}> = ({d, s}) => {
  const v = useVertical();
  return (
    <Scene>
      <Words text={s.texte} size={taille(s.texte, v)} delay={4} stagger={3} />
      <Appear delay={20}>
        <div
          style={{
            padding: '18px 44px',
            borderRadius: 999,
            background: d.accent,
            color: '#ffffff',
            fontFamily: 'Poppins',
            fontWeight: 700,
            fontSize: v ? 40 : 36,
          }}
        >
          {d.titre}
        </div>
      </Appear>
    </Scene>
  );
};

export const SceneVue: React.FC<{d: Donnees; s: SceneDonnees}> = ({d, s}) => {
  switch (s.type) {
    case 'titre':
      return <Titre d={d} s={s} />;
    case 'points':
      return <Points d={d} s={s} />;
    case 'code':
      return <Code d={d} s={s} />;
    case 'fin':
      return <Fin d={d} s={s} />;
    default:
      return <Texte d={d} s={s} />;
  }
};
