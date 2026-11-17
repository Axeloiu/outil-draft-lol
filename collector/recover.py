#!/usr/bin/env python3
"""Récupération unique des données écrasées le 16/11 vers 21 h (clone raté, le passage est reparti de zéro).

Usage : recover.py <dossier data> <sha du dernier bon commit de la branche data>
- relit l'ancien état et les anciennes lignes par partie (raw.githubusercontent.com, le commit reste lisible) ;
- fusionne les lignes anciennes et actuelles, sans doublon (clé : début de partie + 10 champions) ;
- recalcule tous les compteurs à partir des lignes fusionnées ;
- fusionne les parties déjà vues et l'avancement du rattrapage par joueur ;
- note le sha dans l'état : un second lancement ne fait rien.
"""
import gzip, io, json, os, sys, urllib.error, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect as C  # noqa: E402

DATA, SHA = sys.argv[1], sys.argv[2]
REPO = os.environ.get('REPO', 'Axeloiu/outil-draft-lol')
RAW = os.environ.get('RAW_BASE', 'https://raw.githubusercontent.com/{repo}/{sha}/{path}')
REV = {v: k for k, v in C.POS.items()}
ST = os.path.join(DATA, 'state.json.gz')
ROWS_DIR = os.path.join(DATA, 'rows')


def raw(path):
    url = RAW.format(repo=REPO, sha=SHA, path=path)
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def read_rows(b):
    if not b:
        return []
    with gzip.GzipFile(fileobj=io.BytesIO(b)) as f:  # plusieurs blocs gzip possibles
        return [json.loads(l) for l in f.read().decode('utf-8').splitlines() if l.strip()]


def key(r):
    return (r.get('t'), r.get('q'), tuple(c[0] for c in r.get('B', [])), tuple(c[0] for c in r.get('R', [])))


def as_match(r):
    ps = []
    for side, team in (('B', 100), ('R', 200)):
        for c, role, items, _sp in r[side]:
            p = {'championId': c, 'teamPosition': REV.get(role, ''), 'teamId': team, 'win': r['w'] == side}
            for i, it in enumerate(items[:7]):
                p[f'item{i}'] = it
            ps.append(p)
    return {'info': {'queueId': r['q'], 'gameDuration': r['d'], 'gameVersion': r['p'] + '.1',
                     'gameStartTimestamp': (r.get('t') or 0) * 1000, 'participants': ps}}


def main():
    cur = json.load(gzip.open(ST, 'rt', encoding='utf-8')) if os.path.exists(ST) else {'v': 2, 'regions': {}, 'seen': {}, 'stats': {}}
    if SHA in cur.get('recovered', []):
        print('récupération déjà faite')
        return
    old_b = raw('state.json.gz')
    if not old_b:
        print('ancien état introuvable, rien à faire')
        return
    old = json.loads(gzip.decompress(old_b))

    # lignes : anciennes d'abord, puis actuelles ; un fichier par jour comme avant
    files = {}
    for day in ('2026-11-15', '2026-11-16', '2026-11-17'):
        rs = read_rows(raw(f'rows/{day}.jsonl.gz'))
        if rs:
            files.setdefault(day + '.jsonl.gz', []).extend(rs)
    n_old = sum(len(v) for v in files.values())
    n_cur = 0
    if os.path.isdir(ROWS_DIR):
        for name in sorted(os.listdir(ROWS_DIR)):
            if name.endswith('.jsonl.gz'):
                with open(os.path.join(ROWS_DIR, name), 'rb') as f:
                    rs = read_rows(f.read())
                n_cur += len(rs)
                files.setdefault(name, []).extend(rs)
    seen_k, out = set(), {}
    for name in sorted(files):
        keep = []
        for r in files[name]:
            k = key(r)
            if k in seen_k:
                continue
            seen_k.add(k)
            keep.append(r)
        out[name] = keep
    n_all = sum(len(v) for v in out.values())

    # compteurs recalculés sur toutes les lignes
    st2 = {'stats': {}}
    for name in sorted(out):
        for r in out[name]:
            C.count_match(st2, as_match(r))
    C.ROWS.clear()

    os.makedirs(ROWS_DIR, exist_ok=True)
    for name, rs in out.items():
        tmp = os.path.join(ROWS_DIR, name + '.tmp')
        with gzip.open(tmp, 'wt', encoding='utf-8') as f:
            for r in rs:
                f.write(json.dumps(r, separators=(',', ':')) + '\n')
        os.replace(tmp, os.path.join(ROWS_DIR, name))

    # état : parties vues (union), rattrapage terminé conservé, dernier passage par joueur = le plus récent
    cur['stats'] = st2['stats']
    seen = dict(old.get('seen', {}))
    seen.update(cur.get('seen', {}))
    cur['seen'] = seen
    for reg, Ro in old.get('regions', {}).items():
        Rc = cur.setdefault('regions', {}).setdefault(reg, Ro)
        if Rc is Ro:
            continue
        bf = Rc.setdefault('bf', {})
        for p, v in Ro.get('bf', {}).items():
            if v == 0:
                bf[p] = 0
            elif p not in bf:
                bf[p] = v
        last = Rc.setdefault('last', {})
        for p, v in Ro.get('last', {}).items():
            last[p] = max(v, last.get(p, 0))
    cur.setdefault('recovered', []).append(SHA)
    with gzip.open(ST + '.tmp', 'wt', encoding='utf-8') as f:
        json.dump(cur, f, separators=(',', ':'))
    os.replace(ST + '.tmp', ST)
    tot = sum(s['n'] for s in cur['stats'].values())
    print(f'récupération : {n_old} lignes anciennes + {n_cur} actuelles -> {n_all} parties uniques ; compteurs recalculés ({tot})')


if __name__ == '__main__':
    main()
