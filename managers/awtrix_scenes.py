"""Pixel-art frame generators for the 32x8 Awtrix matrix.

Three scenes -- vent, meteo, houle -- driven by the real forecast.
Only `dl` (line) and `dp` (pixel) instructions are used: both are proven
against this firmware by the original sea animation.

Each scene says ONE thing, and they are deliberately different subjects so
the loop does not show "the weather" three times:

  vent   -- what the air does to an object: a flag on a mast, limp or whipping
  meteo  -- what the sky does: sun or moon at its hour, clouds, rain, over a
            Marseille horizon
  houle  -- what the sea does: the water itself, its swell and foam, with a
            pointu riding it when it is flat enough for one to be out

EVERY scene is loop-ready. The frames are encoded as a GIF the clock plays on
repeat, so the last frame must flow into the first with no visible jump. The
rule that guarantees it: nothing depends on the frame index directly, only on
the loop phase `u = f / N` in [0, 1), and every periodic term advances by a
WHOLE number of cycles over that phase -- sines get sin(2*pi * (k*u + ...))
with k integer, and anything travelling wraps on its own span an integer
number of times. At u = 1 the state is identical to u = 0.

The look is limited-palette pixel art: sixteen fixed colours, nothing drawn
outside them, skies dithered between neighbouring ramp steps, ground and
rigging as deep-plum silhouettes against a lit sky, two small accents.
"""

import math
from datetime import datetime

W, H = 32, 8
TAU = math.pi * 2


# ==========================================================================
# PALETTE -- seize couleurs, et rien en dehors
#
# Une seule rampe principale, du clair chaud au sombre froid : la teinte
# tourne en descendant (os -> sable -> peche -> rose -> mauve -> ardoise ->
# indigo -> prune), on n'assombrit jamais en baissant seulement la valeur.
# Trois bleus froids pour le ciel de jour, trois verts d'eau pour la mer,
# et deux accents seulement -- l'or et la brique -- qui portent toute
# l'energie : le drapeau, le guidon du pointu, la Vierge sur sa colline.
# Pas de blanc pur, pas de noir pur, pas de primaire : le blanc est un os,
# le noir une prune.
# ==========================================================================

BONE = "#F4E9CF"       # blanc os : ecume, lune, etoiles, coeur du soleil, nuages, voile
SAND = "#E9CC8C"       # sable : soleil, etoiles, nuage au soleil, plis du drapeau
PEACH = "#D8946E"      # peche : horizon du couchant, rayons, dessous du drapeau a l'ombre
ROSE = "#B6667C"       # rose poussiere : ciel du soir et de l'aube
MAUVE = "#7F4F82"      # mauve : haut du ciel au couchant, dessous des nuages
SLATE = "#4B4A7C"      # ardoise : horizon de nuit, ciel couvert
INDIGO = "#2E3161"     # indigo : ciel de nuit
PLUM = "#2E2350"       # prune : le "noir" -- sol, colline, mât, coque
SKY_PALE = "#A6D3DA"   # bleu pale : horizon de jour, traînees d'air, gouttes, ecume la nuit
SKY = "#5E9CC0"        # bleu : ciel de jour
SKY_DEEP = "#3D6B9F"   # bleu profond : zenith de jour
SEA_LIGHT = "#79C7B8"  # eau claire : face eclairee de la vague
SEA = "#3E8F90"        # eau
SEA_DEEP = "#27596C"   # eau profonde
GOLD = "#F0B23F"       # ACCENT or : plis eclaires du drapeau, tête de mât, la Vierge
BRICK = "#C4463C"      # ACCENT brique : le guidon du pointu, rien d'autre

PALETTE = (BONE, SAND, PEACH, ROSE, MAUVE, SLATE, INDIGO, PLUM,
           SKY_PALE, SKY, SKY_DEEP, SEA_LIGHT, SEA, SEA_DEEP, GOLD, BRICK)

# matrice de Bayer 2x2 : seuils pour tramer entre deux couleurs voisines
_BAYER = ((0.2, 0.7), (0.95, 0.45))


def _dither(x, y, frac):
    """True when pixel (x, y) takes the second colour of a frac-blend."""
    return frac > _BAYER[y % 2][x % 2]


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _is_night(hour):
    return hour >= 21 or hour < 6


