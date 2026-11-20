#!/usr/bin/env python3
"""Parties de l'équipe pour l'onglet Après-game.

1. Retrouve les parties flex (440) et normal draft (400) des joueurs de equipe.json où au moins « min_ensemble »
   d'entre eux jouent dans la même équipe, avec leur timeline (API Riot, même clé et mêmes limites que collect.py).
2. Calcule les repères Master+ à partir des parties déjà collectées (rows/ et timelines/ de la branche data) :
   écarts d'or, d'XP et de farm contre le vis-à-vis à 10 et 14 minutes, par rôle et par matchup, morts avant 14:00.

Écrit dans <data>/equipe/ : parties.json (nos parties, la plus récente en premier), reperes.json, etat.json.
Usage : python3 equipe.py <dossier data>
"""
import glob, gzip, json, os, sys, time, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import collect as C  # noqa: E402  (get, log, POS, SKIP_ITEMS, limites de requêtes)

DATA = sys.argv[1] if len(sys.argv) > 1 else 'data'
OUTD = os.path.join(DATA, 'equipe')
CFG = json.load(open(os.path.join(HERE, 'equipe.json'), encoding='utf-8'))
REG = 'europe'
REPERES_JOURS = int(os.environ.get('REPERES_JOURS', '21'))


def load(fn, default):
    try:
        with open(os.path.join(OUTD, fn), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def save(fn, obj):
    os.makedirs(OUTD, exist_ok=True)
    tmp = os.path.join(OUTD, fn + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, os.path.join(OUTD, fn))


# ---------------------------------------------------------------- nos parties
def puuid_of(riot, st):
    if riot in st['puuid']:
        return st['puuid'][riot]
    name, _, tag = riot.partition('#')
    a = C.get(REG, f'/riot/account/v1/accounts/by-riot-id/{urllib.parse.quote(name)}/{urllib.parse.quote(tag)}')
    if a and a.get('puuid'):
        st['puuid'][riot] = a['puuid']
        return a['puuid']
    C.log(f'équipe : Riot ID introuvable : {riot}')
    return None


def frame_vals(frames, minute, pid):
    if len(frames) <= minute:
        return None
    f = (frames[minute].get('participantFrames') or {}).get(str(pid)) or {}
    return [f.get('totalGold', 0), f.get('xp', 0), f.get('minionsKilled', 0) + f.get('jungleMinionsKilled', 0)]


def record(m, tl, ours):
    """Résumé d'une de nos parties, vu de notre équipe. ours : {puuid: riot}"""
    info = m.get('info') or {}
    ps = info.get('participants') or []
    our_team = next(p['teamId'] for p in ps if p.get('puuid') in ours)
    frames = ((tl or {}).get('info') or {}).get('frames') or []
    d14, k14 = {}, {}
    gold = []
    for k, fr in enumerate(frames):
        pf = fr.get('participantFrames') or {}
        tg = {100: 0, 200: 0}
        for p in ps:
            tg[p['teamId']] += (pf.get(str(p['participantId'])) or {}).get('totalGold', 0)
        gold.append(tg[our_team] - tg[300 - our_team])
    ev = [e for fr in frames for e in (fr.get('events') or [])]
    team = {p['participantId']: p['teamId'] for p in ps}
    obj = {'dr': [], 'gr': [], 'he': [], 'ba': [], 'fb': None, 'ft': None}
    for e in ev:
        ty, ts = e.get('type'), int((e.get('timestamp') or 0) / 1000)
        if ty == 'CHAMPION_KILL':
            v, kl = e.get('victimId'), e.get('killerId')
            if ts < 840:
                d14[v] = d14.get(v, 0) + 1
                for a in [kl] + list(e.get('assistingParticipantIds') or []):
                    if a in team and team[a] != team.get(v):
                        k14[a] = k14.get(a, 0) + 1
            if obj['fb'] is None and kl in team:
                obj['fb'] = [team[kl] == our_team, ts]
        elif ty == 'BUILDING_KILL' and e.get('buildingType') == 'TOWER_BUILDING' and obj['ft'] is None:
            obj['ft'] = [(300 - (e.get('teamId') or 0)) == our_team, ts, (e.get('laneType') or '')[:3]]
        elif ty == 'ELITE_MONSTER_KILL':
            key = {'DRAGON': 'dr', 'HORDE': 'gr', 'RIFTHERALD': 'he', 'BARON_NASHOR': 'ba'}.get(e.get('monsterType'))
            if key:
                obj[key].append([e.get('killerTeamId') == our_team, ts] + ([(e.get('monsterSubType') or '')[:4]] if key == 'dr' else []))
    tk = {t.get('teamId'): (t.get('objectives') or {}) for t in info.get('teams') or []}
    tw = [(tk.get(our_team, {}).get('tower') or {}).get('kills', 0), (tk.get(300 - our_team, {}).get('tower') or {}).get('kills', 0)]
    kills = {t: sum(p.get('kills', 0) for p in ps if p['teamId'] == t) for t in (100, 200)}

    def pl(p):
        pid = p['participantId']
        f10, f14 = frame_vals(frames, 10, pid), frame_vals(frames, 14, pid)
        return {'c': p.get('championId'), 'r': C.POS.get(p.get('teamPosition') or '', ''), 'me': ours.get(p.get('puuid')),
                'k': p.get('kills', 0), 'd': p.get('deaths', 0), 'a': p.get('assists', 0),
                'kp': round((p.get('kills', 0) + p.get('assists', 0)) / max(1, kills[p['teamId']]), 3),
                'cs': p.get('totalMinionsKilled', 0) + p.get('neutralMinionsKilled', 0), 'g': p.get('goldEarned', 0),
                'dmg': p.get('totalDamageDealtToChampions', 0), 'tk': p.get('totalDamageTaken', 0),
                'vs': p.get('visionScore', 0), 'wp': p.get('wardsPlaced', 0), 'wk': p.get('wardsKilled', 0),
                'cw': p.get('visionWardsBoughtInGame', 0),
                'f10': f10, 'f14': f14, 'd14': d14.get(pid, 0), 'k14': k14.get(pid, 0),
                'it': [p.get(f'item{i}') for i in range(7) if p.get(f'item{i}') and p.get(f'item{i}') not in C.SKIP_ITEMS]}
    ver = str(info.get('gameVersion', ''))
    return {'m': (m.get('metadata') or {}).get('matchId', ''), 'q': info.get('queueId'), 't': int((info.get('gameStartTimestamp') or 0) / 1000),
            'd': info.get('gameDuration'), 'p': '.'.join(ver.split('.')[:2]), 'side': 'B' if our_team == 100 else 'R',
            'win': any(p.get('win') for p in ps if p['teamId'] == our_team),
            'us': [pl(p) for p in ps if p['teamId'] == our_team], 'them': [pl(p) for p in ps if p['teamId'] != our_team],
            'gold': gold, 'obj': obj, 'tw': tw}


def collect_team():
    st = load('etat.json', {'puuid': {}, 'vu': {}, 'last': 0})
    games = load('parties.json', [])
    have = {g['m'] for g in games}
    ours = {}
    for j in CFG['joueurs']:
        pu = puuid_of(j['riot'], st)
        if pu:
            ours[pu] = j['riot']
    if not ours:
        save('etat.json', st)
        return games
    now = int(time.time())
    since = max(st.get('last', 0) - 2 * 86400, now - CFG.get('jours_premier_passage', 30) * 86400)
    mids = set()
    for pu in ours:
        for q in CFG.get('files', [440, 400]):
            ids = C.get(REG, f'/lol/match/v5/matches/by-puuid/{pu}/ids', {'queue': q, 'startTime': since, 'start': 0, 'count': 50}) or []
            mids.update(ids)
    new = 0
    for mid in sorted(mids):
        if mid in have or mid in st['vu']:
            continue
        m = C.get(REG, f'/lol/match/v5/matches/{mid}')
        if not m:
            continue   # erreur passagère : on réessaiera au prochain passage
        info = m.get('info') or {}
        ps = info.get('participants') or []
        teams = {}
        for p in ps:
            if p.get('puuid') in ours:
                teams[p.get('teamId')] = teams.get(p.get('teamId'), 0) + 1
        if len(ps) != 10 or (info.get('gameDuration') or 0) < 600 or max(teams.values() or [0]) < CFG.get('min_ensemble', 3):
            st['vu'][mid] = now   # pas une partie d'équipe (ou remake) : on ne la regarde plus
            continue
        tl = C.get(REG, f'/lol/match/v5/matches/{mid}/timeline', tries=2)
        games.append(record(m, tl, ours))
        have.add(mid)
        new += 1
    games.sort(key=lambda g: -g['t'])
    st['vu'] = {k: v for k, v in st['vu'].items() if v > now - 60 * 86400}
    st['last'] = now
    save('parties.json', games)
    save('etat.json', st)
    C.log(f'équipe : {new} nouvelle(s) partie(s), {len(games)} au total')
    return games


# ---------------------------------------------------------------- repères Master+
def quantiles(xs, ps=(10, 20, 30, 40, 50, 60, 70, 80, 90)):
    xs = sorted(xs)
    if not xs:
        return None
    out = []
    for p in ps:
        k = (len(xs) - 1) * p / 100
        i = int(k)
        out.append(round(xs[i] + (xs[min(i + 1, len(xs) - 1)] - xs[i]) * (k - i), 1))
    return out


def reperes():
    """Repères Master+ (solo/duo et flex) sur les REPERES_JOURS derniers jours collectés."""
    cut = time.strftime('%Y-%m-%d', time.gmtime(time.time() - REPERES_JOURS * 86400))
    rows = {}
    for fn in sorted(glob.glob(os.path.join(DATA, 'rows', '*.jsonl.gz'))):
        if os.path.basename(fn)[:10] < cut:
            continue
        with gzip.open(fn, 'rt', encoding='utf-8') as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get('m'):
                    rows[r['m']] = r
    lane = {r: {'g10': [], 'g14': [], 'x14': [], 'c10': [], 'c14': [], 'd14': []} for r in ('top', 'jgl', 'mid', 'adc', 'sup')}
    mu, cr, tg14, n = {}, {}, [], 0
    for fn in sorted(glob.glob(os.path.join(DATA, 'timelines', '*.jsonl.gz'))):
        if os.path.basename(fn)[:10] < cut:
            continue
        with gzip.open(fn, 'rt', encoding='utf-8') as f:
            for line in f:
                try:
                    t = json.loads(line)
                except Exception:
                    continue
                r = rows.get(t.get('m'))
                if not r or not t.get('f14') or not t.get('f10') or len(t['f14']) != 10:
                    continue
                pl = [(p[0], p[1]) for p in r['B']] + [(p[0], p[1]) for p in r['R']]
                if len(pl) != 10:
                    continue
                n += 1
                tg14.append(sum(x[0] for x in t['f14'][:5]) - sum(x[0] for x in t['f14'][5:]))
                for i in range(10):
                    c, role = pl[i]
                    if role not in lane:
                        continue
                    j = next((k for k in (range(5, 10) if i < 5 else range(5)) if pl[k][1] == role), None)
                    if j is None:
                        continue
                    a10, a14, b10, b14 = t['f10'][i], t['f14'][i], t['f10'][j], t['f14'][j]
                    L = lane[role]
                    L['g10'].append(a10[0] - b10[0]); L['g14'].append(a14[0] - b14[0]); L['x14'].append(a14[1] - b14[1])
                    L['c10'].append(a10[2]); L['c14'].append(a14[2])
                    if t.get('d14'):
                        L['d14'].append(t['d14'][i])
                    k = f'{c}|{role}|{pl[j][0]}'
                    s = mu.setdefault(k, [0, 0, 0, 0])
                    s[0] += 1; s[1] += a14[0] - b14[0]; s[2] += a14[1] - b14[1]; s[3] += a14[2] - b14[2]
                    k2 = f'{c}|{role}'
                    s2 = cr.setdefault(k2, [0, 0, 0, 0, 0])
                    s2[0] += 1; s2[1] += a10[2]; s2[2] += a14[2]; s2[3] += a14[0] - b14[0]; s2[4] += a14[0]
    out = {'maj': int(time.time()), 'jours': REPERES_JOURS, 'n': n,
           'lane': {r: {k: quantiles(v) for k, v in L.items() if len(v) >= 50} for r, L in lane.items()},
           'tg14': quantiles(tg14),
           'mu': {k: [s[0], round(s[1] / s[0]), round(s[2] / s[0]), round(s[3] / s[0], 1)] for k, s in mu.items() if s[0] >= 15},
           'cr': {k: [s[0], round(s[1] / s[0], 1), round(s[2] / s[0], 1), round(s[3] / s[0]), round(s[4] / s[0])] for k, s in cr.items() if s[0] >= 30}}
    save('reperes.json', out)
    C.log(f'repères Master+ : {n} parties avec timeline, {len(out["mu"])} matchups, {len(out["cr"])} champions par rôle')


def main():
    if not C.KEY:
        C.log('équipe : aucune clé Riot, collecte sautée')
    else:
        try:
            collect_team()
        except Exception as e:   # ne doit jamais empêcher la collecte Master+ qui suit
            C.log(f'équipe : erreur {type(e).__name__}: {e}')
    rp = load('reperes.json', None)
    if not rp or time.time() - rp.get('maj', 0) > 20 * 3600 or os.environ.get('REPERES_FORCE') == '1':
        try:
            reperes()
        except Exception as e:
            C.log(f'repères : erreur {type(e).__name__}: {e}')


if __name__ == '__main__':
    main()
