# Mise à jour automatique du 18/11/2026 17:32 UTC

Catalogue des objets : Data Dragon 16.23.1, 253 objets.

## Modèle Master+
Parties postérieures aux priors : 143586 ; test sur les 28718 plus récentes : log loss en place 0.68533, nouveau 0.68535, côté seul 0.69155.
→ modèle mis à jour : poids [1.0008, 0.693, 1.1753, 0.626], côté bleu -1.88, flex -2.10.

## Parties pros
Parties pros : 6785 parties Leaguepedia sur 365 jours (2354 réorientées bleu / rouge).
Recalage : modèle Master+ × 0.431, WR pro × 0.558, côté bleu +2.85 ; gain du WR pro sur l’Elo +0.00476 ; κ par rôle [0.245, 0.064, 0.116, 0.19, 0.179].
→ données pros mises à jour.

## Objets
Effet des objets sur les parties test : gain +0.00747 (IC95 bas +0.00705) sur 420320 joueurs.
→ objets mis à jour.

## Site
Site reconstruit. Bilan : Master+ mis à jour, pros mis à jour, objets mis à jour.
Rappel : les priors u.gg / LoLalytics datent du 2026-11-07 ; ils se rafraîchissent à la main (puis changer priors_date dans maj/config.json).