def _clip(instr):
    """Keep every instruction on the panel: off-panel pixels are dropped and
    line endpoints clamped, so the firmware never sees a negative coordinate."""
    out = []
    for it in instr:
        if "dp" in it:
            x, y, c = it["dp"]
            if 0 <= x < W and 0 <= y < H:
                out.append(it)
        else:
            x0, y0, x1, y1, c = it["dl"]
            out.append({"dl": [_clamp(x0, 0, W - 1), _clamp(y0, 0, H - 1),
                               _clamp(x1, 0, W - 1), _clamp(y1, 0, H - 1), c]})
    return out


# --------------------------------------------------------------------------
# Ciel
# --------------------------------------------------------------------------

def sky_palette(hour, cloudiness=0, is_raining=False):
    """The sky as a ramp of palette colours, top to bottom.

    The last step is never the darkest one: a sky that fades to black at the
    horizon reads as a half-lit panel, not as a sky.
    """
    if is_raining:
        return (INDIGO, SLATE, SLATE)
    if cloudiness > 70:
        return (SLATE, SLATE, MAUVE)
    if 5 <= hour < 8:                      # aube
        return (MAUVE, ROSE, ROSE, PEACH)   # l'horizon reste peche : un soleil de sable s'y lit
    if 8 <= hour < 18:                     # jour
        return (SKY_DEEP, SKY, SKY_PALE)
    if 18 <= hour < 21:                    # couchant
        return (SLATE, MAUVE, ROSE, PEACH)
    return (INDIGO, SLATE, MAUVE)          # nuit : jamais aussi sombre que les silhouettes,
                                           # une lueur mauve de ville a l'horizon


def _sky(ramp):
    """Draw the ramp over the panel, dithering between neighbouring steps
    instead of banding: a full row is a `dl`, a mixed row is 32 `dp`."""
    out = []
    n = len(ramp) - 1
    for y in range(H):
        t = y / (H - 1) * n
        a = min(int(t), n - 1) if n else 0
        frac = t - a
        if n == 0 or frac < 0.05:
            out.append({"dl": [0, y, W - 1, y, ramp[a]]})
        elif frac > 0.97:
            out.append({"dl": [0, y, W - 1, y, ramp[a + 1]]})
        else:
            for x in range(W):
                out.append({"dp": [x, y, ramp[a + 1] if _dither(x, y, frac) else ramp[a]]})
    return out


# --------------------------------------------------------------------------
# VENT -- un drapeau, le seul instrument que tout le monde sait lire
# --------------------------------------------------------------------------

