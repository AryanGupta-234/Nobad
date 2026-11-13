"""Country names <-> ISO 3166-1 alpha-2 codes. The list itself comes from TMDB (/configuration/countries) at
runtime; the only local data is a set of spelling aliases used by Wikipedia section titles and server names
(reference data, not availability data). Historical states (Soviet Union, Czechoslovakia) intentionally map to
no current code."""
import re

ALIASES = {
    "usa": "US", "us": "US", "america": "US", "unitedstatesofamerica": "US", "theunitedstates": "US",
    "uk": "GB", "britain": "GB", "greatbritain": "GB", "england": "GB", "scotland": "GB", "wales": "GB",
    "peoplesrepublicofchina": "CN", "thepeoplesrepublicofchina": "CN", "mainlandchina": "CN", "prc": "CN",
    "republicofchina": "TW", "taiwan": "TW", "hongkong": "HK", "macau": "MO", "macao": "MO",
    "southkorea": "KR", "korea": "KR", "republicofkorea": "KR", "northkorea": "KP",
    "russia": "RU", "russianfederation": "RU", "iran": "IR", "syria": "SY", "vietnam": "VN", "laos": "LA",
    "bolivia": "BO", "venezuela": "VE", "tanzania": "TZ", "moldova": "MD", "turkey": "TR", "turkiye": "TR",
    "uae": "AE", "unitedarabemirates": "AE", "emirates": "AE", "czechrepublic": "CZ", "czechia": "CZ",
    "republicofireland": "IE", "ireland": "IE", "democraticrepublicofthecongo": "CD", "drcongo": "CD",
    "republicofthecongo": "CG", "ivorycoast": "CI", "cotedivoire": "CI", "palestine": "PS",
    "stateofpalestine": "PS", "burma": "MM", "myanmar": "MM", "eswatini": "SZ", "swaziland": "SZ",
    "holland": "NL", "thenetherlands": "NL", "brunei": "BN", "capeverde": "CV", "northmacedonia": "MK",
    "macedonia": "MK", "vatican": "VA", "holysee": "VA", "southafrica": "ZA", "newzealand": "NZ",
}
# Common VPN server cities -> country (reference data for server names only; such matches are labelled estimated).
CITIES = {
    **{c: "US" for c in "newyork nyc losangeles la chicago dallas miami seattle sanfrancisco sanjose siliconvalley denver atlanta phoenix lasvegas boston washington ashburn newjersey secaucus houston saltlakecity kansascity buffalo portland charlotte".split()},
    **{c: "CA" for c in "toronto montreal vancouver calgary".split()},
    **{c: "MX" for c in "mexicocity".split()},
    **{c: "BR" for c in "saopaulo riodejaneiro".split()},
    **{c: "AR" for c in "buenosaires".split()},
    **{c: "CL" for c in "santiago".split()},
    **{c: "CO" for c in "bogota".split()},
    **{c: "PE" for c in "lima".split()},
    **{c: "GB" for c in "london manchester".split()},
    **{c: "IE" for c in "dublin".split()},
    **{c: "FR" for c in "paris marseille".split()},
    **{c: "NL" for c in "amsterdam rotterdam".split()},
    **{c: "BE" for c in "brussels".split()},
    **{c: "DE" for c in "frankfurt berlin munich hamburg dusseldorf nuremberg falkenstein".split()},
    **{c: "CH" for c in "zurich geneva".split()},
    **{c: "AT" for c in "vienna".split()},
    **{c: "CZ" for c in "prague".split()},
    **{c: "PL" for c in "warsaw".split()},
    **{c: "HU" for c in "budapest".split()},
    **{c: "RO" for c in "bucharest".split()},
    **{c: "BG" for c in "sofia".split()},
    **{c: "RS" for c in "belgrade".split()},
    **{c: "HR" for c in "zagreb".split()},
    **{c: "GR" for c in "athens".split()},
    **{c: "IT" for c in "milan rome".split()},
    **{c: "ES" for c in "madrid barcelona".split()},
    **{c: "PT" for c in "lisbon".split()},
    **{c: "DK" for c in "copenhagen".split()},
    **{c: "SE" for c in "stockholm".split()},
    **{c: "NO" for c in "oslo".split()},
    **{c: "FI" for c in "helsinki".split()},
    **{c: "EE" for c in "tallinn".split()},
    **{c: "LV" for c in "riga".split()},
    **{c: "LT" for c in "vilnius".split()},
    **{c: "UA" for c in "kyiv kiev".split()},
    **{c: "RU" for c in "moscow stpetersburg".split()},
    **{c: "TR" for c in "istanbul".split()},
    **{c: "IL" for c in "telaviv".split()},
    **{c: "AE" for c in "dubai abudhabi".split()},
    **{c: "QA" for c in "doha".split()},
    **{c: "SA" for c in "riyadh".split()},
    **{c: "EG" for c in "cairo".split()},
    **{c: "ZA" for c in "johannesburg capetown".split()},
    **{c: "NG" for c in "lagos".split()},
    **{c: "KE" for c in "nairobi".split()},
    **{c: "MA" for c in "casablanca".split()},
    **{c: "IN" for c in "mumbai bombay newdelhi delhi bangalore bengaluru chennai hyderabad kolkata pune noida".split()},
    **{c: "PK" for c in "karachi lahore".split()},
    **{c: "BD" for c in "dhaka".split()},
    **{c: "LK" for c in "colombo".split()},
    **{c: "NP" for c in "kathmandu".split()},
    **{c: "SG" for c in "singapore".split()},
    **{c: "MY" for c in "kualalumpur".split()},
    **{c: "ID" for c in "jakarta".split()},
    **{c: "TH" for c in "bangkok".split()},
    **{c: "VN" for c in "hanoi hochiminh saigon".split()},
    **{c: "PH" for c in "manila".split()},
    **{c: "HK" for c in "hongkong".split()},
    **{c: "TW" for c in "taipei".split()},
    **{c: "JP" for c in "tokyo osaka".split()},
    **{c: "KR" for c in "seoul".split()},
    **{c: "CN" for c in "beijing shanghai shenzhen".split()},
    **{c: "AU" for c in "sydney melbourne brisbane perth".split()},
    **{c: "NZ" for c in "auckland".split()},
    **{c: "KZ" for c in "almaty".split()},
    **{c: "GE" for c in "tbilisi".split()},
    **{c: "AM" for c in "yerevan".split()},
    **{c: "AZ" for c in "baku".split()},
    **{c: "IS" for c in "reykjavik".split()},
    **{c: "LU" for c in "luxembourg".split()},
}
HISTORICAL = {"sovietunion", "ussr", "czechoslovakia", "yugoslavia", "eastgermany", "westgermany",
              "commonwealthofindependentstates", "organisationofislamiccooperation", "rhodesia", "zaire"}


