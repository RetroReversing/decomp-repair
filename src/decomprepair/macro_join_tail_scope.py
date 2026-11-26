"""A brace macro split at its last internal branch, its tail wrapped with the rest of the arm in a one-shot scope.

GCC 2.x ranks the saved registers by `floor_log2(refs) * refs / live_length` (global.c), counts each reference once more
per loop it sits in (flow.c: `REG_N_REFS += loop_depth`), and doubles the live length of a pseudo that is set once to a
constant (local-alloc.c `update_equiv_regs`: `REG_LIVE_LENGTH (regno) *= 2` for a REG_EQUIV constant). A constant local
such as a texture mask (`mask = 0;` read by every arm's tile command after a join) therefore ranks below a value read
far less often, and only more references move it. `do { } while (0)` adds them at no instruction cost, but it is also a
scheduling boundary: wrapped in the middle of a display-list arm it breaks the interleaved stores (3000 points worse).
Where a block boundary already exists it costs nothing. A statement macro whose body has a conditional (`MAX`/`MIN`, a
`?:` in `CALC_DXT`) ends a basic block inside the macro: the statements after it start at a join label. The wrapper fits
exactly there, from the first statement after the macro's last conditional to the end of the arm.

A 638-instruction N64 texture loader (sn-n64-281 GCC 2.8.1, `-G0 -mips3 -O2 ... -mfp64`; libultra-style
`gDPLoadTextureBlock` macros in five arms, `cm = 2; mask = 0;` locals) sat at 75 with only the mask and the type
exchanged between `$s5` and `$s6` (mask 6 references over a doubled live length, 110, against the type's 214). Splitting
the load macro after its `LoadBlock` (whose `MIN`/`CALC_DXT` branch) and wrapping the tail of the palette arm with its
`LoadTLUT` and call, plus the arm's enclosing `if (pal != NULL) ... else ...`, gave the mask 9 references (248) while the
palette pointer gained as many as the image pointer: 75 -> 0. Each half alone was 70 (the image and palette pointers
exchanged instead). The priorities are read from cc1's `-dl` table; the doubling is in the compiler source.

`variants` finds every braced statement macro (`#define NAME(...) { ...; ...; }`) whose body has a statement with a
conditional (directly or through the macros it names) followed by at least one more statement, writes `NAME_join_head`
and `NAME_join_tail` beside it, and for each whole-statement use of NAME in the function offers: the use split and its
tail wrapped with the rest of its block; the same with the innermost enclosing `if`/`else` chain wrapped as well; and
pairs of uses' tails. The wrappers are scaffolding (polishing removes them once a match is recorded); the judge decides."""
import itertools
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view
from .macro_scope_weight import LINE, uses
from .pattern_repairs import close

FAMILY = 'macro_join_tail_scope'
FAMILIES = (FAMILY,)
LIMIT = 40
SITES = 8
BRANCHY = re.compile(r'\?|\bif\b|&&|\|\||\bfor\b|\bwhile\b|\bswitch\b')
HEAD, TAIL = '_join_head', '_join_tail'


def statements(body):
    """The top-level statements of a macro body (backslash-newlines read as spaces), each with its `;` or block."""
    text = body.replace('\\\n', ' ')
    out, start, depth, i = [], 0, 0, 0
    while i < len(text):
        c = text[i]
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        elif c == '{' and depth == 0:
            end = close(text, i, '{', '}')
            if not end:
                return None
            if not text[start:i].strip():
                out.append(text[i:end].strip())
                start = i = end
                continue
            depth += 1
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
        elif c == ';' and depth == 0:
            out.append(text[start:i + 1].strip())
            start = i + 1
        i += 1
    if text[start:].strip() or depth:
        return None
    return [s for s in out if s and s != ';']


def _definitions(text):
    return {m['name']: m['text'] for m in LINE.finditer(text)}


def branchy(text, defined, seen=()):
    """Whether this text, with the macros it names written out, has a conditional (a branch the compiler emits)."""
    if BRANCHY.search(text):
        return True
    for word in set(re.findall(IDENT, text)):
        if word in defined and word not in seen and branchy(defined[word], defined, seen + (word,)):
            return True
    return False


