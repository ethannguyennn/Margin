"""Glyph sanitizer for the G2 lens.

Mirror of the app's ``app/src/ui/glyphs.ts`` (``sanitizeForG2``). Both suites
run the same fixtures (``relay/tests/fixtures/glyph_cases.json``), so any rule
change here must land in the app in the same breath.

The G2 renders one firmware font and silently drops every glyph outside it, so
a torque spec written as "4 N·m" would reach the lens as "4 N m" at best and
"4 -m" at worst. Everything is mapped to ASCII except the small allow-list of
box/arrow/meter glyphs the lens UI draws with.
"""

from __future__ import annotations

# Non-ASCII code points that the G2 firmware font renders. Kept as one constant
# so it can be narrowed after hardware testing.
G2_ALLOWED_NON_ASCII: frozenset[str] = frozenset(
    chr(cp)
    for cp in (
        0x25B2, 0x25B3, 0x25B6, 0x25B7, 0x25BC, 0x25BD, 0x25C0, 0x25C1,
        0x25CF, 0x25CB, 0x25A0, 0x25A1, 0x2605, 0x2606,
        0x2501, 0x2500, 0x2588, 0x2587, 0x2586, 0x2585, 0x2584, 0x2583, 0x2582, 0x2581,
        0x256D, 0x256E, 0x256F, 0x2570, 0x2502,
    )
)

REPLACEMENTS: dict[str, str] = {
    "§": "Sec ",  # section sign
    "·": "-",     # middle dot
    "•": "-",     # bullet
    "°": " deg",  # degree sign
    "µ": "u",     # micro sign
    "Ω": " ohm",  # ohm sign
    "–": "-",     # en dash
    "—": "-",     # em dash
    "“": '"',     # left double quote
    "”": '"',     # right double quote
    "‘": "'",     # left single quote
    "’": "'",     # right single quote
    "×": "x",     # multiplication sign
    "±": "+/-",   # plus-minus sign
    "≥": ">=",    # greater-than or equal
    "≤": "<=",    # less-than or equal
    "→": "->",    # right arrow
}


def sanitize(text: str) -> str:
    """Return ``text`` with every glyph the G2 cannot render mapped or dropped.

    Character by character over code points, no Unicode normalization and no
    whitespace changes, so the app can reproduce it byte for byte.
    """
    out: list[str] = []
    for ch in text:
        if ch < "\x80" or ch in G2_ALLOWED_NON_ASCII:
            out.append(ch)
        else:
            out.append(REPLACEMENTS.get(ch, ""))
    return "".join(out)
