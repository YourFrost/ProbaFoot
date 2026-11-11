"use strict";
/* Lexique : notes explicatives affichées au survol des « ? » et dans l'onglet Lexique. */
const GLOSSARY = {
  lineupBook: ["Paris après la composition (test)", "Carnet d'essai : dès qu'une composition officielle tombe (vérifiée toutes les 2 minutes dans la dernière heure), le programme note le pari qu'il ferait à cet instant. La CLV de ce carnet dira si les bookmakers ajustent leurs cotes assez lentement pour en profiter."],
  devig: ["Retrait de la marge", "Les cotes contiennent la marge du bookmaker, surtout sur les outsiders. La méthode « puissance » la retire en tenant compte de ce biais : elle donne des probabilités plus justes que la simple normalisation."],
  meta: ["Modèle final appris", "Les cotes des bookmakers (marge retirée) sont la meilleure base de départ. Le programme les corrige ensuite selon l'écart de ses deux modèles (xG et cotes passées) et selon les absences, avec des coefficients appris sur tout l'historique. Résultat : des probabilités aussi précises que le marché le plus efficace."],
  clv: ["Cote de clôture (CLV)", "Compare la cote que vous avez prise à la « juste » cote juste avant le coup d'envoi (la plus précise qui existe). +2 % = votre cote était 2 % meilleure. Mesuré sur 8 900 matchs : chaque point de CLV vaut un point de rendement à long terme. C'est l'indicateur le plus fiable de la qualité d'un pari, bien avant d'avoir assez de résultats."],
  optimizer: ["Meilleures stratégies", "Des centaines de stratégies sont rejouées sur la saison précédente (les compositions n'y étaient pas connues à l'avance : pas de biais), classées par rendement en pénalisant celles qui misent peu souvent, puis vérifiées sur la saison en cours. Une stratégie qui gagne sur les deux périodes est plus crédible."],
  advisorHit: ["Réussite des conseils", "Part des paris conseillés qui ont été gagnés, en rejouant la stratégie active sur la saison précédente (sans biais). À comparer à la réussite du pronostic sur tous les matchs (~52 %) : le conseiller ne parie que lorsqu'il voit un avantage, pas forcément sur le favori."],
  advisor: ["Conseiller", "Applique la stratégie de mise active aux matchs à venir : il indique quoi jouer, chez quel bookmaker, combien miser (selon la bankroll de la simulation), et explique pourquoi les autres matchs sont à éviter. Ses conseils sont suivis automatiquement dans la bankroll « Conseiller (simulation) »."],
  tiers: ["Réussite selon la confiance", "Taux de réussite du pronostic en ne gardant que les matchs où le favori dépasse un certain seuil de probabilité. Plus le seuil est haut, plus la réussite est élevée, mais moins il y a de matchs (et les cotes sont basses)."],
  oddsMove: ["Évolution des cotes", "Les cotes de 5 bookmakers sont relevées toutes les heures. Quand la probabilité implicite d'une issue monte (sa cote baisse), c'est que l'argent des parieurs arrive dessus — souvent des parieurs bien informés. Les cotes proches du coup d'envoi sont les plus précises."],
  h2h: ["Confrontations directes", "Derniers face-à-face entre les deux équipes. Information seulement : peu nombreux et peu prédictifs, ils ont été retirés du calcul."],
  infoOnly: ["Informations sans effet sur le calcul", "Fatigue, rotation avant un match européen, enjeu, derby et météo ont été testés sur plus de 2 000 matchs : aucun n'améliorait la précision. Ils restent affichés pour information mais ne modifient plus les probabilités."],
  formVsExp: ["Points vs attendu", "Points pris par match sur les 6 derniers, moins les points que les cotes d'avant-match laissaient espérer. Tient compte de l'adversaire : battre une grosse équipe rapporte plus que battre une petite. Positif = mieux que prévu, négatif (normal) = moins bien que prévu."],
  formSeq: ["Derniers matchs", "Résultats des 6 derniers matchs de championnat, du plus ancien au plus récent : V victoire, N nul, D défaite. Information indicative : la forme brute n'améliore pas les prévisions une fois la force des équipes connue."],
  mrDefense: ["Défense · cotes", "Buts encaissés attendus par le marché, relatifs à la moyenne. Moins de 1 = défense solide."],
  mrAttack: ["Attaque · cotes", "Force offensive vue par le marché (d'après les cotes des matchs passés). 1 = moyenne de la ligue, 1,30 = le marché s'attend à 30 % de buts en plus qu'une équipe moyenne."],
  mratings: ["Force selon les cotes passées", "Pour chaque match passé, les cotes des bookmakers sont converties en buts attendus. On en déduit l'attaque et la défense de chaque équipe telles que les voit le marché (qui intègre blessures, dynamique, valeur de l'effectif…). Très précis, et disponible même pour les matchs dont les cotes ne sont pas encore publiées."],
  proba1n2: ["Probabilités 1 · N · 2", "1 = victoire de l'équipe à domicile, N = match nul, 2 = victoire de l'équipe à l'extérieur. Les trois font 100 %. Le pronostic (en gras) est l'issue la plus probable."],
  xg: ["xG (expected goals)", "Buts attendus : la qualité des occasions, mesurée par la probabilité que chaque tir finisse au fond. 1,8 xG = des occasions qui valent en moyenne 1,8 but. Plus stable que le score réel pour juger une équipe."],
  npxg: ["npxG", "xG hors penalties. Les penalties sont en partie dus au hasard (décision arbitrale), on les retire pour mesurer la vraie capacité à se créer des occasions."],
  xgExpected: ["Buts attendus du match", "Nombre de buts que le modèle Poisson attend pour chaque équipe dans CE match, après prise en compte de l'adversaire, du terrain et de tous les facteurs (absences, fatigue, météo…)."],
  xa: ["xA (expected assists)", "Passes décisives attendues : la valeur en xG des tirs qu'un joueur a provoqués par ses passes."],
  poisson: ["Poisson / Dixon-Coles (xG)", "Estime la force offensive et défensive de chaque équipe à partir des xG et des buts des 2 dernières saisons (les matchs récents comptent plus), en tenant compte de la force des adversaires : marquer 3 buts à une grosse défense vaut plus que contre une défense faible. En déduit les buts attendus puis la probabilité de chaque score."],
  market: ["Marché (cotes du match)", "Probabilités tirées des cotes du match, marge retirée. Source prioritaire : Betfair Exchange (bourse de paris, la plus efficace), puis Pinnacle, puis la moyenne des bookmakers."],
  ensemble: ["Ensemble", "Pronostic final : moyenne pondérée de trois modèles (Poisson xG, force selon les cotes passées, marché). Les poids sont appris automatiquement. Elo, forme et confrontations directes ont été testés et retirés car ils n'amélioraient pas les prévisions."],
  weight: ["Poids", "Part de chaque modèle dans le pronostic final. Un modèle qui s'est montré peu fiable voit son poids baisser lors de l'apprentissage."],
  profile: ["Profil avec / sans cotes", "Les cotes ne sont publiées que quelques jours avant le match. Deux jeux de poids sont donc appris : un quand les cotes existent, un autre quand elles manquent."],
  sharpness: ["Netteté", "Correctif appliqué au pronostic final. Au-dessus de 1, les probabilités sont rendues plus tranchées (le mélange de modèles a tendance à être trop prudent). 1 = aucun effet."],
  attack: ["Attaque (1 = moyenne)", "Force offensive relative : 1,20 = l'équipe produit 20 % d'occasions de plus qu'une équipe moyenne de la ligue, à adversaire égal."],
  defense: ["Défense (< 1 = solide)", "Buts concédés relatifs : 0,80 = l'équipe concède 20 % de moins qu'une équipe moyenne. Plus c'est bas, mieux c'est."],
  homeadv: ["Force à domicile", "Buts marqués / encaissés à domicile par rapport à ce que les ratings de l'équipe laissaient attendre (1 = normal). 1,10 / 0,90 = l'équipe marque 10 % de plus et encaisse 10 % de moins à domicile qu'attendu. Pris en compte dans le calcul."],
  rest: ["Jours de repos", "Temps écoulé depuis le dernier match, toutes compétitions confondues. Information seulement : l'effet mesuré de la fatigue était nul."],
  rotation: ["Coupe / Europe à venir", "Prochain match de coupe ou européen dans les 7 jours. Information seulement : l'effet mesuré de la rotation était nul."],
  derby: ["Derby", "Rivalité locale ou historique. Information seulement : pas d'effet mesurable sur les résultats."],
  weather: ["Météo", "Prévisions FotMob (température, vent, pluie). Information seulement : trop peu de matchs par mauvais temps pour mesurer un effet."],
  absAtt: ["Impact des absences (attaque)", "Part de la production offensive de l'équipe (xG + xA de la saison) portée par les joueurs absents. 25 % = un quart des occasions créées d'habitude manquent."],
  absDef: ["Impact des absences (défense)", "Part des minutes des défenseurs et du gardien absents, rapportée à la ligne défensive (5 postes). Fait monter les buts attendus de l'adversaire."],
  absRating: ["Impact des absences (notes)", "Part de la « qualité » de l'effectif qui manque : chaque joueur vaut son temps de jeu × (sa note moyenne − 6). Perdre un joueur noté 7,5 pèse bien plus qu'un joueur noté 6,4."],
  rating: ["Note moyenne", "Note FotMob sur 10 attribuée à chaque match selon les actions du joueur, moyennée sur la saison (pondérée par les minutes). 6 = passable, 7 = bon match, 8+ = excellent."],
  xiRating: ["Note du onze", "Moyenne des notes des titulaires annoncés, comparée au onze habituel (les 11 joueurs les plus utilisés). Un écart négatif = équipe affaiblie."],
  lineup: ["Composition officielle", "Publiée environ 1 h avant le coup d'envoi. ProbaFoot la guette toutes les 2 minutes dans l'heure qui précède le match et recalcule aussitôt le pronostic : titulaire = présent, remplaçant = compte pour moitié, hors feuille = absent."],
  unavailable: ["Blessés & suspendus", "Liste officielle des indisponibles (FotMob). « Incertain » compte pour moitié dans l'impact des absences."],
  minutesShare: ["Min.", "Part des minutes jouées par le joueur sur la saison. 90 % = titulaire indiscutable."],
  attShare: ["xG+xA", "Part du joueur dans la production offensive de l'équipe (xG + xA de la saison)."],
  over25: ["+2.5 buts", "Probabilité qu'il y ait au moins 3 buts dans le match (les deux équipes confondues). +1.5 = au moins 2 buts, +3.5 = au moins 4."],
  btts: ["Les deux marquent (BTTS)", "Probabilité que chaque équipe marque au moins un but."],
  topScores: ["Scores les plus probables", "Probabilité de chaque score exact selon le modèle Poisson. Même le score le plus probable dépasse rarement 12 % : le football est très aléatoire."],
  heatmap: ["Matrice des scores", "Chaque case donne la probabilité d'un score exact (lignes : buts à domicile, colonnes : buts à l'extérieur). Plus la case est foncée, plus le score est probable."],
  odds: ["Cote", "Gain total pour 1 € misé si le pari est gagnant (mise comprise). Une cote de 2,50 correspond à une probabilité « implicite » de 1 / 2,50 = 40 %."],
  impliedProb: ["Proba cote", "Probabilité implicite de la cote : 1 ÷ cote. Elle inclut la marge du bookmaker, donc la somme des trois issues dépasse 100 %."],
  edge: ["Avantage (edge)", "Proba du modèle × cote − 1. +8 % signifie qu'en misant 100 € à chaque fois dans cette situation, on gagnerait 8 € en moyenne si le modèle est juste. Négatif = la cote est trop basse."],
  value: ["Value bet", "Pari dont l'avantage dépasse +5 % : la cote proposée est supérieure à la « juste » cote calculée par le modèle."],
  margin: ["Marge du bookmaker", "Commission cachée dans les cotes : 1/cote1 + 1/coteN + 1/cote2 − 1. 5 % de marge = le bookmaker garde en moyenne 5 % des mises. Plus elle est faible, meilleures sont les cotes."],
  bestOdds: ["Meilleure cote", "La plus haute cote proposée pour chaque issue parmi les bookmakers comparés (en vert). Toujours jouer la meilleure cote augmente nettement le rendement sur la durée."],
  referee: ["Arbitre", "Statistiques de l'arbitre désigné : cartons jaunes par match, penalties sifflés. Un arbitre sévère augmente les risques de cartons et de penalties."],
  accuracy: ["Réussite (favori)", "Pourcentage de matchs où l'issue la plus probable selon le modèle s'est produite. Autour de 50–55 % est un bon niveau en football (3 issues possibles)."],
  brier: ["Score de Brier", "Écart moyen entre les probabilités annoncées et ce qui s'est passé (0 = parfait, plus bas = mieux). Récompense les probabilités justes, pas seulement le bon favori."],
  logloss: ["Log-loss", "Pénalise fortement les erreurs commises avec assurance (annoncer 90 % et se tromper coûte très cher). Plus bas = mieux. Une référence naïve fait environ 1,07."],
  baseline: ["Référence naïve", "Un « modèle » qui annonce toujours les taux moyens de la ligue (≈ 44 % domicile, 26 % nul, 30 % extérieur). Tout modèle utile doit faire mieux."],
  calibration: ["Calibration", "Vérifie l'honnêteté des probabilités : parmi toutes les fois où le modèle a annoncé 60 %, l'issue doit s'être produite environ 60 % du temps. Idéalement, les points suivent la diagonale."],
  backtest: ["Backtest", "Le programme rejoue les matchs passés comme s'il ne connaissait pas leur résultat (uniquement les données antérieures à chaque match). Sert à mesurer la fiabilité et à apprendre les poids."],
  live: ["Pronostics réels", "Pronostics calculés avant le match et figés au coup d'envoi. C'est la mesure de fiabilité la plus honnête."],
  validation: ["Validation hors échantillon", "Les coefficients sont choisis sur les 80 % de matchs les plus anciens puis jugés sur les 20 % les plus récents, jamais vus. Évite de « coller » au hasard du passé."],
  coefs: ["Coefficients d'ajustement", "Intensité de chaque facteur contextuel (absences, fatigue, météo…). Ils sont ré-estimés à chaque apprentissage, seulement si assez de matchs concernés existent et si le gain est confirmé hors échantillon."],
  bankroll: ["Bankroll", "Capital consacré aux paris. On mise toujours une petite fraction de la bankroll pour survivre aux séries perdantes."],
  kelly: ["Critère de Kelly", "Mise optimale théorique = (proba × cote − 1) ÷ (cote − 1) de la bankroll. On en joue une fraction (¼ de Kelly par défaut) car les probabilités du modèle sont imparfaites : c'est beaucoup plus sûr."],
  flat: ["Mise fixe", "Même pourcentage de la bankroll à chaque pari, quel que soit l'avantage. Simple et peu risqué."],
  roi: ["ROI", "Bénéfice rapporté à la bankroll de départ. +10 % = la bankroll a augmenté de 10 %."],
  yield: ["Yield (rendement)", "Bénéfice rapporté au total misé. +5 % = 5 € de gain pour 100 € misés. Le meilleur indicateur de la qualité des paris."],
  drawdown: ["Drawdown max", "Plus forte baisse de la bankroll depuis un sommet. Mesure le risque : 30 % = à un moment, on a perdu 30 % de ce qu'on avait au plus haut."],
  hitRate: ["Taux de réussite", "Part des paris gagnés. Sur des value bets à grosse cote, il peut être faible tout en restant rentable."],
  autoBook: ["Simulation automatique", "Les conseils du Conseiller sont « pariés » virtuellement avec la stratégie active, mise figée au coup d'envoi puis réglée au résultat. Permet de juger la rentabilité sans risquer d'argent."],
  histSim: ["Simulation historique", "Applique la stratégie à tous les pronostics passés (backtest + réels) avec les vraies cotes des bookmakers de l'époque. Attention : optimiste si les poids ont été appris sur ces mêmes matchs."],
  calendar: ["Calendrier européen", "Matchs de Ligue des champions, Ligue Europa, Ligue Conférence et coupes nationales des équipes suivies. Sert à calculer le repos réel et le risque de rotation."],
};

