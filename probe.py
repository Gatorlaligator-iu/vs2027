"""Diagnostic ponctuel (8e série) : sites du tri navigateur + nouveaux cabinets."""
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


def ctx(name, url, motif, n=6):
    try:
        t = requests.get(url, headers=UA, timeout=25).text
        hits = [t[max(0, m.start() - 150):m.end() + 200].replace("\n", " ") for m in re.finditer(motif, t, re.I)][:n]
        out.append(f"### {name} (contexte « {motif} »)\n" + "\n".join(f"- `{h}`" for h in hits))
    except Exception as e:
        out.append(f"### {name}\n- ERREUR {str(e)[:120]}")


ctx("KKR greenhouse", "https://www.kkr.com/careers/student-careers/student-career-opportunities", r"greenhouse|job_board|for=")
api("Mutares RSS", "https://career.mutares.com/jobs.rss")
api("Aurelius RSS", "https://career.aurelius-group.com/jobs.rss")
page("Aurelius career", "https://career.aurelius-group.com/")
api("Evercore SR", "https://api.smartrecruiters.com/v1/companies/Evercore/postings?limit=5")
api("Evercore SR2", "https://api.smartrecruiters.com/v1/companies/EvercorePartnersInternationalLLP/postings?limit=5")
ctx("Evercore EU", "https://www.evercore.com/careers/students-graduates/students-graduates-europe-asia/", r"smartrecruiters|click here")
ctx("Deloitte FR stages", "https://www.deloitte.com/fr/fr/careers/content/job/results.html", r"myworkday|workday|api|json")
ctx("Seven2 WK", "https://seven2.welcomekit.co", r"reference|organization|jobs")
ctx("Mirova", "https://recrutement.natixis.com/nos-offres-demploi?tax_brands=mirova,mirova-us&external=false", r"api|json|ajax|wp-json")
api("Natixis wp-json", "https://recrutement.natixis.com/wp-json/wp/v2/types")
page("Eurazeo carrières", "https://www.eurazeo.com/fr/talents")
ctx("Eurazeo home", "https://www.eurazeo.com/fr", r"carri|career|talent|recrut")
ctx("Wendel home", "https://www.wendelgroup.com/fr/", r"carri|career|talent|recrut|rejoindre")
page("Omnes careers", "https://www.omnescapital.com/culture-and-careers")
ctx("Centerview", "https://www.centerviewpartners.com/careers", r"apply|job|greenhouse|lever|workday")
ctx("Arcmont home", "https://arcmont.com/", r"career|join|vacanc")
ctx("Lincoln GH Paris", "https://boards-api.greenhouse.io/v1/boards/lincolninternational/jobs", r"Paris|Munich|Frankfurt|Milan|London|New York", 10)
page("Quantum", "https://quantum-capitalpartners.com/")
page("DC Advisory", "https://www.dcadvisory.com/careers/students-and-graduates/")
page("Vauban", "https://vauban-ip.com/en/")

body = "\n\n".join(out)
print(body)
repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
if repo and token:
    requests.post(f"https://api.github.com/repos/{repo}/issues",
                  json={"title": "Diagnostic des sources (8)", "body": body[:60000], "labels": ["diagnostic"]},
                  headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}, timeout=25)
