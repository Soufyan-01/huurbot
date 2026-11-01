"""Koppeling met MijnDAK Midden-Holland (sociale huur, middenhuur, vrije sector).

De site is een OutSystems-app; de woningen komen uit één JSON-verzoek
('DataActionHaalUitgelogdAanbod') dat zonder inloggen werkt.
"""
import copy
import re

BASE = "https://middenholland.mijndak.nl"
ACTION = "screenservices/DAKWP/Overzicht/Woningaanbod/DataActionHaalUitgelogdAanbod"
SCRIPT = "/scripts/DAKWP.Overzicht.Woningaanbod.mvc.js"
CSRF = "T6C+9iB49TLra4jEsMeSckDMNhQ="          # standaard anoniem OutSystems-token
COOKIE_NR2 = "crf%3dT6C%2b9iB49TLra4jEsMeSckDMNhQ%3d%3buid%3d0%3bunm%3d"
DEFAULT_VERSIONS = {"moduleVersion": "P_one+P4LDqbJ1Obu9uRaA",
                    "apiVersion": "7VY+7u8+RlC1gUalF+dr8Q"}

# Welke lijst in het antwoord welke categorie is (None = overslaan)
CATEGORIES = {
    "MiddenHuur": "Middenhuur",
    "VrijeSector": "Vrije sector",
    "Loting": "Loting",
    "Aanbod": "Sociale huur",
    "Koop": None,
    "ParkerenOverig": None,
}
FAST = {"Middenhuur", "Vrije sector"}           # hier telt snelheid

# ── verzoek opbouwen (zelfde structuur als de browser stuurt) ───────────────
_FILTER_ITEM = {"Naam": "", "IsGeselecteerd": False, "Id": "0", "Categorie": "",
                "Aantal": 0, "IsVisible": True, "IsEmptyValue": False}
_FILTER_KEYS = ["Woonplaatsen", "Eigenaren", "TypeWoning", "AantalKamers", "Aanbodmodel",
                "Doelgroep", "Voorzieningen", "Contractvormen", "Toegankelijkheid",
                "OnzichtbareFilters"]


def _filters():
    f = {k: {"List": [], "EmptyListItem": dict(_FILTER_ITEM)} for k in _FILTER_KEYS}
    f.update({"MaxPrijs": 0, "MinPrijs": 0, "Sortering": 0, "SorteringIsAscending": False})
    return f


_ADRES = {"Straatnaam": "", "Huisnummer": 0, "Huisletter": "", "HuisnummerToevoeging": "",
          "Postcode": "", "Woonplaats": "", "Wijk": "", "PublicatieId": "0"}
_CLUSTER = {"Naam": "", "DetailSoort": "", "Doelgroep": "", "PrijsMinBekend": False,
            "PrijsMin": "0", "PrijsMaxBekend": False, "PrijsMax": "0",
            "WoonOppervlakteMinBekend": False, "WoonVertrekkenTotOppMin": 0,
            "WoonOppervlakteMaxBekend": False, "WoonVertrekkenTotOppMax": 0,
            "AantalEenheden": 0, "AantalKamersMin": 0, "AantalKamersMax": 0,
            "Lengtegraad": "0", "Breedtegraad": "0", "Toegankelijkheid": "",
            "Toegankelijkheidstag": "", "PublicatieId": "0", "SoortBouw": "", "Eigenaar": ""}
_EENHEID = {"DetailSoort": "", "Bestemming": "", "AantalKamers": 0, "TotaleOppervlakte": "0",
            "WoonVertrekkenTotOpp": "0", "Doelgroep": "", "NettoHuurBekend": False,
            "NettoHuur": "0", "Lengtegraad": "0", "Breedtegraad": "0", "Toegankelijkheid": "",
            "Toegankelijkheidstag": "", "PublicatieId": "0", "SoortBouw": "", "EnergieLabel": "",
            "EnergieIndex": 0, "Eigenaar": "", "BrutoHuurBekend": False, "Brutohuur": "0",
            "SubsidiabeleHuur": "0"}
_PUBLICATIE = {"Id": "0", "EinddatumTijd": "1900-01-01T00:00:00", "PublicatieModel": "",
               "PublicatieModule": "", "PublicatieDatum": "1900-01-01T00:00:00",
               "Matchpercentage": 0, "VoorlopigePositie": "0", "Foto_Locatie": "",
               "GepersonaliseerdeHuur": "0", "Slaagkans": 0, "IsCluster": False,
               "EenheidSoort": "", "Adres": _ADRES, "Cluster": _CLUSTER, "Eenheid": _EENHEID,
               "PublicatieLabel": "", "IsBewaard": False, "IsVerborgen": False,
               "ContractVorm": "", "PublicatieOmschrijving": {"Id": "0", "Tekst": None},
               "AantalReactiesOpPublicatie": "0", "HeeftGereageerd": False,
               "IsIntrekkenReactieToegestaan": False, "RedenNietIntrekkenReactie": "",
               "PositieAanbiedingsproces": "", "VirtuelePositie": 0,
               "Opleverdatum": "1900-01-01T00:00:00", "HeeftLift": False, "Verdieping": "",
               "IsMetGepersonaliseerdeHuur": False, "Voorziening": "",
               "AanbiedingProcesSoort": "", "AantalEenhedenBeschikbaar": 0}
