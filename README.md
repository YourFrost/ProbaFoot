# ProbaFoot

Probabilités des matchs des 5 grands championnats (semaine en cours + suivante), suivi des
pronostics, ré-apprentissage automatique, comparaison des bookmakers et suivi de bankroll.

## Lancer

```bash
pip install -r requirements.txt
python app.py
```

Ouvrir http://127.0.0.1:5000. Au premier lancement, la base est vide : une synchronisation
démarre toute seule (~7 min la première fois : 4 saisons × 5 championnats, calendrier FotMob,
notes des joueurs). Ensuite **Backtest** (~6 min la première fois, calendrier européen de la
saison précédente) puis **Apprendre**.

Tant que le serveur tourne : synchro complète toutes les heures, et guet des compositions
officielles toutes les 2 min pour les matchs qui commencent dans moins de 80 min.

## Sources de données

| Source | Contenu |
|---|---|
| Understat | calendrier, résultats, xG / npxG, xPts, stats joueurs (xG, xA, minutes) |
| FotMob | compositions officielles (~1 h avant), blessés/suspendus, notes des joueurs, météo, arbitre, stade, coupes d'Europe et coupes nationales |
| football-data.co.uk | cotes de 10+ bookmakers (Bet365, Pinnacle, William Hill, Betfair…) + moyenne/max |

FBref bloque les accès automatisés (Cloudflare, HTTP 403) : il n'est pas utilisé. Politesse :
1 requête/s max par site, cache disque dans `data/cache/`.

## Les modèles (`probafoot/models.py`)

Trois modèles, retenus après une étude d'ablation sur 2 002 matchs (log-loss hors échantillon) :

1. **Poisson / Dixon-Coles (xG)** — buts attendus = moyenne de la ligue × attaque × défense adverse.
   Ratings sur 60 % npxG + 40 % buts, ajustés à la force des adversaires, pondérés dans le temps
   (demi-vie 600 j, optimisée), régularisés (a priori plus faible pour les promus).
2. **Force selon les cotes passées** — les cotes de chaque match passé sont converties en buts
   attendus, puis on estime l'attaque/défense de chaque équipe « vue par le marché » (moindres
   carrés pondérés, demi-vie 120 j). Meilleur modèle après les cotes du match, et disponible pour
   les matchs lointains sans cotes.
3. **Marché** — cotes du match : Betfair Exchange, sinon Pinnacle, sinon moyenne ; marge retirée.

Ajustements appris : absences (xG+xA perdus, défense, qualité selon les notes FotMob) et avantage
domicile propre à l'équipe.

**Retirés du calcul** (aucun gain mesuré, parfois une perte) : Elo, forme brute, confrontations
directes, fatigue, rotation avant match européen, enjeu de fin de saison, derby, météo. Repos,
calendrier, classement, derby et météo restent affichés pour information. La forme est affichée
en « points vs attendu » (points pris − points espérés d'après les cotes d'avant-match).

| Élément | Perte de précision si on le retire |
|---|---|
| Force selon les cotes passées | +0,0043 (sans cotes) |
| Absences (défense / attaque / notes) | +0,0039 / +0,0021 / +0,0018 |
| Poisson xG | +0,0017 (avec cotes) |
| Elo, forme, confrontations directes | 0 |
| Fatigue, rotation, derby, météo | ≤ 0 |

## Conseiller, cotes en direct, scores en direct

- **Cotes en direct** (`probafoot/odds_tracker.py`) : Bet365, Unibet, Betfred, Interwetten et
  Paddy Power relevés toutes les heures via FotMob pour tous les matchs de la quinzaine (un point
  à chaque changement). Servent au modèle « marché », aux value bets et au graphique d'évolution.
- **Conseiller** (`probafoot/advisor.py`) : applique la stratégie active aux matchs à venir, un
  pari maximum par match, mise selon la bankroll, raisons, matchs à éviter, pronostics les plus
  sûrs avec leur taux de réussite historique. Ses paris alimentent la bankroll « Conseiller ».
- **Meilleures stratégies** : ~270 stratégies rejouées sur la saison précédente (sans biais de
  composition), vérifiées sur la saison en cours, applicables en un clic.
- **Scores en direct** : FotMob, rafraîchis chaque minute pendant les matchs.
- **Fiche équipe** : clic sur un nom d'équipe (classement, bilan dom./ext., forces xG et cotes,
  forme, résultats, calendrier, blessés, effectif triable).
- Valeur marchande des effectifs testée : aucun gain (corrélation −0,004 avec les erreurs du
  modèle, validation croisée négative), donc non utilisée.

## Ce que dit l'étude sur 8 saisons (12 700 matchs, toujours jugés sur des saisons non vues)

