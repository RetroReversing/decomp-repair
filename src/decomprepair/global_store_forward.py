"""A temporary that is stored to a global and read back, written as the global itself.

m2c names every value it computes: `temp = 1 << f(p); ... G = temp; ... if (x & temp) { *q |= temp; }`. The
game wrote `G = 1 << f(p); ... *q |= G;`: gcc's cse hands the stored value to the later reads of `G` in the same
basic block, so the register the value lives in is the one the target shows, but the pseudo is a *scratch*
register (it dies in the block) rather than a user variable the allocator and the scheduler treat as long lived.
A byte-wide temporary beside a word shift also adds a `subreg` copy, which flipped the `or`'s operand order and
a pair of shifts in one KMC gcc 2.7.2 function (a bit-stream writer, 90 -> 0 with this rewrite; every renaming
and re-typing of the temporary stayed at 90 or 5).

The rewrite forwards the temporary: the assignment becomes `G = expr;` where it was, the `G = temp;` line goes,
every other read of the temporary reads `G`, and its declaration goes. A global narrower than a word that the
target masks with `andi 0xff` (an unsigned byte) when read back is offered unsigned too, since an `s8` read back
is `sll`/`sra`. Only for a temporary assigned once and a global stored once from it, with no other write to the
global between the two lines."""
import re

from .csource import _blank, find

FAMILY = 'global_store_forward'
FAMILY_UNSIGNED = 'global_store_forward_unsigned'
FAMILIES = (FAMILY, FAMILY_UNSIGNED)
ID = r'[A-Za-z_]\w*'
SIGNED = {'s8': 'u8', 'char': 'unsigned char', 's16': 'u16', 'signed char': 'unsigned char', 'short': 'unsigned short'}


def _body(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return None
    depth = 0
    for i in range(opening, span[1]):
        depth += (clean[i] == '{') - (clean[i] == '}')
        if depth == 0:
            return opening, i + 1, clean
    return None


def _forwards(lines, globals_):
    """[(local, global, first_line, store_line)] for each temporary that can be forwarded."""
    found = []
    for t_line, text in enumerate(lines):
        m = re.fullmatch(rf'\s*({ID})\s*=\s*([^;]+);\s*', text)
        if not m or m[1] in globals_:
            continue
        local, expr = m[1], m[2]
        if re.search(r'[+\-*/&|^]=|\+\+|--', text) or re.search(rf'(?:^|[(,=;{{!~?:]|\breturn)\s*&\s*{local}\b', '\n'.join(lines), re.M):
            continue
        writes = [i for i, other in enumerate(lines)
                  if re.search(rf'(?<![\w.>])\s*{local}\s*(?:[-+*/&|^%]|<<|>>)?=(?!=)', other)
                  or re.search(rf'(?:\+\+|--)\s*{local}\b|\b{local}\s*(?:\+\+|--)', other)]
        if not writes or writes[0] != t_line:
            continue
        # m2c reuses one name for unrelated values: only the live range up to the next assignment is forwarded,
        # and that assignment must not read the old value.
        stop = writes[1] if len(writes) > 1 else len(lines)
        if stop < len(lines) and re.search(rf'\b{local}\b', lines[stop].split('=', 1)[1]):
            continue
        stores = [(i, re.fullmatch(rf'\s*({ID})\s*=\s*{local}\s*;\s*', other)) for i, other in enumerate(lines)
                  if t_line < i < stop]
        stores = [(i, s[1]) for i, s in stores if s and s[1] in globals_]
        if len(stores) != 1:
            continue
        store, glob = stores[0]
        if re.search(rf'\b{glob}\b', expr):
            continue
        between = '\n'.join(lines[t_line + 1:store])
        if re.search(rf'\b{glob}\s*(?:[-+*/&|^%]|<<|>>)?=(?!=)', between):
            continue
        found.append((local, glob, t_line, store, stop))
    return found


def variants(source, name):
    part = _body(source, name)
    if not part:
        return []
    opening, end, clean = part
    outside = clean[:opening]
    types = {m['g']: m['type'].strip() for m in re.finditer(
        rf'(?m)^[ \t]*extern\s+(?P<type>[\w ]+?)\s+(?P<g>{ID})\s*;', outside)}
    if not types:
        return []
    head, body, tail = source[:opening + 1], source[opening + 1:end - 1], source[end - 1:]
    lines = body.split('\n')
    stripped = [re.sub(r'//.*|/\*.*?\*/', '', line) for line in lines]
    options = _forwards(stripped, set(types))
    if not options:
        return []

    def rewrite(chosen, unsigned):
        out = list(lines)
        decls = set()
        for local, glob, first, store, stop in chosen:
            rhs = re.fullmatch(rf'(\s*){local}\s*=\s*([^;]+);\s*', stripped[first])
            out[first] = f'{rhs[1]}{glob} = {rhs[2]};'
            out[store] = None
            decls.add(local)
        for i, line in enumerate(out):
            if line is None:
                continue
            for local, glob, first, store, stop in chosen:
                if first < i < stop:
                    line = re.sub(rf'\b{local}\b', glob, line)
            out[i] = line
        for local in decls:
            if sum(bool(l) and bool(re.search(rf'\b{local}\b', l)) for l in out) == 1:
                out = [l for l in out if l is None or not re.fullmatch(rf'\s*[\w ]+\s+\*?{local}\s*;\s*', l)]
        text = head + '\n'.join(l for l in out if l is not None) + tail
        if unsigned:
            for _, glob, *_ in chosen:
                kind = types[glob]
                if kind in SIGNED:
                    text = re.sub(rf'(?m)^([ \t]*extern\s+){re.escape(kind)}(\s+{glob}\s*;)',
                                  rf'\g<1>{SIGNED[kind]}\g<2>', text)
        return text

    result = []
    groups = [[o] for o in options] + ([options] if len(options) > 1 else [])
    for chosen in groups:
        base = rewrite(chosen, False)
        result.append((FAMILY, base))
        widened = rewrite(chosen, True)
        if widened != base:
            result.append((FAMILY_UNSIGNED, widened))
    return result[:6]