def wind_frames(wind_speed=15.0, wind_deg=270, hour=12, cloudiness=0,
                is_raining=False, n_frames=64, temp=20.0, style="drapeau",
                wave_height=None, sea_temp=20.0):
    """A flag on a mast: limp, sagging, streaming or whipping.

    The air is invisible; the flag is what it does. Its length, how far it
    lifts from the mast, the ripple's amplitude and frequency all come from
    wind_speed, so a still evening hangs and a mistral snaps. wind_deg is the
    direction the wind comes FROM: a westerly (270) blows the cloth to the
    right, so the mast stands on the left.

    A few pale streaks of air cross behind it -- they move at the flag's speed
    and give the eye the motion even when the cloth is short.

    style="voilier" draws the alternative scene instead -- a small sailing
    boat riding the swell, see _boat_frames -- with the same wind reading.
    """
    if style == "voilier":
        return _boat_frames(wind_speed, wind_deg, hour, cloudiness, is_raining,
                            n_frames, wave_height, sea_temp)

    ramp = sky_palette(hour, cloudiness, is_raining)

    to_right = 1 if (wind_deg < 90 or wind_deg >= 270) else -1
    strength = _clamp(wind_speed / 45.0, 0.0, 1.0)

    ext = strength ** 0.55                    # une brise souleve deja bien la toile
    length = 5 + int(round(17 * strength))    # 5..22 px de tissu
    amp = 0.30 + 0.60 * strength              # ondulation, en lignes : modeste,
    lam = 10.0 - 3.0 * strength               # la violence passe par la longueur
    laps = 1 + int(round(3 * strength))       # et la vitesse ; entier -> boucle
    mast_x = 3 if to_right > 0 else W - 4
    root_y = 1

    # traînées d'air derriere le drapeau
    n_streaks = 1 + int(round(4 * strength))
    s_laps = 1 + int(round(2 * strength))
    s_len = 3 + int(round(5 * strength))
    streaks = [{"y": 2 + (i * 3) % 4, "phase": i / n_streaks} for i in range(n_streaks)]
    streak_col = SKY_PALE

    frames = []
    for f in range(n_frames):
        u = f / n_frames
        instr = _sky(ramp)

        # sol : silhouette
        instr.append({"dl": [0, H - 1, W - 1, H - 1, PLUM]})

        # air : traînées pales, derriere tout le reste
        span = W + s_len
        for s in streaks:
            head = ((u * s_laps + s["phase"]) % 1.0) * span
            if to_right > 0:
                x0 = int(head) - s_len
            else:
                x0 = W - int(head)
            x1 = x0 + s_len - 1
            a, b = max(0, x0), min(W - 1, x1)
            if b >= a:
                instr.append({"dl": [a, s["y"], b, s["y"], streak_col]})

        # mât : silhouette, une pointe d'or
        instr.append({"dl": [mast_x, 0, mast_x, H - 2, PLUM]})
        instr.append({"dp": [mast_x, 0, GOLD]})

        # drapeau : une chaine de points du mât vers le bord libre. Une seule
        # toile d'or, modelee par l'ondulation : or sur sable dans les plis
        # eclaires, sable sur peche dans les plis a l'ombre. Une seule teinte,
        # pour que le mât sombre ne complete jamais un tricolore.
        pts = []
        for t in range(length):
            k = t / max(1, length - 1)                  # 0 au mât, 1 au bord libre
            ph = TAU * (t / lam - laps * u)
            x = mast_x + to_right * (1 + t * ext)
            y = (root_y
                 + t * (1.0 - ext) * 0.8                # la toile pend quand l'air manque
                 + amp * math.sin(ph) * (0.25 + 0.75 * k)   # attachee au mât, libre au bout
                 + 0.5 * (1.0 - ext) * k * math.sin(TAU * u))  # balancement lent, k=1
            lit = 0.5 + 0.5 * math.cos(ph)              # face eclairee de l'ondulation
            pts.append((x, y, lit))

        prev = None
        for i, (x, y, lit) in enumerate(pts):
            ix, iy = int(round(x)), int(round(y))
            # l'epaisseur se met en travers de la toile : a cote quand elle
            # pend, dessous quand elle flotte
            nx, ny = pts[min(i + 1, len(pts) - 1)][:2] if i + 1 < len(pts) else pts[i - 1][:2]
            steep = abs(ny - y) > abs(nx - x)
            ox, oy = (to_right, 0) if steep else (0, 1)
            top, under = (GOLD, SAND) if lit > 0.5 else (SAND, PEACH)
            if prev is not None:
                # relie les points pour garder une toile continue
                instr.append({"dl": [prev[0], prev[1], ix, iy, top]})
                instr.append({"dl": [prev[0] + prev[2], prev[1] + prev[3],
                                     ix + ox, iy + oy, under]})
            else:
                instr.append({"dp": [ix, iy, top]})
                instr.append({"dp": [ix + ox, iy + oy, under]})
            prev = (ix, iy, ox, oy)

        frames.append(_clip(instr))
    return frames


# --------------------------------------------------------------------------
# METEO -- le ciel au-dessus de Marseille, a cette heure-ci
# --------------------------------------------------------------------------

