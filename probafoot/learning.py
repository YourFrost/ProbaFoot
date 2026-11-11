"""Suivi des performances et ré-apprentissage des poids.

- Chaque pronostic est sauvegardé (source 'live' = fait avant le match, figé au coup d'envoi ;
  'backtest' = rejoué a posteriori avec uniquement les données antérieures au match).
- Métriques : taux de réussite (favori = résultat), score de Brier, log-loss, calibration.
- Apprentissage : on cherche les poids de l'ensemble (et les coefficients absences/fatigue)
  qui minimisent la log-loss sur les matchs terminés, avec une régularisation vers les poids
  précédents pour éviter de sur-réagir. Un modèle peu fiable voit donc son poids baisser.
"""
import copy
import json
import math
from collections import defaultdict
from datetime import date

import numpy as np
from scipy.optimize import minimize, minimize_scalar

from . import models
from .config import (BACKTEST_SAMPLE_WEIGHT, BACKTEST_SEASONS, DEFAULT_PARAMS, DEFAULT_WEIGHTS,
                     MIN_SAMPLES_LEARN, MODEL_NAMES, TUNABLE, current_season)
from .dataset import Dataset
from .db import now_iso
from .predict import predict_match, save_prediction

NAMES = MODEL_NAMES
MIN_AFFECTED = 30  # nb minimum de matchs concernés pour ré-estimer un coefficient d'ajustement


def current_model(conn) -> tuple[dict, dict]:
    row = conn.execute("SELECT * FROM weights_history ORDER BY id DESC LIMIT 1").fetchone()
    # poids d'une ancienne version (modèles différents) : on repart des valeurs par défaut
    if not row or "mratings" not in json.loads(row["weights"]).get("with_market", {}):
        return copy.deepcopy(DEFAULT_WEIGHTS), dict(DEFAULT_PARAMS)
    return json.loads(row["weights"]), {**DEFAULT_PARAMS, **json.loads(row["params"])}


def collect(conn, sources=("live",), league: str | None = None) -> list[dict]:
    q = """SELECT p.*, m.hg, m.ag, m.league, m.home, m.away, m.kickoff FROM predictions p
           JOIN matches m ON m.id = p.match_id
           WHERE m.is_result = 1 AND m.hg IS NOT NULL AND p.source IN (%s)""" % ",".join("?" * len(sources))
    args = list(sources)
    if league:
        q += " AND m.league = ?"
        args.append(league)
    out = []
    for r in conn.execute(q + " ORDER BY m.kickoff", args):
        s = dict(r)
        s["y"] = 0 if s["hg"] > s["ag"] else 1 if s["hg"] == s["ag"] else 2
        s["data"] = json.loads(s["data"])
        out.append(s)
    return out


def _scores(p, y):
    p = np.asarray(p, dtype=float)
    onehot = np.eye(3)[y]
    return {"correct": int(np.argmax(p) == y), "brier": float(((p - onehot) ** 2).sum()),
            "logloss": float(-math.log(max(p[y], 1e-9)))}


def _summary(rows):
    if not rows:
        return {"n": 0}
    return {"n": len(rows), "accuracy": np.mean([r["correct"] for r in rows]),
            "brier": np.mean([r["brier"] for r in rows]), "logloss": np.mean([r["logloss"] for r in rows])}


def metrics(samples: list[dict]) -> dict:
    overall, per_model, per_league = [], defaultdict(list), defaultdict(list)
    calib = defaultdict(lambda: [0, 0.0, 0])  # tranche -> [n, somme p, réalisés]
    for s in samples:
        final = [s["p_home"], s["p_draw"], s["p_away"]]
        sc = _scores(final, s["y"])
        overall.append(sc)
        per_league[s["league"]].append(sc)
        for name, p in s["data"]["models"].items():
            if p is not None:
                per_model[name].append(_scores(p, s["y"]))
        for i, p in enumerate(final):
            b = min(int(p * 10), 9)
            calib[b][0] += 1
            calib[b][1] += p
            calib[b][2] += int(s["y"] == i)
    # référence naïve : toujours les taux de base de la ligue
    baseline = [_scores(s["data"]["details"].get("base_rates") or [0.44, 0.26, 0.30], s["y"]) for s in samples]
    return {
        "overall": _summary(overall),
        "baseline": _summary(baseline),
        "per_model": {k: _summary(v) for k, v in per_model.items()},
        "per_league": {k: _summary(v) for k, v in per_league.items()},
        "calibration": [{"bin": f"{b * 10}-{b * 10 + 10}%", "n": v[0], "predicted": v[1] / v[0],
                         "observed": v[2] / v[0]} for b, v in sorted(calib.items()) if v[0]],
    }


