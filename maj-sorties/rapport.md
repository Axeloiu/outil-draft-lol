# Mise à jour automatique du 23/11/2026 13:21 UTC

Catalogue des objets : Data Dragon 16.23.1, 253 objets.

## Modèle Master+
→ erreur, ancien modèle gardé : node /home/runner/work/outil-draft-lol/outil-draft-lol/src/analyses/modele/tool_clean.js /home/runner/work/outil-draft-lol/outil-draft-lol/sortie/travail/outil… a échoué : evalmachine.<anonymous>:1226
function presRaw(c, r) { return Math.log1p((PRO26.freq[r] || {})[c.id] || 0); }
                                                      ^

TypeError: Cannot read properties of undefined (reading 'top')
    at presRaw (evalmachine.<anonymous>:1226:55)
    at evalmachine.<anonymous>:1230:116
    at Array.forEach (<anonymous>)
    at presPts (evalmachine.<anonymous>:1230:49)
    at evalmachine.<anonymous>:1280:63
    at Array.forEach (<anonymous>)
    at Object.draftScore (evalmachine.<anonymous>:1280:29)
    at /home/runner/work/outil-draft-lol/outil-draft-lol/src/analyses/modele/tool_clean.js:21:14
    at Array.map (<anonymous>)
    at Object.<anonymous> (/home/runner/work/outil-draft-lol/outil-draft-lol/src/analyses/modele/tool_clean.js:17:43)

Node.js v20.20.2


## Parties pros
Parties pros : 6796 parties Leaguepedia sur 365 jours (2354 réorientées bleu / rouge).
→ erreur, anciennes données pros gardées : node /home/runner/work/outil-draft-lol/outil-draft-lol/src/analyses/modele/lanepairs.js /home/runner/work/outil-draft-lol/outil-draft-lol/sortie/travail/outil… a échoué : evalmachine.<anonymous>:25
function chPts(c, r) { return typeof MODEL !== 'undefined' && mlHas('ch') ? MODEL.ch[c.id + '|' + r] || 0 : 0; }
                                           ^

ReferenceError: mlHas is not defined
    at chPts (evalmachine.<anonymous>:25:44)
    at bwr (evalmachine.<anonymous>:27:42)
    at f (/home/runner/work/outil-draft-lol/outil-draft-lol/src/analyses/modele/lanepairs.js:12:22)
    at /home/runner/work/outil-draft-lol/outil-draft-lol/src/analyses/modele/lanepairs.js:16:40
    at Array.map (<anonymous>)
    at Object.<anonymous> (/home/runner/work/outil-draft-lol/outil-draft-lol/src/analyses/modele/lanepairs.js:14:42)
    at Module._compile (node:internal/modules/cjs/loader:1521:14)
    at Module._extensions..js (node:internal/modules/cjs/loader:1623:10)
    at Module.load (node:internal/modules/cjs/loader:1266:32)
    at Module._load (node:internal/modules/cjs/loader:1091:12)

Node.js v20.20.2


## Objets
Effet des objets sur les parties test : gain +0.00697 (IC95 bas +0.00665) sur 599780 joueurs.
→ objets mis à jour.

## Site
Site reconstruit. Bilan : Master+ erreur, pros erreur, objets mis à jour.
Rappel : les priors u.gg / LoLalytics datent du 2026-11-07 ; ils se rafraîchissent à la main (puis changer priors_date dans maj/config.json).
