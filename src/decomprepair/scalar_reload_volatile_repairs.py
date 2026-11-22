"""A scalar global the game stored and then read back from memory: declared `volatile`.

gcc forwards a stored value to the read that follows (`sh $v0, G` and the argument `G` taken from `$v0`); a game whose
header declared the global `volatile` (a flag another thread or an interrupt writes) loads it again (`lui $a0,
%hi(G); lhu $a0, %lo(G)($a0)`) and the value kept in its register keeps another register. A KMC gcc 2.7.2 save-menu
function that stored a menu action and passed it to the next call was 30 (the value in `$a0` instead of `$v0`) and
exact with `extern volatile u16 G;` once the switch arms stored once at the join. `volatile` only adds loads, so the
meaning stays; the family offers it for each extern scalar global (never a pointer, array or one whose address is
taken) that the function assigns and reads again later, one global at a time, and all of them together.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'scalar_reload_volatile'
FAMILIES = (FAMILY,)

SCALAR = (r'(?:(?:unsigned|signed|const)\s+)*(?:u8|s8|u16|s16|u32|s32|u64|s64|f32|f64|int|short|char|long|float|double|'
          r'unsigned|signed|bool|size_t)(?:\s+(?:int|long|char|short))*')
EXTERN = re.compile(r'(?m)^[ \t]*extern\s+(?P<type>' + SCALAR + r')\s+(?P<g>[A-Za-z_]\w*)\s*;')


def _reloaded(body, glob):
    """True when `glob` is assigned and read again afterwards (a plain read, not an assignment's left side)."""
    word = re.compile(r'\b' + re.escape(glob) + r'\b')
    stored, read_after = False, False
    for m in word.finditer(body):
        before = body[:m.start()].rstrip()
        if before.endswith(('&', '.', '->')) or re.match(r'\s*\[', body[m.end():]):
            return False
        store = re.match(r'\s*(?:[-+*/|&^%]|<<|>>)?=(?!=)', body[m.end():]) and not before.endswith(('*', '('))
        if store:
            stored = True
        elif stored:
            read_after = True
    return stored and read_after


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    found = []
    for decl in EXTERN.finditer(clean, 0, span[0]):
        if 'volatile' in decl['type'] or re.search(r'(?m)^[ \t]*#\s*define[^\n]*\b' + decl['g'] + r'\b', clean):
            continue
        if _reloaded(body, decl['g']):
            found.append(decl)
    found = found[:4]

    def apply(decls):
        text = source
        for decl in sorted(decls, key=lambda d: -d.start('type')):
            text = text[:decl.start('type')] + 'volatile ' + text[decl.start('type'):]
        return text
    result = [(FAMILY, apply([d])) for d in found]
    if len(found) > 1:
        result.append((FAMILY, apply(found)))
    return result
