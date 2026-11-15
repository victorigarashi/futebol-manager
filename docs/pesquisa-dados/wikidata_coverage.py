"""Wikidata (CC0) coverage check for Série A 2026 squads — read-only research tool.

Counts, per club, players whose current (open-ended) P54 'member of sports team'
statement points to the club, and how many of them have birth date, citizenship,
position and a recent start date. It imports nothing into the game catalogue.
The Wikidata Query Service asks for a descriptive User-Agent and low request rates
(on 15/11/2026 it was limiting to 1 request/minute during an outage): run it rarely.

    python3 docs/pesquisa-dados/wikidata_coverage.py
"""
import json, urllib.parse, urllib.request
UA = {"User-Agent": "BrasileiraoManagerResearch/0.1 (catalog coverage check)", "Accept": "application/sparql-results+json"}
CLUBS = ["Clube de Regatas do Flamengo", "Sociedade Esportiva Palmeiras", "Sport Club Corinthians Paulista", "São Paulo Futebol Clube",
         "Santos Futebol Clube", "Botafogo de Futebol e Regatas", "Fluminense Football Club", "Club de Regatas Vasco da Gama",
         "Clube Atlético Mineiro", "Cruzeiro Esporte Clube", "Grêmio Foot-Ball Porto Alegrense", "Sport Club Internacional",
         "Esporte Clube Bahia", "Esporte Clube Vitória", "Club Athletico Paranaense", "Coritiba Foot Ball Club",
         "Red Bull Bragantino", "Mirassol Futebol Clube", "Associação Chapecoense de Futebol", "Clube do Remo"]
def get(url, headers=UA):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60))
labels = " ".join('"%s"@pt' % n for n in CLUBS)
r = get("https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": f"SELECT ?club ?l WHERE {{ VALUES ?l {{ {labels} }} ?club rdfs:label ?l ; wdt:P31/wdt:P279* wd:Q476028 . }}"}))
ids = {b["l"]["value"]: b["club"]["value"].split("/")[-1] for b in r["results"]["bindings"]}
values = " ".join(f"wd:{q}" for q in ids.values())
query = f"""SELECT ?club (COUNT(DISTINCT ?p) AS ?players) (COUNT(DISTINCT ?b) AS ?birth) (COUNT(DISTINCT ?n) AS ?nat) (COUNT(DISTINCT ?pos) AS ?posn) (COUNT(DISTINCT ?s) AS ?since) WHERE {{
 VALUES ?club {{ {values} }}
 ?p p:P54 ?st . ?st ps:P54 ?club . FILTER NOT EXISTS {{ ?st pq:P582 ?end }}
 ?p wdt:P106 wd:Q937857 .
 OPTIONAL {{ ?p wdt:P569 ?bd . BIND(?p AS ?b) }} OPTIONAL {{ ?p wdt:P27 ?c . BIND(?p AS ?n) }}
 OPTIONAL {{ ?p wdt:P413 ?po . BIND(?p AS ?pos) }} OPTIONAL {{ ?st pq:P580 ?start . FILTER(YEAR(?start) >= 2018) BIND(?p AS ?s) }}
}} GROUP BY ?club"""
r = get("https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": query}))
rows = {b["club"]["value"].split("/")[-1]: b for b in r["results"]["bindings"]}
tot = [0]*5
for name, q in ids.items():
    b = rows.get(q); vals = [int(b[k]["value"]) if b else 0 for k in ("players","birth","nat","posn","since")]
    tot = [t+v for t,v in zip(tot, vals)]
    print(f"{name[:34]:34s} {q:10s} open-ended={vals[0]:3d} birth={vals[1]:3d} nat={vals[2]:3d} pos={vals[3]:3d} start>=2018={vals[4]:3d}")
print("TOTAL", tot, "clubs matched", len(ids))
