"""A value stored to a global before the loops staged in the loops' counter, and the later loops' counters merged into it.

GCC 2.x global.c gives a pseudo the hard-register preferences of the pseudos it is tied to: `expand_preferences` merges
the preferences of an insn's destination and of a register that dies in it, and a parameter's copy prefers the register
the parameter arrived in. A counter the target keeps in an argument register (`$a2`) that nothing in its loops sets from
a hard register therefore inherits that preference from a value the original computed in the same variable: on an N64
texture-strip blitter (SN GCC 2.8.1, `-G0 -mips3 -O2`, 477 instructions) the strip counters of both `switch` arms were in
`$a2`, the register `y0` arrived in, and so was `y0 << 2` stored to a global before the `switch` (`sll $a2, $fp, 2`).
With `D = y0 << 2;` and a counter of their own the loops' counters took `$a3` and `$t1`, because the lower-priority
counter had no preference for `$a2` and `prune_preferences` let the higher-ranked temporaries of the loop (a command
word, a rounding term) take it first; written `n = y0 << 2; D = n;` with the second arm's counter the same `n`, the
counter prefers `$a2`, the temporaries that conflict with it skip `$a2` in `find_reg`'s first pass, and both loops got
the target's registers (525 -> 435, 30 register rows fixed; the staging alone was 520, the merge alone 600). Read in the
`-dg` dump: `;; 95 preferences: 6 9` only once the global's value went through the counter.

`variants` takes each `G = E;` at the top level of the body that stores a non-constant, call-free expression to a name
that is no local or parameter, and each word local declared at the top of the function whose first mention after the
store is a plain assignment inside a loop and that is never mentioned before it. It offers the store staged in that
local, then the staging with every same-typed local declared inside a later loop's body renamed to it (one child:
the parts are worse alone). A block where the counter is already used as a scratch value that is set and read once by
the next statement (`n = m * hh; strip = n / texh;`) has that value inlined first; a block that uses it any other
way is left alone. That the preference decides the register is read from the dumps of one function; the judge decides."""
import re

from .integer_repair_support import edit, view
from .local_weight_ladder import _declaration, _parameters

FAMILY = 'global_store_counter_stage'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'
WORD = {'s32', 'u32', 'int', 'signed int', 'unsigned int', 'long', 'unsigned long', 'unsigned', 'signed'}
LOOP = re.compile(r'\b(?:while|for|do)\b')
LIMIT = 8


def _depths(clean, start, end):
    """The brace depth at every offset of clean[start:end] (relative to start)."""
    depth, out = 0, []
    for char in clean[start:end]:
        if char == '}':
            depth -= 1
        out.append(depth)
        if char == '{':
            depth += 1
    return out


def _mention(name):
    return re.compile(rf'(?<![\w.>]){re.escape(name)}\b')


def _block_end(clean, opening):
    depth = 0
    for at in range(opening, len(clean)):
        depth += (clean[at] == '{') - (clean[at] == '}')
        if depth == 0:
            return at
    return -1


def _in_loop(clean, start, at):
    """Whether offset `at` lies inside the body of a while/for/do that starts after `start`."""
    for loop in LOOP.finditer(clean, start, at):
        opening = clean.find('{', loop.end(), at + 1)
        if opening < 0:
            continue
        if re.search(r';', clean[loop.end():opening]) and loop[0] != 'for':
            continue
        close = _block_end(clean, opening)
        if close > at:
            return True
    return False


def _loop_blocks(clean, start, end):
    """(opening, close) of each loop body after `start`."""
    out = []
    for loop in LOOP.finditer(clean, start, end):
        opening = clean.find('{', loop.end(), end)
        if opening < 0 or (loop[0] != 'for' and ';' in clean[loop.end():opening]):
            continue
        close = _block_end(clean, opening)
        if close > 0:
            out.append((opening, close))
    return out


def _wrapped(text):
    """Whether text is one parenthesised expression, `(a * b)`."""
    if not (text.startswith('(') and text.endswith(')')):
        return False
    depth = 0
    for at, char in enumerate(text):
        depth += (char == '(') - (char == ')')
        if depth == 0 and at < len(text) - 1:
            return False
    return True


