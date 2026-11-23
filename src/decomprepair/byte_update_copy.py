"""A byte local updated by one `if` and stored, updated through a second byte local of its own.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) scroll-window update that stood at 905: a loop re-read a
byte member into the local `selected` at its bottom (`selected = w->selected;`) and compared it with the counter, and
in the loop's exit arm `if (i <= selected) selected = i; w->selected = selected;` lowered it. Because that one local was
both the loop-carried value and the one assigned `i`, the compiler masked it (`andi $v1,$v1,0xff`) at every compare and
kept the guard of the loop as a real compare. The target keeps the loaded byte unmasked (the guard is a constant
`move $v0,$zero`) and writes the lowered value through another register: a second byte local for the update
(`m = selected; if (i <= m) m = i; w->selected = m;`) took the score from 905 to 465 (the register file of the loop and
its exit arm then matched).

byte_update_copy
    `if (c(v)) v = e; dst = v;` for a narrow (`u8`, `s8`, `u16`, `s16`) local `v` that `e` does not read becomes `w = v;
    if (c(w)) w = e; dst = w;` with a new local `w` of the same type, and also (second child) with the condition left on
    `v`. Offered only when `v` is not read between the update and the store. Hypothesis from the match, not from the
    compiler source: a narrow pseudo set from a `subreg` of a wider value in one place and from a load in another loses
    the compiler's knowledge that it is zero-extended; a second pseudo keeps the load's.

The exact judge decides every child; nothing here proves it is the compiler's reason.
"""
import re

from .integer_repair_support import IDENT, INTEGER, edit, view
from .pattern_repairs import close

FAMILY = 'byte_update_copy'
FAMILIES = (FAMILY,)
LIMIT = 6
_NARROW = {'u8', 's8', 'u16', 's16', 'char', 'short', 'unsigned char', 'unsigned short', 'signed char'}
_DECL = rf'(?m)^[ \t]*(?P<type>{INTEGER})\s+(?P<names>{IDENT}(?:\s*,\s*{IDENT})*)\s*;'


def _names(text, name):
    """The occurrences of the local `name`, not the members that happen to be called that."""
    return [m for m in re.finditer(rf'\b{re.escape(name)}\b', text) if not re.search(r'(?:->|\.)\s*$', text[:m.start()])]


def _fresh(part, v):
    taken = set(re.findall(IDENT, part.clean[part.opening:part.end]))
    return next((c for c in (f'{v}_copy', f'{v}_update', 'copy') if c not in taken), None)


def _narrow_local(part, v):
    base = part.opening + 1
    for hit in re.finditer(_DECL, part.clean[base:part.end]):
        if v in re.split(r'\s*,\s*', hit['names']) and re.sub(r'\s+', ' ', hit['type']) in _NARROW:
            return base + hit.end(), re.sub(r'\s+', ' ', hit['type']), base + hit.start()
    return None


def _children(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|goto|asm|__asm__)\b', part.body):
        return []
    clean, result = part.clean, []
    for head in re.finditer(r'\bif\s*\(', clean[part.opening + 1:part.end]):
        start = part.opening + 1 + head.start()
        stop = close(clean, start + head.group(0).index('('))
        if stop is None or re.search(r'\belse\b\s*$', clean[:start]):
            continue
        condition = clean[start + head.group(0).index('(') + 1:stop - 1]
        update = re.compile(rf'\s*(?:\{{\s*)?(?P<v>{IDENT})\s*=(?!=)\s*(?P<e>[^;{{}}]+?)\s*;\s*(?:\}}\s*)?').match(clean, stop)
        if not update:
            continue
        v, e = update['v'], update['e'].strip()
        if re.compile(r'\s*else\b').match(clean, update.end()):
            continue
        store = re.compile(rf'\s*(?P<dst>[^;={{}}\n]+?)\s*=\s*{re.escape(v)}\s*;').match(clean, update.end())
        local = _narrow_local(part, v)
        fresh = _fresh(part, v)
        if (not store or not local or not fresh or _names(e, v) or not _names(condition, v)
                or '==' in store['dst'] or re.search(r'[<>!]', store['dst'].replace('->', ''))
                or re.search(IDENT + r'\s*\(|\+\+|--|[^=!<>]=[^=]', condition)):
            continue
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:start])[0]
        braced = clean[stop:update.start('v')].count('{')
        close_brace = ' }' if braced else ''
        open_brace = '{ ' if braced else ''
        end = store.end()
        for rewritten in (_swap(condition, v, fresh), condition):
            text = (f'{fresh} = {v};\n{indent}if ({rewritten}) {open_brace}{fresh} = {e};{close_brace}\n'
                    f'{indent}{store["dst"].strip()} = {fresh};')
            end_of_decl, kind, decl_start = local
            edits = [(start, end, text), (end_of_decl, end_of_decl, f'\n{_indent(source, decl_start)}{kind} {fresh};')]
            result.append((FAMILY, edit(source, edits)))
    return result[:LIMIT]


def _swap(condition, v, fresh):
    out, last = [], 0
    for m in _names(condition, v):
        out.append(condition[last:m.start()])
        out.append(fresh)
        last = m.end()
    out.append(condition[last:])
    return ''.join(out)


def _indent(source, position):
    return re.match(r'[ \t]*', source[source.rfind('\n', 0, position) + 1:position])[0]


def variants(source, name):
    return _children(source, name)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
