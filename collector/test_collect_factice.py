#!/usr/bin/env python3
"""Test du collecteur contre un serveur Riot factice (aucune vraie clé, aucun appel réseau extérieur).
Vérifie : parties comptées et écrites dans rows/, timelines écrites dans timelines/ et reliées par l'identifiant,
ordre des joueurs identique à rows, et qu'une timeline en erreur (500) ou absente (404) ne fait pas perdre la partie.
Usage : python3 test_collect_factice.py
"""
import gzip, http.server, json, os, random, shutil, subprocess, sys, tempfile, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROLES = ['TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'UTILITY']
CHAMPS = [266, 103, 84, 12, 32, 34, 1, 22, 136, 268, 432, 53, 63, 201, 51, 164, 69, 31, 42, 122]
MIDS = [f'EUW1_{1000 + i}' for i in range(6)]
TL_FAIL = {'EUW1_1002': 500, 'EUW1_1004': 404}
calls = {'tl': 0}


def match(mid, k):
    rnd = random.Random(k)
    ch = rnd.sample(CHAMPS, 10)
    ps = []
    for i in range(10):
        ps.append({'participantId': i + 1, 'teamId': 100 if i < 5 else 200, 'teamPosition': ROLES[i % 5], 'championId': ch[i],
                   'win': i < 5 if k % 2 == 0 else i >= 5, 'summoner1Id': 4, 'summoner2Id': 12,
                   **{f'item{j}': [3031, 3006, 6672, 3036, 0, 0, 3340][j] for j in range(7)}})
    return {'metadata': {'matchId': mid}, 'info': {'queueId': 420, 'gameDuration': 1800, 'gameVersion': '16.23.1.1',
                                                  'gameStartTimestamp': 1795000000000 + k * 1000, 'participants': ps}}


def timeline(k):
    frames = []
    for minute in range(31):
        pf = {str(p): {'totalGold': 500 + 300 * minute + p, 'xp': 200 * minute + p, 'minionsKilled': 7 * minute, 'jungleMinionsKilled': (5 * minute if p in (2, 7) else 0),
                       'position': {'x': 1000 + 100 * minute + p, 'y': 2000 + p}} for p in range(1, 11)}
        ev = []
        if minute == 1:
            ev += [{'type': 'ITEM_PURCHASED', 'participantId': p, 'itemId': 1055, 'timestamp': 60000} for p in range(1, 11)]
            ev += [{'type': 'ITEM_PURCHASED', 'participantId': 1, 'itemId': 2003, 'timestamp': 61000}]   # potion : ignorée
        if minute == 4:
            ev += [{'type': 'CHAMPION_KILL', 'killerId': 7, 'victimId': 2, 'timestamp': 240500}]
        if minute == 6:
            ev += [{'type': 'ELITE_MONSTER_KILL', 'killerTeamId': 100, 'monsterType': 'DRAGON', 'monsterSubType': 'FIRE_DRAGON', 'timestamp': 330000}]
        if minute == 9:
            ev += [{'type': 'ELITE_MONSTER_KILL', 'killerTeamId': 200, 'monsterType': 'HORDE', 'timestamp': 500000}]
            ev += [{'type': 'ITEM_PURCHASED', 'participantId': 3, 'itemId': 3020, 'timestamp': 510000},
                   {'type': 'ITEM_UNDO', 'participantId': 3, 'beforeId': 3020, 'afterId': 0, 'timestamp': 512000}]
        if minute == 13:
            ev += [{'type': 'BUILDING_KILL', 'teamId': 200, 'buildingType': 'TOWER_BUILDING', 'laneType': 'BOT_LANE', 'timestamp': 760000}]
        frames.append({'participantFrames': pf, 'events': ev})
    return {'info': {'frames': frames}}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, obj=None):
        body = json.dumps(obj).encode() if obj is not None else b'{}'
        self.send_response(code); self.send_header('Content-Type', 'application/json'); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        p = self.path.split('?')[0]; q = self.path.split('?')[1] if '?' in self.path else ''
        if '/league/v4/challengerleagues/by-queue/RANKED_SOLO_5x5' in p:
            return self.send(200, {'entries': [{'puuid': 'joueur-a'}, {'puuid': 'joueur-b'}]})
        if '/league/v4/' in p:
            return self.send(200, {'entries': []})
        if '/by-puuid/' in p:
            if 'start=' in q:   # rattrapage : rien de plus
                return self.send(200, [])
            return self.send(200, MIDS[:3] if 'joueur-a' in p else MIDS[2:])
        if p.endswith('/timeline'):
            mid = p.split('/')[-2]; calls['tl'] += 1
            if mid in TL_FAIL:
                return self.send(TL_FAIL[mid])
            return self.send(200, timeline(MIDS.index(mid)))
        if '/lol/match/v5/matches/' in p:
            mid = p.split('/')[-1]
            return self.send(200, match(mid, MIDS.index(mid)))
        self.send(404)


