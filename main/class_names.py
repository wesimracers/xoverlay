"""Shared class header labels for simulator sessions with missing class names.

Car-path categories come from the project's existing irdashies cars-bundle.json
(Lovely Sim Racing car data). Porsche CUP entries use the readable Porsche Cup
label. Simulator class names take precedence over these model categories.
"""

import re
from collections import defaultdict


CAR_PATH_CLASSES = {'acuraarx06gtp': 'GTP',
 'acuransxevo22gt3': 'GT3',
 'amvantageevogt3': 'GT3',
 'amvantagegt4': 'GT4',
 'audir18': 'LMP1',
 'audir8lmsevo2gt3': 'GT3',
 'audirs3lms': 'TCR',
 'audirs3lmsgen2': 'TCR',
 'bmwlmdh': 'GTP',
 'bmwm2csr': 'M2C',
 'bmwm4evogt4': 'GT4',
 'bmwm4gt3': 'GT3',
 'bmwm4gt4': 'GT4',
 'bmwm8gte': 'GTE',
 'c8rvettegte': 'GTE',
 'cadillacctsvr': 'CTS',
 'cadillacvseriesrgtp': 'GTP',
 'chevyvettez06rgt3': 'GT3',
 'dallaradw12': 'INDY',
 'dallaraf3': 'F3',
 'dallarail15': 'NXT',
 'dallarair01': 'iR01',
 'dallarair18': 'INDY',
 'dallarap217': 'LMP2',
 'ferrari296challenge': 'F296',
 'ferrari296gt3': 'GT3',
 'ferrari488gte': 'GTE',
 'ferrari499p': 'GTP',
 'fordgt2017': 'GTE',
 'fordmustanggt3': 'GT3',
 'fordmustanggt4': 'GT4',
 'formulair04': 'F4',
 'formularenault20': 'F2.0',
 'formularenault35': 'F3.5',
 'hondacivictyper': 'TCR',
 'hpdarx01c': 'LMP2',
 'hyundaielantracn7': 'TCR',
 'hyundaivelostern': 'TCR',
 'lamborghinievogt3': 'GT3',
 'ligierjsp320': 'LMP3',
 'mclaren570sgt4': 'GT4',
 'mclaren720sgt3': 'GT3',
 'mclarenmp4': 'GT3',
 'mercedesamgevogt3': 'GT3',
 'mercedesamggt4': 'GT4',
 'mercedesw12': 'F1',
 'mercedesw13': 'F1',
 'mx5 mx52016': 'MX5',
 'nascar-chevrolet-camaro-nextgen': 'NXG',
 'nascar-chevrolet-montecarlo-gen4-2003': 'Gen4',
 'nascar-ford-mustang-nextgen': 'NXG',
 'nascar-ford-taurus-gen4-2003': 'Gen4',
 'nascar-oreilly-chevrolet-camaro': 'ORE',
 'nascar-oreilly-ford-mustang': 'ORE',
 'nascar-oreilly-toyota-supra': 'ORE',
 'nascar-toyota-camry-nextgen': 'NXG',
 'porsche718gt4': 'GT4',
 'porsche919': 'LMP1',
 'porsche963gtp': 'GTP',
 'porsche991rsr': 'GTE',
 'porsche9922cup': 'Porsche Cup',
 'porsche992cup': 'Porsche Cup',
 'porsche992rgt3': 'GT3',
 'radical sr8': 'SR8',
 'radicalsr10': 'SR10',
 'raygr22': 'F1.6',
 'renaultcliocup': 'CUP',
 'specracer': 'SCCA',
 'supercars chevycamarogen3': 'SUP',
 'supercars fordmustanggen3': 'SUP',
 'superformulalights324': 'SFL',
 'superformulasf23 honda': 'SF',
 'superformulasf23 toyota': 'SF',
 'toyotagr86': 'GR86',
 'usf2000usf17': 'USF'}


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _normalized_path(path):
    return re.sub(r"[^a-z0-9]", "", _text(path).lower())


_PATH_LABELS = {_normalized_path(path): label for path, label in CAR_PATH_CLASSES.items()}


def class_labels(drivers):
    """Resolve every class from its simulator names, model mapping or car names.

    IDs group cars only; they never imply a category. An unmapped model uses
    its simulator display name. Multiple model categories in a custom class
    are retained together rather than choosing an arbitrary car's category.
    """
    groups = defaultdict(list)
    for driver in drivers:
        if not isinstance(driver, dict) or driver.get("CarIsPaceCar"):
            continue
        try:
            cid = int(driver.get("CarClassID", -1))
        except (TypeError, ValueError):
            continue
        if cid >= 0:
            groups[cid].append(driver)

    labels = {}
    for cid, group in groups.items():
        # One car can provide the class name missing from the other entries.
        for field in ("CarClassShortName", "CarClassName"):
            names = [_text(driver.get(field)) for driver in group]
            name = next((name for name in names if name), "")
            if name:
                labels[cid] = name
                break
        if cid in labels:
            continue
        names = set()
        for driver in group:
            name = _PATH_LABELS.get(_normalized_path(driver.get("CarPath")))
            if not name:
                name = _text(driver.get("CarScreenName")) or _text(driver.get("CarScreenNameShort"))
            if name:
                names.add(name)
        labels[cid] = " / ".join(sorted(names)) if names else f"CLASS {cid}"
    return labels
