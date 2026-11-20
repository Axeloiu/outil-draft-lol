#!/usr/bin/env python3
"""Test de equipe.py contre un serveur Riot factice (aucune vraie clé, aucun appel extérieur).
Vérifie : Riot ID -> PUUID, parties gardées seulement si au moins 3 joueurs de l'équipe jouent ensemble,
remakes et parties solo ignorés, résumé vu de notre côté (victoire, or à 14 min, objectifs, morts avant 14),
pas de doublon au 2e passage, et repères Master+ calculés depuis rows/ et timelines/.
Usage : python3 test_equipe_factice.py
"""
import gzip, http.server, json, os, random, shutil, subprocess, sys, tempfile, threading, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_collect_factice as T  # noqa: E402  (match() et timeline() factices)
CFG = json.load(open(os.path.join(HERE, 'equipe.json'), encoding='utf-8'))
RIOT = [j['riot'] for j in CFG['joueurs']]
PU = {r: f'puuid-{i}' for i, r in enumerate(RIOT)}
# EUW1_2000 : 4 des nôtres en rouge (gardée) ; 2001 : 2 des nôtres (ignorée) ; 2002 : remake 5 min (ignorée) ; 2003 : 5 des nôtres en bleu
SPEC = {'EUW1_2000': ('R', 4, 1800), 'EUW1_2001': ('B', 2, 1800), 'EUW1_2002': ('B', 5, 300), 'EUW1_2003': ('B', 5, 2000)}
calls = {'acc': 0, 'match': 0, 'tl': 0}


def our_match(mid):
    side, k, dur = SPEC[mid]
    m = T.match(mid, int(mid[-2:]))
    m['info']['queueId'] = 440; m['info']['gameDuration'] = dur
    ps = m['info']['participants']
    rng = [i for i in range(10) if (i < 5) == (side == 'B')]
    for n, i in enumerate(rng[:k]):
        ps[i]['puuid'] = PU[RIOT[n]]
    for p in ps:
        p.setdefault('puuid', f'autre-{p["participantId"]}')
        p.update(kills=3, deaths=2, assists=4, totalMinionsKilled=150, neutralMinionsKilled=10, goldEarned=11000,
                 totalDamageDealtToChampions=15000, totalDamageTaken=14000, visionScore=20, wardsPlaced=8, wardsKilled=2, visionWardsBoughtInGame=1)
    m['info']['teams'] = [{'teamId': 100, 'objectives': {'tower': {'kills': 7}}}, {'teamId': 200, 'objectives': {'tower': {'kills': 3}}}]
    return m


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, obj=None):
        body = json.dumps(obj).encode() if obj is not None else b'{}'
        self.send_response(code); self.send_header('Content-Type', 'application/json'); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path); path = urllib.parse.unquote(u.path)
        if '/riot/account/v1/accounts/by-riot-id/' in path:
            calls['acc'] += 1
            name, tag = path.split('/by-riot-id/')[1].split('/')
            r = f'{name}#{tag}'
            return self.send(200, {'puuid': PU[r], 'gameName': name, 'tagLine': tag}) if r in PU else self.send(404)
        if '/matches/by-puuid/' in path:
            q = urllib.parse.parse_qs(u.query).get('queue', ['0'])[0]
            return self.send(200, list(SPEC) if q == '440' else [])
        if path.endswith('/timeline'):
            calls['tl'] += 1
            return self.send(200, T.timeline(int(path.split('/')[-2][-2:])))
        if '/lol/match/v5/matches/' in path:
            calls['match'] += 1
            return self.send(200, our_match(path.split('/')[-1]))
        self.send(404)


def fake_master(data):
    """rows/ et timelines/ factices (format de collect.py) pour les repères."""
    import collect as C
    os.makedirs(os.path.join(data, 'rows')); os.makedirs(os.path.join(data, 'timelines'))
    import time
    day = time.strftime('%Y-%m-%d', time.gmtime())
    with gzip.open(os.path.join(data, 'rows', day + '.jsonl.gz'), 'wt') as fr, gzip.open(os.path.join(data, 'timelines', day + '.jsonl.gz'), 'wt') as ft:
        for k in range(120):
            m = T.match(f'EUW1_{5000 + k}', k)
            tl = T.timeline(k)
            # écarts variés entre les deux équipes
            for f in tl['info']['frames']:
                for p, v in f['participantFrames'].items():
                    v['totalGold'] += (int(p) * 37 * (k % 7)) % 900
            row = C.row_of(m['info'], '16.23', 420, 'euw1', m['metadata']['matchId'])
            t = dict(C.tl_of(tl, m['info']), m=m['metadata']['matchId'])
            fr.write(json.dumps(row) + '\n'); ft.write(json.dumps(t) + '\n')


def main():
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    tmp = tempfile.mkdtemp()
    data = os.path.join(tmp, 'data')
    os.makedirs(data)
    fake_master(data)
    env = dict(os.environ, RIOT_API_KEY='factice', RIOT_BASE=f'http://127.0.0.1:{srv.server_port}/{{host}}', RATE='500/1')
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(('OK   ' if cond else 'ÉCHEC ') + msg); ok = ok and cond

    for run in (1, 2):
        out = subprocess.run([sys.executable, os.path.join(HERE, 'equipe.py'), data], env=env, capture_output=True, text=True, timeout=120)
        if out.returncode:
            print(out.stdout, out.stderr)
        check(out.returncode == 0, f'passage {run} sans erreur')
    G = json.load(open(os.path.join(data, 'equipe', 'parties.json')))
    check(sorted(g['m'] for g in G) == ['EUW1_2000', 'EUW1_2003'], 'seules les parties à 3 joueurs ou plus, hors remake, sont gardées (pas de doublon)')
    g0 = next(g for g in G if g['m'] == 'EUW1_2000')
    check(g0['side'] == 'R' and len(g0['us']) == 5 and sum(1 for p in g0['us'] if p['me']) == 4, 'partie vue de notre côté (rouge, 4 des nôtres nommés)')
    m = T.match('EUW1_2000', 0)
    check(g0['win'] == (int('00') % 2 != 0), 'victoire de notre équipe')
    check(g0['gold'][14] == 25 and len(g0['gold']) == 31, 'écart d’or de notre équipe minute par minute (rouge : +25 ici)')
    check(g0['obj']['dr'][0][0] is False and g0['obj']['gr'][0][0] is True, 'objectifs vus de notre côté (dragon bleu, larves rouges)')
    vict = next(p for p in g0['them'] if p['r'] == 'jgl')
    check(vict['d14'] == 1 and g0['us'][1]['k14'] >= 1, 'morts et kills avant 14:00')
    check(g0['tw'] == [3, 7], 'tours de chaque équipe vues de notre côté')
    check(calls['acc'] == 5, f'Riot ID résolus une seule fois ({calls["acc"]} appels)')
    R = json.load(open(os.path.join(data, 'equipe', 'reperes.json')))
    check(R['n'] == 120 and R['lane']['mid']['g14'] and len(R['lane']['mid']['g14']) == 9, 'repères par rôle (déciles) calculés sur 120 parties')
    check(isinstance(R['mu'], dict) and isinstance(R['cr'], dict), 'repères par matchup et par champion')
    check(R['lane']['top'].get('d14') is not None, 'repère des morts avant 14:00')
    shutil.rmtree(tmp)
    print('\nRÉSULTAT :', 'tout est bon' if ok else 'ÉCHEC')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