def key(name):
    return re.sub(r"[^a-z]", "", (name or "").casefold().replace("&", "and"))


class Countries:
    def __init__(self, tmdb_list=None):
        """tmdb_list: [{'iso_3166_1': 'IN', 'english_name': 'India', 'native_name': ...}, ...]"""
        self.names, self.by_key = {}, dict(ALIASES)
        self.cities = dict(CITIES)
        for c in tmdb_list or []:
            code = (c.get("iso_3166_1") or "").upper()
            if not re.fullmatch(r"[A-Z]{2}", code):
                continue
            name = c.get("english_name") or c.get("native_name") or code
            self.names[code] = name
            for n in (name, c.get("native_name")):
                if n:
                    self.by_key.setdefault(key(n), code)
            self.by_key.setdefault(key(re.sub(r"\(.*?\)", "", name)), code)

    def name(self, code):
        return self.names.get((code or "").upper(), code)

    def code(self, name):
        """ISO code for a country name, None for unknown/historical names."""
        k = key(re.sub(r"^(the\s+)", "", (name or "").strip(), flags=re.I))
        if not k or k in HISTORICAL:
            return None
        if k in self.by_key:
            return self.by_key[k]
        return self.by_key.get("the" + k)

    def city(self, name):
        return self.cities.get(key(name))

    def is_code(self, s):
        return (s or "").upper() in self.names
