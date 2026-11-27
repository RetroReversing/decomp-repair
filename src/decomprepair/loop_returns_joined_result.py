"""A loop that leaves the function by several `return`s, written to leave it at one `return` through a result local.

m2c writes each exit of a `for (;;)` search loop as its own `return`; the compiler then ends each with its own copy of
the epilogue and keeps a call's result where the call left it. Where the target joins every exit at one tail the result
passes through a register the tail reads (`move $s0,$v0` after the call), and the source was

    s32 ret = 0;
    for (;;) { ...  if (c) { ret = f(); goto done; }  if (d) { goto done; } }
    done: return ret;

On an N64 function (KMC GCC 2.7.2 `-G0 -mips3 -mgp32 -mfp32 -O1`, a two-exit read loop, 200 points with its copy fence
removed) writing both exits that way was exact.

loop_returns_joined_result
    In a function with a scalar result type and a loop, every `return E;` that ends a braced block (two or more of
    them) becomes `ret = E;` and `goto done;`, `done: return ret;` closes the body, and `ret` is declared after the
    function's leading declarations, initialised to 0 in one child and bare in another, and in a child per literal an exit returns (two at most) initialised
    to it with that exit just leaving (`goto done;`). The locals' names are fresh.
    A function with a `return` that is not the last thing in its block (braceless `if`), a `switch`, or no loop is
    left alone. The judge decides each child.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close as _close

FAMILY = 'loop_returns_joined_result'
FAMILIES = (FAMILY,)
RETURN = re.compile(r'\breturn\b\s*(?P<e>[^;]*?)\s*;')
LOOP = re.compile(r'\b(?:for|while|do)\b')
DECL = re.compile(r'(?:(?:unsigned|signed|const|struct|volatile)\s+)*(?!return\b|goto\b|else\b|break\b|continue\b)'
                  r'[A-Za-z_]\w*[\s*]+[A-Za-z_]\w*\s*(?:\[[^\]]*\])?\s*(?:=[^;]*)?;')
TYPE = re.compile(r'(?:^|[;}])\s*(?P<t>(?:(?:unsigned|signed|static|const)\s+)*(?:u8|u16|u32|s8|s16|s32|int|short|char|long|'
                  r'unsigned|f32)(?:\s+(?:int|char|short|long))?|[A-Za-z_]\w*\s*\*+)\s+$')


def _fresh(text, base):
    name, n = base, 0
    while re.search(rf'\b{name}\b', text):
        n += 1
        name = f'{base}_{n}'
    return name


INTEGERS = r'(?:u8|u16|u32|s8|s16|s32|int|char|short|unsigned|signed)'
FENCE = re.compile(rf'(?P<a>{IDENT})\s*=\s*(?P<src>{IDENT})\s*;\s*do\s*\{{\s*(?P<c>{IDENT})\s*=\s*(?P=a)\s*;')


def _unfenced(source, name):
    """`a = x; do { c = a; BODY } while (0);` (the scaffold a copy fence leaves) as BODY with `x` for `c` and `a`: the
    fence and its two copies are a weight-scope probe, not source. None when there is no such fence or `a` and `c`
    are read elsewhere."""
    part = view(source, name)
    hit = part and FENCE.search(part.clean, part.opening, part.end)
    if not hit:
        return None
    opening = hit.start() + hit.group(0).index('{')
    end = _close(part.clean, opening, '{', '}')
    tail = re.compile(r'\s*while\s*\(\s*0\s*\)\s*;').match(part.clean, end) if end else None
    if not tail:
        return None
    body = source[hit.end():end - 1]
    rest = part.clean[:hit.start()] + part.clean[tail.end():part.end]
    rest = re.sub(rf'\b{INTEGERS}\s+\w+\s*;', '', rest)  # their declarations stay
    if any(re.search(rf'\b{n}\b', rest) for n in (hit['a'], hit['c'])):
        return None
    for n in (hit['a'], hit['c']):
        body = re.sub(rf'\b{n}\b', hit['src'], body)
    return source[:hit.start()] + body.strip() + source[tail.end():]


def variants(source, name):
    unfenced = _unfenced(source, name)
    if unfenced:
        source = unfenced
    part = view(source, name)
    if not part or not part.body.strip() or re.search(r'\bswitch\b', part.body):
        return []
    clean = part.clean
    head = re.search(rf'\b{re.escape(name)}\s*\(', clean)
    kind = head and TYPE.search(clean[:head.start()] + ' ')
    if not kind or not LOOP.search(part.body):
        return []
    rtype = ' '.join(kind['t'].split())
    if rtype in ('static',) or re.search(r'\b(?:void)\b', rtype):
        return []
    returns = list(RETURN.finditer(clean, part.opening + 1, part.end - 1))
    if len(returns) < 2:
        return []
    for hit in returns:
        before = clean[part.opening + 1:hit.start()].rstrip()
        if not before or before[-1] not in ';{}':
            return []
        after = clean[hit.end():part.end].lstrip()
        if not after or after[0] != '}':
            return []
        if not hit['e']:
            return []
    ret = _fresh(clean, 'ret')
    done = _fresh(clean, 'done')
    # after the leading declarations
    at = part.opening + 1
    while True:
        skip = re.compile(r'\s*').match(clean, at).end()
        decl = DECL.match(clean, skip)
        if not decl:
            break
        at = decl.end()
    edits = [(hit.start(), hit.end(), f'{ret} = {hit["e"]}; goto {done};') for hit in returns]
    close = clean.rfind('}', 0, part.end)
    tail = (close, close, f'{done}:\n    return {ret};\n')
    out = []
    for init in (' = 0', ''):
        out.append(edit(source, edits + [(at, at, f'\n    {rtype} {ret}{init};'), tail]))
    # the result starts at a literal an exit returns, and that exit just leaves: `ret = 0; ... goto done;`
    literals = dict.fromkeys(hit['e'] for hit in returns if re.fullmatch(NUMBER, hit['e']))
    for literal in list(literals)[:2]:
        kept = [(hit.start(), hit.end(), f'goto {done};' if hit['e'] == literal else f'{ret} = {hit["e"]}; goto {done};')
                for hit in returns]
        out.append(edit(source, kept + [(at, at, f'\n    {rtype} {ret} = {literal};'), tail]))
    return [(FAMILY, child) for child in dict.fromkeys(out)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
