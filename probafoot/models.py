"""Les modèles de probabilité. Chacun renvoie [P(dom), P(nul), P(ext)].

1. Poisson / Dixon-Coles : buts attendus λ = moyenne_ligue × attaque × défense_adverse,
   ratings estimés sur xG+buts pondérés dans le temps (ajustés à la force des adversaires).
2. Force selon les cotes passées : attaque/défense de chaque équipe déduites des cotes de ses
   matchs précédents (ce que « pense » le marché de chaque équipe), même matrice des scores.
3. Marché : probabilités implicites des cotes du match (Betfair Exchange, sinon Pinnacle,
   sinon moyenne), marge du bookmaker retirée.

Elo, forme et confrontations directes ont été testés puis retirés : ils n'amélioraient pas
les prévisions une fois ces trois modèles combinés.
"""
import math

import numpy as np
from scipy.stats import poisson

DAY = 86400.0


# ---------------------------------------------------------------- Poisson / Dixon-Coles
def team_ratings(la, as_of: float, params: dict, priors: dict) -> dict | None:
    i0 = np.searchsorted(la.ts, as_of - params["window_days"] * DAY, "left")
    i1 = np.searchsorted(la.ts, as_of, "left")
    if i1 - i0 < 10:
        return None
    h, a = la.h[i0:i1], la.a[i0:i1]
    w = 0.5 ** (((as_of - la.ts[i0:i1]) / DAY) / params["half_life_days"])
    xw = params["xg_weight"]
    gh = xw * la.hx[i0:i1] + (1 - xw) * la.hg[i0:i1]
    ga = xw * la.ax[i0:i1] + (1 - xw) * la.ag[i0:i1]
    home_avg, away_avg = (w * gh).sum() / w.sum(), (w * ga).sum() / w.sum()

    n, k = la.n_teams, params["shrink_k"]
    p_att, p_def = np.ones(n), np.ones(n)
    for i, (pa_, pd_) in priors.items():
        p_att[i], p_def[i] = pa_, pd_
    att, de = p_att.copy(), p_def.copy()
    den = np.bincount(h, w, n) + np.bincount(a, w, n)
    active = den > 0
    for _ in range(5):
        num = np.bincount(h, w * gh / (home_avg * de[a]), n) + np.bincount(a, w * ga / (away_avg * de[h]), n)
        att = (num + k * p_att) / (den + k)
        num = np.bincount(h, w * ga / (away_avg * att[a]), n) + np.bincount(a, w * gh / (home_avg * att[h]), n)
        de = (num + k * p_def) / (den + k)
        att /= np.average(att[active], weights=den[active])
        de /= np.average(de[active], weights=den[active])

    hw = (w * (la.hg[i0:i1] > la.ag[i0:i1])).sum() / w.sum()
    dw = (w * (la.hg[i0:i1] == la.ag[i0:i1])).sum() / w.sum()

    # Avantage domicile propre à l'équipe : buts marqués / encaissés à domicile rapportés à
    # l'attendu (ratings globaux), régularisé vers 1
    kh = params["home_adv_k"]
    exp_for = home_avg * att[h] * de[a]
    exp_against = away_avg * att[a] * de[h]
    home_att = (np.bincount(h, w * gh, n) + kh * home_avg) / (np.bincount(h, w * exp_for, n) + kh * home_avg)
    home_def = (np.bincount(h, w * ga, n) + kh * away_avg) / (np.bincount(h, w * exp_against, n) + kh * away_avg)
    return {"att": att, "de": de, "home_avg": home_avg, "away_avg": away_avg,
            "n_eff": den, "base": [hw, dw, 1 - hw - dw], "home_att": home_att, "home_def": home_def}


def adjusted_lambdas(lh0: float, la0: float, adj: dict, params: dict) -> tuple[float, float]:
    """Applique les absences et l'avantage domicile propre à l'équipe aux buts attendus."""
    cap = params["max_abs_share"]
    g = lambda k: min(adj.get(k) or 0, cap)
    b_att, b_def, b_rat = params["abs_att_beta"], params["abs_def_beta"], params["abs_rating_beta"]
    # absences : xG+xA perdus, défense affaiblie, qualité perdue (notes)
    lh = lh0 * (1 - b_att * g("abs_att_h")) * (1 + b_def * g("abs_def_a"))
    la = la0 * (1 - b_att * g("abs_att_a")) * (1 + b_def * g("abs_def_h"))
    lh *= (1 - b_rat * g("abs_rating_h")) * (1 + b_rat / 2 * g("abs_rating_a"))
    la *= (1 - b_rat * g("abs_rating_a")) * (1 + b_rat / 2 * g("abs_rating_h"))
    hb = params["home_adv_beta"]
    lh *= (adj.get("home_att") or 1.0) ** hb
    la *= (adj.get("home_def") or 1.0) ** hb
    return max(lh, 0.05), max(la, 0.05)


