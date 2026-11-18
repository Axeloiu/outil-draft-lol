#!/usr/bin/env python3
"""Collecteur de parties Master+ (ranked solo/duo) pour l'outil de draft.

Tourne sur GitHub Actions toutes les heures, pendant ~50 minutes :
  1. lit le ladder Challenger / Grandmaster / Master de chaque région (league-v4) ;
  2. passe les joueurs en revue et récupère leurs nouvelles parties classées (match-v5) ;
  3. ajoute chaque partie à des compteurs agrégés (rien d'identifiant n'est gardé dans les stats).

Compteurs, par patch :
  cr  champion|rôle                     -> [parties, victoires]
  mu  champion|rôle|adversaire de lane  -> [parties, victoires]
  ct  champion|rôle -> scénario         -> [parties, victoires]
  it  champion|rôle -> scénario -> objet final -> [parties, victoires]
Scénarios = profil de la compo adverse : all, ap3, ad4, cc3, heal2, shield2, tank2, burst2, auto3.
Files : solo/duo (420) et flex (440), comptées à part (clé « patch|file »).
En plus des compteurs, une ligne par partie est ajoutée à rows/AAAA-MM-JJ.jsonl.gz (pour le modèle appris et
les simulations) : région, patch, file, durée, début, équipe gagnante, et pour chaque équipe les 5 champions avec rôle,
objets finaux et sorts. Aucun identifiant de joueur.

La clé Riot vient de la variable d'environnement RIOT_API_KEY (secret du dépôt), jamais du code.
Bibliothèque standard uniquement.
"""
import gzip, json, os, sys, threading, time, urllib.error, urllib.parse, urllib.request
from collections import deque

KEY = os.environ.get('RIOT_API_KEY', '').strip()
REGIONS = [r.strip() for r in os.environ.get('REGIONS', 'euw1,kr').split(',') if r.strip()]
BUDGET = int(os.environ.get('BUDGET_SECONDS', str(50 * 60)))
BASE = os.environ.get('RIOT_BASE', '')  # tests : serveur factice, ex. http://127.0.0.1:9000/{host}
STATE = sys.argv[1] if len(sys.argv) > 1 else 'state.json.gz'
QUEUES = (420, 440)
LADDER_QUEUES = ('RANKED_SOLO_5x5', 'RANKED_FLEX_SR')
ROWS_KEEP_DAYS = int(os.environ.get('ROWS_KEEP_DAYS', '3650'))  # on garde tout (≈ 3 Mo par jour hors rattrapage)
OUT = sys.argv[2] if len(sys.argv) > 2 else 'stats.json'
HERE = os.path.dirname(os.path.abspath(__file__))
# profil compact par champion : type de dégâts (AD/AP/T) puis 6 drapeaux cc, tank, burst, heal, shield, auto
_TK = ('cc', 'tank', 'burst', 'heal', 'shield', 'auto')
TRAITS = {int(k): dict(d=v[:-6], **{n: int(v[-6 + i]) for i, n in enumerate(_TK)})
          for k, v in json.load(open(os.path.join(HERE, 'champtraits.json'))).items()}
REGIONAL = {'euw1': 'europe', 'eun1': 'europe', 'tr1': 'europe', 'ru': 'europe', 'kr': 'asia', 'jp1': 'asia',
            'na1': 'americas', 'br1': 'americas', 'la1': 'americas', 'la2': 'americas', 'oc1': 'sea', 'sg2': 'sea', 'tw2': 'sea', 'vn2': 'sea'}
POS = {'TOP': 'top', 'JUNGLE': 'jgl', 'MIDDLE': 'mid', 'BOTTOM': 'adc', 'UTILITY': 'sup'}
SKIP_ITEMS = {0, 2003, 2031, 2033, 2055, 2138, 2139, 2140, 3340, 3363, 3364, 3330, 2010, 2150, 2151, 2152}
LADDER_EVERY = 12 * 3600
LOOKBACK = 3 * 86400
# Rattrapage : en plus des nouvelles parties, chaque visite d'un joueur remonte une page (100 parties) de son
# historique, jusqu'à BACKFILL_DAYS jours en arrière (environ un patch), puis le joueur est marqué terminé.
BACKFILL_DAYS = int(os.environ.get('BACKFILL_DAYS', '14'))
KEEP_PATCHES = 3

