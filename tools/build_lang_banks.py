"""Build Quirk's eight phase-1 language banks using only Python's standard library.

Run from the work folder:
  python tools/banks/build_lang_banks.py
  python tools/banks/build_lang_banks.py --offline --check
  python tools/banks/build_lang_banks.py --offline --languages es pt-BR id tr fr

Inputs are retained in cache/; source_lock.json pins their SHA-256. A changed
upstream resource is an error, never silently accepted. --pin-missing explicitly
admits a first snapshot of an unpinned archive. No external packages,
Hunspell executable, app code, or real repository are needed or modified.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import html
import io
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BANKS = ROOT / "content/src/main/assets/banks"
NOTICES = ROOT / "app/src/main/assets/licenses"
PUBLIC_REPO = "https://github.com/cjonlinetogether/quirk-word-lists"
DATE = "2026-10-23"
VERSION = 1
SEED = 20261023
ABC = "abcdefghijklmnopqrstuvwxyz"
LANGS = {
    "es": dict(name="Spanish (Mexico and Spain, explicitly combined)",
               alphabet=ABC + "áéíñóúü", licence="MPL-1.1",
               dictionaries=[("es_MX.dic", "es_MX.aff"), ("es_ES.dic", "es_ES.aff")],
               credit="RLA-ES; Santiago Bosio and contributors",
               home="https://github.com/LibreOffice/dictionaries/tree/master/es",
               notices=["README_hunspell_es.txt", "LICENSE.md", "MPL-1.1.txt"], frequency="es"),
    "pt-BR": dict(name="Brazilian Portuguese", alphabet=ABC + "àáâãçéêíóôõúü",
                  licence="LGPL-3.0-only", dictionaries=[("pt_BR.dic", "pt_BR.aff")],
                  credit="VERO; Raimundo Santos Moura and team (Copyright 2006-2013)",
                  home="https://github.com/LibreOffice/dictionaries/tree/master/pt_BR",
                  notices=["README_en.txt", "README_pt_BR.txt", "LGPLv3.txt", "GPLv3.txt"], frequency="pt_br"),
    "id": dict(name="Indonesian", alphabet=ABC, licence="LGPL-3.0-only",
               dictionaries=[("id_ID.dic", "id_ID.aff")],
               credit="hunspell-id Authors; Benitius Brevoort and contributors",
               home="https://github.com/LibreOffice/dictionaries/tree/master/id",
               notices=["README-dict.adoc", "LICENSE-dict", "LGPLv3.txt", "GPLv3.txt"], frequency="id"),
    "tr": dict(name="Turkish", alphabet="abcçdefgğhıijklmnoöprsştuüvyzâîû", licence="MIT",
               dictionaries=[("tr-index.dic", "tr-index.aff")],
               credit="Copyright (c) 2014 Harun Reşit Zafer",
               home="https://github.com/wooorm/dictionaries/tree/main/dictionaries/tr",
               notices=["tr-license", "tr-readme.md"], frequency="tr"),
    "fr": dict(name="French (Grammalecte classique v7.7)",
               alphabet=ABC + "àâäæçéèêëîïôöœùûüÿ", licence="MPL-2.0",
               dictionaries=[("fr.dic", "fr.aff")], credit="Grammalecte/Dicollecte; Olivier R. and contributors",
               home="https://grammalecte.net/",
               notices=["README_dict_fr.txt", "MPL-2.0.txt"], frequency="fr"),
    "de": dict(name="German (Wiktionary, including common nouns)",
               alphabet=ABC + "äöüß", licence="CC-BY-SA-4.0",
               tabfile="de-wiktionary.tsv", frequency="de",
               credit="English Wiktionary contributors; Tatu Ylonen / Kaikki / Wiktextract; Hannes Krumbiegel (Vuizur)",
               home="https://github.com/Vuizur/Wiktionary-Dictionaries/tree/be0cfb8d614470bc8b9d9006ddff8b921cd5c2e3",
               notices=["wiktionary-mirror-README.md", "CC-BY-SA-4.0.txt"]),
    "it": dict(name="Italian", alphabet=ABC + "àèéìíîòóùú", licence="CC-BY-SA-4.0",
               tabfile="it-wiktionary.tsv", frequency="it",
               credit="English Wiktionary contributors; Tatu Ylonen / Kaikki / Wiktextract; Hannes Krumbiegel (Vuizur)",
               home="https://github.com/Vuizur/Wiktionary-Dictionaries/tree/be0cfb8d614470bc8b9d9006ddff8b921cd5c2e3",
               notices=["wiktionary-mirror-README.md", "CC-BY-SA-4.0.txt"]),
    "pl": dict(name="Polish", alphabet=ABC + "ąćęłńóśźż", licence="CC-BY-4.0",
               dictionaries=[("pl_PL.dic", "pl_PL.aff")], credit="SJP.PL dictionary authors and contributors",
               home="https://sjp.pl/sl/ort/", notices=["README_pl_PL.txt", "CC-BY-4.0.txt"], frequency="pl"),
}
EXTERNAL = {
    "sjp-hunspell-pl-20260901.zip": "https://sjp.pl/sl/ort/sjp-hunspell-pl-20260901.zip",
}
EXTERNAL_SHA256 = {
    # Independently recorded by the FreeBSD/Ravenports release manifests and
    # the pinned SJP downloader; this is the complete outer SJP archive.
    "sjp-hunspell-pl-20260901.zip": "47a5ab02cf3def374994b1b03efd9fed2de868349b8ddcebac281b484353d157",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_text(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def normalise(word: str, lang: str) -> str:
    word = unicodedata.normalize("NFC", word)
    if lang == "tr":
        word = word.translate(str.maketrans({"I": "ı", "İ": "i"}))
    # casefold is deliberately forbidden: it conflates German ß with ss.
    return unicodedata.normalize("NFC", word.lower())


def valid(word: str, lang: str, lo=2, hi=12) -> bool:
    return lo <= len(word) <= hi and all(c in LANGS[lang]["alphabet"] for c in word)


class Inputs:
    def __init__(self, cache: Path, offline: bool, pin_missing: bool, check: bool):
        self.cache, self.offline, self.pin_missing, self.check = cache, offline, pin_missing, check
        self.inventory = {x["file"]: x for x in json.loads((HERE / "source_inventory.json").read_text("utf-8"))["files"]}
        self.lock_path = HERE / "source_lock.json"
        self.lock = json.loads(self.lock_path.read_text("utf-8")) if self.lock_path.exists() else {}
        self.used = set()

    def get(self, name: str) -> Path:
        self.used.add(name)
        path = self.cache / name
        meta = self.inventory.get(name, {})
        url = meta.get("url", EXTERNAL.get(name))
        if not path.exists():
            if self.offline:
                raise RuntimeError(f"Missing cached source: {path}")
            if not url:
                raise RuntimeError(f"No approved download URL for {name}")
            if self.check:
                raise RuntimeError(f"--check does not download missing input {name}")
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".part")
            print(f"Downloading {url}", flush=True)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Quirk-bank-build/1 (source packaging)"})
                with urllib.request.urlopen(req, timeout=60) as response, temporary.open("wb") as out:
                    while chunk := response.read(1024 * 1024):
                        out.write(chunk)
                temporary.replace(path)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
        data = path.read_bytes()
        actual = digest(data)
        if name in self.lock:
            if actual != self.lock[name]["sha256"]:
                raise RuntimeError(f"Source hash mismatch: {name}; preserve released inputs and investigate")
        else:
            git_hash = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            if meta.get("gitBlob"):
                if git_hash != meta["gitBlob"]:
                    raise RuntimeError(f"Git blob mismatch: {name}")
            elif name in EXTERNAL_SHA256:
                if actual != EXTERNAL_SHA256[name]:
                    raise RuntimeError(f"Upstream archive checksum mismatch: {name}")
            elif not self.pin_missing or self.check:
                raise RuntimeError(f"Unpinned archive {name}: first inspect its notices, then use --pin-missing")
            if self.check:
                raise RuntimeError(f"Missing source lock entry: {name}")
            self.lock[name] = {"url": url, "sha256": actual, "bytes": len(data),
                               "gitBlob": meta.get("gitBlob"), "retrieved": DATE}
            self.lock_path.write_text(json_text(self.lock), encoding="utf-8", newline="\n")
        return path

    def text(self, name: str) -> str:
        # Mirror source bytes stay intact, including ISO-8859 dictionaries and
        # legacy notices. Decode only after their original Git/SHA hashes pass.
        encoding = self.inventory.get(name, {}).get("encoding", "utf-8-sig")
        return self.get(name).read_text(encoding=encoding)


class Policy:
    def __init__(self, lang: str):
        data = json.loads((HERE / "language_filters.json").read_text("utf-8"))
        spec = data[lang]
        review = json.loads((HERE / "review_exclusions.json").read_text("utf-8"))
        extra = review.get(lang, {})
        rules = spec["deny"] + data["shared"]["deny"] + review["shared"]["deny"] + extra.get("deny", [])
        self.exact = {normalise(w, lang) for w in rules if not w.endswith("*")}
        self.roots = tuple(normalise(w[:-1], lang) for w in rules if w.endswith("*"))
        self.allow_prefix = tuple(normalise(w, lang) for w in spec.get("allow_prefix", []))
        self.answer_only = {normalise(w, lang) for w in spec.get("answers_only", []) + extra.get("answers_only", [])}
        self.stats = collections.Counter()

    def denied(self, word: str) -> bool:
        return word in self.exact or (word.startswith(self.roots) and not word.startswith(self.allow_prefix))


@dataclass
class Rule:
    side: str
    flag: str
    strip: str
    add: str
    continuation: set[str]
    condition: re.Pattern

    def apply(self, word: str) -> str | None:
        if not self.condition.search(word):
            return None
        if self.side == "PFX":
            if not word.startswith(self.strip):
                return None
            return self.add + word[len(self.strip):]
        if not word.endswith(self.strip):
            return None
        return (word[:-len(self.strip)] if self.strip else word) + self.add


class Hunspell:
    """Conservative subset, not an implementation of the full Hunspell engine.

    Read flags (UTF-8, long or num), conditions, strip/add and continuation
    flags. Include standalone stems and one affix application, only retaining
    derived forms independently attested in the frequency source. Circumfix,
    chained affix, compound and NEEDAFFIX stems are deliberately not expanded.
    Blocking flags and unsafe stems propagate to every derived form.
    """
    def __init__(self, aff: str):
        self.mode = "UTF-8"
        self.special = {}
        self.rules = collections.defaultdict(list)
        for line in aff.splitlines():
            bits = line.split()
            if len(bits) >= 2 and bits[0] == "FLAG":
                self.mode = bits[1]
            if len(bits) >= 2 and bits[0] in {"FORBIDDENWORD", "NOSUGGEST", "NEEDAFFIX", "ONLYINCOMPOUND", "CIRCUMFIX", "KEEPCASE"}:
                self.special[bits[0]] = bits[1]
        for line in aff.splitlines():
            bits = line.split()
            if len(bits) < 5 or bits[0] not in {"PFX", "SFX"}:
                continue
            side, flag, strip, addition, condition = bits[:5]
            add, _, continuation = addition.partition("/")
            strip, add = ("" if strip == "0" else strip), ("" if add == "0" else add)
            pattern = ("^" + condition) if side == "PFX" else (condition + "$")
            self.rules[flag].append(Rule(side, flag, strip, add, set(self.flags(continuation)), re.compile(pattern)))

    def flags(self, text: str) -> list[str]:
        if self.mode == "num":
            return text.split(",") if text else []
        if self.mode == "long":
            if len(text) % 2:
                raise ValueError(f"Odd long-flag sequence: {text!r}")
            return [text[i:i + 2] for i in range(0, len(text), 2)]
        return list(text)

    def words(self, dic: str, lang: str, frequency: dict, policy: Policy):
        bases, derived, blocked = set(), set(), set()
        lines = dic.splitlines()
        if not lines or not lines[0].strip().isdigit():
            raise ValueError("Hunspell dictionary lacks its entry count")
        # Hunspell's first line is advisory; the pinned French v7.7 file has
        # 84,749 records despite its 84,782 header. Integrity uses cryptographic
        # hashes, not that upstream estimate. Record every discrepancy.
        entries = [line for line in lines[1:] if line.strip() and not line.startswith("#")]
        if len(entries) != int(lines[0].strip()):
            policy.stats["upstream_header_count_delta"] += len(entries) - int(lines[0].strip())
        unsafe_flags = {v for k, v in self.special.items() if k in {"FORBIDDENWORD", "NOSUGGEST", "ONLYINCOMPOUND", "KEEPCASE"}}
        need = self.special.get("NEEDAFFIX")
        circumfix = self.special.get("CIRCUMFIX")
        for line in entries:
            token = line.split()[0]
            raw, _, flagtext = token.partition("/")
            word = normalise(raw, lang)
            flags = set(self.flags(flagtext))
            if flags & unsafe_flags or policy.denied(word):
                blocked.add(word)
                policy.stats["unsafe_stems"] += 1
                continue
            if raw != word or not valid(word, lang):
                policy.stats["case_shape_length"] += 1
                continue
            if need in flags or circumfix in flags:
                policy.stats["needs_complex_affix"] += 1
                continue
            bases.add(word)
            for flag in flags:
                for rule in self.rules.get(flag, ()):
                    if rule.continuation & (unsafe_flags | {need, circumfix}):
                        continue
                    form = rule.apply(word)
                    if form and form in frequency and valid(form, lang) and not policy.denied(form):
                        derived.add(form)
        # A forbidden duplicate always wins over a permissive record.
        return bases - blocked, derived - blocked, blocked


BAD_TAGS = {"vulgar", "offensive", "derogatory", "slur", "pejorative", "taboo", "archaic",
            "obsolete", "historical", "dated", "rare", "nonstandard", "misspelling", "error-unrecognized-form",
            "abbreviation", "acronym", "initialism", "proper-noun", "name", "surname"}
GOOD_POS = {"noun", "verb", "adj", "adv", "pron", "det", "prep", "conj", "num", "intj", "particle", "article"}

# Quirk editorial topic policy, matching the six retained banks' sensitivity scope.
# Conservative whole-group rejection propagates through the mirror's form links.
SENSITIVE_GLOSS = re.compile(
    r"\b(?:prostitut\w*|whore\w*|slut\w*|fuck\w*|shit\w*|piss\w*|cunt\w*|"
    r"bastard\w*|bitch\w*|vulgar|obscen\w*|derogator\w*|slur|offensive|"
    r"penis|vagina\w*|genital\w*|sexual\w*|sex|erection|orgasm\w*|semen|"
    r"homosexual\w*|lesbian\w*|porn\w*|naked|nudity|breast\w*|underwear|"
    r"feces|faeces|defecat\w*|urina\w*|toilet|diarrh\w*|vomit\w*|"
    r"insult\w*|idiot\w*|stupid\w*|moron\w*|fool\w*|crippl\w*|"
    r"murder\w*|kill\w*|death|dead|die|dying|corpse\w*|coffin\w*|grave|cemetery|"
    r"funeral\w*|mourn\w*|suicid\w*|tortur\w*|rape\w*|violence|violent|"
    r"weapon\w*|gun\w*|rifle\w*|pistol\w*|revolver\w*|bullet\w*|ammunition|"
    r"bomb\w*|explosi\w*|grenade\w*|dagger\w*|sword\w*|blade\w*|"
    r"war|warfare|military|soldier\w*|army|navy|admiral\w*|colonel\w*|sergeant\w*|"
    r"lieutenant\w*|captain\w*|general|battalion\w*|battle\w*|enemy|enemies|"
    r"crime\w*|criminal\w*|prison\w*|jail\w*|police\w*|sheriff\w*|arrest\w*|"
    r"thief|thieves|theft|steal\w*|stolen|robber\w*|kidnap\w*|hostage\w*|"
    r"mafia|gangster\w*|fraud\w*|brib\w*|blackmail\w*|revenge|threat\w*|"
    r"religio\w*|god\w*|goddess\w*|church\w*|pope\w*|priest\w*|rabbi\w*|"
    r"bishop\w*|monk\w*|monastery|convent\w*|nun\w*|chapel\w*|altar\w*|"
    r"prayer\w*|pray\w*|bless\w*|holy|sacred|biblical|bible|christ\w*|"
    r"jew\w*|muslim\w*|islam\w*|heaven\w*|hell|devil\w*|demon\w*|sin|sinner\w*|"
    r"angel\w*|witch\w*|wizard\w*|zombie\w*|vampire\w*|sorcer\w*|"
    r"disease\w*|illness\w*|sick\w*|cancer\w*|tumou?r\w*|diagnos\w*|"
    r"medicin\w*|medical|surgery|surgeon\w*|hospital\w*|doctor\w*|physician\w*|"
    r"patient\w*|therapy|therapist\w*|infection\w*|virus\w*|fever\w*|"
    r"wound\w*|injur\w*|blood\w*|pain\w*|poison\w*|antidote\w*|"
    r"drug\w*|cocain\w*|heroin\w*|morphine|overdose\w*|addict\w*|"
    r"alcohol\w*|beer\w*|wine\w*|whisk\w*|vodka|brandy|tequila|gin|rum|"
    r"drunk\w*|tobacco|cigar\w*|smok\w*|gambl\w*|poker|casino|"
    r"racis\w*|slave\w*|slavery|nazi\w*|fascis\w*|politic\w*|senat\w*|"
    r"parliament\w*|minister\w*|government\w*|nationality|demonym|ethnic\w*)\b", re.I)

# Individually inspected ordinary German noun meanings in the pinned source.
# The mirror merges Haus/Baum with place/surname POS, Wasser with a spirit sense,
# and Straße with crime/poker senses. Admit only their checked noun HEADWORDS;
# never inherit the ambiguous group's unlabelled aliases through this exception.
SAFE_NOUN_HEADWORDS = {"Haus": "house/home", "Baum": "tree", "Wasser": "water", "Straße": "street/road"}


def wiktionary(inputs: Inputs, lang: str, policy: Policy, frequency: dict):
    """Read the pinned Kaikki-derived Tabfile mirror, without executing its code.

    The first pipe-separated key is the headword; remaining keys are linked
    inflections/variants. POS and raw gloss qualifiers survive in the HTML field.
    Keys were merged across POS, so a rejected sense blocks the whole key group.
    This deliberately sacrifices ambiguous homographs instead of leaking names.
    """
    bases, derived, blocked = set(), set(), set()
    provenance = collections.defaultdict(set)
    evidence = collections.defaultdict(list)
    reviewed_heads = set()
    qualifier_bad = re.compile(r"\b(?:" + "|".join(sorted(BAD_TAGS | {
        "dialectal", "regional", "literary", "poetic", "slang", "proscribed", "offensively", "colloquial"
    })) + r")\b", re.I)
    with inputs.get(LANGS[lang]["tabfile"]).open(encoding="utf-8") as stream:
        for line in stream:
            keys, definition = line.rstrip("\n").split("\t", 1)
            spellings = keys.split("|")
            raw = spellings[0]
            word = normalise(raw, lang)
            pos = set(re.findall(r"<i>([a-z-]+)</i>", definition))
            plain = html.unescape(re.sub(r"<[^>]+>", " ", definition))
            qualifiers = " ".join(re.findall(r"\([^)]*\)", plain))
            unsafe = (not pos or not pos <= GOOD_POS or qualifier_bad.search(qualifiers)
                      or re.search(r"\b(?:abbreviation|acronym|initialism|clipping|misspelling) of\b", plain, re.I)
                      or SENSITIVE_GLOSS.search(plain) or policy.denied(word))
            reviewed_noun = lang == "de" and raw in SAFE_NOUN_HEADWORDS and "noun" in pos
            if reviewed_noun and unsafe and not policy.denied(word):
                unsafe = False
                pos = {"noun"}
                spellings = [raw]
                reviewed_heads.add(word)
            if unsafe:
                blocked.update(normalise(w, lang) for w in spellings)
                policy.stats["wiktionary_rejected_groups"] += 1
                continue
            if raw != word and not (lang == "de" and "noun" in pos and raw[0].isupper() and raw[1:] == raw[1:].lower()):
                continue
            if not valid(word, lang):
                continue
            if lang == "it" and any(c not in ABC for c in word[:-1]):
                # Editorial/internal stress accents are not ordinary Italian spelling.
                continue
            bases.add(word)
            page = "https://en.wiktionary.org/wiki/" + urllib.parse.quote(raw, safe="")
            provenance[word].add(page)
            evidence[word].append(dict(headword=raw, pos=sorted(pos), page=page))
            for form in spellings[1:]:
                spelling = normalise(form, lang)
                if (spelling in frequency and valid(spelling, lang) and not policy.denied(spelling)
                    and (lang != "it" or not any(c not in ABC for c in spelling[:-1]))):
                    derived.add(spelling)
                    provenance[spelling].add(page)
    # Apply root exclusions through the source's inflection links as well.
    # A rejected verb alias (e.g. haus from hausen) must not undo a separately
    # inspected safe noun headword; explicit native deny rules still win above.
    blocked.difference_update(reviewed_heads)
    inputs.wiktionary_evidence = evidence
    return bases - blocked, derived - blocked, blocked, provenance


def frequency_list(inputs: Inputs, lang: str) -> dict[str, int]:
    name = LANGS[lang]["frequency"] + "_50k.txt"
    result = {}
    for line in inputs.text(name).splitlines():
        word, count = line.rsplit(" ", 1)
        if word != normalise(word, lang) or not valid(word, lang):
            continue
        result[word] = result.get(word, 0) + int(count)
    return result


def source(name, licence, url, notice, own=False):
    return dict(name=name, licence=licence, url=url, notice=notice, own=own)


def make_bank(lang: str, kind: str, words: set[str], inputs: Inputs, reviewed: bool):
    spec = LANGS[lang]
    text = "\n".join(sorted(words)) + "\n"
    notice = f"app/src/main/assets/licenses/Quirk-bank-{lang}.txt"
    sources = [source(spec["credit"], spec["licence"], spec["home"], notice),
               source("FrequencyWords 2018; Hermit Dave; OpenSubtitles", "CC-BY-SA-4.0",
                      "https://github.com/hermitdave/FrequencyWords", "app/src/main/assets/licenses/Quirk-FrequencyWords.txt"),
               source("Quirk language-specific editorial filters and sample review", "Quirk", "", "", True)]
    if "tabfile" in spec:
        sources[-1].update(licence="CC-BY-SA-4.0", notice=notice)
    manifest = dict(id=f"{lang}-{kind}", version=VERSION, category=3, language=lang,
                    description=(f"Common {spec['name']} puzzle answers, 3-8 letters." if kind == "answers" else
                                 f"Broader {spec['name']} entry list, 2-12 letters; bounded, not exhaustive."),
                    sources=sources, normalisation="UTF-8 NFC lowercase; preserve accents and ligatures; no whitespace, punctuation, digits or accent stripping",
                    acceptedForms="Attested spellings remain distinct. Digraphs use two tiles; œ, æ and ß use one. Turkish I→ı and İ→i; never Unicode casefold.",
                    review="AgentReviewed" if reviewed else "AgentReviewPending",
                    reviewScope="Seeded sample of 100 answers plus automated corpus checks; acceptance entries are not individually reviewed",
                    humanReview="NotPerformedByOwnerDecision2026-10-23",
                    file="words.txt", entries=len(words), sha256=digest(text.encode("utf-8")),
                    alphabet=list(spec["alphabet"]), usedAlphabet=sorted(set("".join(words))),
                    lengthCounts={str(n): sum(len(w) == n for w in words) for n in range(2, 13)},
                    sourceLock="tools/banks/source_lock.json", buildScript="tools/banks/build_lang_banks.py",
                    dataRights=f"Dictionary rights: {spec['licence']}; frequency-derived selection: CC-BY-SA-4.0. Preserve both notices and source-specific terms.",
                    changesDate=DATE)
    if "tabfile" in spec:
        manifest["dataRights"] = "Adapted word-list data and selection: CC-BY-SA-4.0; mirror input CC-BY-SA-3.0 (or GFDL); adapted under BY-SA 3.0 section 4(b)(ii)."
        manifest["pageAttribution"] = f"app/src/main/assets/licenses/Quirk-bank-{lang}-pages.jsonl"
    return text, manifest


def write_output(path: Path, text: str, check: bool):
    data = text.encode("utf-8")
    if check:
        if not path.exists() or path.read_bytes() != data:
            raise RuntimeError(f"Generated output differs: {path.relative_to(ROOT)}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def ladder_metrics(words: set[str]):
    result = {}
    for length in range(3, 9):
        band = {w for w in words if len(w) == length}
        parent = {w: w for w in band}

        def find(w):
            while parent[w] != w:
                parent[w] = parent[parent[w]]
                w = parent[w]
            return w

        buckets = {}
        for word in sorted(band):
            for i in range(length):
                pattern = word[:i] + "_" + word[i + 1:]
                if pattern in buckets:
                    parent[find(word)] = find(buckets[pattern])
                else:
                    buckets[pattern] = word
        sizes = collections.Counter(find(w) for w in band)
        result[str(length)] = dict(words=len(band), components=len(sizes),
                                   largest=max(sizes.values(), default=0),
                                   isolated=sum(n == 1 for n in sizes.values()))
    return result


def licence_notice(inputs: Inputs, lang: str, extra: list[str]):
    spec = LANGS[lang]
    if "tabfile" in spec:
        text = (f"Quirk {lang} word banks, version 1\n"
                "Adapted from English Wiktionary contributors via Tatu Ylonen / Kaikki / Wiktextract\n"
                "and Hannes Krumbiegel (Vuizur), Wiktionary ebook reader dictionaries.\n"
                f"Mirror: {spec['home']}\n"
                "Original mirror data: CC BY-SA 3.0 (alternatively GFDL); CC licence elected.\n"
                "https://creativecommons.org/licenses/by-sa/3.0/\n"
                "Quirk adapted word-list data and selection: CC BY-SA 4.0, under BY-SA 3.0 section 4(b)(ii).\n"
                "https://creativecommons.org/licenses/by-sa/4.0/\n"
                "Frequency ranking: Hermit Dave / FrequencyWords / OpenSubtitles 2018, CC BY-SA 4.0.\n"
                "https://github.com/hermitdave/FrequencyWords ; https://www.opensubtitles.org/\n"
                f"Changes by Quirk {DATE}: select headwords and linked forms, POS/safety/length/alphabet\n"
                "filtering, NFC lowercase, frequency ranking, deduplication, and 100-answer agent review.\n"
                "German common nouns are lowercased for tiles; spelling marks remain distinct.\n"
                "Earlier modifications: Wiktextract extraction; Vuizur conversion to ebook Tabfile,\n"
                "merging inflected forms and POS/glosses. No generator code from that project is included.\n"
                "Source pages and contributor histories for EVERY distributed spelling are in\n"
                f"Quirk-bank-{lang}-pages.jsonl beside this notice.\n"
                "Page URLs preserve original case and point to English Wiktionary, the source edition.\n"
                "Mirror data last updated 2022-11-09; original Wikimedia dump date is not disclosed.\n"
                f"Word lists, manifests, notices, builder and source pins (URLs, Git blob hashes, SHA-256): {PUBLIC_REPO}\n"
                "The app ships this notice and page map; app EULA/DRM does not restrict the data licence.\n"
                "These separately distributed data files use share-alike; application code has its own licence.\n"
                "No endorsement. Data supplied as-is without warranties; see the licence disclaimer below.\n\n")
        for name in spec["notices"]:
            text += f"===== Original notice / licence: {name} =====\n" + inputs.text(name) + "\n"
        return text
    text = (f"Quirk {lang} word banks, version 1\n{spec['credit']}\nSource: {spec['home']}\n"
            f"Selected dictionary licence: {spec['licence']}.\n"
            f"Changes by Quirk on {DATE}: NFC/case normalization, alphabet/length/case and safety filtering,\n"
            "conservative attested affix expansion, frequency selection, deduplication and agent sample review.\n" +
            "FrequencyWords-derived selection is additionally CC BY-SA 4.0 (see Quirk-FrequencyWords.txt).\n" +
            f"Source form (word lists and manifests), builder and exact upstream URLs/hashes: {PUBLIC_REPO}\n"
            "Those materials are distributed there under these grants.\n"
            "These independent data files are excluded from proprietary application-code restrictions.\n"
            "No endorsement by source authors. No native-speaker review was performed.\n\n")
    for name in spec["notices"]:
        text += f"===== Original notice / licence: {name} =====\n" + inputs.text(name) + "\n"
    for content in extra:
        text += "===== Original archive notice =====\n" + content + "\n"
    # Keep source-file copyright/licence comments, including earlier modification notices.
    for _, aff in spec.get("dictionaries", []):
        comments = [line for line in inputs.text(aff).splitlines() if line.lstrip().startswith("#")]
        text += f"===== Upstream comments: {aff} =====\n" + "\n".join(comments) + "\n"
    for dic, _ in (spec.get("dictionaries", []) if lang in {"de", "it", "pl"} else []):
        comments = [line for line in inputs.text(dic).splitlines()[1:]
                    if line.lstrip().startswith(("#", "/"))]
        if comments:
            text += f"===== Upstream comments: {dic} =====\n" + "\n".join(comments) + "\n"
    return text


def build_one(inputs: Inputs, lang: str, check: bool):
    inputs.used = set()
    spec, policy = LANGS[lang], Policy(lang)
    frequency = frequency_list(inputs, lang)
    provenance, archive_notices = {}, []
    regions = collections.defaultdict(set)
    if "tabfile" in spec:
        bases, derived, blocked, provenance = wiktionary(inputs, lang, policy, frequency)
    elif "archive" in spec:
        with zipfile.ZipFile(inputs.get(spec["archive"])) as outer:
            # The SJP download is an outer ZIP containing pl_PL.zip, rather
            # than the dictionary files directly. Read in memory; do not extract.
            if any(n.endswith("pl_PL.dic") for n in outer.namelist()):
                archive_data = inputs.get(spec["archive"]).read_bytes()
            else:
                inner_name = next(n for n in outer.namelist() if n.endswith("pl_PL.zip"))
                archive_data = outer.read(inner_name)
        with zipfile.ZipFile(io.BytesIO(archive_data)) as archive:
            names = archive.namelist()
            dic_name = next(n for n in names if n.endswith("pl_PL.dic"))
            aff_name = next(n for n in names if n.endswith("pl_PL.aff"))
            aff_bytes = archive.read(aff_name)
            encoding = re.search(rb"(?m)^SET\s+(\S+)", aff_bytes).group(1).decode("ascii")
            parser = Hunspell(aff_bytes.decode(encoding))
            bases, derived, blocked = parser.words(archive.read(dic_name).decode(encoding).lstrip("\ufeff"), lang, frequency, policy)
            for name in names:
                if any(part in name.lower() for part in ("readme", "license", "licence", "copying")) and not name.endswith("/"):
                    data = archive.read(name)
                    try:
                        archive_notices.append(data.decode("utf-8"))
                    except UnicodeDecodeError:
                        archive_notices.append(data.decode(encoding))
            if not archive_notices:
                raise RuntimeError("SJP archive lacks expected author/licence notices; inspect before admission")
    else:
        bases, derived, blocked = set(), set(), set()
        for dic_name, aff_name in spec["dictionaries"]:
            parser = Hunspell(inputs.text(aff_name))
            b, d, bad = parser.words(inputs.text(dic_name), lang, frequency, policy)
            if lang == "es":
                for word in b | d:
                    regions[word].add(dic_name.split(".")[0])
            bases.update(b)
            derived.update(d)
            blocked.update(bad)
    available = {w for w in (bases | derived) - blocked if valid(w, lang) and not policy.denied(w)}
    # Real corpus attestation first; standalone entries before unranked expansions.
    order = lambda w: (-frequency.get(w, 0), w not in bases, hashlib.sha256(w.encode()).hexdigest())
    accept = set(sorted(available, key=order)[:80000])
    # Standalone dictionary records only for answers; no invented suffix targets.
    candidates = {w for w in bases & accept & frequency.keys()
                  if valid(w, lang, 3, 8) and w not in policy.answer_only}
    answers = set(sorted(candidates, key=order)[:2500])
    if len(answers) != 2500:
        raise RuntimeError(f"{lang}: insufficient common answer candidates: {len(answers)}")
    if not 20000 <= len(accept) <= 80000:
        raise RuntimeError(f"{lang}: acceptance size outside requested range: {len(accept)}")
    assert answers <= accept
    sample = sorted(sorted(answers, key=lambda w: hashlib.sha256(f"{SEED}:{lang}:{w}".encode()).digest())[:100])
    review_path = HERE / "quality/sample_reviews.json"
    receipt = json.loads(review_path.read_text("utf-8")).get(lang, {}) if review_path.exists() else {}
    answer_hash = digest(("\n".join(sorted(answers)) + "\n").encode("utf-8"))
    sample_text = "\n".join(sample) + "\n"
    reviewed = (receipt.get("status") == "AgentReviewed" and receipt.get("answersSha256") == answer_hash
                and receipt.get("sampleSha256") == digest(sample_text.encode("utf-8"))
                and receipt.get("reviewedWords") == sample and not receipt.get("unresolvedSampleProblems", ["pending"]))
    stats = dict(language=lang, answers=len(answers), accept=len(accept),
                 candidateAnswers=len(candidates), sourceBases=len(bases), derivedAttested=len(derived),
                 blockedRecords=len(blocked), filtering=dict(policy.stats),
                 sampleSeed=SEED, sampleSize=100, sampleMethod="100 lowest SHA-256(seed:language:word) priorities; stable random sample",
                 sampleReview="AgentReviewed" if reviewed else "AgentReviewPending",
                 alphabet=list(spec["alphabet"]), ladder=ladder_metrics(answers),
                 lowestAnswerFrequency=min(frequency[w] for w in answers),
                 alphabetPolicy="NFC lowercase; one precomposed character per tile; preserve all accents; digraphs use multiple tiles")
    for kind, words in (("answers", answers), ("accept", accept)):
        text, manifest = make_bank(lang, kind, words, inputs, reviewed)
        write_output(BANKS / f"{lang}-{kind}/words.txt", text, check)
        write_output(BANKS / f"{lang}-{kind}/manifest.json", json_text(manifest), check)
        stats[kind + "Lengths"] = manifest["lengthCounts"]
    write_output(HERE / f"quality/{lang}-sample.txt", sample_text, check)
    write_output(NOTICES / f"Quirk-bank-{lang}.txt", licence_notice(inputs, lang, archive_notices), check)
    if provenance:
        records = []
        for word in sorted(accept):
            pages = sorted(provenance[word])
            records.append(json.dumps(dict(word=word, pages=pages,
                                          histories=[p + "?action=history" for p in pages]), ensure_ascii=False))
        write_output(HERE / f"quality/{lang}-page-attribution.jsonl", "\n".join(records) + "\n", check)
        write_output(NOTICES / f"Quirk-bank-{lang}-pages.jsonl", "\n".join(records) + "\n", check)
        evidence = [dict(word=w, sources=inputs.wiktionary_evidence[w]) for w in sorted(answers)]
        write_output(HERE / f"quality/{lang}-answer-provenance.jsonl",
                     "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in evidence) + "\n", check)
        stats["nounAnswers"] = sum(any("noun" in s["pos"] for s in r["sources"]) for r in evidence)
        stats["inflectedAccept"] = len((derived - bases) & accept)
    if regions:
        records = [json.dumps(dict(word=w, regions=sorted(regions[w])), ensure_ascii=False) for w in sorted(accept)]
        write_output(HERE / "quality/es-regions.jsonl", "\n".join(records) + "\n", check)
    stats["inputs"] = sorted(inputs.used)
    write_output(HERE / f"quality/{lang}-counts.json", json_text(stats), check)
    print(f"{lang}: {len(answers)} answers; {len(accept)} accept; 100-word sample seed {SEED}", flush=True)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--languages", nargs="+", choices=list(LANGS), default=list(LANGS))
    parser.add_argument("--cache", type=Path, default=HERE / "cache")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--pin-missing", action="store_true", help="Pin newly obtained non-GitHub archives after inspection")
    args = parser.parse_args()
    inputs = Inputs(args.cache, args.offline, args.pin_missing, args.check)
    failures = []
    for lang in args.languages:
        try:
            build_one(inputs, lang, args.check)
        except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
            failures.append(lang)
            print(f"{lang}: FAILED: {exc}", file=sys.stderr, flush=True)
    freq_notice = ("Quirk frequency selection, version 1\n"
                   "FrequencyWords 2018, Hermit Dave; OpenSubtitles 2018 contributors.\n"
                   "https://github.com/hermitdave/FrequencyWords ; https://www.opensubtitles.org/\n"
                   "Content and adapted selection: CC BY-SA 4.0; https://creativecommons.org/licenses/by-sa/4.0/\n"
                   f"Quirk modifications {DATE}: dictionary intersection, lexical filtering and commonness selection.\n"
                   f"Source URLs/hashes and the adapted lists: {PUBLIC_REPO}\n\n")
    freq_notice += inputs.text("FrequencyWords-README.md") + "\n" + inputs.text("CC-BY-SA-4.0.txt")
    write_output(NOTICES / "Quirk-FrequencyWords.txt", freq_notice, args.check)
    # Combined attribution is independent of the selected build subset.
    combined = "Quirk phase-1 word-bank attribution, 2026-10-23\n\n"
    for lang in LANGS:
        path = NOTICES / f"Quirk-bank-{lang}.txt"
        if path.exists():
            combined += path.read_text("utf-8") + "\n"
    combined += freq_notice
    write_output(NOTICES / "Quirk-language-banks-ATTRIBUTION.txt", combined, args.check)
    # Register complete notices with the existing app licence asset index.
    index_path = NOTICES / "index.json"
    index = json.loads(index_path.read_text("utf-8"))
    index["entries"] = [e for e in index["entries"] if not e["file"].startswith("Quirk-bank-")
                        and e["file"] != "Quirk-FrequencyWords.txt"]
    for lang, spec in LANGS.items():
        path = NOTICES / f"Quirk-bank-{lang}.txt"
        if path.exists():
            index["entries"].append(dict(name=f"Quirk {lang} word banks / {spec['credit']}", kind="word-bank",
                                         version="1 (2026-10-23)", license=spec["licence"] +
                                         "; CC BY-SA 4.0 selection",
                                         file=path.name, source=spec["home"], sha256=digest(path.read_bytes()),
                                         copyright=spec["credit"]))
            if "tabfile" in spec:
                pages = NOTICES / f"Quirk-bank-{lang}-pages.jsonl"
                if pages.exists():
                    index["entries"].append(dict(name=f"Quirk {lang} Wiktionary page attribution", kind="word-bank-attribution",
                                                 version="1 (2026-10-23)", license="CC BY-SA 4.0",
                                                 file=pages.name, source="https://en.wiktionary.org/",
                                                 sha256=digest(pages.read_bytes()), copyright=spec["credit"]))
    index["entries"].append(dict(name="FrequencyWords / OpenSubtitles 2018", kind="word-bank",
                                 version="2018, pinned 2026-10-23", license="CC BY-SA 4.0",
                                 file="Quirk-FrequencyWords.txt", source="https://github.com/hermitdave/FrequencyWords",
                                 sha256=digest(freq_notice.encode("utf-8")), copyright="Hermit Dave; OpenSubtitles contributors"))
    write_output(index_path, json_text(index), args.check)
    print("FAILED languages: " + ", ".join(failures) if failures else "All requested banks match." if args.check else "Build complete.")
    return int(bool(failures))


if __name__ == "__main__":
    sys.exit(main())