function tip(key) {
  const g = GLOSSARY[key];
  if (!g) return "";
  return `<span class="tip" tabindex="0" data-tip="${key}" aria-label="${g[0]} : explication">?</span>`;
}

(function initTooltips() {
  const box = document.getElementById("tooltip");
  const show = (el) => {
    const g = GLOSSARY[el.dataset.tip];
    if (!g) return;
    box.innerHTML = `<strong>${g[0]}</strong>${g[1]}`;
    box.classList.remove("hidden");
    const r = el.getBoundingClientRect();
    const bw = box.offsetWidth, bh = box.offsetHeight;
    let left = Math.min(Math.max(8, r.left + r.width / 2 - bw / 2), window.innerWidth - bw - 8);
    let top = r.bottom + 8;
    if (top + bh > window.innerHeight - 8) top = r.top - bh - 8;
    box.style.left = left + "px";
    box.style.top = top + "px";
  };
  const hide = () => box.classList.add("hidden");
  document.addEventListener("mouseover", (e) => { const el = e.target.closest("[data-tip]"); if (el) show(el); });
  document.addEventListener("mouseout", (e) => { if (e.target.closest("[data-tip]")) hide(); });
  document.addEventListener("focusin", (e) => { const el = e.target.closest("[data-tip]"); if (el) show(el); });
  document.addEventListener("focusout", hide);
  document.addEventListener("scroll", hide, true);
})();
