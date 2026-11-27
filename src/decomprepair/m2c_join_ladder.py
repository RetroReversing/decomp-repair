"""m2c's join ladder, its uninitialised saved register and its halfword read of a byte-declared table.

Measured on a 73-instruction N64 object update (SN gcc 2.8.1, `-G0 -mips3 -O2 -mgas`) whose machine draft stood at 1820.
The target dispatches on a byte field to one of four calls that return a byte, keeps the result in a saved register and
tests it once after the dispatch; the default path leaves the register unset. m2c wrote that as

    if (k == 0) { v = f(); goto block_9; }  ..  x = saved_reg_s2 & 0xFF;  if (k == 3) { v = h(); block_9: x = v & 0xFF; }

and read the halfword table through its own `extern u8` declaration as `(u16) *((k * 2) + table)`.

m2c_saved_register_local
    `saved_reg_s2` is m2c's name for a read of `$s2` before the function sets it. The local m2c named for the same
    register (`var_s2`, `temp_s2`) is that value, left unset on the path (1820 -> 670 alone).
m2c_goto_join_ladder
    `if (a) { A; goto L; } .. S; if (z) { B; L: S; }` as `if (a) { A; } else if .. else if (z) { B; } S;`, when the
    statement before the last `if` is the labelled one (here after the register rename, which the child includes:
    655). With the table read: 510.
m2c_halfword_byte_table
    `(u16) *((i * 2) + table)` with `table` declared `u8 []` reads one byte; the halfword load is
    `*(u16 *)((i * 2) + table)` (and `s16`, or a word with `* 4`). This changes what the C reads, back to the load the
    cast and the scale name.

From 510, `statement_slide` and `narrow_widening` reach 0. Candidate rewrites; the exact judge decides each.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

SAVED = 'm2c_saved_register_local'
LADDER = 'm2c_goto_join_ladder'
TABLE = 'm2c_halfword_byte_table'
FAMILIES = (SAVED, LADDER, TABLE)
LIMIT = 8

_SAVED_NAME = re.compile(r'\bsaved_reg_(s[0-7]|f\d{1,2}|fp)\b')
_IF = re.compile(r'(?<![\w])if\s*\(')
_CAST_LOAD = re.compile(r'\(\s*(?P<type>u16|s16|u32|s32)\s*\)\s*\*\s*\(')
_WIDTH = {'u16': 2, 's16': 2, 'u32': 4, 's32': 4}


def _same(left, right):
    return re.sub(r'\s+', '', left) == re.sub(r'\s+', '', right)


def _saved_register(body):
    """Each `saved_reg_X` read replaced by one local m2c named for register X."""
    clean = _blank(body)
    results = []
    for register in dict.fromkeys(_SAVED_NAME.findall(clean)):
        saved = f'saved_reg_{register}'
        if re.search(rf'\b{saved}\b\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|&\s*{saved}\b', clean):
            continue
        for local in dict.fromkeys(re.findall(rf'\b(?:var|temp)_{register}(?:_\d+)?\b', clean)):
            text = re.sub(rf'(?m)^[ \t]*[A-Za-z_]\w*[ \t*]+{saved};[ \t]*\n', '', body)
            results.append(re.sub(rf'\b{saved}\b', local, text))
    return results


def _blocks(clean):
    """{end: (start, condition, body start, body end)} for each `if (..) {..}` with no `else` after it."""
    found = {}
    for match in _IF.finditer(clean):
        condition_end = close(clean, match.end() - 1)
        if condition_end is None:
            continue
        brace = condition_end + len(clean[condition_end:]) - len(clean[condition_end:].lstrip())
        if not clean.startswith('{', brace):
            continue
        end = close(clean, brace, '{', '}')
        if end is None or re.match(r'\s*else\b', clean[end:]):
            continue
        found[end] = (match.start(), (match.end(), condition_end - 1), brace + 1, end - 1)
    return found


def _goto_join(body):
    """The ladder of arms that jump into the last arm's final statement, as an `else if` chain before that statement."""
    clean = _blank(body)
    blocks = _blocks(clean)
    results = []
    for end, (start, condition, inner, inner_end) in blocks.items():
        labelled = re.search(r'(?<![\w?])([A-Za-z_]\w*)\s*:(?!:)\s*([A-Za-z_][^;{}:?]*;)\s*$', clean[inner:inner_end])
        if not labelled:
            continue
        label = labelled[1]
        join = body[inner + labelled.start(2):inner + labelled.end(2)]
        target = re.match(r'([A-Za-z_]\w*)\s*=(?!=)', join)
        if label in ('case', 'default') or not target:
            continue
        before = clean[:start].rstrip()
        default_start = max(before[:-1].rfind(mark) for mark in ';{}') + 1
        if not before.endswith(';') or not _same(body[default_start:len(before)], join):
            continue
        arms, cursor = [], len(clean[:default_start].rstrip())
        while cursor in blocks:
            arm_start, arm_condition, arm_inner, arm_end = blocks[cursor]
            jump = re.search(rf'\bgoto\s+{label}\s*;\s*$', clean[arm_inner:arm_end])
            if not jump or re.match(r'.*\belse\s*$', clean[:arm_start], re.S):
                break
            arms.append((arm_start, arm_condition, (arm_inner, arm_inner + jump.start())))
            cursor = len(clean[:arm_start].rstrip())
        if not arms or len(arms) != len(re.findall(rf'\bgoto\s+{label}\b', clean)):
            continue
        arms.reverse()
        arms.append((start, condition, (inner, inner + labelled.start())))
        # the default's value must not be read on the way to the labelled statement
        read = ' '.join(clean[a:b] for _, cond, inside in arms for a, b in (cond, inside))
        if re.search(rf'\b{target[1]}\b', read) or re.search(r'(?<![?\w])\b[A-Za-z_]\w*\s*:(?!:)', read):
            continue
        indent = body[body.rfind('\n', 0, arms[0][0]) + 1:arms[0][0]]
        if indent.strip():
            indent = ''
        chain = []
        for _, (c0, c1), (a, b) in arms:
            statements = body[a:b].rstrip()
            chain.append(f'if ({body[c0:c1]}) {{{statements}\n{indent}}}')
        results.append(body[:arms[0][0]] + ' else '.join(chain) + f'\n{indent}{join}' + body[end:])
    return results