def weather_frames(temp=20.0, cloudiness=0, is_raining=False, wind_speed=10.0,
                   hour=12, n_frames=64, sunrise=7.0, sunset=20.0):
    """Sun or moon placed on its arc for the hour, clouds covering it in
    proportion to the forecast, rain falling from them, over a hill with the
    Bonne Mere on top.

    Reading order at a glance: is there a sun or a moon, how much cloud sits
    in front of it, is anything falling. The horizon is a silhouette, so the
    eye has a ground to read the lit sky against.
    """
    ramp = sky_palette(hour, cloudiness, is_raining)
    night = not (sunrise <= hour < sunset)
    rng = _Lcg(int(temp) * 104729 + int(cloudiness) * 31 + (1 if is_raining else 0))

    # position de l'astre sur son arc : gauche au lever, zenith au milieu,
    # droite au coucher. La nuit, la lune fait le meme trajet.
    if night:
        p = ((hour - sunset) % 24.0) / ((sunrise - sunset) % 24.0)
    else:
        p = (hour - sunrise) / (sunset - sunrise)
    p = _clamp(p, 0.0, 0.999)
    ax = int(round(2 + 27 * p))
    elev = math.sin(math.pi * p)
    ay = int(round(5.2 - 4.2 * elev))          # 5 a l'horizon (a demi couche), 1 au zenith

    # nuages : couverture -> nombre et taille ; >= 90 % -> plafond
    cover = max(cloudiness, 60) if is_raining else cloudiness
    overcast = cover >= 90
    n_clouds = 0 if cover < 15 else (1 if cover < 45 else (2 if cover < 75 else 3))
    clouds = []
    if not overcast:
        for i in range(n_clouds):
            w = (5 if cover < 45 else 7) + rng.randint(0, 3)
            clouds.append({"x0": (i + rng.uniform(0.1, 0.6)) / max(1, n_clouds),
                           "y": 1 + rng.randint(0, 1), "w": w, "span": W + w})
    c_laps = 1 if wind_speed < 25 else 2

    # plafond : deux rangs pleins et une base dechiquetee qui derive
    lumps = [{"x0": rng.uniform(0, 1), "w": 3 + rng.randint(0, 4)} for _ in range(5)]

    # etoiles : une seule famille, celle de la lune -- chacune clignote
    # entre sable et os, seule la luminosite change, jamais la teinte
    stars = []
    if night and cover < 60:
        n_stars = 7 if cover < 30 else 4
        while len(stars) < n_stars:
            sx, sy = rng.randint(0, W - 1), rng.randint(0, 3)
            if abs(sx - ax) > 2 and abs(sx - 21) > 1 and all(abs(sx - s[0]) > 1 for s in stars):
                stars.append((sx, sy, rng.uniform(0, 1), 1 + rng.randint(0, 2)))

    drops = [{"x": rng.randint(0, W - 1), "y0": rng.uniform(0, 1),
              "laps": 2 + rng.randint(0, 1)} for _ in range(16)] if is_raining else []
    slant = 1 if wind_speed > 18 else 0

    if night:
        cloud_hi, cloud_lo = MAUVE, SLATE
    elif is_raining:
        cloud_hi, cloud_lo = MAUVE, SLATE
    elif overcast:
        cloud_hi, cloud_lo = SKY_PALE, MAUVE
    else:
        cloud_hi, cloud_lo = BONE, MAUVE

    frames = []
    for f in range(n_frames):
        u = f / n_frames
        instr = _sky(ramp)

        # --- astre ---
        if night:
            for (sx, sy, ph, k) in stars:
                tw = 0.5 + 0.5 * math.sin(TAU * (k * u + ph))
                instr.append({"dp": [sx, sy, BONE if tw > 0.5 else SAND]})
            instr.append({"dl": [ax, ay - 1, ax, ay + 1, BONE]})
            instr.append({"dp": [ax - 1, ay, BONE]})
            instr.append({"dp": [ax + 1, ay - 1, SAND]})
            instr.append({"dp": [ax + 1, ay + 1, SAND]})
        elif not overcast:
            # soleil : croix de sable a coeur d'os, coins peche pour l'arrondir.
            # Bas sur l'horizon il garde ces couleurs : c'est le ciel qui
            # dit le couchant, un soleil peche s'y perdrait
            core, mid, rim = BONE, SAND, PEACH
            instr.append({"dl": [ax - 1, ay, ax + 1, ay, mid]})
            instr.append({"dp": [ax, ay - 1, mid]})
            instr.append({"dp": [ax, ay + 1, mid]})
            instr.append({"dp": [ax, ay, core]})
            for (dx, dy) in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                instr.append({"dp": [ax + dx, ay + dy, rim]})
            if cover < 75:
                # huit rayons qui s'echangent leur lumiere une fois par
                # boucle : le soleil tourne lentement, seule vie d'un ciel pur.
                # Trois pas -- vif, terne, eteint -- comme une animation a la main.
                breath = 0.5 + 0.5 * math.sin(TAU * u)
                for rays, b in ((((0, -2), (0, 2), (-2, 0), (2, 0)), breath),
                                (((-2, -2), (2, -2), (-2, 2), (2, 2)), 1.0 - breath)):
                    col = mid if b > 0.66 else (rim if b > 0.33 else None)
                    if col:
                        for (dx, dy) in rays:
                            instr.append({"dp": [ax + dx, ay + dy, col]})

        # --- pluie : sous les nuages, jusqu'au sol ---
        for d in drops:
            y = ((d["y0"] + d["laps"] * u) % 1.0) * 5.0 + 2.0     # 2..7
            iy = int(y)
            x = (d["x"] + slant * int(y - 2)) % W
            if 3 <= iy <= 5:
                instr.append({"dl": [x, iy, x, min(5, iy + 1), SKY_PALE]})

        # --- nuages ---
        if overcast:
            # plafond : un rang lumineux trame, un rang d'ombre, une base qui derive
            for x in range(W):
                instr.append({"dp": [x, 0, cloud_hi if _dither(x, 0, 0.5) else BONE]})
            instr.append({"dl": [0, 1, W - 1, 1, cloud_hi if is_raining else cloud_lo]})
            for l in lumps:
                cx = ((l["x0"] + c_laps * u) % 1.0) * (W + l["w"]) - l["w"]
                a, b = max(0, int(cx)), min(W - 1, int(cx) + l["w"] - 1)
                if b >= a:
                    instr.append({"dl": [a, 2, b, 2, cloud_lo]})
            if not night:
                # le soleil se devine a travers le plafond : une tache de sable
                a, b = max(0, ax - 1), min(W - 1, ax + 1)
                instr.append({"dl": [a, 1, b, 1, SAND]})
                instr.append({"dl": [a, 0, b, 0, BONE]})
        else:
            for c in clouds:
                cx = ((c["x0"] + c_laps * u) % 1.0) * c["span"] - c["w"]
                x0 = int(cx)
                x1 = x0 + c["w"] - 1
                y = c["y"]
                a, b = max(0, x0), min(W - 1, x1)
                if b >= a:
                    instr.append({"dl": [a, y, b, y, cloud_hi]})
                a2, b2 = max(0, x0 + 1), min(W - 1, x1 - 1)
                if b2 >= a2:
                    instr.append({"dl": [a2, y + 1, b2, y + 1, cloud_lo]})
                if c["w"] >= 7:
                    a3, b3 = max(0, x0 + 2), min(W - 1, x0 + 4)
                    if b3 >= a3 and y - 1 >= 0:
                        instr.append({"dl": [a3, y - 1, b3, y - 1, cloud_hi]})

        # --- sol : silhouette de prune, deux rangs, et la colline de la
        # Bonne Mere a droite du centre, pour que l'astre se leve et se
        # couche sur du plat et passe au-dessus d'elle a midi ---
        instr.append({"dl": [0, H - 2, W - 1, H - 2, PLUM]})
        instr.append({"dl": [0, H - 1, W - 1, H - 1, PLUM]})
        instr.append({"dl": [18, 5, 24, 5, PLUM]})
        instr.append({"dl": [20, 4, 22, 4, PLUM]})
        # la Vierge doree, eclairee la nuit ; de jour, une pointe de sable
        instr.append({"dp": [21, 3, GOLD if night else SAND]})

        frames.append(_clip(instr))
    return frames


