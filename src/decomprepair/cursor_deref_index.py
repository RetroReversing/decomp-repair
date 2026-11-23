"""A cursor read as `*q` and stepped by one beside a loop counter, written as a base indexed by the counter, with the loop's
invariant address locals written where the loop reads them (GCC 2.7.2, KMC, N64).

A search (or m2c) writes a table walk with a cursor of its own and the addresses the body reaches as locals set once
before the loop:

    t4 = ((char *) &flags) - 1;
    p = (void **) (((char *) &table4) - 0x10);
    i = 0;
    do {
        if (*p == NULL) { make(i); use(*p); t4[0] &= ~(1 << i); t4[-1] &= ~(1 << i); }
        i += 1;
        p += 1;
    } while (count > i);

The game indexed the table by the counter and wrote the addresses where it used them:

    do {
        if (p[i] == NULL) { make(i); use(p[i]); (((char *) &flags) - 1)[0] &= ...; }
        i += 1;
    } while (count > i);

A stepped `p` is a basic induction variable that loop.c keeps as it is; an invariant base indexed by `i` is a derived
address (a giv) that the loop pass reduces into a register of its own, started in the preheader, which puts the other
preheader copies (the flag byte's base and its `- 1` neighbour, `move $s2,$s1; addiu $s4,$s2,-1`) in the target's
registers. The address locals matter too: set before the loop they are pseudos with their own live range and
priority, written at their uses they are constants that cse turns into offsets from a register already holding the
symbol. Each edit alone is worse; together they are better. Measured on a 556-instruction N64 split-screen setup routine
(`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`): indexed cursor alone 4500 -> 4830, address local inlined alone
4500 -> 4830, both 4500 -> 4335 (116 -> 94 differing rows; the preheader's `move`/`addiu` rows matched).

`cursor_base_index_loop` covers cursors read as `q[k]` and a test written `i < E`; this family takes the `*q` reads and
the `E > i` test it declines, and offers the combination as one child. The rewrite keeps the program's meaning:

  * the loop is `do { body } while (i < E);` or `while (E > i);`, the body has no `break`, `continue`, `goto`, `return`
    or `switch`, and steps the cursor (`q += 1;`, `q++;`, `++q;`) and the counter (by 1) once each, at its own level, with
    no other write of either;
  * the cursor is set before the loop (`q = EXPR;`), read in the body only as `*q` or `q[k]` before its step, never
    address-taken, and after the loop only assigned or not mentioned; the counter's last assignment before the loop is
    `i = 0;`;
  * an address local is assigned exactly once in the function, before the loop, from casts, literals and `&global`
    (no local, call or memory read), is never address-taken, and every read of it is in the loop's body.

Children: the indexed cursor with every address local written at its reads (the cursor itself kept), the same with the
cursor's base written in too, and the indexed cursor alone.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'cursor_deref_index'
FAMILIES = (FAMILY,)
MAX_CHILDREN = 3

_DO = re.compile(r'\bdo\s*\{')
_JUMPS = re.compile(r'\b(?:continue|break|goto|return|switch|case|default)\b')
_TYPES = {'void', 'char', 'short', 'int', 'long', 'unsigned', 'signed', 'const', 'volatile', 'struct', 'union',
          's8', 'u8', 's16', 'u16', 's32', 'u32', 's64', 'u64', 'f32', 'f64', 'float', 'double'}


def _level(body, at):
    return body[:at].count('{') == body[:at].count('}')


def _steps(body, name):
    pattern = rf'(?:\+\+\s*{re.escape(name)}|(?<![\w.>]){re.escape(name)}\s*\+\+|(?<![\w.>]){re.escape(name)}\s*\+=\s*1)\s*;'
    return list(re.finditer(pattern, body))


def _writes(text, name):
    return re.findall(rf'(?<![\w.>]){re.escape(name)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?<![\w.>])(?:\+\+|--)\s*{re.escape(name)}\b|'
                      rf'(?<![\w.>]){re.escape(name)}\s*(?:\+\+|--)', text)


def _line(source, start, end):
    """The span to delete for a statement: its whole line when it is alone on it, else the statement."""
    line = source.rfind('\n', 0, start) + 1
    stop = source.find('\n', end)
    stop = len(source) if stop < 0 else stop
    if not source[line:start].strip() and not source[end:stop].strip():
        return line, min(stop + 1, len(source))
    return start, end


def _loops(part):
    clean = part.clean
    for match in _DO.finditer(clean, part.opening + 1, part.end):
        body_open = match.end() - 1
        body_end = close(clean, body_open, '{', '}')
        if not body_end:
            continue
        tail = re.match(r'\s*while\s*\(', clean[body_end:part.end])
        if not tail:
            continue
        cond_open = body_end + tail.end() - 1
        cond_end = close(clean, cond_open)
        if not cond_end or not re.match(r'\s*;', clean[cond_end:]):
            continue
        test = clean[cond_open + 1:cond_end - 1].strip()
        forward = re.fullmatch(rf'(?P<c>{IDENT})\s*<\s*(?P<e>[^<>]+)', test)
        backward = re.fullmatch(rf'(?P<e>[^<>]+?)\s*>\s*(?P<c>{IDENT})', test)
        hit = forward or backward
        if not hit or hit['c'] == hit['e'].strip():
            continue
        yield {'do': match.start(), 'open': body_open, 'end': body_end, 'counter': hit['c'],
               'after': cond_end + re.match(r'\s*;', clean[cond_end:]).end()}


def _index(part, loop):
    """(edits, cursor) that index the loop's `*q` cursor by its counter, or None."""
    clean, base = part.clean, loop['open'] + 1
    body = clean[base:loop['end'] - 1]
    counter = loop['counter']
    if _JUMPS.search(body):
        return None
    counted = _steps(body, counter)
    if len(counted) != 1 or not _level(body, counted[0].start()) or len(_writes(body, counter)) != 1:
        return None
    cursors = [s for s in re.finditer(rf'(?:\+\+\s*(?P<a>{IDENT})|(?<![\w.>])(?P<b>{IDENT})\s*(?:\+\+|\+=\s*1))\s*;', body)
               if (s['a'] or s['b']) != counter and _level(body, s.start())]
    if len(cursors) != 1:
        return None
    step = cursors[0]
    q = step['a'] or step['b']
    if len(_writes(body, q)) != 1 or re.search(rf'&\s*{re.escape(q)}\b', body):
        return None
    edits, deref = [], False
    for use in re.finditer(rf'(?<![\w.>]){re.escape(q)}\b', body):
        if step.start() <= use.start() < step.end():
            continue
        if use.start() > step.start():
            return None
        before = body[:use.start()].rstrip()
        cast = re.search(rf'\(\s*(?P<t>(?:{IDENT}\s+)*{IDENT})(?P<s>[\s*]*)\)\s*\*$', before)
        cast = cast and ('*' in cast['s'] or set(cast['t'].split()) <= _TYPES)
        star = before.endswith('*') and (cast or not re.search(r'[\w)\]]\s*\*$', before))
        indexed = re.match(r'\s*\[', body[use.end():])
        if star:
            at = len(before) - 1
            edits.append((base + at, base + use.end(), f'{q}[{counter}]'))
            deref = True
        elif indexed:
            at = use.end() + indexed.end() - 1
            shut = close(body, at, '[', ']')
            if not shut:
                return None
            inner = body[at + 1:shut - 1].strip()
            if re.search(rf'(?<![\w.>]){re.escape(q)}\b', inner):
                return None
            edits.append((base + use.start(), base + shut, f'{q}[{counter}]' if inner == '0' else f'{q}[{counter} + {inner}]'))
        else:
            return None
    if not deref:
        return None  # `q[k]` alone is cursor_base_index_loop's
    before = clean[part.opening + 1:loop['do']]
    if not re.search(rf'(?<![\w.>]){re.escape(q)}\s*=(?!=)[^;]*;', before):
        return None
    zero = list(re.finditer(rf'(?<![\w.>]){re.escape(counter)}\s*=(?!=)\s*([^;]*);', before))
    if not zero or zero[-1][1].strip() != '0' or _writes(before[zero[-1].end():], counter):
        return None
    after = clean[loop['after']:part.end]
    later = re.search(rf'(?<![\w.>]){re.escape(q)}\b', after)
    if later and not re.match(r'\s*=(?!=)', after[later.end():]):
        return None
    edits.append(_line(part.source, base + step.start(), base + step.end()) + ('',))
    return edits, q


