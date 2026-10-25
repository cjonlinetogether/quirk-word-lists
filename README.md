# Quirk word lists

Word lists used by the word puzzles in the Quirk puzzle app, in eight languages:
German (de), Spanish (es), French (fr), Indonesian (id), Italian (it), Polish (pl),
Brazilian Portuguese (pt-BR) and Turkish (tr).

This repository is the source form of these lists. It is published so that everyone
who receives them inside the app can also get them here, under the same licences.
The app's own code is not part of this repository and has its own licence.

## Contents

| Path | What |
|---|---|
| `banks/<lang>-answers/words.txt` | 2,500 answer words per language |
| `banks/<lang>-accept/words.txt` | the wider list of accepted words (up to 80,000) |
| `banks/*/manifest.json` | counts, alphabet, sources, licences and SHA-256 of each list |
| `notices/Quirk-bank-<lang>.txt` | credits, licence, changes and the original upstream notice per language |
| `notices/Quirk-bank-de-pages.jsonl`, `notices/Quirk-bank-it-pages.jsonl` | the English Wiktionary page and history link for every German and Italian word |
| `notices/Quirk-FrequencyWords.txt` | credits and licence of the frequency ranking |
| `notices/Quirk-language-banks-ATTRIBUTION.txt` | all notices in one file |
| `tools/build_lang_banks.py` | the builder that made the lists from the pinned sources |
| `tools/source_lock.json`, `tools/source_inventory.json` | exact upstream URLs, Git blob hashes, SHA-256 and retrieval dates |
| `tools/language_filters.json` | the per-language filter settings |
| `tools/quality/` | the 100-word review samples, review receipts, counts and source evidence |

All word files are UTF-8 without BOM, NFC, lowercase, unique, sorted and LF-terminated.

## Sources and licences

| Language | Spelling source | Licence of the list |
|---|---|---|
| es | RLA-ES (LibreOffice dictionaries) | MPL-1.1, frequency selection CC BY-SA 4.0 |
| pt-BR | VERO (LibreOffice dictionaries) | LGPL-3.0-only, frequency selection CC BY-SA 4.0 |
| id | hunspell-id (LibreOffice dictionaries) | LGPL-3.0-only, frequency selection CC BY-SA 4.0 |
| tr | dictionary-tr (Harun Reşit Zafer) | MIT, frequency selection CC BY-SA 4.0 |
| fr | Grammalecte / Dicollecte | MPL-2.0, frequency selection CC BY-SA 4.0 |
| pl | SJP.PL (LibreOffice snapshot 2026-05-11) | CC BY 4.0, frequency selection CC BY-SA 4.0 |
| de | English Wiktionary via Kaikki/Wiktextract and Vuizur's Wiktionary-Dictionaries | CC BY-SA 4.0 (originals CC BY-SA 3.0 / GFDL) |
| it | English Wiktionary via Kaikki/Wiktextract and Vuizur's Wiktionary-Dictionaries | CC BY-SA 4.0 (originals CC BY-SA 3.0 / GFDL) |

Frequency ranking: FrequencyWords by Hermit Dave, from OpenSubtitles 2018, CC BY-SA 4.0.
The full licence texts and the original upstream notices are in `notices/`.
No source author endorses Quirk or these lists. The lists are provided as is, without warranty.

## Changes made by Quirk (2026-10-23)

Unicode NFC and lowercase normalisation; alphabet, length and case filtering; safety filtering
of offensive, sexual, religious, medical, drug, weapon, crime and political vocabulary;
conservative attested affix expansion; frequency selection; deduplication; and an agent
review of 100 sampled answers per language. No native-speaker review has been done yet.
The builder's safety blocklist itself is not published here.

## Rebuilding

The builder expects the layout of the Quirk app repository (`content/src/main/assets/banks/`
and `app/src/main/assets/licenses/`) and the upstream files pinned in `tools/source_lock.json`.
Python 3.10 or newer, standard library only.
