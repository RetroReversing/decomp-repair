"""A constant staged through a reused local, and a scalar extern indexed through its address.

Two spellings that hide each other. A hand search on a near-miss keeps a literal in a local the function uses again
for something else (`t = 0x190; p->f = t;` in one arm, `t = p->f;` in another): the one name is one pseudo for the
whole function, so the literal gets another register than the target's. And m2c names a table it saw no type for as a
scalar and indexes its address (`extern M2C_UNK D; ... (&D)[i]`), which folds the address into a different order than
the array the game declared (`extern s32 D[]; ... D[i]`). On one SN GCC 2.8.1 function either edit alone was worse
than the 30 it started from (the literal inlined: 80, the array: 205) and the two together were exact, so they are
also offered as one child. docs: decompdecomp docs/learnings, "staged constant and array extern".

Nothing here changes what the program does: the literal is only moved when every other read of the local follows an
assignment of its own in a block around the read, and `(&D)[i]`, `*(&D + i)` and `D[i]` of an array are the same
access.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILIES = ('staged_constant_inline', 'address_index_array', 'staged_constant_array_index')
STAGED, ARRAY_INDEX, BOTH = FAMILIES
LIMIT = 6
_IDENT = r'[A-Za-z_]\w*'
_WIDE = r'(?:s32|u32|int|unsigned int|unsigned|M2C_UNK|long)'
_NUMBER = r'-?(?:0[xX][0-9a-fA-F]+|\d+)'
_SCALAR_ELEMENT = {'M2C_UNK': 's32', 's32': 's32', 'u32': 'u32', 'int': 'int', 's16': 's16', 'u16': 'u16', 's8': 's8',
                   'u8': 'u8', 'f32': 'f32', 'float': 'float'}


def _body(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    return (clean, span, opening, end) if end else None


def _dominated(clean, opening, at, local):
    """Whether the read at `at` follows a plain assignment of `local` in a block around it, with no label between."""
    assigns = re.compile(r'\s*' + local + r'\s*=(?!=)')
    depth = 0
    for i in range(at - 1, opening - 1, -1):
        ch = clean[i]
        if ch not in '{;}':
            continue
        if not depth:
            found = assigns.match(clean, i + 1)
            # the assignment's own statement has ended before the read (`t = t + 1` reads the value from before it)
            done = clean.find(';', found.end()) if found else -1
            if 0 <= done < at:
                return not re.search(r'\b(?:case|default)\b|^\s*' + _IDENT + r'\s*:(?!:)', clean[done:at], re.M)
        if ch == '}':
            depth += 1
        elif ch == '{' and depth:
            depth -= 1
    return False


def _staged(source, name):
    """`(start, end, text)` edits for every `t = K; X = t;` whose local nothing else needs K from."""
    body = _body(source, name)
    if not body:
        return []
    clean, _, opening, end = body
    text = clean[opening:end]
    if re.search(r'\bgoto\b', text):
        return []
    edits = []
    pattern = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<local>' + _IDENT + r')\s*=\s*(?P<value>' + _NUMBER + r')\s*;\s*?\n'
                         r'[ \t]*(?P<target>[^;{}\n]+?)\s*(?<![=!<>+\-*/&|^])=\s*(?P=local)\s*;')
    for hit in pattern.finditer(clean, opening, end):
        local = hit['local']
        declared = re.search(r'(?m)^[ \t]+(?:register[ \t]+)?' + _WIDE + r'[ \t]+' + local + r'[ \t]*;[ \t]*\n', text)
        if not declared or re.search(r'&\s*' + local + r'\b', text):
            continue
        if re.search(r'\b' + local + r'\b', hit['target']) or not clean[opening:hit.start()].rstrip().endswith(('{', ';', '}')):
            continue
        decl = (opening + declared.start(), opening + declared.end())
        others = [m for m in re.finditer(r'(?<![\w.>])' + local + r'\b', text)
                  if not (hit.start() <= opening + m.start() < hit.end()) and not (decl[0] <= opening + m.start() < decl[1])]
        reads = [m for m in others if not re.match(r'\s*=(?!=)', text[m.end():])]
        if not all(_dominated(clean, opening, opening + m.start(), local) for m in reads):
            continue
        target = source[hit.start('target'):hit.end('target')]
        found = [(hit.start(), hit.end(), f"{hit['indent']}{target} = {hit['value']};")]
        if not others:
            found.append((decl[0], decl[1], ''))
        edits.append(found)
    return edits


def _apply(source, edits):
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source


def _arrays(source):
    """The source with each scalar extern that is only indexed through its address declared as an array."""
    clean = _blank(source)
    result = []
    declarations = re.finditer(r'(?m)^[ \t]*extern\s+(?P<type>' + _IDENT + r')\s+(?P<name>' + _IDENT + r')\s*;', clean)
    for decl in declarations:
        symbol = decl['name']
        if decl['type'] not in _SCALAR_ELEMENT:
            continue
        uses = [m for m in re.finditer(r'(?<![\w.>])' + symbol + r'\b', clean) if m.start() != decl.start('name')]
        edits = []
        for use in uses:
            indexed = None
            before = re.search(r'\(\s*&\s*$', clean[:use.start()])
            after = re.match(r'\s*\)(?=\s*\[)', clean[use.end():])
            if before and after:
                indexed = (before.start(), use.end() + after.end(), symbol)
            else:
                before = re.search(r'\*\s*\(\s*&\s*$', clean[:use.start()])
                after = re.match(r'\s*\+\s*(' + _IDENT + r')\s*\)', clean[use.end():])
                if before and after:
                    indexed = (before.start(), use.end() + after.end(), f'{symbol}[{after[1]}]')
            if not indexed:
                break
            edits.append(indexed)
        else:
            if edits:
                edits.append((decl.start('type'), decl.end('name'),
                              f"{_SCALAR_ELEMENT[decl['type']]} {symbol}[]"))
                result.append(edits)
    return result


def variants(source, name):
    result = []

    def emit(family, text):
        if text != source and text not in [t for _, t in result] and len(result) < LIMIT * 3:
            result.append((family, text))

    staged = _staged(source, name)
    inlined = [_apply(source, edits) for edits in staged[:LIMIT]]
    for text in inlined:
        emit(STAGED, text)
    if not find(source, name):
        return result
    arrays = _arrays(source)
    for edits in arrays[:LIMIT]:
        emit(ARRAY_INDEX, _apply(source, edits))
    if len(arrays) > 1:
        emit(ARRAY_INDEX, _apply(source, [edit for edits in arrays for edit in edits]))
    for text in inlined:
        for edits in _arrays(text)[:LIMIT]:
            emit(BOTH, _apply(text, edits))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry (registry.py)