# --------------------------------------------------------------------------
# HOULE -- la mer, rien que la mer (et un pointu quand elle est plate)
# --------------------------------------------------------------------------

def swell_frames(wave_height=0.4, wind_speed=10.0, sea_temp=20.0, hour=12,
                 cloudiness=0, is_raining=False, n_frames=64, boat="auto",
                 wind_deg=270):
    """The sea seen from the shore: a swell travelling across, lit on its
    face, darker with depth, foam only where a crest breaks.

    wave_height (metres, from Open-Meteo Marine) sets the amplitude and how
    much foam there is, wind_speed tightens the period and adds chop,
    sea_temp picks the water ramp, the sky above follows the hour and the
    cloud.

    The water height keeps the maths of the original liquid animation: a
    resting depth of two rows, an amplitude of up to six, truncated with
    int(), so a real swell climbs most of the panel and a flat sea sits low.

    boat="auto" puts a pointu on the water when the sea is flat enough for
    one to be out (and for its rig to fit above the crests); "oui" always,
    "non" never. Its heel reports the wind, leaning away from wind_deg.
    """
    ramp = sky_palette(hour, cloudiness, is_raining)

    amp = _clamp(wave_height * 4.0 + 0.5, 0.5, 6.0)      # comme l'ancienne animation
    sea = _sea_params(wave_height, wind_speed, sea_temp, hour, cloudiness, is_raining)

    frames = []
    for f in range(n_frames):
        u = f / n_frames
        instr = _sky(ramp)
        surfs = _draw_sea(instr, u, amp, sea)
        if boat == "oui" or (boat == "auto" and amp <= 1.49):
            _draw_boat(instr, surfs, u, _clamp(wind_speed / 45.0, 0.0, 1.0),
                       1 if (wind_deg < 90 or wind_deg >= 270) else -1)
        frames.append(_clip(instr))
    return frames


