// Données envoyées par le service (fabrication_modal/modeles.py → props_remotion) : l'agent IA ne remplit que des champs.
export type TypeScene = 'titre' | 'texte' | 'points' | 'code' | 'fin';

export type SceneDonnees = {
  type: TypeScene;
  texte: string;
  points?: string[];
  code?: string;
  langage?: string;
  numero?: number; // numéro affiché (« Astuce 2 ») ; 0 = pas de numéro
  debut: number; // en images (30 images = 1 seconde), calé sur le minutage de la voix
  duree: number; // en images
};

export type Donnees = {
  modele: 'lecon' | 'astuces' | 'presentation' | 'short';
  titre: string;
  accent: string;
  largeur: number;
  hauteur: number;
  duree: number; // durée totale en images
  scenes: SceneDonnees[];
};