_LISTS = ["Basis", "Gefilterd", "Aanbod", "Loting", "VrijeSector", "MiddenHuur",
          "ParkerenOverig", "Koop"]

_CLIENT = {"Voorkeuren_LaatsteLogin": "1900-01-01T00:00:00", "EnableDarkMode": False,
           "MK_Tijd": "0", "BerichtVerwijderenActief": False, "SWVConfiguratie": "",
           "ClientLogEnabled": False, "IsVerbergenVraagNietMeer": False,
           "MoetInschrijfKostenBetalen": False, "SamenwerkingsverbandId": "16",
           "IsIngelogdMetNumeriekeGebruikersnaam": False, "IsMijnOverheidVraagNietMeer": False,
           "ProfielPanelenIncompleet": "", "MFA_ClientSettings": "", "OpleidingWRBOmschrijving": "",
           "Weergave_Filters": "[]", "MK_Timeout": 10, "IsUitgebreidZoeken": False,
           "MijnOverheid_RequestLogId": "0", "CacheVariant": 1, "ZoekAanbod": "",
           "IsAppDownloadVraagNietWeer": False, "RegelingWRBNaam": "", "SessionToken": "",
           "QiiInProfiel": False, "MFA_Request": "", "SessionStart": "1900-01-01T00:00:00",
           "LastURL": "", "IsVerbergKaart": False, "InschrijvenVoortzettenMogelijk": False,
           "RegelingIsCompleet": False, "Homepage_WaardeIsGezet": False,
           "IsWeergavePuntenteller": False, "MK_Gebruiker": "",
           "SamenwerkingsverbandNaam": "Midden-Holland", "Weergave_HeeftFilters": False,
           "SamenwerkingsverbandCode": "MHO", "Homepage_GebruiktNieuweHomepage": False,
           "MFA_Sessie": "", "IsMK": False, "OpleidingWRBNaam": "",
           "Weergave_SorteringIsAflopend": True, "OpleidingIsCompleet": False,
           "Weergave_GebruikWoonwensFilter": True, "MK_Token": "", "MaandenHistorie": -36,
           "QiiKeuzeRelatiegroepStatusCodeId": 0, "MK_Woningzoekende": "",
           "IsWeergaveEinddatum": True, "CheckProfielPanelenVoorPopup": True,
           "ToonNieuweProfielBerichten": False, "Weergave_HeeftSidebar": False,
           "Weergave_Sortering": 6, "RegelingWRBOmschrijving": "", "IsTelValidatieNietMeerTonen": False,
           "Username": "", "MK_Email": "", "IsLogging_MijnOverheid": True, "MFA_RequestId": "0",
           "Weergave_HeeftKaart": True}


def build_body(versions):
    v = {"ActiefTabblad": 0, "Platform": "", "PlatformVersie": "", "AantalVerborgenWoningen": 0,
         "AdvertentielijstContainerId": "", "MapandFiltersContainerId": "",
         "Filters": _filters(), "Filters_Basis": _filters(),
         "Filters_ChipList": {"List": [], "EmptyListItem": {"Categorie": "", "Label": "", "IsGroen": False}},
         "FilterMenu_Trigger": True}
    for name in _LISTS:
        v[f"PublicatieLijst_{name}"] = {"List": [], "EmptyListItem": copy.deepcopy(_PUBLICATIE)}
    v.update({"PublicatieLijst_HasAanbod": True, "PublicatieLijst_Base_TeWeinigAanbod": False,
              "PublicatieLijst_VerborgenItems": 0, "HuidigePublicatieId": "0",
              "_huidigePublicatieIdInDataFetchStatus": 1})
    for k in ["woonplaats", "soort", "type", "kamers", "doelgroep", "contractvorm",
              "toegankelijkheid", "aanbieder"]:
        v[k] = ""
        v[f"_{k}InDataFetchStatus"] = 1
    return {"versionInfo": dict(versions), "viewName": "Overzicht.Woningaanbod",
            "screenData": {"variables": v}, "clientVariables": dict(_CLIENT)}