def _sea_params(wave_height, wind_speed, sea_temp, hour, cloudiness, is_raining):
    """Everything about the water that does not depend on the frame."""
    waves = 1.5 if wind_speed < 15 else (2 if wind_speed < 25 else 3)   # la phase en u reste entiere
    chop = 0.0 if wind_speed < 20 else _clamp((wind_speed - 20) / 25.0, 0.0, 0.6)
    foam_at = 0.95 - 0.28 * _clamp(wave_height / 1.5, 0.0, 1.0)

    # la rampe de l'eau, du fond a la face eclairee : eau chaude claire,
    # eau froide profonde et sombre, mer d'argent sous un ciel couvert,
    # mer d'encre la nuit
    if _is_night(hour):
        water = (INDIGO, SEA_DEEP, SEA)
    elif is_raining or cloudiness > 70:
        water = (SEA_DEEP, SEA, SKY_PALE)
    elif sea_temp < 17:
        water = (INDIGO, SEA_DEEP, SEA)
    else:
        water = (SEA_DEEP, SEA, SEA_LIGHT)
    return {"waves": waves, "laps": 1, "chop": chop, "foam_at": foam_at,
            "water": water, "foam": SKY_PALE if _is_night(hour) else BONE}


def _sea_level(x, u, amp, sea, direction=1):
    """Water column height at x (rows from the bottom) and the raw sine."""
    ph = TAU * (sea["waves"] * x / W - direction * sea["laps"] * u)
    s = math.sin(ph)
    if sea["chop"]:
        s = (s + sea["chop"] * math.sin(2 * ph + 0.8)) / (1.0 + sea["chop"])
    level = int((s + 1.0) * amp) + 2                 # int() tronque, comme avant
    return max(1, min(level, H)), s, ph


def _draw_sea(instr, u, amp, sea, direction=1):
    """Water from the bottom up: the wave face takes the light step of the
    ramp, then the water steps down through dithered bands to the deep one.
    Foam where a crest breaks. Returns the surface row per column so
    something can float on it."""
    deep, mid, light = sea["water"]
    surfs = []
    for x in range(W):
        level, s, ph = _sea_level(x, u, amp, sea, direction)
        surf = H - level
        surfs.append(surf)

        shade = 0.5 + 0.5 * math.sin(ph + 0.6)      # face au soleil ou dans l'ombre
        lit = shade > 0.55
        for y in range(surf, H):
            depth = y - surf
            if depth == 0:
                col = light if lit else mid
            elif depth == 1:
                col = mid
            elif depth == 2:
                col = mid if _dither(x, y, 0.5) else deep      # une seule bande tramee
            else:
                col = deep
            instr.append({"dp": [x, y, col]})

        # ecume, seulement la ou la crete casse
        if s > sea["foam_at"]:
            instr.append({"dp": [x, surf, sea["foam"]]})
    return surfs


# --------------------------------------------------------------------------
# VOILIER -- variante du vent : un pointu qui gite sur la houle
# --------------------------------------------------------------------------

def _boat_frames(wind_speed, wind_deg, hour, cloudiness, is_raining, n_frames,
                 wave_height=None, sea_temp=20.0):
    """A small sailing boat holding station mid-panel while the water moves
    under it. The sail reports the wind, the hull reports the water.

    Heel and sail shape come from wind_speed: upright with the sail furled in
    a calm, leaning to leeward with a taut sail in a mistral. wind_deg
    decides which side it leans to. The hull rides the same swell maths as
    the houle scene, compressed so there is room for the rig: it rises and
    falls with the crest under it and pitches with the local slope.

    Without a wave_height the sea is guessed from the wind, as the original
    animation did.
    """
    ramp = sky_palette(hour, cloudiness, is_raining)

    to_right = 1 if (wind_deg < 90 or wind_deg >= 270) else -1
    strength = _clamp(wind_speed / 45.0, 0.0, 1.0)
    lee = to_right                                   # la gite est sous le vent

    if wave_height is None:
        wave_height = _clamp(wind_speed / 40.0, 0.1, 1.2)
    # houle comprimee : 1 a 2 rangs de creux, il faut la place du greement
    amp = _clamp(0.6 + wave_height * 0.9, 0.6, 1.49)
    sea = _sea_params(wave_height, wind_speed, sea_temp, hour, cloudiness, is_raining)

    # traînees d'air en haut du ciel, seulement quand ca souffle
    n_streaks = int(round(3 * strength)) if strength > 0.4 else 0
    s_laps = 1 + int(round(2 * strength))
    s_len = 4 + int(round(4 * strength))
    streaks = [{"y": i % 2, "phase": i / max(1, n_streaks)} for i in range(n_streaks)]
    streak_col = SKY_PALE

    frames = []
    for f in range(n_frames):
        u = f / n_frames
        instr = _sky(ramp)

        span = W + s_len
        for st in streaks:
            head = ((u * s_laps + st["phase"]) % 1.0) * span
            x0 = int(head) - s_len if to_right > 0 else W - int(head)
            a, b = max(0, x0), min(W - 1, x0 + s_len - 1)
            if b >= a:
                instr.append({"dl": [a, st["y"], b, st["y"], streak_col]})

        surfs = _draw_sea(instr, u, amp, sea, direction=to_right)
        _draw_boat(instr, surfs, u, strength, lee)
        frames.append(_clip(instr))
    return frames


