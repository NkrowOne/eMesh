"""Countries and IANA time zones for the timezone picker (continent -> country -> zone).

Countries are listed once in ``COUNTRIES`` and referenced by ISO code from ``CONTINENTS`` (a country
can appear in two continents, e.g. Turkey or Russia). Countries with a single offset have one zone
and are applied directly; the rest list their main IANA zones. Any other IANA zone can be typed by
the user and is checked with ``resolve_zone``.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones


@dataclass(frozen=True, slots=True)
class Country:
    code: str  # ISO 3166-1 alpha-2
    es: str
    en: str
    zones: tuple[str, ...]  # IANA names, main zone first

    @property
    def flag(self) -> str:
        return "".join(chr(0x1F1E6 + ord(letter) - ord("A")) for letter in self.code)

    def name(self, lang: str) -> str:
        return self.es if lang == "es" else self.en


def _c(code: str, es: str, en: str, *zones: str) -> Country:
    return Country(code, es, en, zones)


_COUNTRY_LIST: tuple[Country, ...] = (
    # --- North America ---------------------------------------------------------------------------
    _c("US", "Estados Unidos", "United States", "America/New_York", "America/Chicago", "America/Denver",
       "America/Phoenix", "America/Los_Angeles", "America/Anchorage", "Pacific/Honolulu"),
    _c("CA", "Canadá", "Canada", "America/Toronto", "America/Vancouver", "America/Edmonton", "America/Winnipeg",
       "America/Regina", "America/Halifax", "America/St_Johns"),
    _c("MX", "México", "Mexico", "America/Mexico_City", "America/Cancun", "America/Tijuana", "America/Hermosillo",
       "America/Chihuahua", "America/Mazatlan"),
    _c("GL", "Groenlandia", "Greenland", "America/Nuuk"),
    _c("BM", "Bermudas", "Bermuda", "Atlantic/Bermuda"),
    _c("PM", "San Pedro y Miquelón", "Saint Pierre and Miquelon", "America/Miquelon"),
    # --- Central America and the Caribbean -------------------------------------------------------
    _c("GT", "Guatemala", "Guatemala", "America/Guatemala"),
    _c("BZ", "Belice", "Belize", "America/Belize"),
    _c("HN", "Honduras", "Honduras", "America/Tegucigalpa"),
    _c("SV", "El Salvador", "El Salvador", "America/El_Salvador"),
    _c("NI", "Nicaragua", "Nicaragua", "America/Managua"),
    _c("CR", "Costa Rica", "Costa Rica", "America/Costa_Rica"),
    _c("PA", "Panamá", "Panama", "America/Panama"),
    _c("CU", "Cuba", "Cuba", "America/Havana"),
    _c("JM", "Jamaica", "Jamaica", "America/Jamaica"),
    _c("HT", "Haití", "Haiti", "America/Port-au-Prince"),
    _c("DO", "República Dominicana", "Dominican Republic", "America/Santo_Domingo"),
    _c("PR", "Puerto Rico", "Puerto Rico", "America/Puerto_Rico"),
    _c("BS", "Bahamas", "Bahamas", "America/Nassau"),
    _c("BB", "Barbados", "Barbados", "America/Barbados"),
    _c("TT", "Trinidad y Tobago", "Trinidad and Tobago", "America/Port_of_Spain"),
    _c("AW", "Aruba", "Aruba", "America/Aruba"),
    _c("CW", "Curazao", "Curaçao", "America/Curacao"),
    _c("KY", "Islas Caimán", "Cayman Islands", "America/Cayman"),
    _c("LC", "Santa Lucía", "Saint Lucia", "America/St_Lucia"),
    _c("AG", "Antigua y Barbuda", "Antigua and Barbuda", "America/Antigua"),
    _c("DM", "Dominica", "Dominica", "America/Dominica"),
    _c("GD", "Granada", "Grenada", "America/Grenada"),
    _c("VC", "San Vicente y las Granadinas", "Saint Vincent and the Grenadines", "America/St_Vincent"),
    _c("KN", "San Cristóbal y Nieves", "Saint Kitts and Nevis", "America/St_Kitts"),
    _c("TC", "Islas Turcas y Caicos", "Turks and Caicos Islands", "America/Grand_Turk"),
    _c("VI", "Islas Vírgenes de EE. UU.", "U.S. Virgin Islands", "America/St_Thomas"),
    _c("VG", "Islas Vírgenes Británicas", "British Virgin Islands", "America/Tortola"),
    _c("MQ", "Martinica", "Martinique", "America/Martinique"),
    _c("GP", "Guadalupe", "Guadeloupe", "America/Guadeloupe"),
    # --- South America ---------------------------------------------------------------------------
    _c("AR", "Argentina", "Argentina", "America/Argentina/Buenos_Aires"),
    _c("BO", "Bolivia", "Bolivia", "America/La_Paz"),
    _c("BR", "Brasil", "Brazil", "America/Sao_Paulo", "America/Manaus", "America/Rio_Branco", "America/Noronha"),
    _c("CL", "Chile", "Chile", "America/Santiago", "America/Punta_Arenas", "Pacific/Easter"),
    _c("CO", "Colombia", "Colombia", "America/Bogota"),
    _c("EC", "Ecuador", "Ecuador", "America/Guayaquil", "Pacific/Galapagos"),
    _c("GY", "Guyana", "Guyana", "America/Guyana"),
    _c("PY", "Paraguay", "Paraguay", "America/Asuncion"),
    _c("PE", "Perú", "Peru", "America/Lima"),
    _c("SR", "Surinam", "Suriname", "America/Paramaribo"),
    _c("UY", "Uruguay", "Uruguay", "America/Montevideo"),
    _c("VE", "Venezuela", "Venezuela", "America/Caracas"),
    _c("GF", "Guayana Francesa", "French Guiana", "America/Cayenne"),
    _c("FK", "Islas Malvinas", "Falkland Islands", "Atlantic/Stanley"),
    # --- Europe ----------------------------------------------------------------------------------
    _c("AD", "Andorra", "Andorra", "Europe/Andorra"),
    _c("AL", "Albania", "Albania", "Europe/Tirane"),
    _c("AT", "Austria", "Austria", "Europe/Vienna"),
    _c("BA", "Bosnia y Herzegovina", "Bosnia and Herzegovina", "Europe/Sarajevo"),
    _c("BE", "Bélgica", "Belgium", "Europe/Brussels"),
    _c("BG", "Bulgaria", "Bulgaria", "Europe/Sofia"),
    _c("BY", "Bielorrusia", "Belarus", "Europe/Minsk"),
    _c("CH", "Suiza", "Switzerland", "Europe/Zurich"),
    _c("CY", "Chipre", "Cyprus", "Asia/Nicosia"),
    _c("CZ", "Chequia", "Czechia", "Europe/Prague"),
    _c("DE", "Alemania", "Germany", "Europe/Berlin"),
    _c("DK", "Dinamarca", "Denmark", "Europe/Copenhagen"),
    _c("EE", "Estonia", "Estonia", "Europe/Tallinn"),
    _c("ES", "España", "Spain", "Europe/Madrid", "Atlantic/Canary"),
    _c("FI", "Finlandia", "Finland", "Europe/Helsinki"),
    _c("FO", "Islas Feroe", "Faroe Islands", "Atlantic/Faroe"),
    _c("FR", "Francia", "France", "Europe/Paris"),
    _c("GB", "Reino Unido", "United Kingdom", "Europe/London"),
    _c("GI", "Gibraltar", "Gibraltar", "Europe/Gibraltar"),
    _c("GR", "Grecia", "Greece", "Europe/Athens"),
    _c("HR", "Croacia", "Croatia", "Europe/Zagreb"),
    _c("HU", "Hungría", "Hungary", "Europe/Budapest"),
    _c("IE", "Irlanda", "Ireland", "Europe/Dublin"),
    _c("IS", "Islandia", "Iceland", "Atlantic/Reykjavik"),
    _c("IT", "Italia", "Italy", "Europe/Rome"),
    _c("LI", "Liechtenstein", "Liechtenstein", "Europe/Vaduz"),
    _c("LT", "Lituania", "Lithuania", "Europe/Vilnius"),
    _c("LU", "Luxemburgo", "Luxembourg", "Europe/Luxembourg"),
    _c("LV", "Letonia", "Latvia", "Europe/Riga"),
    _c("MC", "Mónaco", "Monaco", "Europe/Monaco"),
    _c("MD", "Moldavia", "Moldova", "Europe/Chisinau"),
    _c("ME", "Montenegro", "Montenegro", "Europe/Podgorica"),
    _c("MK", "Macedonia del Norte", "North Macedonia", "Europe/Skopje"),
    _c("MT", "Malta", "Malta", "Europe/Malta"),
    _c("NL", "Países Bajos", "Netherlands", "Europe/Amsterdam"),
    _c("NO", "Noruega", "Norway", "Europe/Oslo"),
    _c("PL", "Polonia", "Poland", "Europe/Warsaw"),
    _c("PT", "Portugal", "Portugal", "Europe/Lisbon", "Atlantic/Azores"),
    _c("RO", "Rumanía", "Romania", "Europe/Bucharest"),
    _c("RS", "Serbia", "Serbia", "Europe/Belgrade"),
    _c("RU", "Rusia", "Russia", "Europe/Moscow", "Europe/Kaliningrad", "Europe/Samara", "Asia/Yekaterinburg",
       "Asia/Omsk", "Asia/Novosibirsk", "Asia/Krasnoyarsk", "Asia/Irkutsk", "Asia/Yakutsk", "Asia/Vladivostok",
       "Asia/Magadan", "Asia/Kamchatka"),
    _c("SE", "Suecia", "Sweden", "Europe/Stockholm"),
    _c("SI", "Eslovenia", "Slovenia", "Europe/Ljubljana"),
    _c("SK", "Eslovaquia", "Slovakia", "Europe/Bratislava"),
    _c("SM", "San Marino", "San Marino", "Europe/San_Marino"),
    _c("TR", "Turquía", "Türkiye", "Europe/Istanbul"),
    _c("UA", "Ucrania", "Ukraine", "Europe/Kyiv"),
    _c("VA", "Ciudad del Vaticano", "Vatican City", "Europe/Vatican"),
    _c("XK", "Kosovo", "Kosovo", "Europe/Belgrade"),
    # --- Asia ------------------------------------------------------------------------------------
    _c("AE", "Emiratos Árabes Unidos", "United Arab Emirates", "Asia/Dubai"),
    _c("AF", "Afganistán", "Afghanistan", "Asia/Kabul"),
    _c("AM", "Armenia", "Armenia", "Asia/Yerevan"),
    _c("AZ", "Azerbaiyán", "Azerbaijan", "Asia/Baku"),
    _c("BD", "Bangladés", "Bangladesh", "Asia/Dhaka"),
    _c("BH", "Baréin", "Bahrain", "Asia/Bahrain"),
    _c("BN", "Brunéi", "Brunei", "Asia/Brunei"),
    _c("BT", "Bután", "Bhutan", "Asia/Thimphu"),
    _c("CN", "China", "China", "Asia/Shanghai"),
    _c("GE", "Georgia", "Georgia", "Asia/Tbilisi"),
    _c("HK", "Hong Kong", "Hong Kong", "Asia/Hong_Kong"),
    _c("ID", "Indonesia", "Indonesia", "Asia/Jakarta", "Asia/Makassar", "Asia/Jayapura"),
    _c("IL", "Israel", "Israel", "Asia/Jerusalem"),
    _c("IN", "India", "India", "Asia/Kolkata"),
    _c("IQ", "Irak", "Iraq", "Asia/Baghdad"),
    _c("IR", "Irán", "Iran", "Asia/Tehran"),
    _c("JO", "Jordania", "Jordan", "Asia/Amman"),
    _c("JP", "Japón", "Japan", "Asia/Tokyo"),
    _c("KG", "Kirguistán", "Kyrgyzstan", "Asia/Bishkek"),
    _c("KH", "Camboya", "Cambodia", "Asia/Phnom_Penh"),
    _c("KP", "Corea del Norte", "North Korea", "Asia/Pyongyang"),
    _c("KR", "Corea del Sur", "South Korea", "Asia/Seoul"),
    _c("KW", "Kuwait", "Kuwait", "Asia/Kuwait"),
    _c("KZ", "Kazajistán", "Kazakhstan", "Asia/Almaty"),
    _c("LA", "Laos", "Laos", "Asia/Vientiane"),
    _c("LB", "Líbano", "Lebanon", "Asia/Beirut"),
    _c("LK", "Sri Lanka", "Sri Lanka", "Asia/Colombo"),
    _c("MM", "Birmania (Myanmar)", "Myanmar", "Asia/Yangon"),
    _c("MN", "Mongolia", "Mongolia", "Asia/Ulaanbaatar"),
    _c("MO", "Macao", "Macau", "Asia/Macau"),
    _c("MV", "Maldivas", "Maldives", "Indian/Maldives"),
    _c("MY", "Malasia", "Malaysia", "Asia/Kuala_Lumpur"),
    _c("NP", "Nepal", "Nepal", "Asia/Kathmandu"),
    _c("OM", "Omán", "Oman", "Asia/Muscat"),
    _c("PH", "Filipinas", "Philippines", "Asia/Manila"),
    _c("PK", "Pakistán", "Pakistan", "Asia/Karachi"),
    _c("PS", "Palestina", "Palestine", "Asia/Gaza", "Asia/Hebron"),
    _c("QA", "Catar", "Qatar", "Asia/Qatar"),
    _c("SA", "Arabia Saudí", "Saudi Arabia", "Asia/Riyadh"),
    _c("SG", "Singapur", "Singapore", "Asia/Singapore"),
    _c("SY", "Siria", "Syria", "Asia/Damascus"),
    _c("TH", "Tailandia", "Thailand", "Asia/Bangkok"),
    _c("TJ", "Tayikistán", "Tajikistan", "Asia/Dushanbe"),
    _c("TL", "Timor Oriental", "Timor-Leste", "Asia/Dili"),
    _c("TM", "Turkmenistán", "Turkmenistan", "Asia/Ashgabat"),
    _c("TW", "Taiwán", "Taiwan", "Asia/Taipei"),
    _c("UZ", "Uzbekistán", "Uzbekistan", "Asia/Tashkent"),
    _c("VN", "Vietnam", "Vietnam", "Asia/Ho_Chi_Minh"),
    _c("YE", "Yemen", "Yemen", "Asia/Aden"),
    # --- Africa ----------------------------------------------------------------------------------
    _c("DZ", "Argelia", "Algeria", "Africa/Algiers"),
    _c("AO", "Angola", "Angola", "Africa/Luanda"),
    _c("BJ", "Benín", "Benin", "Africa/Porto-Novo"),
    _c("BW", "Botsuana", "Botswana", "Africa/Gaborone"),
    _c("BF", "Burkina Faso", "Burkina Faso", "Africa/Ouagadougou"),
    _c("BI", "Burundi", "Burundi", "Africa/Bujumbura"),
    _c("CM", "Camerún", "Cameroon", "Africa/Douala"),
    _c("CV", "Cabo Verde", "Cape Verde", "Atlantic/Cape_Verde"),
    _c("CF", "República Centroafricana", "Central African Republic", "Africa/Bangui"),
    _c("TD", "Chad", "Chad", "Africa/Ndjamena"),
    _c("KM", "Comoras", "Comoros", "Indian/Comoro"),
    _c("CG", "República del Congo", "Republic of the Congo", "Africa/Brazzaville"),
    _c("CD", "República Democrática del Congo", "DR Congo", "Africa/Kinshasa", "Africa/Lubumbashi"),
    _c("CI", "Costa de Marfil", "Ivory Coast", "Africa/Abidjan"),
    _c("DJ", "Yibuti", "Djibouti", "Africa/Djibouti"),
    _c("EG", "Egipto", "Egypt", "Africa/Cairo"),
    _c("GQ", "Guinea Ecuatorial", "Equatorial Guinea", "Africa/Malabo"),
    _c("ER", "Eritrea", "Eritrea", "Africa/Asmara"),
    _c("SZ", "Esuatini", "Eswatini", "Africa/Mbabane"),
    _c("ET", "Etiopía", "Ethiopia", "Africa/Addis_Ababa"),
    _c("GA", "Gabón", "Gabon", "Africa/Libreville"),
    _c("GM", "Gambia", "Gambia", "Africa/Banjul"),
    _c("GH", "Ghana", "Ghana", "Africa/Accra"),
    _c("GN", "Guinea", "Guinea", "Africa/Conakry"),
    _c("GW", "Guinea-Bisáu", "Guinea-Bissau", "Africa/Bissau"),
    _c("KE", "Kenia", "Kenya", "Africa/Nairobi"),
    _c("LS", "Lesoto", "Lesotho", "Africa/Maseru"),
    _c("LR", "Liberia", "Liberia", "Africa/Monrovia"),
    _c("LY", "Libia", "Libya", "Africa/Tripoli"),
    _c("MG", "Madagascar", "Madagascar", "Indian/Antananarivo"),
    _c("MW", "Malaui", "Malawi", "Africa/Blantyre"),
    _c("ML", "Malí", "Mali", "Africa/Bamako"),
    _c("MR", "Mauritania", "Mauritania", "Africa/Nouakchott"),
    _c("MU", "Mauricio", "Mauritius", "Indian/Mauritius"),
    _c("MA", "Marruecos", "Morocco", "Africa/Casablanca"),
    _c("MZ", "Mozambique", "Mozambique", "Africa/Maputo"),
    _c("NA", "Namibia", "Namibia", "Africa/Windhoek"),
    _c("NE", "Níger", "Niger", "Africa/Niamey"),
    _c("NG", "Nigeria", "Nigeria", "Africa/Lagos"),
    _c("RW", "Ruanda", "Rwanda", "Africa/Kigali"),
    _c("ST", "Santo Tomé y Príncipe", "São Tomé and Príncipe", "Africa/Sao_Tome"),
    _c("SN", "Senegal", "Senegal", "Africa/Dakar"),
    _c("SC", "Seychelles", "Seychelles", "Indian/Mahe"),
    _c("SL", "Sierra Leona", "Sierra Leone", "Africa/Freetown"),
    _c("SO", "Somalia", "Somalia", "Africa/Mogadishu"),
    _c("ZA", "Sudáfrica", "South Africa", "Africa/Johannesburg"),
    _c("SS", "Sudán del Sur", "South Sudan", "Africa/Juba"),
    _c("SD", "Sudán", "Sudan", "Africa/Khartoum"),
    _c("TZ", "Tanzania", "Tanzania", "Africa/Dar_es_Salaam"),
    _c("TG", "Togo", "Togo", "Africa/Lome"),
    _c("TN", "Túnez", "Tunisia", "Africa/Tunis"),
    _c("UG", "Uganda", "Uganda", "Africa/Kampala"),
    _c("ZM", "Zambia", "Zambia", "Africa/Lusaka"),
    _c("ZW", "Zimbabue", "Zimbabwe", "Africa/Harare"),
    _c("EH", "Sáhara Occidental", "Western Sahara", "Africa/El_Aaiun"),
    # --- Oceania ---------------------------------------------------------------------------------
    _c("AU", "Australia", "Australia", "Australia/Sydney", "Australia/Melbourne", "Australia/Brisbane",
       "Australia/Adelaide", "Australia/Darwin", "Australia/Perth", "Australia/Hobart"),
    _c("NZ", "Nueva Zelanda", "New Zealand", "Pacific/Auckland"),
    _c("FJ", "Fiyi", "Fiji", "Pacific/Fiji"),
    _c("PG", "Papúa Nueva Guinea", "Papua New Guinea", "Pacific/Port_Moresby"),
    _c("WS", "Samoa", "Samoa", "Pacific/Apia"),
    _c("TO", "Tonga", "Tonga", "Pacific/Tongatapu"),
    _c("VU", "Vanuatu", "Vanuatu", "Pacific/Efate"),
    _c("SB", "Islas Salomón", "Solomon Islands", "Pacific/Guadalcanal"),
    _c("NC", "Nueva Caledonia", "New Caledonia", "Pacific/Noumea"),
    _c("PF", "Polinesia Francesa", "French Polynesia", "Pacific/Tahiti"),
    _c("GU", "Guam", "Guam", "Pacific/Guam"),
    _c("PW", "Palaos", "Palau", "Pacific/Palau"),
    _c("FM", "Micronesia", "Micronesia", "Pacific/Pohnpei"),
    _c("KI", "Kiribati", "Kiribati", "Pacific/Tarawa"),
    _c("MH", "Islas Marshall", "Marshall Islands", "Pacific/Majuro"),
    _c("CK", "Islas Cook", "Cook Islands", "Pacific/Rarotonga"),
    _c("NR", "Nauru", "Nauru", "Pacific/Nauru"),
    _c("TV", "Tuvalu", "Tuvalu", "Pacific/Funafuti"),
    _c("AS", "Samoa Americana", "American Samoa", "Pacific/Pago_Pago"),
)

COUNTRIES: dict[str, Country] = {c.code: c for c in _COUNTRY_LIST}

# Same order as the picker shows them. Keys have i18n labels ``tz.cont.<key>``.
CONTINENTS: dict[str, tuple[str, ...]] = {
    "nam": ("US", "CA", "MX", "GL", "BM", "PM"),
    "cam": ("GT", "BZ", "HN", "SV", "NI", "CR", "PA", "CU", "JM", "HT", "DO", "PR", "BS", "BB", "TT", "AW", "CW",
            "KY", "LC", "AG", "DM", "GD", "VC", "KN", "TC", "VI", "VG", "MQ", "GP"),
    "sam": ("AR", "BO", "BR", "CL", "CO", "EC", "GY", "PY", "PE", "SR", "UY", "VE", "GF", "FK"),
    "eur": ("AD", "AL", "AT", "BA", "BE", "BG", "BY", "CH", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FO", "FR",
            "GB", "GI", "GR", "HR", "HU", "IE", "IS", "IT", "LI", "LT", "LU", "LV", "MC", "MD", "ME", "MK", "MT",
            "NL", "NO", "PL", "PT", "RO", "RS", "RU", "SE", "SI", "SK", "SM", "TR", "UA", "VA", "XK"),
    "asi": ("AE", "AF", "AM", "AZ", "BD", "BH", "BN", "BT", "CN", "GE", "HK", "ID", "IL", "IN", "IQ", "IR", "JO",
            "JP", "KG", "KH", "KP", "KR", "KW", "KZ", "LA", "LB", "LK", "MM", "MN", "MO", "MV", "MY", "NP", "OM",
            "PH", "PK", "PS", "QA", "RU", "SA", "SG", "SY", "TH", "TJ", "TL", "TM", "TR", "TW", "UZ", "VN", "YE"),
    "afr": ("DZ", "AO", "BJ", "BW", "BF", "BI", "CM", "CV", "CF", "TD", "KM", "CG", "CD", "CI", "DJ", "EG", "GQ",
            "ER", "SZ", "ET", "GA", "GM", "GH", "GN", "GW", "KE", "LS", "LR", "LY", "MG", "MW", "ML", "MR", "MU",
            "MA", "MZ", "NA", "NE", "NG", "RW", "ST", "SN", "SC", "SL", "SO", "ZA", "SS", "SD", "TZ", "TG", "TN",
            "UG", "ZM", "ZW", "EH"),
    "oce": ("AU", "NZ", "FJ", "PG", "WS", "TO", "VU", "SB", "NC", "PF", "GU", "PW", "FM", "KI", "MH", "CK", "NR",
            "TV", "AS"),
}

# Friendlier names than the IANA city for zones users would not recognize: (Spanish, English).
ZONE_LABELS: dict[str, tuple[str, str]] = {
    "Europe/Madrid": ("Península y Baleares", "Mainland and Balearic Islands"),
    "Atlantic/Canary": ("Islas Canarias", "Canary Islands"),
    "Europe/Lisbon": ("Portugal continental", "Mainland Portugal"),
    "America/Santiago": ("Chile continental", "Mainland Chile"),
    "America/Punta_Arenas": ("Magallanes", "Magallanes"),
    "Pacific/Easter": ("Isla de Pascua", "Easter Island"),
    "America/Guayaquil": ("Ecuador continental", "Mainland Ecuador"),
    "Pacific/Galapagos": ("Islas Galápagos", "Galápagos Islands"),
    "America/Mexico_City": ("Ciudad de México (centro)", "Mexico City (central)"),
    "America/Cancun": ("Cancún (sureste)", "Cancún (southeast)"),
    "America/Sao_Paulo": ("São Paulo (Brasilia)", "São Paulo (Brasília)"),
    "America/Manaus": ("Manaos (Amazonas)", "Manaus (Amazonas)"),
    "America/Rio_Branco": ("Río Branco (Acre)", "Rio Branco (Acre)"),
    "America/Noronha": ("Fernando de Noronha", "Fernando de Noronha"),
    "America/New_York": ("Nueva York (este)", "New York (eastern)"),
    "America/Chicago": ("Chicago (centro)", "Chicago (central)"),
    "America/Denver": ("Denver (montaña)", "Denver (mountain)"),
    "America/Phoenix": ("Phoenix (Arizona)", "Phoenix (Arizona)"),
    "America/Los_Angeles": ("Los Ángeles (pacífico)", "Los Angeles (pacific)"),
    "America/Anchorage": ("Alaska", "Alaska"),
    "Pacific/Honolulu": ("Hawái", "Hawaii"),
}

# Pseudo zones present in many tzdata copies that must never be offered or accepted.
_PSEUDO_ZONES = frozenset({"localtime", "factory", "posixrules"})


def _sort_key(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def countries_of(continent: str, lang: str) -> list[Country]:
    """Countries of a continent sorted by their name in ``lang`` (empty for an unknown continent)."""
    return sorted((COUNTRIES[code] for code in CONTINENTS.get(continent, ())), key=lambda c: _sort_key(c.name(lang)))


def zone_label(zone: str, lang: str) -> str:
    label = ZONE_LABELS.get(zone)
    if label is None:
        return zone.rsplit("/", 1)[-1].replace("_", " ")
    return label[0] if lang == "es" else label[1]


def utc_offset_label(zone: str, now: datetime | None = None) -> str:
    """``UTC+1``, ``UTC-3``, ``UTC+5:30`` at ``now`` (current offset, DST aware; UTC for an unknown zone)."""
    zone_info: tzinfo
    try:
        zone_info = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        zone_info = timezone.utc
    moment = (now or datetime.now(timezone.utc)).astimezone(zone_info)
    minutes = int((moment.utcoffset() or timedelta(0)).total_seconds() // 60)
    hours, rest = divmod(abs(minutes), 60)
    sign = "-" if minutes < 0 else "+"
    return f"UTC{sign}{hours}" + (f":{rest:02d}" if rest else "")


@lru_cache(maxsize=1)
def _known_zones() -> dict[str, str]:
    return {z.casefold(): z for z in available_timezones() if z.casefold() not in _PSEUDO_ZONES}


def resolve_zone(text: str) -> str | None:
    """Canonical IANA name for what the user typed (case insensitive, spaces as ``_``) or None."""
    key = re.sub(r"\s+", "_", (text or "").strip()).casefold()
    zone = _known_zones().get(key)
    if zone is None:
        return None
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None
    return zone
