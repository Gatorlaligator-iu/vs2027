"""Veille stages : interroge les pages carrières des cabinets cibles,
repère les nouvelles offres et ouvre une issue GitHub pour chacune.

Lancé toutes les 10 min par GitHub Actions (.github/workflows/veille.yml).
"""
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
STATE = ROOT / "state" / "seen.json"
UA = "Mozilla/5.0 (compatible; veille-stages/1.0; personal job alert)"
BROWSER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}
TIMEOUT = 25

CFG = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))
F = CFG["filtres"]
RE_TYPE = re.compile("|".join(F["type_poste"]), re.I)
RE_LIEU = re.compile("|".join(F["lieux"]), re.I)
RE_EXCLU = re.compile("|".join(F["exclure"]), re.I) if F.get("exclure") else None
RE_METIER = re.compile("|".join(F["metier"]), re.I) if F.get("metier") else None


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def keep(title, location="", extra="", deja_filtre=False, metier_libre=False):
    """Garde une offre si c'est un stage / graduate, dans un métier et une ville cibles."""
    t = f"{title} {location} {extra}"
    if deja_filtre:  # la page source est déjà filtrée (stage + métier) : on vérifie les dates exclues et le lieu
        if RE_EXCLU and RE_EXCLU.search(t):
            return False
        return not location or bool(RE_LIEU.search(t))
    if not RE_TYPE.search(t):
        return False
    if RE_EXCLU and RE_EXCLU.search(t):
        return False
    if RE_METIER and not metier_libre and not RE_METIER.search(f"{title} {extra}"):
        return False
    # Lieu : si l'info existe, elle doit matcher ; sinon on garde (pages mono-pays).
    if location and not RE_LIEU.search(t):
        return False
    return True