def _draw_boat(instr, surfs, u, strength, lee, cx=15):
    """A pointu on the water surface `surfs`, holding station at column cx.

    Hull and mast are a plum silhouette against the lit sky -- the classic
    image -- the sail is bone, and one brick pennant at the masthead keeps
    the rig from reading as an anonymous stick. The hull follows the crest
    under it and pitches with the local slope; the rig heels to leeward
    with the wind. In a calm the sail is furled on the boom: no sail up is
    the honest reading of no wind.
    """
    calm = strength < 0.15
    heel = 0 if calm else (1 if strength < 0.55 else 2)
    widths = (0, 0, 2) if calm else ((1, 2, 2) if strength < 0.55 else (1, 2, 3))
    flutter_k = 0 if calm else (2 if strength < 0.55 else 4)     # entier -> boucle

    # la coque se pose sur la surface au centre et suit la pente locale
    surf_c = surfs[cx]
    slope = surfs[cx - 2] - surfs[cx + 2]        # > 0 : l'eau monte vers la droite
    tilt = 0 if abs(slope) < 1 else (1 if slope > 0 else -1)
    y_h = surf_c - 1
    instr.append({"dl": [cx - 2, y_h + tilt, cx + 2, y_h - tilt, PLUM]})
    instr.append({"dl": [cx - 1, surf_c, cx + 1, surf_c, PLUM]})

    # mât qui gite sous le vent, guidon brique en tête
    mx_top = cx + lee * heel
    instr.append({"dl": [cx, y_h - 1, mx_top, y_h - 3, PLUM]})
    instr.append({"dp": [mx_top, y_h - 3, BRICK]})

    # voile : un triangle accroche au mât, cote sous le vent
    flap = 0.5 + 0.5 * math.sin(TAU * (flutter_k * u)) if flutter_k else 0.0
    for r in range(3):                            # r = 0 en haut
        w = widths[r]
        if w == 0:
            continue
        y = y_h - 3 + r
        mx = cx + lee * int(round(heel * (2 - r) / 2.0))
        x0, x1 = mx + lee, mx + lee * w
        instr.append({"dl": [x0, y, x1, y, SAND if calm else BONE]})   # ferlee : sable
        if w >= 2 and flutter_k:
            # la chute de la voile bat : son dernier pixel passe os / sable
            instr.append({"dp": [x1, y, BONE if flap > 0.5 else SAND]})


# --------------------------------------------------------------------------

class _Lcg:
    """Deterministic PRNG: same forecast -> same scene, no global random state."""

    def __init__(self, seed):
        self.s = (seed or 1) & 0x7FFFFFFF or 1

    def _next(self):
        self.s = (1103515245 * self.s + 12345) & 0x7FFFFFFF
        return self.s

    def uniform(self, a, b):
        return a + (b - a) * (self._next() / 0x7FFFFFFF)

    def randint(self, a, b):
        return a + self._next() % (b - a + 1)


# ==========================================================================
# Rendu GIF + envoi dans la flash de l'horloge
#
# Pourquoi un GIF plutot que du dessin en HTTP : pousser les frames une par
# une plafonne a ~14 fps et sautille. Le firmware joue un GIF stocke en local
# a sa vitesse native, sans reseau. Mesure sur cette horloge : 32 frames a
# 50 ms plein ecran, 6,3 ko, zero perte reseau.
#
# Les fichiers gardent un NOM FIXE et sont ecrases : le firmware conserve un
# handle sur le dernier GIF joue, un DELETE ne passe qu'apres un reboot.
# ==========================================================================

import io
import json
import logging
import urllib.request

try:
    from PIL import Image, ImageDraw
except ImportError:      # pragma: no cover
    Image = ImageDraw = None

log = logging.getLogger(__name__)