def _ensemble_ll(P, mask, y, sw, w, sharp):
    """Log-loss moyenne du mélange pondéré (poids w, netteté sharp)."""
    mw = mask * w
    p = ((P * mw[:, :, None]).sum(1) / mw.sum(1, keepdims=True)) ** sharp
    p /= p.sum(1, keepdims=True)
    return float(-(sw * np.log(np.clip(p[np.arange(len(y)), y], 1e-9, 1))).sum() / sw.sum())


def _profile_vec(profile: dict, active: list[str]) -> np.ndarray:
    w = np.array([profile.get(n, 0) if n in active else 0 for n in NAMES], dtype=float)
    return w / w.sum()


def _fit_profile(P, mask, y, sw, profile: dict, active: list[str], reg=0.02):
    """Optimise les poids (softmax sur les modèles actifs) + la netteté."""
    ia = [NAMES.index(n) for n in active]
    w0 = _profile_vec(profile, active)

    def unpack(theta):
        w = np.zeros(len(NAMES))
        e = np.exp(theta[:-1] - theta[:-1].max())
        w[ia] = e / e.sum()
        return w, math.exp(theta[-1])

    def loss(theta):
        w, sharp = unpack(theta)
        return _ensemble_ll(P, mask, y, sw, w, sharp) + reg * ((w - w0) ** 2).sum()

    x0 = np.append(np.log(np.clip(w0[ia], 1e-4, None)), math.log(profile.get("sharpness", 1.0)))
    res = minimize(loss, x0, method="L-BFGS-B",
                   bounds=[(None, None)] * len(ia) + [(math.log(0.7), math.log(1.6))])
    w, sharp = unpack(res.x)
    out = {n: round(float(v), 4) for n, v in zip(NAMES, w)}
    out["sharpness"] = round(sharp, 4)
    return out, _ensemble_ll(P, mask, y, sw, w, sharp)


# ---------------------------------------------------------------- modèle final appris (méta-modèle)
MIN_META_MATCHES = 1500


def _meta_rows(samples: list[dict]):
    """Une ligne par issue (3 par match) : variables explicatives, décalage = logit(proba du marché)."""
    X, off, y = [], [], []
    for s in samples:
        d = s["data"]
        pw, b = d["models"].get("market"), d.get("base") or {}
        if not pw or not b.get("poisson"):
            continue
        for i in range(3):
            X.append(models.meta_features(pw, b["poisson"], b.get("mratings"), i))
            off.append(models.logit(pw[i]))
            y.append(float(s["y"] == i))
    return np.array(X), np.array(off), np.array(y)


def _fit_beta(X, off, y, l2=5.0) -> list[float]:
    def loss(b):
        z = off + X @ b
        return np.mean(np.log1p(np.exp(-np.where(y > 0, z, -z)))) + l2 * (b[1:] ** 2).sum() / len(y)
    return [float(v) for v in minimize(loss, np.zeros(X.shape[1]), method="L-BFGS-B").x]


def _meta_ll(samples: list[dict], meta: dict, use_abs=True) -> float:
    out = []
    for s in samples:
        d = s["data"]
        pw, b = d["models"].get("market"), d.get("base") or {}
        if pw and b.get("poisson"):
            q = models.meta_probs(pw, b["poisson"], b.get("mratings"), meta, d["models"]["poisson"] if use_abs else None)
            out.append(-math.log(max(q[s["y"]], 1e-9)))
    return float(np.mean(out)) if out else float("nan")


