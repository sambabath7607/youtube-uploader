import React from 'react';
import {CalculateMetadataFunction, Composition} from 'remotion';
import './fonts';
import {Modele} from './Modele';
import type {Donnees} from './types';

// Durée et taille viennent des données (calées sur la voix) : une seule composition par modèle.
const metadonnees: CalculateMetadataFunction<Donnees> = ({props}) => ({
  durationInFrames: Math.max(1, props.duree),
  width: props.largeur,
  height: props.hauteur,
});

const exemple = (modele: Donnees['modele'], largeur: number, hauteur: number): Donnees => ({
  modele,
  titre: 'Les listes en Python',
  accent: '#3B8BFF',
  largeur,
  hauteur,
  duree: 450,
  scenes: [
    {type: 'titre', texte: 'Les listes en Python', debut: 0, duree: 120},
    {type: 'points', texte: 'Une liste, c’est :', points: ['ordonnée', 'modifiable', 'entre crochets'], numero: 1, debut: 120, duree: 150},
    {type: 'code', texte: 'Ajouter un élément', code: 'fruits = ["pomme"]\nfruits.append("kiwi")\nprint(fruits)', langage: 'python', numero: 2, debut: 270, duree: 120},
    {type: 'fin', texte: 'Merci d’avoir regardé !', debut: 390, duree: 60},
  ],
});

export const RemotionRoot: React.FC = () => (
  <>
    <Composition id="lecon" component={Modele} fps={30} width={1920} height={1080} durationInFrames={450}
      defaultProps={exemple('lecon', 1920, 1080)} calculateMetadata={metadonnees} />
    <Composition id="astuces" component={Modele} fps={30} width={1920} height={1080} durationInFrames={450}
      defaultProps={exemple('astuces', 1920, 1080)} calculateMetadata={metadonnees} />
    <Composition id="presentation" component={Modele} fps={30} width={1920} height={1080} durationInFrames={450}
      defaultProps={exemple('presentation', 1920, 1080)} calculateMetadata={metadonnees} />
    <Composition id="short" component={Modele} fps={30} width={1080} height={1920} durationInFrames={450}
      defaultProps={exemple('short', 1080, 1920)} calculateMetadata={metadonnees} />
  </>
);
