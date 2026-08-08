#!/usr/bin/env python3
"""Build a deterministic EPUB3 fixture with original content.

The fixture is an original didactic work (public domain by the author, no
third-party text) structured like a study text: Parts -> Chapters -> Sections,
with verse-numbered paragraphs and in-text cross references. This gives the
digester real spine + TOC hierarchy to align to, and gives downstream consumers
a meaningful chapter query and reference query to run against the index.

Run:  python3 tools/make_fixture.py
Out:  fixtures/wayfarers-compass.epub  (byte-for-byte reproducible)
"""
from __future__ import annotations

import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "fixtures", "wayfarers-compass.epub")

# Fixed timestamp so the zip is byte-for-byte reproducible.
FIXED_DATE = (2020, 1, 1, 0, 0, 0)

# --- Book content model -----------------------------------------------------
# Each chapter: (num, title, part, [sections]) where a section is
# (heading, [verses]) and a verse is a paragraph string. Verses are numbered
# per chapter starting at 1, in document order across the chapter's sections.

BOOK = {
    "title": "The Wayfarer's Compass",
    "subtitle": "A Field Manual for Steady Living",
    "author": "B. Nipper",
    "language": "en",
    "identifier": "urn:uuid:wayfarers-compass-0001",
    "parts": [
        {
            "name": "Part I — Bearings",
            "chapters": [
                {
                    "num": 1,
                    "title": "On Beginning",
                    "sections": [
                        ("The First Step", [
                            "Every long road opens with a single unremarkable step, taken before the traveler feels ready.",
                            "Readiness is not a feeling that arrives; it is a decision that is made and then defended.",
                            "The wayfarer who waits for certainty waits forever, for certainty is a harbor that no honest map contains.",
                        ]),
                        ("Packing Light", [
                            "Carry only what serves the walk; every ounce of vanity is paid for later in blisters.",
                            "A heavy pack is often a heavy heart, refusing to leave behind what it has outgrown (cf. 3:2).",
                            "Water, bread, and a true bearing outlast gold on any real journey.",
                        ]),
                    ],
                },
                {
                    "num": 2,
                    "title": "On Direction",
                    "sections": [
                        ("Reading the Compass", [
                            "A compass does not tell you where to go; it tells you the truth about where you are pointed.",
                            "Trust the needle over the mood, for the mood turns with the weather and the needle does not.",
                            "When the trail and the needle disagree, suspect the trail (see 1:3).",
                        ]),
                        ("True North", [
                            "There is magnetic north, which is convenient, and true north, which is correct; know the difference.",
                            "Correct for the drift between them daily, or the small error will compound into a lost afternoon.",
                            "The traveler who never checks the correction is the most confident and the most lost.",
                        ]),
                    ],
                },
            ],
        },
        {
            "name": "Part II — Weather",
            "chapters": [
                {
                    "num": 3,
                    "title": "On Storms",
                    "sections": [
                        ("When the Sky Turns", [
                            "Storms announce themselves to those who watch the horizon and ambush those who watch their feet.",
                            "Shelter early; the traveler who runs from the first drop is dry, and the proud one is drowned (cf. 1:2).",
                            "A storm is not punishment; it is weather, and weather is the price of being outside.",
                        ]),
                        ("Patience in the Wet", [
                            "Waiting is a skill, not a failure; the patient wayfarer conserves what the anxious one spends.",
                            "Count the thunder after the light to learn how far the danger stands, and let the number steady you.",
                            "No storm has ever lasted the whole of a life, though many have felt that long (see 4:1).",
                        ]),
                    ],
                },
                {
                    "num": 4,
                    "title": "On Arrival",
                    "sections": [
                        ("The Last Mile", [
                            "The last mile is longer than the first because the body is tired and the mind is already home.",
                            "Do not sprint the ending you walked the whole way to earn; finish with attention (cf. 2:2).",
                        ]),
                        ("Setting Down the Pack", [
                            "Arrival is not the end of the compass but the beginning of its rest; put it where you can find it again.",
                            "Tell the road honestly to the next traveler: the dry shelters, the false trails, the true bearings (see 3:2).",
                            "Then set down the pack, and let the walk have been enough.",
                        ]),
                    ],
                },
            ],
        },
    ],
}

CSS = """body{font-family:serif;line-height:1.5;margin:1em;}
h1{font-size:1.6em;margin-top:1em;}
h2{font-size:1.2em;color:#333;margin-top:1.2em;}
.v{font-weight:bold;color:#666;font-size:.8em;vertical-align:super;margin-right:.3em;}
p{margin:.6em 0;}
"""


def xhtml(title: str, body: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en">\n'
        f'<head><meta charset="utf-8"/><title>{title}</title>'
        '<link rel="stylesheet" type="text/css" href="style.css"/></head>\n'
        f'<body>\n{body}\n</body>\n</html>\n'
    )


