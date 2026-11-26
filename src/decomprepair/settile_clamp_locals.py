"""gDPSetTile words with the clamp fields as zero-valued locals, as the SDK macros spell them.

libultra's `gDPSetTile` builds the second word as `_SHIFTL(tile, 24, 3) | _SHIFTL(palette, 20, 4) | _SHIFTL(cmt, 18, 2) |
_SHIFTL(maskt, 14, 4) | _SHIFTL(shiftt, 10, 4) | _SHIFTL(cms, 8, 2) | _SHIFTL(masks, 4, 4) | _SHIFTL(shifts, 0, 4)`. A game
that passes its clamp modes as locals set to 0 at the top of the function (`cmt = cms = 0;`) keeps those fields in the
code: in a block that follows a join (a `x < 0x800 ? x : 0x7FF` clamp), cse no longer knows they are 0, so the target
ORs two registers holding 0 into the render tile's word (`move $s5, $zero; ... move $s6, $s5`, then `or $v0, $s5, $fp;
or $v0, $v0, $s6`), and a mip-map loop hoists the invariant fields into registers that cse2 then sets to 0 (copies of
the counter's 0). Drafts and saved bests drop the fields (they are 0), so those registers, and the extra pressure that
spills other values to the stack (a frame 8 bytes larger in the target), cannot come back.

A 606-instruction N64 texture loader (SN64 GCC 2.8.1, `-mfp64`): the fields written into every SetTile word (both
`0xF5...` commands of each format and the mip loop's) with `cmt = cms = 0;` at the top went 6779 -> 2575 on the way, and
7042 -> 0 as the last step (the matched source without the fields is this module's input; its child is exact); set inside
one case or before the loop instead it was 3745-10145, so the locals are set once, first. A matched neighbour of the
same game (a sibling loader) has exactly this spelling.

Children (`settile_clamp_locals`): every command whose first word is a `0xF5xxxxxx` constant (a macro call `G(gfx, w0,
w1)` / `CMD(w0, w1)`, or a `->w0 = ...;` store followed by its `->w1 = ...;`) and whose second word has a mask term
`(... << 14)` and `(... << 4)` but no `<< 18` / `<< 8` term gets `((cmt & 3) << 18) |` before the first and
`((cms & 3) << 8) |` before the second (an OR chain inside parentheses is searched too); the locals are declared after
the function's declarations and set by `cmt = cms = 0;` (a second child: `cms = cmt = 0;`) as the first statement.
Nothing is offered when the function already names `cmt` or `cms`, or no command qualifies.
"""
import re

from . import c_scan
from .csource import _blank, find

FAMILY = 'settile_clamp_locals'
FAMILIES = (FAMILY,)
SETTILE = re.compile(r'0[xX][fF]5[0-9A-Fa-f]{6}\b')
CALL = re.compile(r'\b([A-Za-z_]\w*)\s*\(')
W0 = re.compile(r'(?:->|\.)\s*w0\s*=\s*([^;]*);')
W1 = re.compile(r'\s*[^;{}]*?(?:->|\.)\s*w1\s*=\s*([^;]*);')
MASKT = re.compile(r'<<\s*14\s*\)$')
MASKS = re.compile(r'<<\s*4\s*\)$')
DECLARATION = re.compile(r'[ \t]*(?!(?:return|goto|break|continue|else|case|default|sizeof|do|if|for|while|switch)\b)'
                         r'(?:(?:unsigned|signed|const|volatile|register|static|struct|union|enum)\s+)*[A-Za-z_]\w*[ \t]+'
                         r'\**[ \t]*[A-Za-z_]\w*(?:\[[^\]\n]*\])*[ \t]*(?:[=,][^;\n]*)?;[ \t]*')


def variants(source, name):
    return [(FAMILY, text) for text in rewrites(source, name)]


