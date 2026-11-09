"""Diagnostic ponctuel (6e série) : A&M, AlixPartners, McKinsey, Bain, Roland Berger, Kroll, Vauban, Omnes, Intesa."""
import os
import re

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
      "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"}
ATS = r"https?://[a-z0-9.-]*(?:myworkdayjobs|myworkdaysite|greenhouse|lever\.co|smartrecruiters|successfactors|welcomekit|recruitee|workable|personio|teamtailor|taleo|avature|icims|phenom|csod|pinpoint|jobvite|eightfold|oraclecloud)[a-z0-9./_?=&%-]*"
out = []


def show(name, r, n=1200):
    t = r.text
    ats = list(dict.fromkeys(re.findall(ATS, t, re.I)))[:6]
    jobs = list(dict.fromkeys(re.findall(r'href="([^"]*(?:job|offre|position|vacanc|career)[^"]*)"', t, re.I)))[:15]
    kw = len(re.findall(r"intern|stage|stagiaire|tirocinio|analyst", t, re.I))
    out.append(f"### {name}\n- HTTP {r.status_code} → {r.url[:140]} ; {len(t)} car. ; {kw} mots-clés\n- ATS : {ats}\n- liens : {jobs}\n```\n{t[:n] if r.headers.get('content-type','').startswith('application/json') else ''}\n```")


def get(name, url, **kw):
    try:
        show(name, requests.get(url, headers={**UA, **kw.pop("headers", {})}, timeout=25, **kw), kw.pop("n", 1200))
    except Exception as e:
        out.append(f"### {name}\n- ERREUR {str(e)[:150]}")


def post(name, url, body):
    try:
        r = requests.post(url, json=body, headers={**UA, "Accept": "application/json"}, timeout=25)
        out.append(f"### {name}\n- HTTP {r.status_code}\n```\n{r.text[:800]}\n```")
    except Exception as e:
        out.append(f"### {name}\n- ERREUR {str(e)[:150]}")


# AlixPartners : Greenhouse
get("AlixPartners GH", "https://boards-api.greenhouse.io/v1/boards/alixpartners/jobs", headers={"Accept": "application/json"})
# Roland Berger : SmartRecruiters
get("RB SmartRecruiters", "https://api.smartrecruiters.com/v1/companies/RolandBerger/postings?limit=100", headers={"Accept": "application/json"})
get("RB site", "https://www.rolandberger.com/en/Join/All-Jobs/")
# Kroll
get("Kroll site", "https://careers.kroll.com/en/search-results?keywords=intern")
post("Kroll phenom widgets", "https://careers.kroll.com/widgets",
     {"lang": "en_global", "deviceType": "desktop", "country": "global", "pageName": "search-results", "ddoKey": "refineSearch",
      "sortBy": "", "subsearch": "", "from": 0, "jobs": True, "counts": True, "all_fields": ["category", "country", "city", "type"],
      "size": 10, "clearAll": False, "jdsource": "facets", "isSliderEnable": False, "pageId": "page1",
      "siteType": "external", "keywords": "intern", "global": True, "selected_fields": {}})
# A&M
get("A&M careers", "https://www.alvarezandmarsal.com/careers")
get("A&M jobs", "https://jobs.alvarezandmarsal.com/")
for t, n, s in [("alvarezandmarsal", 1, "AM_Careers"), ("alvarezandmarsal", 5, "AlvarezMarsal"), ("am", 1, "AM")]:
    post(f"A&M workday {t}.wd{n}/{s}", f"https://{t}.wd{n}.myworkdayjobs.com/wday/cxs/{t}/{s}/jobs",
         {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""})
get("A&M GH", "https://boards-api.greenhouse.io/v1/boards/alvarezandmarsal/jobs", headers={"Accept": "application/json"})
# McKinsey
get("McK API", "https://www.mckinsey.com/services/ContentAPI/SearchAPI.svc/jobs/search?&pageSize=20&start=1&countries=France", headers={"Accept": "application/json"})
get("McK site", "https://www.mckinsey.com/careers/search-jobs?countries=France")
# Bain
get("Bain API", "https://www.bain.com/en/api/jobsearch/keyword/get?start=0&results=20&filters=&searchValue=intern", headers={"Accept": "application/json"})
get("Bain site", "https://www.bain.com/careers/find-a-role/?filters=offices(275)")
# Vauban, Omnes, Intesa
get("Vauban", "https://www.vauban-ip.com/en/careers")
get("Vauban 2", "https://www.vauban-ip.com/careers")
get("Omnes", "https://www.omnescapital.com/fr/carrieres")
get("Omnes 2", "https://www.omnescapital.com/en/careers")
get("Intesa", "https://jobs.intesasanpaolo.com/")
get("Intesa 2", "https://group.intesasanpaolo.com/en/careers")

body = "\n\n".join(out)
print(body)
repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
if repo and token:
    requests.post(f"https://api.github.com/repos/{repo}/issues",
                  json={"title": "Diagnostic des sources (6)", "body": body[:60000], "labels": ["diagnostic"]},
                  headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}, timeout=25)