# ── versies verversen als MijnDAK een update heeft gedaan ───────────────────
def refresh_versions(session):
    versions = dict(DEFAULT_VERSIONS)
    try:
        r = session.get(f"{BASE}/moduleservices/moduleversioninfo", timeout=20)
        token = r.json().get("versionToken")
        if token:
            versions["moduleVersion"] = token
    except Exception:
        pass
    try:
        js = session.get(BASE + SCRIPT, timeout=20).text
        m = re.search(r'DataActionHaalUitgelogdAanbod",\s*"[^"]*",\s*"([^"]+)"', js)
        if m:
            versions["apiVersion"] = m.group(1)
    except Exception:
        pass
    return versions


def _post(session, versions):
    headers = {"Accept": "application/json", "Content-Type": "application/json; charset=UTF-8",
               "Origin": BASE, "Referer": f"{BASE}/Woningaanbod", "X-CSRFToken": CSRF,
               "OutSystems-Locale": "nl-NL"}
    session.cookies.set("nr2Users", COOKIE_NR2, domain="middenholland.mijndak.nl")
    session.cookies.set("nr1Users", "lid%3dAnonymous%3btuu%3d0%3bexp%3d0",
                        domain="middenholland.mijndak.nl")
    r = session.post(f"{BASE}/{ACTION}", json=build_body(versions), headers=headers, timeout=25)
    return r


def fetch(session, state):
    """Geeft (items, versions) terug. items: dicts met url/title/place/price/area/categorie."""
    versions = state.get("mijndak_versions") or dict(DEFAULT_VERSIONS)
    data = None
    for attempt in range(2):
        r = _post(session, versions)
        try:
            data = r.json()
        except ValueError:
            data = None
        vi = (data or {}).get("versionInfo") or {}
        failed = (r.status_code != 200 or not data or "exception" in data
                  or vi.get("hasApiVersionChanged"))
        if not failed:
            break
        if attempt == 0:
            versions = refresh_versions(session)
    if not data or "exception" in data:
        msg = (data or {}).get("exception", {}).get("message") if data else f"HTTP {r.status_code}"
        raise RuntimeError(f"MijnDAK: {msg}")
    state["mijndak_versions"] = versions
    return parse(data.get("data", data))


def _f(x):
    try:
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


RANK = {"?": 1, "Sociale huur": 2, "Loting": 3, "Middenhuur": 3, "Vrije sector": 3}


def parse(data):
    found, excluded = {}, set()

    def walk(o, cat):
        if isinstance(o, dict):
            if isinstance(o.get("Adres"), dict) and str(o.get("Id", "0")) not in ("", "0"):
                pid = str(o["Id"])
                a = o["Adres"]
                street = " ".join(str(x) for x in [a.get("Straatnaam"), a.get("Huisnummer") or "",
                                                    a.get("Huisletter"), a.get("HuisnummerToevoeging")]
                                  if x not in (None, "", 0)).strip()
                city = (a.get("Woonplaats") or "").strip()
                if o.get("IsCluster"):
                    c = o.get("Cluster") or {}
                    title = c.get("Naam") or street
                    price = _f(c.get("PrijsMin")) if c.get("PrijsMinBekend") else 0
                    area = c.get("WoonVertrekkenTotOppMin") or 0
                else:
                    e = o.get("Eenheid") or {}
                    title = street
                    price = _f(e.get("NettoHuur")) if e.get("NettoHuurBekend") else _f(e.get("Brutohuur"))
                    area = _f(e.get("WoonVertrekkenTotOpp"))
                label = " · ".join(x for x in [o.get("AanbiedingProcesSoort"), o.get("PublicatieModel"),
                                               o.get("ContractVorm")] if x)
                item = {"url": f"{BASE}/HuisDetails?PublicatieId={pid}",
                        "title": f"{title}, {city.title()}" if city else title,
                        "city": city, "price": int(round(price)) if price else None,
                        "area": int(area) if area else None, "categorie": cat, "label": label}
                if cat is None:                       # koop / parkeren
                    excluded.add(pid)
                    return
                old = found.get(pid)
                if not old or RANK.get(cat, 0) > RANK.get(old["categorie"], 0):
                    found[pid] = item
                return
            for k, v in o.items():
                sub = cat
                if k.startswith("PublicatieLijst"):
                    suffix = k.split("_", 1)[1] if "_" in k else ""
                    sub = CATEGORIES.get(suffix, "?") if suffix not in ("Basis", "Gefilterd") else "?"
                walk(v, sub)
        elif isinstance(o, list):
            for v in o:
                walk(v, cat)

    walk(data, "?")
    out = []
    for pid, it in found.items():
        if pid in excluded:
            continue
        if it["categorie"] == "?":
            it["categorie"] = "Huur"
        out.append(it)
    return out