def _split_macros(source, header):
    defined = {**_definitions(header or ''), **_definitions(source)}
    found = []
    for line in LINE.finditer(source):
        name, params = line['name'], line['params']
        # `macros()` reads one-line bodies; a body written over continuation lines starts with `\` before its `{`
        body = line['text'].replace('\\\n', ' ').strip()
        if not params or name.endswith((HEAD, TAIL)) or not body.startswith('{') or close(body, 0, '{', '}') != len(body):
            continue
        parts = statements(body[1:-1])
        if not parts or len(parts) < 2:
            continue
        last = max((i for i, s in enumerate(parts) if branchy(s, defined, (name,))), default=None)
        if last is None or last == len(parts) - 1:
            continue
        text = (f"\n#define {name}{HEAD}{params} {{ {' '.join(parts[:last + 1])} }}"
                f"\n#define {name}{TAIL}{params} {{ {' '.join(parts[last + 1:])} }}")
        found.append((name, (line.start(), line.end()), text))
    return found


def _python_block_end(clean, position, lo, hi):
    """The offset of the `}` that closes the innermost block holding `position` (inside the function), or None."""
    depth = 0
    for i in range(position - 1, lo - 1, -1):
        c = clean[i]
        if c == '}':
            depth += 1
        elif c == '{':
            if depth == 0:
                end = close(clean, i, '{', '}')
                return end - 1 if end and end <= hi else None
            depth -= 1
    return None


_block_end = _python_block_end
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _block_end(clean, position, lo, hi):
        found = _scan.enclosing_open(clean, position, lo, -1)
        if found is NotImplemented:
            return _python_block_end(clean, position, lo, hi)
        if found < 0:
            return None
        end = close(clean, found, '{', '}')
        return end - 1 if end and end <= hi else None


def _if_chains(clean, lo, hi):
    """(start, end) of every braced `if (...) { } [else if (...) { }]* [else { }]` chain in the function body."""
    chains = []
    for hit in re.finditer(r'\bif\s*\(', clean[lo:hi]):
        start = lo + hit.start()
        if re.search(r'\belse\s*$', clean[lo:start]):
            continue
        position = start
        while True:
            paren = close(clean, lo + hit.end() - 1 if position == start else position, '(', ')')
            if not paren:
                break
            block = re.match(r'\s*\{', clean[paren:hi])
            if not block:
                break
            end = close(clean, paren + block.end() - 1, '{', '}')
            if not end:
                break
            chains_end = end
            follow = re.match(r'\s*else\s*', clean[end:hi])
            if not follow:
                chains.append((start, chains_end))
                break
            after = end + follow.end()
            if clean.startswith('{', after):
                last = close(clean, after, '{', '}')
                if last:
                    chains.append((start, last))
                break
            nested = re.match(r'if\s*\(', clean[after:hi])
            if not nested:
                break
            position = after + nested.end() - 1
    return chains


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = _blank(source)
    lo, hi = part.opening + 1, part.end
    split = _split_macros(source, header)
    if not split:
        return []
    chains = _if_chains(clean, lo, hi)
    sites = []
    for macro, definition, text in split:
        found = uses(clean, macro, definition)
        for a, b in found or ():
            if lo < a < hi:
                end = _block_end(clean, a, lo, hi)
                if end is not None and end >= b:
                    sites.append((a, b, end, macro, definition, text))
    sites = sorted(sites)[:SITES]
    if not sites:
        return []

    def tail(site):
        a, b, end, macro, _definition, _text = site
        use = source[a:b]
        head = use.replace(macro, macro + HEAD, 1)
        rest = source[b:end].rstrip()
        return (a, end, f"{head} do {{ {use.replace(macro, macro + TAIL, 1)}{rest} }} while (0);\n")

    def enclosing(site):
        inside = [(s, e) for s, e in chains if s < site[0] and site[2] < e]
        if not inside:
            return []
        s, e = max(inside)
        return [(s, s, 'do { '), (e, e, ' } while (0);')]

    def child(chosen, wrap):
        edits = [tail(site) for site in chosen]
        if wrap:
            edits += enclosing(chosen[0])
            if len(edits) == 1:
                return None
        spans = sorted((s, e) for s, e, _ in edits)
        if any(spans[i][1] > spans[i + 1][0] for i in range(len(spans) - 1)):
            return None
        defines = [(definition[1], definition[1], text) for _m, definition, text in
                   dict.fromkeys((site[3], site[4], site[5]) for site in chosen)]
        return edit(source, edits + defines)

    out = []
    for site in sites:
        for wrap in (False, True):
            made = child((site,), wrap)
            if made:
                out.append((FAMILY, made))
    for pair in itertools.combinations(sites, 2):
        made = child(pair, False)
        if made:
            out.append((FAMILY, made))
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 900}  # the registry: no caller wiring (registry.py)
