"""Diagnostic ponctuel (7e série) : sites du tri navigateur + nouveaux cabinets."""
import os
import re

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
      "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"}
ATS = r"https?://[a-z0-9.-]*(?:myworkdayjobs|myworkdaysite|greenhouse|lever\.co|smartrecruiters|successfactors|welcomekit|welcometothejungle|recruitee|workable|personio|teamtailor|taleo|avature|icims|phenom|csod|pinpoint|jobvite|eightfold|oraclecloud|jibe|bamboohr|join\.com|softgarden|rexx|dvinci|jobylon|hibob|ashbyhq)[a-z0-9./_?=&%-]*"
out = []


def page(name, url):
    try:
        r = requests.get(url, headers=UA, timeout=25)
        t = r.text
        ats = list(dict.fromkeys(re.findall(ATS, t, re.I)))[:6]
        jobs = list(dict.fromkeys(re.findall(r'href="([^"]*(?:job|offre|position|vacanc|career|stelle|karriere|opportunit)[^"]*)"', t, re.I)))[:12]
        kw = len(re.findall(r"intern|stage|stagiaire|praktik|analyst", t, re.I))
        out.append(f"### {name}\n- HTTP {r.status_code} → {r.url[:120]} ; {len(t)} car. ; {kw} mots-clés\n- ATS : {ats}\n- liens : {jobs}")
    except Exception as e:
        out.append(f"### {name}\n- ERREUR {str(e)[:120]}")


def api(name, url, method="get", body=None, n=300):
    try:
        h = {**UA, "Accept": "application/json, application/xml, */*"}
        r = requests.post(url, json=body, headers=h, timeout=25) if method == "post" else requests.get(url, headers=h, timeout=25)
        ok = r.status_code == 200
        out.append(f"### {name}\n- HTTP {r.status_code} {'✅' if ok else ''} ({len(r.text)} car.)\n```\n{r.text[:n] if ok else ''}\n```")
    except Exception as e:
        out.append(f"### {name}\n- ERREUR {str(e)[:120]}")


WD = {"appliedFacets": {}, "limit": 3, "offset": 0, "searchText": "intern"}

# --- Sites du tri navigateur ---
page("KKR page", "https://www.kkr.com/careers/student-careers/student-career-opportunities")
for b in ["kkr", "kkrstudent", "kkrcampus", "kkrcareers"]:
    api(f"KKR GH {b}", f"https://boards-api.greenhouse.io/v1/boards/{b}/jobs")
api("Antin RSS", "https://antininfrastructurepartners-1655458195.teamtailor.com/jobs.rss")
page("Antin jobs", "https://antininfrastructurepartners-1655458195.teamtailor.com/jobs")
page("Seven2 WK", "https://seven2.welcomekit.co")
api("Seven2 WTTJ API", "https://api.welcometothejungle.com/api/v1/organizations/seven2/jobs")
page("Seven2 WTTJ", "https://www.welcometothejungle.com/fr/companies/seven2/jobs")
page("Mirova Natixis", "https://recrutement.natixis.com/nos-offres-demploi?tax_brands=mirova,mirova-us&external=false")
page("A&M careers", "https://careers.alvarezandmarsal.com/search/jobs?q=intern%20Paris")
api("A&M jibe api", "https://careers.alvarezandmarsal.com/api/jobs?keywords=intern&page=1")
api("McK API", "https://www.mckinsey.com/services/ContentAPI/SearchAPI.svc/jobs/search?&pageSize=20&start=1&countries=France")
page("Kroll listing", "https://careers.kroll.com/en/listing-page?keyword=intern&location=")
for t, n, s in [("kroll", 1, "Kroll"), ("kroll", 5, "External"), ("kroll", 1, "External"), ("duffandphelps", 1, "Kroll")]:
    api(f"Kroll WD {t}.wd{n}/{s}", f"https://{t}.wd{n}.myworkdayjobs.com/wday/cxs/{t}/{s}/jobs", "post", WD)

# --- PE couverts seulement par le web ---
page("Advent", "https://www.adventinternational.com/careers/")
api("Advent GH", "https://boards-api.greenhouse.io/v1/boards/adventinternational/jobs")
page("CVC", "https://www.cvc.com/careers/")
page("Eurazeo", "https://www.eurazeo.com/fr/carrieres")
page("Eurazeo WTTJ", "https://www.welcometothejungle.com/fr/companies/eurazeo/jobs")
page("Wendel", "https://www.wendelgroup.com/fr/carrieres/")
page("Vauban", "https://www.vauban-ip.com/en/join-us")
page("Omnes", "https://www.omnescapital.com/carrieres")

# --- Nouveaux cabinets ---
page("Mutares", "https://www.mutares.com/en/career/")
api("Mutares personio", "https://mutares.jobs.personio.de/xml")
page("Aurelius", "https://aurelius-group.com/en/career/")
api("Aurelius personio", "https://aurelius.jobs.personio.de/xml")
page("Quantum", "https://www.quantum-capitalpartners.com/en/career/")
api("Quantum personio", "https://quantum-capital-partners.jobs.personio.de/xml")
page("Evercore", "https://www.evercore.com/careers/")
for t, n, s in [("evercore", 1, "Evercore_Careers"), ("evercore", 1, "EvercoreCareers"), ("evercore", 5, "Evercore")]:
    api(f"Evercore WD {s}", f"https://{t}.wd{n}.myworkdayjobs.com/wday/cxs/{t}/{s}/jobs", "post", WD)
page("Centerview", "https://www.centerviewpartners.com/careers")
api("Centerview GH", "https://boards-api.greenhouse.io/v1/boards/centerviewpartners/jobs")
page("DC Advisory", "https://www.dcadvisory.com/careers/")
page("Lincoln", "https://www.lincolninternational.com/careers/")
api("Lincoln GH", "https://boards-api.greenhouse.io/v1/boards/lincolninternational/jobs")
page("Deloitte FR", "https://www2.deloitte.com/fr/fr/careers/students.html")
api("PwC WD", "https://pwc.wd3.myworkdayjobs.com/wday/cxs/pwc/Global_Experienced_Careers/jobs", "post",
    {"appliedFacets": {}, "limit": 3, "offset": 0, "searchText": "stage restructuring France"})
page("PwC FR", "https://www.pwc.fr/fr/carrieres/offres.html")
page("Oderis", "https://www.oderis.fr/carrieres")
page("Arcmont", "https://www.arcmont.com/careers")
page("Attestor", "https://attestor.com/careers/")
api("Attestor GH", "https://boards-api.greenhouse.io/v1/boards/attestor/jobs")
page("Butler", "https://www.butlerindustries.fr/")

body = "\n\n".join(out)
print(body)
repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
if repo and token:
    requests.post(f"https://api.github.com/repos/{repo}/issues",
                  json={"title": "Diagnostic des sources (7)", "body": body[:60000], "labels": ["diagnostic"]},
                  headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}, timeout=25)
