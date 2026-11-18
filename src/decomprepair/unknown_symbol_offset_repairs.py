"""Byte offsets m2c added to symbols of unknown type, scaled again by the type the draft gave them.

m2c writes `*(&D_800C0784 + temp)` for a symbol it knows nothing about, with `temp` counted in bytes. Drafts declare
such a symbol `extern M2C_UNK D_800C0784;` (`M2C_UNK` is `s32`), so C multiplies the offset by 4 once more: a table of
16-byte records indexed by `arg2 * 0x10` compiled to `sll 6` where the game has `sll 4`. Two rewrites, both with the
offset m2c meant, the compiler deciding between them:
- element offsets: the byte multiplier divided by the symbol's size (`arg2 * 0x10` -> `arg2 * 4`), in place or in
  the one assignment of a temporary used only as such an offset. An N64 game's function matched this way.
- byte offsets: `*(M2C_UNK *)((s8 *)&D + temp)`, also with the temporary folded into each use.
Only symbols the source itself declares `M2C_UNK`, `M2C_UNK32` or `M2C_UNK16`; an offset that isn't a multiple of
the size gets the byte form only.
"""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT
from .pattern_repairs import close

FAMILY = 'unknown_symbol_offsets'
FAMILIES = (FAMILY,)
SIZES = {'M2C_UNK': 4, 'M2C_UNK32': 4, 'M2C_UNK16': 2}
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)'


def _number(text):
    return int(text, 0)


def _like(original, value):
    return hex(value) if original.lower().startswith('0x') else str(value)


def _scaled(expression, size):
    """`expression` (a byte count) in elements of `size` bytes, or None when it isn't plainly a multiple."""
    text = expression.strip()
    while text.startswith('(') and close(text, 0) == len(text):
        text = text[1:-1].strip()
    if re.fullmatch(NUMBER, text):
        value = _number(text)
        return _like(text, value // size) if value % size == 0 else None
    hit = re.fullmatch(r'(.+?)\s*\*\s*(' + NUMBER + r')', text, re.S)
    if hit and _number(hit[2]) % size == 0 and not re.search(r'[+\-<>&|^?:,]', hit[1].replace('->', '')):
        factor = _number(hit[2]) // size
        return hit[1] if factor == 1 else f'{hit[1]} * {_like(hit[2], factor)}'
    hit = re.fullmatch(r'(.+?)\s*<<\s*(' + NUMBER + r')', text, re.S)
    shift = {4: 2, 2: 1}[size]
    if hit and _number(hit[2]) >= shift and not re.search(r'[+\-<>&|^?:,*/]', hit[1].replace('->', '')):
        rest = _number(hit[2]) - shift
        return hit[1] if rest == 0 else f'{hit[1]} << {rest}'
    return None


def _sites(clean, body_start, body_end, symbols):
    """Each `&SYM + E` the body has, inside its own parentheses: (symbol, size, start of `&`, E start, E end)."""
    found = []
    pattern = r'\(\s*&\s*(' + '|'.join(map(re.escape, symbols)) + r')\s*\+'
    for hit in re.finditer(pattern, clean[body_start:body_end]):
        opening = body_start + hit.start()
        end = close(clean, opening)
        if not end:
            return None
        amp = clean.rfind('&', opening, body_start + hit.start(1))
        found.append((hit[1], symbols[hit[1]], amp, body_start + hit.end(), end - 1))
    return found


def _edit(source, edits):
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    declared = {m[2]: m[1] for m in re.finditer(r'(?m)^[ \t]*extern\s+(M2C_UNK(?:32|16)?)\s+(' + IDENT + r')\s*;',
                                                        clean[:span[0]] + clean[span[1]:])}
    symbols = {symbol: SIZES[kind] for symbol, kind in declared.items()}
    if not symbols:
        return []
    sites = _sites(clean, opening + 1, span[1], symbols)
    if not sites:
        return []
    body = clean[opening + 1:span[1]]
    element, byte, folded = [], [], []
    temps = {}
    usable = True
    for symbol, size, amp, low, high in sites:
        offset = clean[low:high].strip()
        lead = low + len(clean[low:high]) - len(clean[low:high].lstrip())
        byte.append((amp, high, f'({declared[symbol]} *)((s8 *)&{symbol} + {source[lead:high].strip()})'))
        if re.fullmatch(IDENT, offset):
            temps.setdefault(offset, set()).add(size)
            continue
        scaled = _scaled(source[lead:high], size)
        if scaled is None:
            usable = False
        else:
            element.append((lead, high, scaled))
    fold_byte = list(byte)
    for temp, sizes in temps.items():
        writes = list(re.finditer(r'(?<![\w.>])' + temp + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*' + temp + r'\b|\b'
                                  + temp + r'\s*(?:\+\+|--)', body))
        uses = len(re.findall(r'\b' + temp + r'\b', body))
        offsets = sum(1 for _, _, _, low, high in sites if clean[low:high].strip() == temp)
        declarations = len(re.findall(r'\b' + IDENT + r'\s+' + temp + r'\s*;', body))
        plain = re.match(temp + r'\s*=\s*([^;]+);', body[writes[0].start():]) if len(writes) == 1 else None
        if len(sizes) != 1 or not plain or uses != offsets + 1 + declarations:
            usable = False  # used elsewhere too, or assigned more than once: its value must stay as it is
            continue
        value_start = opening + 1 + writes[0].start() + plain.start(1)
        value_end = opening + 1 + writes[0].start() + plain.end(1)
        scaled = _scaled(source[value_start:value_end], sizes.pop())
        if scaled is None:
            usable = False
        else:
            element.append((value_start, value_end, scaled))
        # Folding the temporary into its uses: only values of names nothing in the function assigns, and no calls.
        value = source[value_start:value_end]
        names = set(re.findall(r'(?<!\w)' + IDENT, value))  # (not the `x10` of `0x10`)
        if not re.search(r'\(\s*' + IDENT + r'\s*\(|' + IDENT + r'\s*\(', value) and not any(
                re.search(r'(?<![\w.>])' + n + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*' + n + r'\b|\b' + n
                          + r'\s*(?:\+\+|--)', body) for n in names):
            statement_start = opening + 1 + writes[0].start()
            statement_end = opening + 1 + writes[0].start() + plain.end()
            line_start = source.rfind('\n', 0, statement_start) + 1
            line_end = source.find('\n', statement_end)
            whole = source[line_start:statement_start].strip() == '' and source[statement_end:line_end].strip() == ''
            fold_byte = [(a, b, t.replace(f'+ {temp})', f'+ ({value}))')) for a, b, t in fold_byte]
            fold_byte.append((line_start, line_end + 1, '') if whole else (statement_start, statement_end, ''))
            folded.append(temp)
    result = []
    if usable and element:
        result.append((FAMILY, _edit(source, element)))
    result.append((FAMILY, _edit(source, byte)))
    if folded:
        result.append((FAMILY, _edit(source, fold_byte)))
    return result