def score_matrix(lh: float, la: float, rho: float, maxg: int = 10) -> np.ndarray:
    g = np.arange(maxg + 1)
    m = np.outer(poisson.pmf(g, lh), poisson.pmf(g, la))
    m[0, 0] *= 1 - lh * la * rho
    m[0, 1] *= 1 + lh * rho
    m[1, 0] *= 1 + la * rho
    m[1, 1] *= 1 - rho
    m = np.clip(m, 0, None)
    return m / m.sum()


def markets(m: np.ndarray) -> dict:
    g = np.arange(m.shape[0])
    total = np.add.outer(g, g)
    order = np.argsort(m, axis=None)[::-1][:8]
    top = [{"score": f"{i}-{j}", "p": float(m[i, j])} for i, j in zip(*np.unravel_index(order, m.shape))]
    return {
        "1x2": [float(np.tril(m, -1).sum()), float(np.trace(m)), float(np.triu(m, 1).sum())],
        "over25": float(m[total >= 3].sum()),
        "over15": float(m[total >= 2].sum()),
        "over35": float(m[total >= 4].sum()),
        "btts": float(m[1:, 1:].sum()),
        "top_scores": top,
    }


def poisson_probs(lh0: float, la0: float, adj: dict, params: dict) -> list[float]:
    lh, la = adjusted_lambdas(lh0, la0, adj, params)
    return markets(score_matrix(lh, la, params["dc_rho"]))["1x2"]


# ---------------------------------------------------------------- Ratings « cotes passées »
_GRID = None


def _implied_grid():
    """Table (λ dom, λ ext) -> P(dom), P(ext), P(+2.5) pour inverser les cotes rapidement."""
    global _GRID
    if _GRID is None:
        vals = np.round(np.arange(0.2, 4.01, 0.05), 2)
        g = np.arange(11)
        pm = {v: poisson.pmf(g, v) for v in vals}
        tot = np.add.outer(g, g)
        rows = []
        for lh in vals:
            for la in vals:
                m = np.outer(pm[lh], pm[la])
                m[0, 0] *= 1 + 0.06 * lh * la
                m[0, 1] *= 1 - 0.06 * lh
                m[1, 0] *= 1 - 0.06 * la
                m[1, 1] *= 1.06
                m /= m.sum()
                rows.append((lh, la, np.tril(m, -1).sum(), np.triu(m, 1).sum(), m[tot >= 3].sum()))
        _GRID = np.array(rows)
    return _GRID


def implied_goals(p: list[float], over: float | None = None) -> tuple[float, float]:
    """Buts attendus (dom, ext) cohérents avec des probabilités 1N2 (et +2.5) issues des cotes."""
    G = _implied_grid()
    err = (G[:, 2] - p[0]) ** 2 + (G[:, 3] - p[2]) ** 2
    if over is not None:
        err = err + 0.5 * (G[:, 4] - over) ** 2
    i = int(np.argmin(err))
    return float(G[i, 0]), float(G[i, 1])


def market_team_ratings(mi, as_of: float, params: dict, priors: dict) -> dict | None:
    """Force de chaque équipe déduite des cotes de ses matchs passés.
    log λ_dom = μ + avantage + attaque_dom − défense_ext ; log λ_ext = μ + attaque_ext − défense_dom,
    moindres carrés pondérés dans le temps + régularisation (a priori plus faible pour les promus)."""
    i0 = np.searchsorted(mi.ts, as_of - params["mr_window_days"] * DAY, "left")
    i1 = np.searchsorted(mi.ts, as_of, "left")
    if i1 - i0 < 20:
        return None
    h, a = mi.h[i0:i1], mi.a[i0:i1]
    w = 0.5 ** (((as_of - mi.ts[i0:i1]) / DAY) / params["mr_half_life_days"])
    n, m = mi.n_teams, i1 - i0
    k = 2 + 2 * n  # μ, avantage, attaques, défenses
    X = np.zeros((2 * m, k))
    r = np.arange(m)
    X[r, 0] = 1; X[r, 1] = 1; X[r, 2 + h] = 1; X[r, 2 + n + a] = -1
    X[m + r, 0] = 1; X[m + r, 2 + a] = 1; X[m + r, 2 + n + h] = -1
    y = np.concatenate([np.log(mi.lh[i0:i1]), np.log(mi.la[i0:i1])])
    W = np.concatenate([w, w])
    b0 = np.zeros(k)
    for t, (pa_, pd_) in priors.items():
        b0[2 + t] = math.log(pa_)
        b0[2 + n + t] = -math.log(pd_)
    lam = np.full(k, params["mr_ridge"])
    lam[:2] = 1e-6
    A = X.T @ (X * W[:, None]) + np.diag(lam)
    beta = np.linalg.solve(A, X.T @ (W * y) + lam * b0)
    return {"mu": beta[0], "home": beta[1], "att": beta[2:2 + n], "def": beta[2 + n:]}


def market_rating_lambdas(r: dict, hi: int, ai: int) -> tuple[float, float]:
    lh = math.exp(r["mu"] + r["home"] + r["att"][hi] - r["def"][ai])
    la = math.exp(r["mu"] + r["att"][ai] - r["def"][hi])
    return lh, la