def rasterise(instructions):
    """Turn one frame of Awtrix draw instructions into a 32x8 image."""
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    for it in instructions:
        if "dl" in it:
            x0, y0, x1, y1, col = it["dl"]
            d.line((x0, y0, x1, y1), fill=col)
        elif "dp" in it:
            x, y, col = it["dp"]
            if 0 <= x < W and 0 <= y < H:
                d.point((x, y), fill=col)
    return img


def build_gif(frames, fps=20, colors=64):
    """Encode frames as a native 32x8 animated GIF that loops seamlessly.

    The generators already guarantee frame N-1 flows into frame 0; `loop=0`
    plus a constant delay is all the encoder has to add.
    """
    imgs = [rasterise(f).quantize(colors=colors, method=Image.MEDIANCUT) for f in frames]
    buf = io.BytesIO()
    imgs[0].save(buf, format="GIF", save_all=True, append_images=imgs[1:],
                 duration=int(1000 / fps), loop=0, optimize=True, disposal=1)
    return buf.getvalue()


def upload_icon(host_ip, name, data, timeout=25):
    """PUT a GIF into /ICONS on the clock, overwriting any previous version."""
    boundary = "----awtrixscenes"
    body = (f"--{boundary}\r\n".encode()
            + f'Content-Disposition: form-data; name="data"; filename="/ICONS/{name}.gif"\r\n'.encode()
            + b"Content-Type: image/gif\r\n\r\n" + data
            + f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(f"http://{host_ip}/edit", data=body,
                                 headers={"Content-Type":
                                          f"multipart/form-data; boundary={boundary}"})
    return urllib.request.urlopen(req, timeout=timeout).status


def register_app(host_ip, name, duration=8, timeout=10):
    """Make the clock show that icon as a full-screen app in its loop."""
    payload = {"icon": name, "text": "", "duration": duration}
    req = urllib.request.Request(f"http://{host_ip}/api/custom?name={name}",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def refresh_scenes(host_ip, weather, sea=None, n_frames=64, fps=20, duration=8):
    """Regenerate the three scenes from the current forecast and push them.

    `weather` is the MARSEILLE dict DisplayManager already holds; `sea` is the
    Open-Meteo Marine dict ({'height': ...}) when available.

    Call once per content cycle. The clock then plays all three natively and
    smoothly, with no further network traffic until the next refresh.
    """
    if Image is None:
        log.warning("Pillow absent, scenes GIF desactivees")
        return False

    def num(key, default):
        try:
            return float(weather.get(key, default) or default)
        except (TypeError, ValueError):
            return float(default)

    wind_speed = num("wind_speed", 10)
    wind_deg = int(num("wind_direction", num("wind_deg", 270)))
    cloudiness = int(num("cloudiness", 0))
    temp = num("temp", 20)

    desc = str(weather.get("description", "")).lower()
    is_raining = any(k in desc for k in ("pluie", "pioggia", "rain", "averse", "drizzle"))
    hour = datetime.now().hour

    wave_h = 0.4
    sea_temp = 20.0
    if sea:
        try:
            wave_h = float(sea.get("height", 0.4) or 0.4)
        except (TypeError, ValueError):
            pass
        try:
            sea_temp = float(sea.get("temp", 20.0) or 20.0)
        except (TypeError, ValueError):
            pass

    scenes = {
        "vent": wind_frames(wind_speed=wind_speed, wind_deg=wind_deg, hour=hour,
                            cloudiness=cloudiness, is_raining=is_raining,
                            n_frames=n_frames, temp=temp),
        "meteo": weather_frames(temp=temp, cloudiness=cloudiness, is_raining=is_raining,
                                wind_speed=wind_speed, hour=hour, n_frames=n_frames),
        # boat="auto": the pointu only comes out when the sea is flat enough
        # for one to be out and for its rig to fit on eight rows
        "houle": swell_frames(wave_height=wave_h, wind_speed=wind_speed,
                              sea_temp=sea_temp, hour=hour, cloudiness=cloudiness,
                              is_raining=is_raining, n_frames=n_frames,
                              boat="auto", wind_deg=wind_deg),
    }

    ok = True
    for name, frames in scenes.items():
        try:
            data = build_gif(frames, fps=fps)
            upload_icon(host_ip, name, data)
            register_app(host_ip, name, duration=duration)
            log.info("Scene '%s' poussee (%d frames, %d octets)", name, len(frames), len(data))
        except Exception as e:
            log.error("Scene '%s' KO: %s", name, e)
            ok = False
    return ok