def main():
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    tmp = tempfile.mkdtemp()
    env = dict(os.environ, RIOT_API_KEY='cle-de-test', RIOT_BASE=f'http://127.0.0.1:{srv.server_address[1]}/{{host}}',
               REGIONS='euw1', BUDGET_SECONDS='30', RATE='500/1,5000/120')
    r = subprocess.run([sys.executable, os.path.join(HERE, 'collect.py'), os.path.join(tmp, 'state.json.gz'), os.path.join(tmp, 'stats.json')],
                       env=env, capture_output=True, text=True, timeout=200)
    print(r.stdout[-1500:], r.stderr[-1500:])
    srv.shutdown()
    rd = lambda d: [json.loads(l) for f in sorted(os.listdir(os.path.join(tmp, d))) for l in gzip.open(os.path.join(tmp, d, f), 'rt')]
    rows, tls = rd('rows'), rd('timelines')
    ok = True
    def check(cond, msg):
        nonlocal ok
        print(('OK   ' if cond else 'ÉCHEC ') + msg); ok &= bool(cond)
    check(len(rows) == len(MIDS) and len({x['m'] for x in rows}) == len(MIDS), f'{len(rows)} parties dans rows, sans doublon')
    check(len(tls) == len(MIDS) - len(TL_FAIL), f'{len(tls)} timelines (les 2 en erreur 500 / 404 manquent, les parties restent)')
    check({x['m'] for x in tls} <= {x['m'] for x in rows}, 'chaque timeline est reliée à une partie de rows')
    t = next(x for x in tls if x['m'] == 'EUW1_1000'); row = next(x for x in rows if x['m'] == 'EUW1_1000')
    check(len(t['f10']) == 10 and t['f10'][0] == [3501, 2001, 70] and t['f14'][1][2] == 14 * 12, 'or, xp, farm à 10 et 14 min, dans l’ordre de rows')
    check(t['buy'][0] == [[1055, 1]] and t['buy'][2] == [[1055, 1]], 'achats : potion ignorée, achat annulé retiré')
    check(t['o']['fb'] == [200, 240] and t['o']['dr'] == [[100, 330, 'FIRE']] and t['o']['gr'] == [[200, 500]] and t['o']['ft'] == [100, 760, 'BOT'],
          'premier sang, dragon, larves, première tour')
    check(t['jg'] == [100, 200] and len(t['jp']) == 4, 'positions des deux junglers de 1 à 4 min')
    check([p[1] for p in row['B']] == ['top', 'jgl', 'mid', 'adc', 'sup'], 'rows inchangé (rôles, champions)')
    check('timelines : 4 gardées, 2 manquantes' in r.stdout, 'bilan des timelines dans le journal')
    shutil.rmtree(tmp)
    print('\nRÉSULTAT :', 'tout est bon' if ok else 'ÉCHEC'); sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
