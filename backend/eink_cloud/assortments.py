"""Standaard assortimenten per branche, voor winkels zonder kassakoppeling.

De winkel kiest een branche, vinkt aan wat hij verkoopt en vult alleen de prijzen in. Naam,
eenheid, omschrijving en ontwerp staan al goed. Bij vis staat de wetenschappelijke naam in de
omschrijving (EU-verordening 1379/2013); vangstgebied/herkomst en vistuig vult de winkel zelf aan,
want dat verschilt per partij.

Allergenen staan er bewust niet in: die hangen af van het recept van de winkel zelf.

Kibbeling en lekkerbekje worden van verschillende vissoorten gemaakt. Daar staat bewust géén soort
voorgevuld: de winkel kiest de soort die hij echt verkoopt (pollak als kabeljauw verkopen is misleidend).
"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class AssortmentItem:
    name: str
    unit: str = "st"  # st, kg, 100g, l, pak
    description: str | None = None
    template: str | None = None  # None = winkelontwerp
    unit_price_unit: str = "kg"
    variants: tuple[str, ...] = ()  # keuze vissoort e.d.; verplicht kiezen als er varianten zijn
    options: tuple[str, ...] = ()  # voorgestelde keuzes op het label, bv. sauzen


@dataclass(frozen=True)
class Assortment:
    id: str
    name: str
    prefix: str  # voorvoegsel voor voorgestelde artikelnummers
    template: str  # aanbevolen winkelontwerp
    items: tuple[AssortmentItem, ...]

    def as_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "template": self.template,
            "items": [dict(asdict(item), sku=f"{self.prefix}{i:03d}", variants=list(item.variants),
                   options=list(item.options)) for i, item in enumerate(self.items, start=1)],
        }


def _items(*rows) -> tuple[AssortmentItem, ...]:
    return tuple(row if isinstance(row, AssortmentItem) else AssortmentItem(*row) if isinstance(row, tuple)
                 else AssortmentItem(row) for row in rows)


# Handelsbenaming + wetenschappelijke naam, voor gebakken witvis (kibbeling, lekkerbekje).
WHITEFISH = (
    "Kabeljauw (Gadus morhua)",
    "Pollak (Pollachius pollachius)",
    "Alaska koolvis (Gadus chalcogrammus)",
    "Koolvis (Pollachius virens)",
    "Wijting (Merlangius merlangus)",
    "Heek (Merluccius merluccius)",
)
SAUCES = ("Knoflook", "Ravigotte", "Remoulade", "Cocktail", "Tartaar")


ASSORTMENTS: dict[str, Assortment] = {a.id: a for a in (
    Assortment("slagerij", "Slagerij", "SL", "ambachtelijk", _items(
        ("Runderbiefstuk", "kg"), ("Entrecote", "kg"), ("Ribeye", "kg"), ("Ossenhaas", "kg"),
        ("Rosbief", "kg"), ("Runderlappen", "kg"), ("Sukadelappen", "kg"), ("Riblappen", "kg"),
        ("Rundergehakt", "kg"), ("Gehakt half-om-half", "kg"), ("Tartaar", "st"), ("Hamburger", "st"),
        ("Varkenshaas", "kg"), ("Varkensfilet", "kg"), ("Speklapjes", "kg"), ("Procureur", "kg"),
        ("Karbonade", "kg"), ("Spareribs", "kg"), ("Slavink", "st"), ("Saucijzen", "kg"),
        ("Rookworst", "st"), ("Gehaktballen", "st"), ("Schnitzel", "st"), ("Cordon bleu", "st"),
        ("Kipfilet", "kg"), ("Kippendijen", "kg"), ("Kippenpoten", "kg"), ("Kipsaté", "kg"),
        ("Shoarmavlees", "kg"), ("Lamskoteletten", "kg"),
        ("Achterham", "100g"), ("Rookvlees", "100g"), ("Ossenworst", "100g", "Amsterdams recept"),
        ("Fricandeau", "100g"), ("Leverworst", "100g"), ("Boerenmetworst", "100g"),
        ("Gebraden gehakt", "100g"), ("Huisgemaakte rollade", "kg"),
    )),
    Assortment("vis", "Viswinkel", "VI", "vis", _items(
        AssortmentItem("Kibbeling", "st", variants=WHITEFISH, options=SAUCES),
        AssortmentItem("Lekkerbekje", "st", variants=WHITEFISH, options=SAUCES),
        ("Hollandse Nieuwe", "st", "Haring (Clupea harengus)"),
        ("Zure haring", "st", "Haring (Clupea harengus)"),
        ("Rolmops", "st", "Haring (Clupea harengus)"),
        ("Kabeljauwfilet", "kg", "Gadus morhua"),
        ("Zalmfilet", "kg", "Salmo salar"),
        ("Gerookte zalm", "100g", "Salmo salar"),
        ("Scholfilet", "kg", "Pleuronectes platessa"),
        ("Tongfilet", "kg", "Solea solea"),
        ("Koolvisfilet", "kg", "Pollachius virens"),
        ("Pangasiusfilet", "kg", "Pangasius hypophthalmus, gekweekt"),
        ("Tonijnsteak", "kg", "Thunnus albacares"),
        ("Makreel gerookt", "st", "Scomber scombrus"),
        ("Gerookte paling", "100g", "Anguilla anguilla"),
        ("Mosselen", "kg", "Mytilus edulis"),
        ("Hollandse garnalen", "100g", "Crangon crangon"),
        ("Gamba's", "kg", "Penaeus vannamei"),
        ("Inktvisringen", "kg", "Loligo spp., gepaneerd"),
        ("Vissalade", "100g"),
        AssortmentItem("Visburger", "st", options=SAUCES),
        ("Zalmsalade", "100g"),
    )),
    Assortment("bakkerij", "Bakkerij", "BA", "bakker", _items(
        ("Volkorenbrood", "st", "Heel"), ("Half volkorenbrood", "st", "Half"), ("Witbrood", "st"),
        ("Tijgerbrood", "st"), ("Desembrood", "st"), ("Meergranenbrood", "st"), ("Speltbrood", "st"),
        ("Stokbrood", "st"), ("Krentenbrood", "st"), ("Rozijnenbrood", "st"),
        ("Witte bolletjes", "st"), ("Bruine bolletjes", "st"), ("Krentenbol", "st"), ("Kaiserbroodje", "st"),
        ("Croissant", "st"), ("Chocoladebroodje", "st"), ("Saucijzenbroodje", "st"), ("Kaasbroodje", "st"),
        ("Appelflap", "st"), ("Gevulde koek", "st"), ("Tompouce", "st"), ("Moorkop", "st"),
        ("Appeltaart", "st", "Heel"), ("Appeltaartpunt", "st"), ("Vlaai", "st"), ("Ontbijtkoek", "st"),
        ("Roomboterkoekjes", "100g"), ("Stroopwafels", "pak"), ("Boterkoek", "st"),
    )),
    Assortment("kaas", "Kaas en delicatessen", "KA", "delicatesse", _items(
        ("Jonge kaas", "kg"), ("Jong belegen kaas", "kg"), ("Belegen kaas", "kg"), ("Extra belegen kaas", "kg"),
        ("Oude kaas", "kg"), ("Overjarige kaas", "kg"), ("Komijnekaas", "kg"), ("Kruidenkaas", "kg"),
        ("Geitenkaas", "kg"), ("Schapenkaas", "kg"), ("Boerenkaas", "kg", "Van rauwe melk"),
        ("Brie", "100g"), ("Camembert", "st"), ("Roquefort", "100g"), ("Parmezaanse kaas", "100g"),
        ("Olijven", "100g"), ("Tapenade", "100g"), ("Pesto", "100g"), ("Hummus", "100g"),
        ("Zongedroogde tomaten", "100g"), ("Notenmix", "100g"),
    )),
    Assortment("groente", "Groente en fruit", "GF", "markt", _items(
        ("Elstar appels", "kg"), ("Jonagold appels", "kg"), ("Conference peren", "kg"), ("Bananen", "kg"),
        ("Sinaasappels", "kg"), ("Mandarijnen", "kg"), ("Citroenen", "st"), ("Druiven", "kg"),
        ("Aardbeien", "pak", "Bakje 400 g"), ("Blauwe bessen", "pak", "Bakje 125 g"), ("Kiwi", "st"),
        ("Avocado", "st"), ("Mango", "st"), ("Ananas", "st"), ("Meloen", "st"),
        ("Aardappelen", "kg"), ("Uien", "kg"), ("Rode uien", "kg"), ("Knoflook", "st"),
        ("Bospeen", "st", "Per bos"), ("Winterpeen", "kg"), ("Tomaten", "kg"), ("Trostomaten", "kg"),
        ("Cherrytomaten", "pak", "Bakje 250 g"), ("Komkommer", "st"), ("Paprika rood", "st"),
        ("Courgette", "st"), ("Broccoli", "st"), ("Bloemkool", "st"), ("Spinazie", "pak"),
        ("IJsbergsla", "st"), ("Champignons", "pak", "Bakje 250 g"), ("Prei", "st"), ("Spruitjes", "kg"),
    )),
)}


def suggestions() -> list[dict]:
    """Alle productnamen uit alle branches, voor suggesties tijdens het typen."""
    seen, out = set(), []
    for a in ASSORTMENTS.values():
        for item in a.items:
            if item.name not in seen:
                seen.add(item.name)
                out.append({"name": item.name, "unit": item.unit, "description": item.description,
                            "template": item.template or (a.template if a.id == "vis" else None),
                            "variants": list(item.variants), "options": list(item.options)})
    return sorted(out, key=lambda x: x["name"].lower())