def _split(expr, sep):
    """(start, end) spans of the top-level operands of `expr` split at `sep` (`,` or a single `|`), or None."""
    spans, at, i = [], 0, 0
    while i < len(expr):
        c = expr[i]
        if c in '([':
            close = c_scan.close(expr, i, c, ')' if c == '(' else ']')
            if close < 0:
                return None
            i = close + 1
            continue
        if c == sep and (sep != '|' or (expr[i + 1:i + 2] != '|' and expr[i - 1:i] != '|')):
            spans.append((at, i))
            at = i + 1
        i += 1
    spans.append((at, len(expr)))
    return spans


def _insertions(expr, base=0):
    """Offsets in `expr` (plus `base`) where the cmt and cms terms go: [(offset, 'cmt'|'cms')]."""
    spans = _split(expr, '|')
    if not spans:
        return []
    found = []
    for a, b in spans:
        part = expr[a:b]
        text = part.strip()
        if not text:
            return []
        lead = a + len(part) - len(part.lstrip())
        if MASKT.search(text):
            found.append((base + lead, 'cmt'))
        elif MASKS.search(text):
            found.append((base + lead, 'cms'))
        elif text.startswith('(') and c_scan.close(text, 0, '(', ')') == len(text) - 1:
            inner = text[1:-1]
            if _split(inner, '|') and len(_split(inner, '|')) > 1:
                found.extend(_insertions(inner, base + lead + 1))
    return found


def _word_sites(body, base):
    """(start, end) spans, in the whole source, of second words whose command's first word is a SetTile constant."""
    sites = []
    for m in CALL.finditer(body):
        opening = m.end() - 1
        close = c_scan.close(body, opening, '(', ')')
        if close < 0:
            continue
        args = _split(body[opening + 1:close], ',')
        if not args or len(args) < 2:
            continue
        for k in range(len(args) - 1):
            a, b = args[k]
            if SETTILE.search(body[opening + 1 + a:opening + 1 + b]):
                c, d = args[k + 1]
                sites.append((base + opening + 1 + c, base + opening + 1 + d))
                break
    for m in W0.finditer(body):
        if not SETTILE.search(m.group(1)):
            continue
        n = W1.match(body, m.end())
        if n:
            sites.append((base + n.start(1), base + n.end(1)))
    return sites


def _first_statement(clean, opening, end):
    """Offset of the first line after the declarations that open the body."""
    at = clean.find('\n', opening) + 1
    while 0 < at < end:
        line_end = clean.find('\n', at)
        line_end = end if line_end < 0 or line_end > end else line_end
        line = clean[at:line_end]
        if line.strip() == '' or DECLARATION.fullmatch(line):
            at = line_end + 1
        else:
            break
    return at


def rewrites(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    start, end = span
    opening = clean.find('{', start, end)
    if opening < 0:
        return []
    close = c_scan.close(clean, opening, '{', '}')
    if close < 0:
        return []
    body = clean[opening:close]
    if re.search(r'\b(?:cmt|cms)\b', clean[start:close]):
        return []
    edits = []
    for a, b in _word_sites(body, opening):
        word = clean[a:b]
        if re.search(r'<<\s*(?:18|8)\s*\)', word):
            continue
        found = _insertions(word, a)
        kinds = [kind for _, kind in found]
        if kinds.count('cmt') != 1 or kinds.count('cms') != 1:
            continue
        edits.extend(found)
    if not edits:
        return []
    text = source
    for at, kind in sorted(edits, reverse=True):
        term = '((cmt & 3) << 18) | ' if kind == 'cmt' else '((cms & 3) << 8) | '
        text = text[:at] + term + text[at:]
    first = _first_statement(_blank(text), opening, close)
    if first <= opening:
        return []
    indent = re.match(r'[ \t]*', text[first:]).group() or '    '
    out = []
    for init in ('cmt = cms = 0;', 'cms = cmt = 0;'):
        out.append(text[:first] + f'{indent}s32 cms;\n{indent}s32 cmt;\n\n{indent}{init}\n' + text[first:])
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60}  # the registry: no caller wiring (registry.py)