def _address_locals(part, loop):
    """name -> (statement span, value) of each local set once before the loop to an address constant and read only in
    the loop's body."""
    clean = part.clean
    body = clean[part.opening + 1:part.end - 1]
    declared = set(re.findall(rf'(?:\b{IDENT}\b|\*)\s*\**\s*({IDENT})\s*(?:[;=,\[])', body))
    found = {}
    for hit in re.finditer(rf'(?<![\w.>])(?P<n>{IDENT})\s*=(?!=)\s*(?P<v>[^;]+);', clean[part.opening + 1:loop['do']]):
        name, value = hit['n'], hit['v'].strip()
        start = part.opening + 1 + hit.start()
        if clean[:start].rstrip()[-1:] not in (';', '{', '}'):
            continue
        if name not in declared or len(_writes(body, name)) != 1 or re.search(rf'&\s*{re.escape(name)}\b', body):
            continue
        if not re.fullmatch(r'[\w\s()*&+\-]+', value) or '&' not in value:
            continue
        globals_ = re.findall(rf'&\s*({IDENT})', value)
        others = set(re.findall(IDENT, re.sub(rf'&\s*{IDENT}', '', value))) - _TYPES
        if others - {o for o in others if re.fullmatch(r'0[xX][0-9a-fA-F]+|\d+', o)} or set(globals_) & declared:
            continue
        if re.search(r'[\w)]\s*\*\s*[\w(]', re.sub(r'\([^()]*\*\s*\)', '', value)):
            continue  # a product, not a cast
        reads = [r.start() for r in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', clean[start + len(hit[0]):part.end])]
        reads = [start + len(hit[0]) + r for r in reads]
        if not reads or any(not (loop['open'] < r < loop['end']) for r in reads):
            continue
        found[name] = ((start, start + len(hit[0])), value, reads)
    return found


def _inline(part, chosen):
    edits = []
    source, clean = part.source, part.clean
    for name, ((start, end), value, reads) in chosen.items():
        for r in reads:
            edits.append((r, r + len(name), f'({value})'))
        a, b = _line(source, start, end)
        # a `{ L = V; }` block that holds only this statement goes with it
        before, after = clean[:a].rstrip(), clean[b:]
        if before.endswith('{') and re.match(r'\s*\}', after) and \
                clean[:len(before) - 1].rstrip()[-1:] in (';', '{', '}'):
            a2 = source.rfind('\n', 0, len(before) - 1) + 1
            b2 = b + re.match(r'\s*\}', after).end()
            stop = source.find('\n', b2)
            if not source[a2:len(before) - 1].strip() and not source[b2:stop if stop >= 0 else len(source)].strip():
                a, b = a2, (stop + 1 if stop >= 0 else len(source))
        edits.append((a, b, ''))
        for decl in re.finditer(rf'^[ \t]*(?:{IDENT}\s+)+\**\s*{re.escape(name)}\s*;[ \t]*\n', source[part.opening:part.end], re.M):
            edits.append((part.opening + decl.start(), part.opening + decl.end(), ''))
    return edits


def _overlap(edits):
    spans = sorted((s, e) for s, e, _ in edits)
    return any(b[0] < a[1] for a, b in zip(spans, spans[1:]))


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|goto)\b', part.clean[part.opening:part.end]):
        return []
    out = []
    for loop in _loops(part):
        done = _index(part, loop)
        if not done:
            continue
        edits, q = done
        addresses = _address_locals(part, loop)
        without = {n: v for n, v in addresses.items() if n != q}
        children = []
        if without:
            children.append(edits + _inline(part, without))
        if q in addresses and len(addresses) > len(without):
            index_reads = {n: (span, value, reads) for n, (span, value, reads) in addresses.items()}
            # the cursor's reads are rewritten to `q[i]` by the index edits; inline its base inside them
            inner = []
            for s, e, r in edits:
                if r.startswith(f'{q}['):
                    r = f'({addresses[q][1]})' + r[len(q):]
                inner.append((s, e, r))
            rest = {n: v for n, v in index_reads.items() if n != q}
            span, value, _ = addresses[q]
            a, b = _line(source, *span)
            decls = [(part.opening + d.start(), part.opening + d.end(), '') for d in
                     re.finditer(rf'^[ \t]*(?:{IDENT}\s+)+\**\s*{re.escape(q)}\s*;[ \t]*\n', source[part.opening:part.end], re.M)]
            children.append(inner + _inline(part, rest) + [(a, b, '')] + decls)
        children.append(edits)
        for group in children:
            if _overlap(group):
                continue
            text = edit(source, group)
            if text != source and (FAMILY, text) not in out:
                out.append((FAMILY, text))
    return out[:MAX_CHILDREN]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