# ---------------------------------------------------------------- Forme (affichage)
def team_form(ds, team_id: str, ts: float, params: dict, implied: dict | None = None) -> dict | None:
    """Derniers résultats + points pris par rapport aux points « attendus » d'après les cotes
    d'avant-match : battre une équipe forte rapporte plus que battre une équipe faible."""
    games = ds.games_before(team_id, ts, params["form_n"])
    if len(games) < 2:
        return None
    seq, diffs = [], []
    for g in games:
        home = g["home_id"] == team_id
        gf, ga = (g["hg"], g["ag"]) if home else (g["ag"], g["hg"])
        pts = 3 if gf > ga else 1 if gf == ga else 0
        seq.append("V" if pts == 3 else "N" if pts == 1 else "D")
        p = (implied or {}).get(g["id"])
        if p:
            pw, pd = (p[0], p[1]) if home else (p[2], p[1])
            diffs.append(pts - (3 * pw + pd))
    return {"seq": "".join(seq),
            "vs_expected": round(sum(diffs) / len(diffs), 2) if diffs else None, "n": len(games)}


def h2h_list(ds, m: dict, n: int = 6) -> list[dict]:
    games = ds.pair_before(m["home_id"], m["away_id"], m["ts"])[-n:]
    return [{"date": g["kickoff"][:10], "home": g["home"], "away": g["away"],
             "score": f"{g['hg']}-{g['ag']}"} for g in reversed(games)]


# ---------------------------------------------------------------- Marché
def devig(odds) -> np.ndarray:
    """Retire la marge du bookmaker par la méthode « puissance » : p_i = (1/cote_i)^k, somme = 1.
    Contrairement à la simple normalisation, elle corrige le biais favori / outsider (les
    outsiders sont surcotés) : mesuré sur 8 900 matchs, log-loss 0,9701 contre 0,9706."""
    inv = np.array([1.0 / o for o in odds])
    lo, hi = 0.5, 3.0
    for _ in range(50):
        k = (lo + hi) / 2
        if (inv ** k).sum() > 1:
            lo = k
        else:
            hi = k
    p = inv ** ((lo + hi) / 2)
    return p / p.sum()


def market_probs(odds: dict | None, books: dict | None = None, sources=("Betfair Exchange", "Pinnacle")) -> list[float] | None:
    """Probabilités implicites, marge retirée. Source la plus efficace disponible d'abord."""
    for src in sources:
        o = (books or {}).get(src)
        if o and o.get("h") and o.get("d") and o.get("a"):
            return devig([o["h"], o["d"], o["a"]]).tolist()
    if not odds or not all(odds.get(k) for k in ("odds_h", "odds_d", "odds_a")):
        return None
    return devig([odds["odds_h"], odds["odds_d"], odds["odds_a"]]).tolist()


# ---------------------------------------------------------------- Modèle final appris
META_FEATURES = ["constante", "domicile", "nul", "écart Poisson xG", "écart cotes passées", "niveau de probabilité", "modèles d'accord"]


def logit(p: float) -> float:
    p = min(max(p, 0.001), 0.999)
    return math.log(p / (1 - p))


def meta_features(pw: list[float], po: list[float], pr: list[float] | None, i: int) -> list[float]:
    dp = logit(po[i]) - logit(pw[i])
    dr = logit(pr[i]) - logit(pw[i]) if pr else 0.0
    return [1.0, float(i == 0), float(i == 1), dp, dr, logit(pw[i]), float(dp * dr > 0 and abs(dp) > 0.1)]


def meta_probs(pw: list[float], po_base: list[float], mr_base: list[float] | None, meta: dict,
               po_adj: list[float] | None = None) -> list[float]:
    """Pronostic final : on part des cotes (marge retirée) et on les corrige selon l'écart de nos
    modèles, avec des coefficients appris sur l'historique. Les absences (inconnues des cotes
    relevées avant les compositions) s'ajoutent via gamma."""
    beta, gamma = meta["beta"], meta.get("gamma", 0.0)
    q = []
    for i in range(3):
        z = logit(pw[i]) + sum(b * x for b, x in zip(beta, meta_features(pw, po_base, mr_base, i)))
        if po_adj is not None and gamma:
            z += gamma * (logit(po_adj[i]) - logit(po_base[i]))
        q.append(1 / (1 + math.exp(-z)))
    t = sum(q)
    return [x / t for x in q]


# ---------------------------------------------------------------- Ensemble
def pick_profile(model_probs: dict, weights: dict) -> tuple[str, dict]:
    name = "with_market" if model_probs.get("market") is not None else "no_market"
    return name, weights[name]


def ensemble(model_probs: dict, profile: dict) -> list[float] | None:
    """Moyenne pondérée des modèles disponibles, puis réglage de la netteté."""
    num, tot = np.zeros(3), 0.0
    for name, p in model_probs.items():
        w = profile.get(name, 0)
        if p is not None and w > 0:
            num += w * np.array(p)
            tot += w
    if not tot:
        return None
    p = (num / tot) ** profile.get("sharpness", 1.0)
    return (p / p.sum()).tolist()
