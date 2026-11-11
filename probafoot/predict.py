"""Assemblage des facteurs d'un match et calcul du pronostic final."""
import json
import math

from . import factors, models
from .config import MODEL_VERSION, VALUE_EDGE_MIN
from .db import now_iso

OUTCOMES = ["H", "D", "A"]
AGGREGATES = {"Avg", "Max"}
# Betfair Exchange : cotes avant commission et inaccessible depuis la France -> jamais « meilleure cote »
NOT_BETTABLE = {"Betfair Exchange"}


def best_odds(books: dict | None) -> dict:
    """Meilleure cote par issue parmi les bookmakers (hors moyenne / max agrégés)."""
    out = {}
    if not books:
        return out
    singles = ({b: o for b, o in books.items() if b not in AGGREGATES and b not in NOT_BETTABLE}
               or {b: o for b, o in books.items() if b == "Max"})
    for key in ("h", "d", "a", "over25", "under25"):
        cands = [(o[key], b) for b, o in singles.items() if o.get(key)]
        if cands:
            out[key] = max(cands)
    return out


def predict_match(ds, m: dict, params: dict, weights: dict, odds: dict | None = None,
                  absences: dict | None = None, ctx: dict | None = None, books: dict | None = None) -> dict | None:
    la = ds.leagues.get(m["league"])
    if la is None:
        return None
    probs, details = {}, {}

    # Informations de contexte (affichées, mais sans effet mesurable sur la précision : hors calcul)
    rr = factors.rest_and_rotation(ds, m)
    st = factors.positions(ds, m)
    absences = absences or {}
    adj = {
        "abs_att_h": absences.get("home", {}).get("att_share", 0),
        "abs_def_h": absences.get("home", {}).get("def_share", 0),
        "abs_rating_h": absences.get("home", {}).get("rating_share", 0),
        "abs_att_a": absences.get("away", {}).get("att_share", 0),
        "abs_def_a": absences.get("away", {}).get("def_share", 0),
        "abs_rating_a": absences.get("away", {}).get("rating_share", 0),
    }

    # 1. Poisson / Dixon-Coles
    base = [0.44, 0.26, 0.30]
    poisson_out = None
    r = models.team_ratings(la, m["ts"], params, ds.priors(m["league"], m["season"], params))
    if r:
        hi, ai = la.idx[m["home_id"]], la.idx[m["away_id"]]
        adj["home_att"] = round(float(r["home_att"][hi]), 4)
        adj["home_def"] = round(float(r["home_def"][hi]), 4)
        lh0 = r["home_avg"] * r["att"][hi] * r["de"][ai]
        la0 = r["away_avg"] * r["att"][ai] * r["de"][hi]
        lh, la_ = models.adjusted_lambdas(lh0, la0, adj, params)
        mk = models.markets(models.score_matrix(lh, la_, params["dc_rho"]))
        matrix = models.score_matrix(lh, la_, params["dc_rho"], 5)
        probs["poisson"] = mk["1x2"]
        base = r["base"]
        poisson_out = {"lh0": lh0, "la0": la0, "lh": lh, "la": la_, "markets": mk,
                       "matrix": [[round(float(x), 4) for x in row] for row in matrix]}
        details["ratings"] = {
            "home": {"att": round(float(r["att"][hi]), 3), "def": round(float(r["de"][hi]), 3)},
            "away": {"att": round(float(r["att"][ai]), 3), "def": round(float(r["de"][ai]), 3)},
            "league_home_avg": round(r["home_avg"], 3), "league_away_avg": round(r["away_avg"], 3),
        }

    # 1 bis. Force déduite des cotes des matchs passés (mêmes ajustements contextuels)
    mi = ds.implied.get(m["league"])
    mr = models.market_team_ratings(mi, m["ts"], params, ds.priors(m["league"], m["season"], params)) if mi else None
    if mr:
        hi, ai = la.idx[m["home_id"]], la.idx[m["away_id"]]
        mlh0, mla0 = models.market_rating_lambdas(mr, hi, ai)
        mlh, mla = models.adjusted_lambdas(mlh0, mla0, {**adj, "home_att": 1.0, "home_def": 1.0}, params)
        probs["mratings"] = models.markets(models.score_matrix(mlh, mla, params["dc_rho"]))["1x2"]
        details["mratings"] = {"lh0": mlh0, "la0": mla0, "lh": mlh, "la": mla,
                               "home": {"att": round(math.exp(mr["att"][hi]), 3), "def": round(math.exp(-mr["def"][hi]), 3)},
                               "away": {"att": round(math.exp(mr["att"][ai]), 3), "def": round(math.exp(-mr["def"][ai]), 3)}}

    # 3. Marché : cotes du match (Betfair Exchange > Pinnacle > moyenne), marge retirée
    probs["market"] = models.market_probs(odds, books)
    details["odds"] = odds
    details["base_rates"] = base

    # Informations affichées (hors calcul)
    details["form"] = {s: models.team_form(ds, m[f"{s}_id"], m["ts"], params, ds.implied_probs) for s in ("home", "away")}
    details["h2h"] = models.h2h_list(ds, m)
    details["context"] = {
        "rest_h": rr["rest_h"], "rest_a": rr["rest_a"], "rest_comp_h": rr["rest_comp_h"], "rest_comp_a": rr["rest_comp_a"],
        "next_cup_h": rr["next_cup_h"], "next_cup_a": rr["next_cup_a"],
        "pos_h": st["pos_h"], "pos_a": st["pos_a"], "pts_h": st["pts_h"], "pts_a": st["pts_a"],
        "derby": factors.is_derby(m["home"], m["away"]),
    }
    if ctx:
        details["weather"] = ctx.get("weather")
        details["referee"] = ctx.get("referee")
        details["stadium"] = ctx.get("stadium")
        details["lineup_confirmed"] = ctx.get("lineup_confirmed")

    # Probabilités « de base » (sans absences) : servent à l'apprentissage du modèle final
    base_adj = {"home_att": adj.get("home_att"), "home_def": adj.get("home_def")}
    base_probs = {"poisson": models.poisson_probs(poisson_out["lh0"], poisson_out["la0"], base_adj, params) if poisson_out else None,
            "mratings": models.poisson_probs(details["mratings"]["lh0"], details["mratings"]["la0"], {}, params) if details.get("mratings") else None}

    profile_name, profile = models.pick_profile(probs, weights)
    meta = weights.get("meta")
    if meta and probs.get("market") and base_probs["poisson"]:
        # modèle final appris : cotes corrigées par nos modèles (+ absences)
        final = models.meta_probs(probs["market"], base_probs["poisson"], base_probs["mratings"], meta, probs["poisson"])
        profile_name, profile = "meta", {"sharpness": 1.0}
    else:
        final = models.ensemble(probs, profile)
    if final is None:
        return None
    pick = OUTCOMES[max(range(3), key=lambda i: final[i])]

    # Value : comparée à la meilleure cote disponible parmi les bookmakers
    best = best_odds(books)
    if not best and odds:
        best = {k2: (odds[k1], "Moyenne") for k1, k2 in (("odds_h", "h"), ("odds_d", "d"), ("odds_a", "a"),
                                                         ("over25", "over25"), ("under25", "under25")) if odds.get(k1)}
    value = []
    for i, key in enumerate(("h", "d", "a")):
        if key in best:
            o, book = best[key]
            edge = final[i] * o - 1
            value.append({"market": "1X2", "outcome": OUTCOMES[i], "odds": o, "bookmaker": book,
                          "p": final[i], "edge": edge, "flag": edge >= VALUE_EDGE_MIN})
    # +/-2.5 buts : Poisson mélangé au marché (même part que dans le profil de poids), sinon
    # le modèle parie systématiquement contre des cotes mieux informées
    ou = None
    if poisson_out:
        ou = poisson_out["markets"]["over25"]
        if odds and odds.get("over25") and odds.get("under25"):
            implied = (1 / odds["over25"]) / (1 / odds["over25"] + 1 / odds["under25"])
            w = 0.7  # part du marché mesurée sur l'historique
            ou = w * implied + (1 - w) * ou
    if ou is not None:
        po = ou
        for key, label, p in (("over25", "O", po), ("under25", "U", 1 - po)):
            if key in best:
                o, book = best[key]
                edge = p * o - 1
                value.append({"market": "OU25", "outcome": label, "odds": o, "bookmaker": book,
                              "p": p, "edge": edge, "flag": edge >= VALUE_EDGE_MIN})

    return {
        "final": final, "pick": pick, "models": probs, "weights": profile, "profile": profile_name,
        "over25": ou,
        "poisson": poisson_out, "adj": adj, "base": base_probs,
        "details": details,
        "absences": {s: {k: v for k, v in a.items() if k != "squad"} for s, a in absences.items()},
        "value": value,
    }


def save_prediction(conn, match_id: str, source: str, pred: dict):
    ts = now_iso()
    p = pred["poisson"] or {}
    conn.execute(
        """INSERT INTO predictions(match_id, source, created_at, updated_at, model_version,
               p_home, p_draw, p_away, xg_home, xg_away, pick, data)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(match_id, source) DO UPDATE SET updated_at=excluded.updated_at,
               model_version=excluded.model_version, p_home=excluded.p_home, p_draw=excluded.p_draw,
               p_away=excluded.p_away, xg_home=excluded.xg_home, xg_away=excluded.xg_away,
               pick=excluded.pick, data=excluded.data""",
        (match_id, source, ts, ts, MODEL_VERSION, *pred["final"], p.get("lh"), p.get("la"),
         pred["pick"], json.dumps(pred, default=float)),
    )