# ---------------------------------------------------------------- fetchers
def fetch_workday(src):
    """Workday : https://<tenant>.wdN.myworkdayjobs.com/<site>"""
    u = urlparse(src["url"])
    parts = [p for p in u.path.split("/") if p and not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", p)]
    if "myworkdaysite" in u.netloc:  # https://wdN.myworkdaysite.com/recruiting/<tenant>/<site>
        tenant, site = parts[1], parts[2]
        job_base = f"{u.scheme}://{u.netloc}/recruiting/{tenant}/{site}"
    else:
        tenant, site = u.netloc.split(".")[0], parts[0]
        job_base = f"{u.scheme}://{u.netloc}/{site}"
    api = f"{u.scheme}://{u.netloc}/wday/cxs/{tenant}/{site}/jobs"
    facets = {}
    for k, v in parse_qsl(u.query):
        facets.setdefault(k, []).append(v)
    jobs, offset = [], 0
    for search in src.get("recherches", [""]):
        offset = 0
        while offset < 400:
            r = requests.post(
                api,
                json={"appliedFacets": facets, "limit": 20, "offset": offset, "searchText": search},
                headers={"User-Agent": UA, "Accept": "application/json"},
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
            posts = data.get("jobPostings", [])
            for p in posts:
                jobs.append({
                    "title": norm(p.get("title")),
                    "location": norm(p.get("locationsText")),
                    "url": f"{job_base}{p.get('externalPath', '')}",
                    "posted": p.get("postedOn", ""),
                })
            if len(posts) < 20:
                break
            offset += 20
    return jobs


def fetch_html(src):
    """Page HTML : garde les liens dont le texte ou l'URL ressemble à une offre."""
    r = requests.get(src["url"], headers={"User-Agent": UA}, timeout=TIMEOUT)
    if r.status_code == 403:  # certains sites refusent les robots déclarés
        r = requests.get(src["url"], headers=BROWSER, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    pat = re.compile(src["motif_lien"], re.I) if src.get("motif_lien") else None
    jobs, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = urljoin(src["url"], a["href"])
        if pat and not pat.search(href):
            continue
        title = norm(a.get_text(" "))
        if title.lower() in GENERIC or len(title) < 12:
            slug = urlparse(href).path.rstrip("/").split("/")[-1]
            title = re.sub(r"[-_]+", " ", slug).strip().capitalize()
        if len(title) < 8 or href in seen:
            continue
        seen.add(href)
        loc = src.get("lieu", "") or (href if src.get("lieu_depuis_url") else "") or (title if src.get("lieu_depuis_titre") else "")
        jobs.append({"title": title, "location": loc, "url": href, "posted": "", "extra": href})
    return jobs


def fetch_oracle(src):
    """Oracle HCM Candidate Experience : .../hcmUI/CandidateExperience/<lang>/sites/<site>/jobs"""
    u = urlparse(src["url"])
    m = re.search(r"/sites/([^/]+)", u.path)
    site_name = m.group(1)
    site_num = src.get("site_number")
    if not site_num:
        page = requests.get(src["url"], headers={"User-Agent": UA}, timeout=TIMEOUT).text
        found = re.search(r"CX_[0-9]+", page)
        site_num = found.group(0) if found else "CX_1"
    api = (f"{u.scheme}://{u.netloc}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
           f"?onlyData=true&expand=requisitionList.secondaryLocations"
           f"&finder=findReqs;siteNumber={site_num},limit=200,sortBy=POSTING_DATES_DESC")
    r = requests.get(api, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=TIMEOUT)
    r.raise_for_status()
    items = r.json().get("items", [])
    reqs = items[0].get("requisitionList", []) if items else []
    base = f"{u.scheme}://{u.netloc}/hcmUI/CandidateExperience/en/sites/{site_name}/job/"
    return [{
        "title": norm(q.get("Title")),
        "location": norm(q.get("PrimaryLocation")),
        "url": base + str(q.get("Id")),
        "posted": q.get("PostedDate", ""),
    } for q in reqs]


def fetch_phenom(src):
    """Phenom (ex. BCG) : API 'widgets' derrière la page de recherche."""
    u = urlparse(src["url"])
    base = f"{u.scheme}://{u.netloc}"
    locale = src.get("locale", "en_global")
    path_prefix = src.get("chemin", "/global/en")
    jobs = []
    for kw in src.get("recherches", ["intern"]):
        for start in range(0, 300, 50):
            payload = {"lang": locale, "deviceType": "desktop", "country": "global", "pageName": "search-results",
                       "ddoKey": "refineSearch", "sortBy": "", "subsearch": "", "from": start, "jobs": True,
                       "counts": False, "all_fields": [], "size": 50, "clearAll": False, "jdsource": "facets",
                       "isSliderEnable": False, "siteType": "external", "keywords": kw, "global": True,
                       "selected_fields": {}, "locationData": {}}
            r = requests.post(f"{base}/widgets", json=payload, headers=BROWSER, timeout=TIMEOUT)
            r.raise_for_status()
            batch = r.json().get("refineSearch", {}).get("data", {}).get("jobs", [])
            for j in batch:
                title = norm(j.get("title"))
                slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
                jobs.append({
                    "title": title,
                    "location": norm(j.get("location") or f"{j.get('city', '')} {j.get('country', '')}"),
                    "url": f"{base}{path_prefix}/job/{j.get('jobSeqNo')}/{slug}",
                    "posted": j.get("postedDate", ""),
                })
            if len(batch) < 50:
                break
    return jobs


def fetch_recruitee(src):
    """Recruitee : API publique https://<societe>.recruitee.com/api/offers/"""
    u = urlparse(src["url"])
    r = requests.get(f"{u.scheme}://{u.netloc}/api/offers/", headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    jobs = []
    for o in r.json().get("offers", []):
        loc = o.get("location") or " ".join(filter(None, [o.get("city"), o.get("country")]))
        jobs.append({"title": norm(o.get("title")), "location": norm(loc),
                     "url": o.get("careers_url") or f"{u.scheme}://{u.netloc}/o/{o.get('slug')}",
                     "posted": o.get("published_at") or o.get("created_at", "")})
    return jobs


def fetch_greenhouse(src):
    """Greenhouse : API publique boards-api.greenhouse.io/v1/boards/<board>/jobs"""
    board = [p for p in urlparse(src["url"]).path.split("/") if p][0]
    r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs", headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    return [{"title": norm(j.get("title")), "location": norm((j.get("location") or {}).get("name")),
             "url": j.get("absolute_url"), "posted": j.get("first_published", "")} for j in r.json().get("jobs", [])]


def fetch_pinpoint(src):
    """Pinpoint : https://<societe>.pinpointhq.com/postings.json"""
    u = urlparse(src["url"])
    r = requests.get(f"{u.scheme}://{u.netloc}/postings.json", headers={"User-Agent": UA, "Accept": "application/json"}, timeout=TIMEOUT)
    r.raise_for_status()
    jobs = []
    for p in r.json().get("data", []):
        loc = p.get("location") or {}
        jobs.append({"title": norm(p.get("title")), "location": norm(" ".join(filter(None, [loc.get("city"), loc.get("name")]))),
                     "url": p.get("url"), "posted": ""})
    return jobs


def fetch_csod(src):
    """Cornerstone (csod) : jeton lu dans la page, puis API rec-job-search."""
    u = urlparse(src["url"])
    page = requests.get(src["url"], headers=BROWSER, timeout=TIMEOUT).text
    token = re.search(r'"token"\s*:\s*"([^"]+)"', page).group(1)
    site = int(re.search(r"careersite/([0-9]+)", u.path).group(1))
    corp = dict(parse_qsl(u.query)).get("c", u.netloc.split(".")[0])
    api = src.get("api", "https://eu-fra.api.csod.com/rec-job-search/external/jobs")
    jobs, page_no = [], 1
    while page_no <= 5:
        body = {"careerSiteId": site, "careerSitePageId": site, "pageNumber": page_no, "pageSize": 100, "cultureId": 1,
                "searchText": "", "cultureName": "en-US", "states": [], "countryCodes": [], "cities": [], "placeID": "",
                "radius": None, "postingsWithinDays": None, "customFieldCheckboxKeys": [], "customFieldDropdowns": [],
                "customFieldRadios": []}
        r = requests.post(api, json=body, headers={**BROWSER, "Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json().get("data", {})
        reqs = data.get("requisitions", [])
        for q in reqs:
            locs = " / ".join(f"{l.get('city', '')} {l.get('country', '')}".strip() for l in q.get("locations", []))
            jobs.append({"title": norm(q.get("displayJobTitle")), "location": norm(locs),
                         "url": f"{u.scheme}://{u.netloc}/ux/ats/careersite/{site}/home/requisition/{q.get('requisitionId')}?c={corp}",
                         "posted": q.get("postingEffectiveDate", "")})
        if len(jobs) >= data.get("totalCount", 0) or not reqs:
            break
        page_no += 1
    return jobs


def fetch_smartrecruiters(src):
    """SmartRecruiters : API publique api.smartrecruiters.com/v1/companies/<id>/postings"""
    company = [p for p in urlparse(src["url"]).path.split("/") if p][0]
    jobs, offset = [], 0
    while offset < 1000:
        r = requests.get(f"https://api.smartrecruiters.com/v1/companies/{company}/postings",
                         params={"limit": 100, "offset": offset}, headers={"User-Agent": UA}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        for p in data.get("content", []):
            loc = p.get("location") or {}
            jobs.append({"title": norm(p.get("name")), "location": norm(loc.get("fullLocation") or loc.get("city")),
                         "url": f"https://jobs.smartrecruiters.com/{company}/{p.get('id')}", "posted": p.get("releasedDate", "")})
        offset += 100
        if offset >= data.get("totalFound", 0):
            break
    return jobs



# ---------------------------------------------------------------- lecture de l'annonce
MOIS_OK = r"(juil\w*|july|jul\.?|luglio|juli|sept\w*|sep\.?|settembre)"
MOIS_KO = (r"(janv\w*|january|jan\.?|gennaio|januar|f[ée]vr\w*|february|feb\.?|febbraio|februar|mars|march|marzo|m[äa]rz|"
           r"avril|april|apr\.?|aprile|mai|may|maggio|juin|june|giugno|juni|"
           r"(?:septembre|september|settembre|octobre|october|ottobre|novembre|november|d[ée]cembre|december|dicembre)\s*(?:de\s*)?2026)")
DEBUT = r"(d[ée]but|d[ée]marr|start|starting|commenc|à partir|from|inizio|beginn|ab dem|ab\b|date)"
RE_OK = re.compile(MOIS_OK + r"[^0-9\n]{0,12}2027|2027[^0-9\n]{0,4}" + MOIS_OK, re.I)
RE_KO = re.compile(DEBUT + r"[^\n]{0,60}?" + MOIS_KO + r"(?:[^0-9\n]{0,12}2027)?", re.I)
RE_ASAP = re.compile(r"d[èe]s que possible|asap|as soon as possible|immediately|immédiatement|il prima possibile|ab sofort", re.I)
EXIGE = r"(courant|fluent|fluency|native|bilingu|madrelingua|ottim\w*|excellent|required|requis|obligatoire|indispensable|essential|verhandlungssicher|flie[sß]end|proficien)"
RE_IT = re.compile(r"(italien|italian|italiano)[^.\n]{0,50}" + EXIGE + "|" + EXIGE + r"[^.\n]{0,50}(italien|italian|italiano)", re.I)
RE_DE = re.compile(r"(allemand|german|deutsch)[^.\n]{0,50}" + EXIGE + "|" + EXIGE + r"[^.\n]{0,50}(allemand|german|deutsch)", re.I)
MOTS_IT = re.compile(r"\b(della|degli|nell[ae]|stage curriculare|tirocinio|candidato|requisiti|laurea)\b", re.I)
MOTS_DE = re.compile(r"\b(und|für|wir|unser\w*|Kenntnisse|Studium|Praktikum)\b")


def texte_html(url):
    r = requests.get(url, headers=BROWSER, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for t in soup(["script", "style", "nav", "footer", "header"]):
        t.decompose()
    return soup.get_text(" ")


def texte_annonce(job, src):
    """Texte complet de l'annonce (API de l'ATS si possible, sinon la page)."""
    t, url = src["type"], job["url"]
    try:
        if t == "workday":
            u = urlparse(url)
            parts = [p for p in u.path.split("/") if p]
            if "myworkdaysite" in u.netloc:
                tenant, site, rest = parts[1], parts[2], "/".join(parts[3:])
            else:
                tenant, site, rest = u.netloc.split(".")[0], parts[0], "/".join(parts[1:])
            r = requests.get(f"{u.scheme}://{u.netloc}/wday/cxs/{tenant}/{site}/{rest}",
                             headers={"User-Agent": UA, "Accept": "application/json"}, timeout=TIMEOUT)
            r.raise_for_status()
            info = r.json().get("jobPostingInfo", {})
            return BeautifulSoup(info.get("jobDescription", ""), "html.parser").get_text(" ") + " " + info.get("startDate", "")
        if t == "greenhouse":
            m = re.search(r"/jobs/([0-9]+)", url) or re.search(r"gh_jid=([0-9]+)", url)
            board = [p for p in urlparse(src["url"]).path.split("/") if p][0]
            if m:
                r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{m.group(1)}?content=true",
                                 headers={"User-Agent": UA}, timeout=TIMEOUT)
                r.raise_for_status()
                import html as _h
                return BeautifulSoup(_h.unescape(r.json().get("content", "")), "html.parser").get_text(" ")
        if t == "smartrecruiters":
            company, pid = [p for p in urlparse(url).path.split("/") if p][:2]
            r = requests.get(f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{pid}",
                             headers={"User-Agent": UA}, timeout=TIMEOUT)
            r.raise_for_status()
            sec = (r.json().get("jobAd") or {}).get("sections") or {}
            return BeautifulSoup(" ".join((v or {}).get("text", "") for v in sec.values()), "html.parser").get_text(" ")
        return texte_html(url)
    except Exception:
        return ""


def analyse(job, src):
    """Renvoie (statut_date, etiquettes) ; statut = ok / hors / inconnue."""
    txt = norm(f"{job['title']} {texte_annonce(job, src)}")
    if len(txt) < 80:
        return "inconnue", ["annonce illisible"], ""
    if RE_OK.search(txt):
        statut = "ok"
    elif RE_KO.search(txt):
        statut = "hors"
    else:
        statut = "inconnue"
    tags = []
    if statut == "inconnue" and RE_ASAP.search(txt):
        tags.append("« dès que possible »")
    if RE_IT.search(txt) or len(MOTS_IT.findall(txt)) >= 6:
        tags.append("🗣️ italien exigé")
    if RE_DE.search(txt) or len(MOTS_DE.findall(txt)) >= 12:
        tags.append("🗣️ allemand exigé")
    m = RE_OK.search(txt) or RE_KO.search(txt)
    extrait = txt[max(0, m.start() - 60):m.end() + 40] if m else ""
    return statut, tags, extrait


def fetch_teamtailor(src):
    """Teamtailor : flux RSS public https://<societe>.teamtailor.com/jobs.rss"""
    import xml.etree.ElementTree as ET
    u = urlparse(src["url"])
    r = requests.get(f"{u.scheme}://{u.netloc}/jobs.rss", headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    jobs = []
    for it in root.iter("item"):
        locs = " / ".join(norm(" ".join(e.itertext())) for e in it.iter() if e.tag.endswith("location"))
        jobs.append({"title": norm(it.findtext("title")), "location": locs,
                     "url": norm(it.findtext("link")), "posted": norm(it.findtext("pubDate"))})
    return jobs


GENERIC = {"learn more", "en savoir plus", "voir l'offre", "voir le programme", "postuler", "apply", "apply now", "read more", "découvrir"}

FETCHERS = {"workday": fetch_workday, "html": fetch_html, "oracle": fetch_oracle, "phenom": fetch_phenom, "recruitee": fetch_recruitee,
            "greenhouse": fetch_greenhouse, "pinpoint": fetch_pinpoint, "csod": fetch_csod, "smartrecruiters": fetch_smartrecruiters,
            "teamtailor": fetch_teamtailor}


# ---------------------------------------------------------------- GitHub
def gh_issue(title, body, labels):
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if not (repo and token):
        print(f"[local] issue: {title}")
        return
    r = requests.post(
        f"https://api.github.com/repos/{repo}/issues",
        json={"title": title[:250], "body": body, "labels": labels},
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        timeout=TIMEOUT,
    )
    if r.status_code >= 300:
        print(f"Issue non créée ({r.status_code}): {r.text[:200]}")


def job_id(job):
    return hashlib.sha1(job["url"].encode()).hexdigest()[:16]


# ---------------------------------------------------------------- main
def main():
    first_run = not STATE.exists()
    seen = {} if first_run else json.loads(STATE.read_text())
    known_sources = set(seen.get("__sources__", []))
    new, report, current, seeded = [], [], [], []

    for src in CFG["sources"]:
        name = src["entreprise"]
        try:
            jobs = FETCHERS[src["type"]](src)
        except Exception as e:  # une source cassée ne bloque pas les autres
            report.append(f"| {name} | ERREUR : {str(e)[:80]} |")
            continue
        req = re.compile(src["titre_requis"], re.I) if src.get("titre_requis") else None
        kept = [j for j in jobs if keep(j["title"], j["location"], j.get("extra", ""), src.get("deja_filtre", False),
                                        src.get("metier_libre", False))
                and (not req or req.search(j["title"]))]
        report.append(f"| {name} | {len(jobs)} lus, {len(kept)} retenus |")
        is_new_source = name not in known_sources and not first_run
        known_sources.add(name)
        for j in kept:
            j["entreprise"] = name
            j["_src"] = src
            current.append(j)
            jid = job_id(j)
            if jid not in seen:
                seen[jid] = {"title": j["title"], "entreprise": name, "url": j["url"]}
                # Source qui vient d'être ajoutée : on enregistre sans notifier une par une
                (seeded if is_new_source else new).append(j)

    table = "| Source | Résultat |\n|---|---|\n" + "\n".join(report)
    print(table)
    (ROOT / "state").mkdir(exist_ok=True)
    (ROOT / "state" / "etat_des_sources.md").write_text(
        "# État des sources (dernier passage)\n\n" + table + "\n", encoding="utf-8")

    if first_run:
        lines = "\n".join(
            f"- **{j['entreprise']}** : [{j['title']}]({j['url']}) {('— ' + j['location']) if j['location'] and not j['location'].startswith('http') else ''}"
            for j in current
        ) or "_Aucune offre correspondante pour l'instant._"
        gh_issue(
            f"Tracker initialisé : {len(current)} offres actuellement en ligne",
            "Premier passage : voici les offres déjà ouvertes qui passent tes filtres. "
            "À partir de maintenant, chaque nouvelle offre ouvrira sa propre issue.\n\n"
            f"{lines}\n\n### État des sources\n| Source | Résultat |\n|---|---|\n" + "\n".join(report),
            ["initialisation"],
        )
    else:
        ecartees = []
        for j in new:
            statut, tags, extrait = analyse(j, j["_src"])
            if statut == "hors":
                ecartees.append(f"| {j['entreprise']} | {j['title']} | {extrait[:120]} |")
                continue
            prefixe = "✅ juil./sept. 2027" if statut == "ok" else "⚠️ date à vérifier"
            etiq = (" · " + " · ".join(tags)) if tags else ""
            lieu = (j['location'] if not j['location'].startswith('http') else 'voir le lien') or 'non précisé'
            gh_issue(
                f"🆕 {prefixe}{etiq} — {j['entreprise']} — {j['title']}",
                f"**Entreprise :** {j['entreprise']}\n\n**Poste :** {j['title']}\n\n"
                f"**Lieu :** {lieu}\n\n**Publié :** {j['posted'] or 'non précisé'}\n\n"
                f"**Date de début :** {'juillet / septembre 2027 trouvé dans l annonce' if statut == 'ok' else 'pas trouvée automatiquement, à vérifier'}"
                f"{(' — « …' + extrait + '… »') if extrait else ''}\n\n"
                f"**Points d'attention :** {', '.join(tags) or 'aucun'}\n\n"
                f"**Lien :** {j['url']}\n\n_À ajouter à l'onglet Offres de ton tracker si la date est bonne._",
                ["nouvelle-offre"],
            )
        if ecartees:
            print("\n### Écartées (début hors fenêtre)\n| Entreprise | Poste | Extrait |\n|---|---|---|\n" + "\n".join(ecartees))

    if seeded:
        lines = "\n".join(f"- **{j['entreprise']}** : [{j['title']}]({j['url']})" for j in seeded)
        gh_issue(
            f"Nouvelles sources ajoutées : {len(seeded)} offres déjà en ligne",
            "Ces offres étaient déjà publiées quand la source a été ajoutée au tracker.\n\n" + lines,
            ["initialisation"],
        )

    seen["__sources__"] = sorted(known_sources)
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(seen, ensure_ascii=False, indent=1))
    print(f"{len(new)} nouvelle(s) offre(s).")


if __name__ == "__main__":
    sys.exit(main())