def fit_meta(samples: list[dict]) -> dict | None:
    """Apprend le modèle final. beta : correction des cotes selon nos modèles (tout l'historique) ;
    gamma : poids des absences, appris sur les matchs où les compositions sont connues."""
    X, off, y = _meta_rows(samples)
    if len(y) < 3 * MIN_META_MATCHES:
        return None
    meta = {"beta": _fit_beta(X, off, y), "gamma": 0.5, "n": len(y) // 3}
    with_abs = [s for s in samples if s["data"]["models"].get("market") and (s["data"].get("base") or {}).get("poisson")
                and any(s["data"]["adj"].get(k) for k in ("abs_att_h", "abs_att_a", "abs_def_h", "abs_def_a", "abs_rating_h", "abs_rating_a"))]
    meta["n_abs"] = len(with_abs)
    if len(with_abs) >= 100:
        res = minimize_scalar(lambda g: _meta_ll(with_abs, {**meta, "gamma": g}), bounds=(0.0, 1.5), method="bounded")
        meta["gamma"] = round(float(res.x), 3)
    # contrôle hors échantillon : appris sur les 80 % plus anciens, jugé sur les 20 % récents
    ordered = sorted([s for s in samples if s["data"]["models"].get("market") and (s["data"].get("base") or {}).get("poisson")],
                     key=lambda s: s["kickoff"])
    cut = int(len(ordered) * 0.8)
    Xt, ot, yt = _meta_rows(ordered[:cut])
    val = ordered[cut:]
    meta["val_meta"] = _meta_ll(val, {"beta": _fit_beta(Xt, ot, yt), "gamma": 0.0}, use_abs=False)
    meta["val_market"] = float(np.mean([-math.log(max(s["data"]["models"]["market"][s["y"]], 1e-9)) for s in val]))
    meta["features"] = models.META_FEATURES
    return meta


def walkforward(conn, params: dict, progress=lambda msg, frac: None) -> dict:
    """Pour chaque saison du backtest, recalcule le pronostic final avec un modèle appris
    UNIQUEMENT sur les saisons précédentes, sans les compositions officielles. C'est ce
    pronostic « honnête » qu'utilisent les statistiques et la simulation de bankroll."""
    rows = []
    for r in conn.execute("""SELECT p.match_id, p.data, m.season, m.hg, m.ag, m.kickoff FROM predictions p
                             JOIN matches m ON m.id = p.match_id WHERE p.source='backtest' ORDER BY m.kickoff"""):
        d = json.loads(r["data"])
        y = None if r["hg"] is None else (0 if r["hg"] > r["ag"] else 1 if r["hg"] == r["ag"] else 2)
        rows.append({"match_id": r["match_id"], "season": r["season"], "kickoff": r["kickoff"], "y": y, "data": d})
    seasons = sorted({r["season"] for r in rows})
    n_wf = 0
    for k, S in enumerate(seasons):
        progress(f"Apprentissage progressif, saison {S}/{S + 1}", k / len(seasons))
        train = [r for r in rows if r["season"] < S and r["y"] is not None]
        X, off, y = _meta_rows(train)
        meta = {"beta": _fit_beta(X, off, y), "gamma": 0.0} if len(y) >= 3 * MIN_META_MATCHES else None
        for r in (x for x in rows if x["season"] == S):
            d = r["data"]
            pw, b, pz = d["models"].get("market"), d.get("base") or {}, d.get("poisson")
            if pw and b.get("poisson"):
                fin = models.meta_probs(pw, b["poisson"], b.get("mratings"), meta) if meta else pw
            elif b.get("poisson"):   # pas de cotes : moyenne des modèles sans absences
                prof = {k2: v for k2, v in (d.get("weights") or {}).items()} if d.get("profile") == "no_market" else {"poisson": 0.4, "mratings": 0.6}
                fin = models.ensemble({"poisson": b["poisson"], "mratings": b.get("mratings")}, {**prof, "sharpness": prof.get("sharpness", 1.0)}) or d["final"]
            else:
                fin = d["final"]
            ou = None
            if pz:
                lh, la = models.adjusted_lambdas(pz["lh0"], pz["la0"], {"home_att": d["adj"].get("home_att"), "home_def": d["adj"].get("home_def")}, params)
                ou = models.markets(models.score_matrix(lh, la, params["dc_rho"]))["over25"]
                o = (d.get("details") or {}).get("odds") or {}
                if o.get("over25") and o.get("under25"):
                    ou = 0.7 * (1 / o["over25"]) / (1 / o["over25"] + 1 / o["under25"]) + 0.3 * ou
            d["sim"] = {"final": [float(x) for x in fin], "over25": ou, "walkforward": bool(meta)}
            n_wf += bool(meta)
            conn.execute("UPDATE predictions SET data=?, p_home=?, p_draw=?, p_away=?, pick=? WHERE match_id=? AND source='backtest'",
                         (json.dumps(d, default=float), fin[0], fin[1], fin[2], "HDA"[int(np.argmax(fin))], r["match_id"]))
        conn.commit()
    return {"seasons": seasons, "walkforward_matches": n_wf}


def learn(conn) -> dict:
    samples = [s for s in collect(conn, ("live", "backtest")) if s["data"].get("poisson")]
    # un match à la fois : si un pronostic live existe, il remplace le backtest
    by_match = {}
    for s in samples:
        if s["match_id"] not in by_match or s["source"] == "live":
            by_match[s["match_id"]] = s
    samples = sorted(by_match.values(), key=lambda s: s["kickoff"])
    if len(samples) < MIN_SAMPLES_LEARN:
        return {"ok": False, "message": f"Pas assez de matchs terminés ({len(samples)}/{MIN_SAMPLES_LEARN}). "
                                         "Lancez un backtest ou attendez de nouveaux résultats."}

    weights, params = current_model(conn)
    y = np.array([s["y"] for s in samples])
    sw = np.array([1.0 if s["source"] == "live" else BACKTEST_SAMPLE_WEIGHT for s in samples])
    mask = np.array([[s["data"]["models"].get(n) is not None for n in NAMES] for s in samples], dtype=float)
    base_P = np.array([[s["data"]["models"].get(n) or [1 / 3] * 3 for n in NAMES] for s in samples], dtype=float)
    im = NAMES.index("market")
    has_market = mask[:, im] > 0
    mask_nm = mask.copy()
    mask_nm[:, im] = 0  # profil « sans cotes » : on ignore le marché même s'il existe
    active_wm, active_nm = NAMES, [n for n in NAMES if n != "market"]

    adj = [s["data"]["adj"] for s in samples]
    pi = NAMES.index("poisson")

    mri = NAMES.index("mratings")

    def probs_for(trial):
        P = base_P.copy()
        for i, s in enumerate(samples):
            pz = s["data"]["poisson"]
            P[i, pi] = models.poisson_probs(pz["lh0"], pz["la0"], adj[i], trial)
            mz = s["data"]["details"].get("mratings")
            if mz:
                P[i, mri] = models.poisson_probs(mz["lh0"], mz["la0"], {**adj[i], "home_att": 1.0, "home_def": 1.0}, trial)
        return P

    def fit(P, idx):
        wm = weights["with_market"]
        im_idx = idx[has_market[idx]]
        if len(im_idx) >= MIN_SAMPLES_LEARN:
            wm, _ = _fit_profile(P[im_idx], mask[im_idx], y[im_idx], sw[im_idx], wm, active_wm)
        nm, _ = _fit_profile(P[idx], mask_nm[idx], y[idx], sw[idx], weights["no_market"], active_nm)
        return {"with_market": wm, "no_market": nm}

    def score(P, idx, prof):
        """Moyenne des log-loss des deux profils (avec cotes / sans cotes) sur les matchs idx."""
        nm, wm = prof["no_market"], prof["with_market"]
        lls = [_ensemble_ll(P[idx], mask_nm[idx], y[idx], sw[idx], _profile_vec(nm, active_nm), nm.get("sharpness", 1.0))]
        im_idx = idx[has_market[idx]]
        if len(im_idx):
            lls.append(_ensemble_ll(P[im_idx], mask[im_idx], y[im_idx], sw[im_idx],
                                    _profile_vec(wm, active_wm), wm.get("sharpness", 1.0)))
        return float(np.mean(lls))

    # Choix des coefficients sur une validation chronologique : on apprend sur les 80 % plus
    # anciens et on juge sur les 20 % les plus récents. Les coefficients sont testés un par un
    # (descente par coordonnées) ; un coefficient ne change que si le gain hors échantillon est
    # réel (> 0.0005 de log-loss) et s'il y a assez de matchs concernés par ce facteur.
    all_idx = np.arange(len(samples))
    cut = int(len(samples) * 0.8)
    tr_idx, va_idx = all_idx[:cut], all_idx[cut:]
    trial = dict(params)
    P_cur = probs_for(trial)
    P_start = P_cur
    val_cur = score(P_cur, va_idx, fit(P_cur, tr_idx))
    val_start = score(P_start, va_idx, weights)
    tested = {}
    for coef, grid in TUNABLE.items():
        n_aff = sum(1 for a in adj if _affected(coef, a))
        tested[coef] = n_aff
        if n_aff < MIN_AFFECTED:
            continue
        best_v, best_val, best_P = trial[coef], val_cur, P_cur
        for v in grid:
            if v == trial[coef]:
                continue
            P = probs_for({**trial, coef: v})
            val = score(P, va_idx, fit(P, tr_idx))
            if val < best_val - 0.0005:
                best_v, best_val, best_P = v, val, P
        trial[coef], val_cur, P_cur = best_v, best_val, best_P

    new_weights = fit(P_cur, all_idx)
    meta = fit_meta(samples)
    if meta:
        new_weights["meta"] = meta
    ll_before = score(P_start, all_idx, weights)
    ll_after = score(P_cur, all_idx, new_weights)
    new_params = {k: trial[k] for k in TUNABLE}
    n_live = int((sw == 1.0).sum())
    conn.execute(
        "INSERT INTO weights_history(created_at, weights, params, n_samples, logloss_before, logloss_after, note) "
        "VALUES(?,?,?,?,?,?,?)",
        (now_iso(), json.dumps(new_weights), json.dumps(new_params), len(samples), ll_before, ll_after,
         f"{n_live} live + {len(samples) - n_live} backtest"),
    )
    return {"ok": True, "weights": new_weights, "params": new_params, "n": len(samples),
            "logloss_before": ll_before, "logloss_after": ll_after, "affected": tested,
            "validation_before": val_start, "validation_after": val_cur,
            "meta": {k: meta[k] for k in ("n", "n_abs", "gamma", "val_meta", "val_market")} if meta else None}


def _affected(coef: str, a: dict) -> bool:
    """Le match est-il concerné par le facteur que règle ce coefficient ?"""
    if coef == "home_adv_beta":
        return a.get("home_att") is not None
    key = {"abs_att_beta": "abs_att", "abs_def_beta": "abs_def", "abs_rating_beta": "abs_rating"}.get(coef)
    return bool(key and any(a.get(f"{key}_{s}") for s in ("h", "a")))


def run_backtest(conn, progress=lambda msg, frac: None) -> dict:
    """Rejoue les matchs terminés (saison précédente + en cours) sans fuite d'information.
    Pour la saison en cours, les compositions réelles (connues ~1 h avant le match) et la météo
    sont utilisées : cela permet d'apprendre l'impact des absences et des notes des joueurs."""
    from . import absences, context
    from .sync import load_books
    first = current_season() - BACKTEST_SEASONS
    weights, params = current_model(conn)
    ds = Dataset(conn, params)
    odds = {r["match_id"]: dict(r) for r in conn.execute("SELECT * FROM odds")}
    books = load_books(conn)
    games = [g for g in ds.played if g["season"] >= first]
    done = 0
    for i, g in enumerate(games):
        ctx = context.stored_context(conn, g["id"])
        abs_ = None
        if ctx and ctx.get("lineup_confirmed"):
            abs_ = {s: absences.team_absences(conn, ds, g, s, {}, ctx, fetch_rosters=False) for s in ("home", "away")}
        pred = predict_match(ds, g, params, weights, odds=odds.get(g["id"]), absences=abs_,
                             ctx=ctx, books=books.get(g["id"]))
        if pred:
            save_prediction(conn, g["id"], "backtest", pred)
            done += 1
        if i % 100 == 0:
            progress(f"Backtest {i}/{len(games)}", 0.85 * i / max(len(games), 1))
            conn.commit()
    conn.commit()
    wf = walkforward(conn, params, lambda msg, f: progress(msg, 0.85 + 0.15 * f))
    return {"ok": True, "n": done, "walkforward": wf["walkforward_matches"]}