T0 = time.time()
LOCK = threading.Lock()
STOP = {'reason': None}
LOG = []


def log(msg):
    line = time.strftime('%H:%M:%S') + ' ' + msg
    print(line, flush=True)
    LOG.append(line)


class Limiter:
    """Limites d'une clé personnelle, par hôte : 20 req / 1 s et 100 req / 120 s (avec une marge)."""
    def __init__(self, rules=None):
        # surcharge possible pour les tests : RATE="19/1,95/120"
        spec = os.environ.get('RATE', '19/1,90/120')
        self.rules = rules or tuple((int(a), float(b)) for a, b in (x.split('/') for x in spec.split(',')))
        self.q = deque()

    def wait(self):
        while True:
            now = time.time()
            while self.q and now - self.q[0] > max(w for _, w in self.rules):
                self.q.popleft()
            delay = 0
            for n, w in self.rules:
                recent = [t for t in self.q if now - t < w]
                if len(recent) >= n:
                    delay = max(delay, w - (now - recent[-n]) + 0.05)
            if delay <= 0:
                self.q.append(now)
                return
            time.sleep(min(delay, 5))


LIMITERS = {}


def get(host, path, params=None):
    """GET sur l'API Riot, avec limites, retry sur 429/5xx. Renvoie le JSON, ou None (404)."""
    lim = LIMITERS.setdefault(host, Limiter())
    url = (BASE.format(host=host) if BASE else f'https://{host}.api.riotgames.com') + path
    if params:
        url += '?' + urllib.parse.urlencode(params)
    for attempt in range(5):
        if STOP['reason']:
            return None
        lim.wait()
        req = urllib.request.Request(url, headers={'X-Riot-Token': KEY, 'User-Agent': 'team-draft-notebook'})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (401, 403):
                STOP['reason'] = f'clé refusée ({e.code}) : clé expirée ou invalide'
                return None
            if e.code == 429:
                ra = float(e.headers.get('Retry-After') or 5)
                log(f'429 sur {host}, pause {ra:.0f} s')
                time.sleep(ra + 0.5)
                continue
            time.sleep(2 + attempt * 3)
        except Exception:
            time.sleep(2 + attempt * 3)
    return None


def load_state():
    if os.path.exists(STATE):
        with gzip.open(STATE, 'rt', encoding='utf-8') as f:
            return json.load(f)
    return {'v': 2, 'regions': {}, 'seen': {}, 'stats': {}}


def save_state(st):
    tmp = STATE + '.tmp'
    with gzip.open(tmp, 'wt', encoding='utf-8') as f:
        json.dump(st, f, separators=(',', ':'))
    os.replace(tmp, STATE)


def tags_of(enemies):
    tr = [TRAITS.get(c) for c in enemies]
    tr = [t for t in tr if t]
    s = lambda k: sum(t[k] for t in tr)
    out = ['all']
    if sum(1 for t in tr if t['d'] == 'AP') >= 3: out.append('ap3')
    if sum(1 for t in tr if t['d'] == 'AD') >= 4: out.append('ad4')
    if s('cc') >= 3: out.append('cc3')
    if s('heal') >= 2: out.append('heal2')
    if s('shield') >= 2: out.append('shield2')
    if s('tank') >= 2: out.append('tank2')
    if s('burst') >= 2: out.append('burst2')
    if s('auto') >= 3: out.append('auto3')
    return out


def add(d, key, win):
    v = d.get(key)
    if v is None:
        v = d[key] = [0, 0]
    v[0] += 1
    v[1] += 1 if win else 0


ROWS = []