def _inline_scratch(source, clean, opening, close, counter):
    """The edits that inline `counter = X; ... counter ...;` pairs in a block, or None when it uses `counter` otherwise."""
    mention = _mention(counter)
    hits = [m.start() for m in mention.finditer(clean, opening, close)]
    if not hits:
        return []
    edits = []
    used = set()
    for hit in re.finditer(rf'(?<![\w.>]){re.escape(counter)}\s*=(?!=)\s*(?P<x>[^;{{}}]+);', clean[opening:close]):
        at = opening + hit.start()
        x = hit['x'].strip()
        if mention.search(x) or re.search(rf'{IDENT}\s*\(|\+\+|--|(?<![=!<>])=(?!=)', x):
            return None
        nxt = re.match(r'\s*(?P<s>[^;{}]+);', clean[opening + hit.end():close])
        if not nxt:
            return None
        s_start = opening + hit.end() + nxt.start('s')
        s_end = opening + hit.end() + nxt.end('s')
        reads = [m.start() for m in mention.finditer(clean, s_start, s_end)]
        if len(reads) != 1 or re.match(rf'\s*{re.escape(counter)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', clean[s_start:s_end]):
            return None
        line_start = source.rfind('\n', 0, at) + 1
        tail = re.match(r'[ \t]*\n', source[opening + hit.end():])
        if source[line_start:at].strip() == '' and tail:
            edits.append((line_start, opening + hit.end() + tail.end(), ''))  # the whole line
        else:
            edits.append((at, opening + hit.end() + nxt.start('s'), ''))
        edits.append((reads[0], reads[0] + len(counter), x if _wrapped(x) or re.fullmatch(r'\w+', x) else f'({x})'))
        used.update({at, reads[0]})
    if any(h not in used for h in hits):
        return None
    return edits


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    start, end = part.opening + 1, part.end
    depth = _depths(clean, start, end)
    params = set(_parameters(part))
    locals_, top = {}, {}
    for line in re.finditer(r'[^\n]*\n?', clean[start:end]):
        if not line[0]:
            break
        match = _declaration(line[0].rstrip('\n'))
        if not match:
            continue
        kind = ' '.join(match['type'].split())
        locals_[match['name']] = kind
        if depth[line.start()] == 0 and '*' not in match['gap'] and not match['init'] and kind in WORD:
            top[match['name']] = (start + line.start(), start + line.end(), kind)
    known = set(locals_) | params
    result, seen = [], set()

    def add(text):
        if text != source and text not in seen:
            seen.add(text)
            result.append((FAMILY, text))

    for store in re.finditer(rf'(?m)^(?P<indent>[ \t]*)(?P<g>{IDENT})\s*=(?!=)\s*(?P<e>[^;{{}}]+);', clean[start:end]):
        at = start + store.start('g')
        if depth[store.start('g')] != 0 or store['g'] in known:
            continue
        expr = store['e'].strip()
        if (re.fullmatch(r'\(?\s*-?(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*\s*\)?', expr)
                or re.search(rf'{IDENT}\s*\(|\+\+|--', expr) or not (set(re.findall(IDENT, expr)) & known)):
            continue
        stmt_end = start + store.end()
        for counter, (d_start, d_end, kind) in top.items():
            mention = _mention(counter)
            if mention.search(clean, d_end, at) or mention.search(expr):
                continue
            first = mention.search(clean, stmt_end, end)
            if not first or not re.match(rf'{re.escape(counter)}\s*=(?!=)', clean[first.start():]):
                continue
            if not _in_loop(clean, stmt_end, first.start()):
                continue
            indent = store['indent']
            staged = (start + store.start(), start + store.end(),
                      f'{indent}{counter} = {source[start + store.start("e"):start + store.end("e")].strip()};\n'
                      f'{indent}{store["g"]} = {counter};')
            add(edit(source, [staged]))
            merges = [staged]
            for opening, close in _loop_blocks(clean, stmt_end, end):
                for decl in re.finditer(r'(?m)^[^\n]*\n', clean[opening + 1:close]):
                    if depth[opening + 1 + decl.start() - start] != depth[opening - start] + 1:
                        continue
                    match = _declaration(decl[0].rstrip('\n'))
                    if not match or match['init'] or '*' in match['gap'] or ' '.join(match['type'].split()) != kind:
                        continue
                    other = match['name']
                    if other == counter:
                        continue
                    inner = _inline_scratch(source, clean, opening, close, counter)
                    if inner is None:
                        continue
                    after = mention.search(clean, close, end)
                    if after and not re.match(rf'{re.escape(counter)}\s*=(?!=)', clean[after.start():]):
                        continue
                    if _mention(other).search(clean, close, end):
                        continue
                    d0 = opening + 1 + decl.start()
                    merges.append((d0, d0 + len(decl[0]), ''))
                    rename = _mention(other)
                    merges.extend((a, b, rename.sub(counter, text)) for a, b, text in inner)
                    for hit in _mention(other).finditer(clean, d0 + len(decl[0]), close):
                        merges.append((hit.start(), hit.end(), counter))
            if len(merges) > 1:
                add(edit(source, merges))
            if len(result) >= LIMIT:
                return result
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 94,
          'lanes': ('beam', 'local')}  # the registry: no caller wiring (registry.py)
