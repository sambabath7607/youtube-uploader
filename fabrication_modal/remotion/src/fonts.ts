import {continueRender, delayRender, staticFile} from 'remotion';

// Les polices du site (Poppins pour les titres, Inter pour le texte).
const fonts: [string, string, string][] = [
  ['Poppins', 'poppins-latin-600-normal.woff2', '600'],
  ['Poppins', 'poppins-latin-700-normal.woff2', '700'],
  ['Poppins', 'poppins-latin-800-normal.woff2', '800'],
  ['Inter', 'inter-latin-400-normal.woff2', '400'],
  ['Inter', 'inter-latin-500-normal.woff2', '500'],
  ['Inter', 'inter-latin-600-normal.woff2', '600'],
];

const handle = delayRender('Chargement des polices', {timeoutInMilliseconds: 120000, retries: 2});
Promise.all(
  fonts.map(([family, file, weight]) => {
    const face = new FontFace(family, `url(${staticFile(file)}) format('woff2')`, {weight});
    return face.load().then(() => document.fonts.add(face));
  }),
)
  .then(() => continueRender(handle))
  .catch((err) => {
    console.error(err);
    continueRender(handle);
  });