def row_of(info, patch, q, region=''):
    ps = info.get('participants') or []
    win = next((p.get('teamId') for p in ps if p.get('win')), 0)
    side = lambda t: [[p.get('championId'), POS.get(p.get('teamPosition') or '', ''),
                       [p.get(f'item{i}') for i in range(7) if p.get(f'item{i}')],
                       [p.get('summoner1Id'), p.get('summoner2Id')]] for p in ps if p.get('teamId') == t]
    return {'g': region, 'p': patch, 'q': q, 'd': info.get('gameDuration'), 't': int((info.get('gameStartTimestamp') or 0) / 1000),
            'w': 'B' if win == 100 else 'R' if win == 200 else '', 'B': side(100), 'R': side(200)}


def count_match(st, m, region=''):
    info = m.get('info') or {}
    q = info.get('queueId')
    if q not in QUEUES or (info.get('gameDuration') or 0) < 900:
        return False
    ver = str(info.get('gameVersion', ''))
    patch = '.'.join(ver.split('.')[:2]) if ver else 'x'
    ps = info.get('participants') or []
    if len(ps) != 10:
        return False
    ROWS.append(row_of(info, patch, q, region))
    S = st['stats'].setdefault(f'{patch}|{q}', {'n': 0, 'cr': {}, 'mu': {}, 'ct': {}, 'it': {}})
    S['n'] += 1
    teams = {}
    for p in ps:
        teams.setdefault(p.get('teamId'), []).append(p)
    for p in ps:
        r = POS.get(p.get('teamPosition') or '')
        if not r:
            continue
        c, win = p.get('championId'), bool(p.get('win'))
        foes = [q for q in ps if q.get('teamId') != p.get('teamId')]
        k = f'{c}|{r}'
        add(S['cr'], k, win)
        opp = next((q for q in foes if POS.get(q.get('teamPosition') or '') == r), None)
        if opp:
            add(S['mu'], f'{k}|{opp.get("championId")}', win)
        tg = tags_of([q.get('championId') for q in foes])
        ct = S['ct'].setdefault(k, {})
        it = S['it'].setdefault(k, {})
        items = {p.get(f'item{i}') for i in range(7)} - SKIP_ITEMS
        for t in tg:
            add(ct, t, win)
            d = it.setdefault(t, {})
            for item in items:
                if item:
                    add(d, str(item), win)
    return True


def run_region(st, region):
    plat, reg = region, REGIONAL.get(region, 'europe')
    R = st['regions'].setdefault(region, {'ladder_at': 0, 'players': [], 'cursor': 0, 'last': {}})
    BF = R.setdefault('bf', {})  # puuid -> [ancre (endTime), décalage] ; 0 = rattrapage terminé
    now = time.time()
    if now - R['ladder_at'] > LADDER_EVERY or not R['players']:
        ids, seen_p = [], set()
        # solo puis flex, et dans chaque file Challenger, puis Grandmaster, puis Master
        for lq in LADDER_QUEUES:
            for tier in ('challengerleagues', 'grandmasterleagues', 'masterleagues'):
                d = get(plat, f'/lol/league/v4/{tier}/by-queue/{lq}')
                for e in (d or {}).get('entries', []):
                    pu = e.get('puuid')
                    if pu and pu not in seen_p:
                        seen_p.add(pu); ids.append(pu)
        if ids:
            with LOCK:
                R['players'], R['ladder_at'], R['cursor'] = ids, now, 0
            log(f'{region} : ladder Master+ = {len(ids)} joueurs')
    n_new = 0

    def take(mids):
        # renvoie le nombre d'ids traités (moins que la liste si le temps est écoulé)
        nonlocal n_new
        for k, mid in enumerate(mids):
            if time.time() - T0 >= BUDGET or STOP['reason']:
                return k
            with LOCK:
                if mid in st['seen']:
                    continue
                st['seen'][mid] = int(time.time())
            m = get(reg, f'/lol/match/v5/matches/{mid}')
            if m:
                with LOCK:
                    if count_match(st, m, region):
                        n_new += 1
        return len(mids)

    while time.time() - T0 < BUDGET and not STOP['reason'] and R['players']:
        i = R['cursor'] % len(R['players'])
        puuid = R['players'][i]
        R['cursor'] = i + 1
        since = int(max(R['last'].get(puuid, 0), time.time() - LOOKBACK))
        mids = get(reg, f'/lol/match/v5/matches/by-puuid/{puuid}/ids', {'type': 'ranked', 'startTime': since, 'count': 20})
        if mids is None:
            continue
        R['last'][puuid] = int(time.time())
        take(mids)
        # rattrapage de l'historique, une page par visite
        b = BF.get(puuid)
        if b == 0 or time.time() - T0 >= BUDGET or STOP['reason']:
            continue
        if not b:
            b = BF[puuid] = [int(time.time()), 0]
        floor = int(time.time() - BACKFILL_DAYS * 86400)
        old = get(reg, f'/lol/match/v5/matches/by-puuid/{puuid}/ids',
                  {'type': 'ranked', 'startTime': floor, 'endTime': b[0], 'start': b[1], 'count': 100})
        if old is None:
            continue
        done = take(old)
        b[1] += done
        if done == len(old) and len(old) < 100:
            BF[puuid] = 0
    left = sum(1 for p in R['players'] if BF.get(p) != 0)
    log(f'{region} : {n_new} nouvelles parties comptées (rattrapage restant : {left} joueurs)')
    return n_new