def _halfword_table(body, declarations):
    """`(u16) *(index * 2 + table)` over a byte array as the halfword load of that address."""
    clean = _blank(body)
    edits = []
    for match in _CAST_LOAD.finditer(clean):
        end = close(clean, match.end() - 1)
        if end is None:
            continue
        address = clean[match.end():end - 1]
        if not re.search(rf'\*\s*{_WIDTH[match["type"]]}\b', address):
            continue
        arrays = re.findall(r'(?:^\s*|\+\s*)([A-Za-z_]\w*)(?=\s*(?:\+|$))', address)
        if not any(re.search(rf'\bextern\s+(?:u8|s8)\s+{name}\s*\[', declarations) for name in arrays):
            continue
        edits.append((match.start(), end, f'*({match["type"]} *)({body[match.end():end - 1]})'))
    if not edits:
        return []
    groups = [[edit] for edit in edits] + ([edits] if len(edits) > 1 else [])
    results = []
    for group in groups:
        text = body
        for start, end, new in reversed(group):
            text = text[:start] + new + text[end:]
        results.append(text)
    return results


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    head, body, tail = source[:span[0]], source[span[0]:span[1]], source[span[1]:]
    renamed = _saved_register(body)
    children = [(SAVED, text) for text in renamed[:LIMIT]]
    for base in [body, *renamed[:LIMIT]]:
        children += [(LADDER, text) for text in _goto_join(base)]
    children += [(TABLE, text) for text in _halfword_table(body, f'{header}\n{source}')[:LIMIT]]
    return list(dict.fromkeys((family, head + text + tail) for family, text in children))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
