// Petit serveur de rendu, lancé au démarrage de chaque machine Modal (classe Rendu de service.py).
// Le navigateur et le projet (déjà préparé : « remotion bundle » fait à la construction de l'image) sont chargés
// UNE fois, au préchauffage ; ensuite chaque morceau de vidéo est rendu sans attente.
import http from 'node:http';
import {openBrowser, renderMedia, selectComposition} from '@remotion/renderer';

const BUNDLE = process.env.REMOTION_BUNDLE || '/remotion/build';
const PORT = Number(process.env.REMOTION_PORT || 3100);

const navigateur = await openBrowser('chrome');
// Ouvre le projet une première fois : le rendu du premier morceau ne paie pas ce chargement
await selectComposition({serveUrl: BUNDLE, id: 'lecon', puppeteerInstance: navigateur});

const repondre = (res, statut, corps) => {
  res.writeHead(statut, {'content-type': 'application/json'});
  res.end(JSON.stringify(corps));
};

const serveur = http.createServer(async (req, res) => {
  if (req.method === 'GET') return repondre(res, 200, {pret: true});
  let corps = '';
  for await (const morceau of req) corps += morceau;
  try {
    const t = JSON.parse(corps);
    const composition = await selectComposition({serveUrl: BUNDLE, id: t.composition, inputProps: t.props, puppeteerInstance: navigateur});
    await renderMedia({
      composition,
      serveUrl: BUNDLE,
      codec: 'h264',
      outputLocation: t.sortie,
      inputProps: t.props,
      frameRange: [t.debut, t.fin],
      muted: true, // le son est ajouté une seule fois à l'assemblage
      concurrency: t.concurrency,
      imageFormat: 'jpeg',
      jpegQuality: 90,
      puppeteerInstance: navigateur,
      logLevel: 'warn',
    });
    repondre(res, 200, {ok: true});
  } catch (e) {
    console.error(e);
    repondre(res, 500, {erreur: String((e && e.message) || e)});
  }
});

serveur.listen(PORT, '127.0.0.1', () => console.log(`Rendu prêt sur le port ${PORT}`));