def write_rows():
    if not ROWS:
        return
    d = os.path.join(os.path.dirname(os.path.abspath(OUT)), 'rows')
    os.makedirs(d, exist_ok=True)
    fn = os.path.join(d, time.strftime('%Y-%m-%d', time.gmtime()) + '.jsonl.gz')
    with gzip.open(fn, 'at', encoding='utf-8') as f:  # ajout : un fichier par jour, plusieurs blocs gzip
        for r in ROWS:
            f.write(json.dumps(r, separators=(',', ':')) + '\n')
    cutoff = time.strftime('%Y-%m-%d', time.gmtime(time.time() - ROWS_KEEP_DAYS * 86400))
    for name in os.listdir(d):
        if name.endswith('.jsonl.gz') and name[:10] < cutoff:
            os.remove(os.path.join(d, name))
    log(f'{len(ROWS)} lignes ajoutées à rows/{os.path.basename(fn)}')


def migrate(st):
    # v1 : stats par patch seul (solo/duo) -> clé « patch|420 »
    for k in [k for k in st['stats'] if '|' not in k]:
        st['stats'][k + '|420'] = st['stats'].pop(k)
    st['v'] = 2


def write_out(st):
    pver = lambda k: [int(x) if x.isdigit() else 0 for x in k.split('|')[0].split('.')]
    patches = sorted({k.split('|')[0] for k in st['stats']}, key=lambda p: pver(p))
    for k in [k for k in st['stats'] if k.split('|')[0] in patches[:-KEEP_PATCHES]]:
        del st['stats'][k]
    # une partie reste connue tant qu'un rattrapage peut encore la retrouver
    cutoff = time.time() - (BACKFILL_DAYS + 1) * 86400
    st['seen'] = {k: v for k, v in st['seen'].items() if v >= cutoff}
    for R in st['regions'].values():
        keep = set(R['players'])
        R['last'] = {k: v for k, v in R['last'].items() if k in keep}
        R['bf'] = {k: v for k, v in R.get('bf', {}).items() if k in keep}
    out = {'updated': int(time.time()), 'regions': REGIONS, 'stop': STOP['reason'],
           'patches': {p: {'n': s['n']} for p, s in st['stats'].items()}, 'stats': st['stats'], 'log': LOG[-20:]}
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(out, f, separators=(',', ':'))
    os.replace(tmp, OUT)


def main():
    st = load_state()
    migrate(st)
    if not KEY:
        STOP['reason'] = 'aucune clé Riot (secret RIOT_API_KEY manquant)'
        log(STOP['reason'])
    else:
        th = [threading.Thread(target=run_region, args=(st, r)) for r in REGIONS]
        for t in th: t.start()
        for t in th: t.join()
    if STOP['reason']:
        log('arrêt : ' + STOP['reason'])
    write_out(st)
    write_rows()
    save_state(st)
    tot = sum(s['n'] for s in st['stats'].values())
    log(f'total gardé : {tot} parties sur {len(st["stats"])} patch(s)')


if __name__ == '__main__':
    main()