| Piste | Résultat | Décision |
|---|---|---|
| Plus de données (9 saisons chargées) | les conclusions tirées de 2 saisons étaient du bruit | **gardé** |
| Cote de clôture (CLV) | 1 point de CLV = 1 point de rendement (pente 1,00) | **gardé** : indicateur n°1 |
| Retrait de marge « puissance » | log-loss du marché 0,9706 → 0,9701 | **gardé** |
| Modèle final appris (cotes corrigées par nos modèles + absences) | 0,9713 → 0,9699 ; value bets de −5/−10 % à ≈ 0 % | **gardé** |
| ¼ Kelly | meilleur rapport gain / drawdown | **gardé** |
| Plafond d'exposition par jour, pause après baisse | baissent le gain sans améliorer le rapport | retiré |
| Handicap asiatique | +3 % avec les cotes « max », −2 à −3 % avec des cotes réalistes | retiré |
| Autres championnats | marges plus fortes (6,6 % contre 4,8 %), pas de gain significatif | retiré |
| Betfair Exchange comme « meilleure cote » | gonflait les résultats (commission, inaccessible en France) | exclu des paris |
| Parier juste après la composition officielle | non mesurable sur l'historique | **instrumenté** (carnet de test + alertes) |

Stratégie par défaut : 1N2, avantage ≥ 6 %, cote ≤ 4, ¼ Kelly — +8,5 % sur 391 paris en 7 saisons, CLV
+2 % (c'est la CLV qui donne l'espérance réaliste). Aucun gain n'est garanti.

Alertes Telegram (optionnel) : définir `PROBAFOOT_TELEGRAM_TOKEN` et `PROBAFOOT_TELEGRAM_CHAT` avant
de lancer `python app.py`. Le port se change avec la variable `PORT` (5000 par défaut).

## Apprentissage (`probafoot/learning.py`)

- Pronostics **live** figés au coup d'envoi ; **backtest** rejoué sans fuite d'information
  (pour la saison en cours avec les compositions réelles, connues 1 h avant, et la météo).
- Poids des modèles (profils avec / sans cotes) + netteté optimisés sur la log-loss.
- Coefficients des facteurs : descente par coordonnées sur une **validation chronologique**
  (80 % anciens / 20 % récents) ; changés seulement si ≥ 30 matchs concernés et gain réel.

## Bankroll (`probafoot/bankroll.py`)

- **Simulation automatique** : pari virtuel sur chaque value bet (meilleure cote), mise en
  fraction de Kelly ou fixe, figée au coup d'envoi, réglée au résultat.
- **Mes paris** : saisie des paris réels (cote et mise conseillées pré-remplies depuis la fiche).
- **Simulation historique** : la stratégie rejouée sur tous les pronostics passés.
- ROI, yield, drawdown, courbe de bankroll, rentabilité par championnat / marché / avantage / bookmaker.

## Interface

Design « terminal » (direction 1b, thème sombre, bouton clair/sombre). Onglets : Matchs
(liste + fiche détaillée), Calendrier (coupes d'Europe et nationales), Bankroll, Performances,
Historique, Lexique. Des « ? » expliquent chaque terme ; chaque graphique propose plusieurs
types d'affichage (choix mémorisé).

## Structure

```
app.py                   serveur Flask + API JSON + boucles (synchro 6 h, compositions 10 min)
probafoot/config.py      championnats, paramètres, grilles des coefficients
probafoot/sources/       understat.py, fotmob.py, footballdata.py
probafoot/sync.py        ingestion, rafraîchissement des pronostics, veille des compositions
probafoot/context.py     calendrier FotMob, notes des joueurs, contexte des matchs
probafoot/dataset.py     index en mémoire (équipes, coupes, confrontations, ligues)
probafoot/models.py      les 5 modèles, ajustements, ensemble
probafoot/factors.py     repos, rotation, enjeu, derby, météo
probafoot/absences.py    absences et compositions
probafoot/predict.py     calcul d'un pronostic, value bets (meilleure cote)
probafoot/learning.py    métriques, backtest, apprentissage
probafoot/bankroll.py    paris simulés et réels, réglement, simulation historique
static/                  interface (HTML/CSS/JS sans framework, Chart.js via CDN)
design_extract/          maquette d'origine (extraite de « ProbaFoot - 2 directions.html »)
data/                    base SQLite + cache (créés automatiquement)
```

## Limites connues

- Notes des joueurs chargées pour la saison en cours seulement (≈ 1 requête par match).
- La détection « blessé / incertain » dépend de la mise à jour FotMob.
- Les cotes ne sont publiées que pour les matchs de la semaine en cours.
