"""Configuration globale de ProbaFoot."""
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
DB_PATH = DATA_DIR / "probafoot.db"

# Clé Understat -> infos d'affichage + code de division football-data.co.uk
LEAGUES = {
    "EPL": {"name": "Premier League", "country": "Angleterre", "fd": "E0"},
    "La_liga": {"name": "La Liga", "country": "Espagne", "fd": "SP1"},
    "Bundesliga": {"name": "Bundesliga", "country": "Allemagne", "fd": "D1"},
    "Serie_A": {"name": "Serie A", "country": "Italie", "fd": "I1"},
    "Ligue_1": {"name": "Ligue 1", "country": "France", "fd": "F1"},
}

HISTORY_SEASONS = 9       # saisons précédentes chargées (ratings, cotes passées, apprentissage)
BACKTEST_SEASONS = 7      # saisons précédentes rejouées en backtest (+ saison en cours)
UNDERSTAT_DELAY = 1.0     # secondes minimum entre deux requêtes vers un même hôte
CACHE_TTL_CURRENT = 3000  # durée de validité du cache pour la saison en cours (s)
AUTO_SYNC_HOURS = 1       # synchro automatique tant que le serveur tourne (0 = off)

MODEL_VERSION = "2.0"

# Paramètres des modèles. Valeurs retenues après une recherche sur le backtest (log-loss) :
# les modèles / facteurs qui n'apportaient rien (Elo, forme, confrontations directes, fatigue,
# rotation, météo, enjeu, derby) ont été retirés du calcul et ne sont plus qu'informatifs.
DEFAULT_PARAMS = {
    # Poisson / Dixon-Coles
    "xg_weight": 0.6,          # part de l'xG (vs buts réels) dans la « force offensive »
    "half_life_days": 600,     # demi-vie de la pondération temporelle (optimisée : 600 > 180)
    "window_days": 800,        # fenêtre d'historique pour les ratings
    "shrink_k": 6.0,           # régularisation vers la moyenne (en matchs équivalents)
    "promoted_att": 0.85,      # a priori attaque d'un promu
    "promoted_def": 1.15,      # a priori défense d'un promu (>1 = encaisse plus)
    "dc_rho": -0.06,           # correction Dixon-Coles des petits scores
    # Force selon les cotes passées
    "mr_window_days": 365,
    "mr_half_life_days": 120,
    "mr_ridge": 0.3,
    # Forme (affichage) : nombre de matchs
    "form_n": 6,
    # Ajustements (appris par le module d'apprentissage)
    "abs_att_beta": 0.75,      # impact des absences offensives sur les buts attendus
    "abs_def_beta": 0.6,       # impact des absences défensives sur les buts adverses
    "abs_rating_beta": 0.8,    # impact de la « qualité » perdue (notes moyennes des absents)
    "home_adv_beta": 1.0,      # avantage domicile propre à chaque équipe
    "home_adv_k": 8.0,         # régularisation de cet avantage (en matchs équivalents)
    "max_abs_share": 0.6,
}

# Coefficients ré-estimés par l'apprentissage : grille testée
TUNABLE = {
    "abs_att_beta": (0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5),
    "abs_def_beta": (0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
    "abs_rating_beta": (0.0, 0.3, 0.5, 0.8, 1.1, 1.4),
    "home_adv_beta": (0.0, 0.25, 0.5, 0.75, 1.0),
}
COEF_LABELS = {
    "abs_att_beta": "Absences offensives (xG+xA)",
    "abs_def_beta": "Absences défensives",
    "abs_rating_beta": "Absences pondérées par les notes",
    "home_adv_beta": "Avantage domicile propre à l'équipe",
}

# Poids initiaux de l'ensemble (ré-appris à partir des résultats).
# Deux profils : avec cotes disponibles, et sans (la plupart des matchs à J-7 et plus).
# "sharpness" > 1 rend les probabilités plus tranchées (corrige la sous-confiance du mélange).
DEFAULT_WEIGHTS = {
    "with_market": {"poisson": 0.19, "mratings": 0.19, "market": 0.62, "sharpness": 1.2},
    "no_market": {"poisson": 0.45, "mratings": 0.55, "market": 0.0, "sharpness": 1.2},
}
MODEL_NAMES = ["poisson", "mratings", "market"]
MODEL_LABELS = {
    "poisson": "Poisson / Dixon-Coles (xG)",
    "mratings": "Force selon les cotes passées",
    "market": "Marché (cotes du match)",
}
# Priorité des sources pour le modèle « marché » : les plus efficaces d'abord
MARKET_SOURCES = ["Betfair Exchange", "Pinnacle", "Avg"]

MIN_SAMPLES_LEARN = 60
BACKTEST_SAMPLE_WEIGHT = 0.5  # poids d'un match de backtest vs un pronostic réel
VALUE_EDGE_MIN = 0.05         # avantage minimum pour signaler un value bet


def current_season(today: date | None = None) -> int:
    """Understat identifie une saison par son année de début (2026 = 2026/27)."""
    today = today or date.today()
    return today.year if today.month >= 7 else today.year - 1