def chapter_html(ch: dict) -> str:
    parts = [f'<h1>Chapter {ch["num"]}. {ch["title"]}</h1>']
    v = 1
    for heading, verses in ch["sections"]:
        parts.append(f"<h2>{heading}</h2>")
        for text in verses:
            parts.append(
                f'<p><span class="v" id="c{ch["num"]}v{v}">{v}</span>{text}</p>'
            )
            v += 1
    return "\n".join(parts)


def build() -> None:
    b = BOOK
    files: list[tuple[str, str]] = []  # (arcname, text)

    # Front matter (spine documents that the digester should EXCLUDE).
    files.append((
        "OEBPS/cover.xhtml",
        xhtml("Cover", f'<h1>{b["title"]}</h1><p><em>{b["subtitle"]}</em></p>'),
    ))
    files.append((
        "OEBPS/copyright.xhtml",
        xhtml("Copyright", (
            f'<p>{b["title"]}: {b["subtitle"]}</p>'
            f'<p>Written by {b["author"]}.</p>'
            '<p>This is an original work created as a test fixture. '
            'All rights reserved by the author; reproduced here as a '
            'digester fixture.</p>'
        )),
    ))

    # Body: one XHTML per chapter.
    chapter_files: list[tuple[int, str, str, str]] = []  # num,title,part,arc
    for part in b["parts"]:
        for ch in part["chapters"]:
            arc = f'OEBPS/chapter-{ch["num"]:02d}.xhtml'
            files.append((arc, xhtml(ch["title"], chapter_html(ch))))
            chapter_files.append((ch["num"], ch["title"], part["name"], arc))

    # EPUB3 navigation document (the TOC hierarchy: Part -> Chapter).
    nav_items = []
    for part in b["parts"]:
        subs = []
        for ch in part["chapters"]:
            href = f'chapter-{ch["num"]:02d}.xhtml'
            subs.append(
                f'<li><a href="{href}">Chapter {ch["num"]}. {ch["title"]}</a></li>'
            )
        nav_items.append(
            f'<li><span>{part["name"]}</span><ol>\n'
            + "\n".join(subs)
            + "\n</ol></li>"
        )
    nav_body = (
        '<nav epub:type="toc" id="toc"><h1>Table of Contents</h1>\n<ol>\n'
        + "\n".join(nav_items)
        + "\n</ol></nav>"
    )
    nav_html = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en" lang="en">\n'
        '<head><meta charset="utf-8"/><title>Contents</title></head>\n'
        f'<body>\n{nav_body}\n</body>\n</html>\n'
    )
    files.append(("OEBPS/nav.xhtml", nav_html))
    files.append(("OEBPS/style.css", CSS))

    # content.opf (package document): manifest + spine.
    manifest = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="css" href="style.css" media-type="text/css"/>',
        '<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>',
        '<item id="copyright" href="copyright.xhtml" media-type="application/xhtml+xml"/>',
    ]
    spine = [
        '<itemref idref="cover"/>',
        '<itemref idref="copyright"/>',
    ]
    for num, title, part, arc in chapter_files:
        iid = f"chap{num:02d}"
        href = os.path.basename(arc)
        manifest.append(
            f'<item id="{iid}" href="{href}" media-type="application/xhtml+xml"/>'
        )
        spine.append(f'<itemref idref="{iid}"/>')

    opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        'unique-identifier="pub-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'    <dc:identifier id="pub-id">{b["identifier"]}</dc:identifier>\n'
        f'    <dc:title>{b["title"]}: {b["subtitle"]}</dc:title>\n'
        f'    <dc:creator>{b["author"]}</dc:creator>\n'
        f'    <dc:language>{b["language"]}</dc:language>\n'
        '    <meta property="dcterms:modified">2020-01-01T00:00:00Z</meta>\n'
        '  </metadata>\n'
        '  <manifest>\n    ' + "\n    ".join(manifest) + '\n  </manifest>\n'
        '  <spine>\n    ' + "\n    ".join(spine) + '\n  </spine>\n'
        '</package>\n'
    )
    files.append(("OEBPS/content.opf", opf))

    container = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<container version="1.0" '
        'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        '  <rootfiles>\n'
        '    <rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/>\n'
        '  </rootfiles>\n'
        '</container>\n'
    )
    files.append(("META-INF/container.xml", container))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if os.path.exists(OUT):
        os.remove(OUT)

    # Write the zip deterministically. mimetype MUST be first and stored.
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        zi = zipfile.ZipInfo("mimetype", date_time=FIXED_DATE)
        zi.compress_type = zipfile.ZIP_STORED
        z.writestr(zi, "application/epub+zip")
        for arc, text in sorted(files, key=lambda t: t[0]):
            zi = zipfile.ZipInfo(arc, date_time=FIXED_DATE)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, text)

    print(f"wrote {OUT} ({os.path.getsize(OUT)} bytes)")


if __name__ == "__main__":
    build()
