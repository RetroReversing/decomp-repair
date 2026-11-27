"""A pointer local set once to a global array's element, used for its members (or passed on), written as the element.

`ent = &TABLE[count]; ent->kind = 1; ent->t = t; ...` and `TABLE[count].kind = 1; TABLE[count].t = t; ...` are the same
program while nothing between them changes `count`, but GCC 2.x expands them differently: the pointer is one pseudo
holding the whole element address (index scaled, then the base added), the indexed form an address cse builds from the
symbol and the index, with the symbol's `lui`/`addiu` emitted first. The first scheduler then puts the base ahead of the
index load (the index in `$a0`, the base in `$v0`), which no ordering of the pointer form gives.

A 920-instruction N64 ray/triangle test (sn-n64-281 GCC 2.8.1, `-G0 -mips3 -O2 -mgas -meb -mcpu=VR4300 -mhard-float
-mfp32`) that records each hit in a global record array went 352 -> 11 with the record's fourteen member stores written
through `TABLE[count]` instead of a pointer local (measured with the app's judge-worker; one function).

`variants` finds every `P = &ARRAY[INDEX];` whose pointer is a local assigned nowhere else and read only as `P->member`
within the same block, after the assignment, with no call and no change to INDEX (or to P) in between; one child per
such pointer writes each `P->` as `ARRAY[INDEX].` and drops the assignment (the declaration stays when P is still named
elsewhere, and goes when it is not). INDEX is an identifier or an integer literal, or (since a vertex writer needed it)
several subscripts of names, literals and `+ - *`, none of whose names change between the set and the last use:
`vt = &VERTS[buf][base + k]; vt->ob[0] = ..; vt->flag = 0; ..` as `VERTS[buf][base + k].ob[0] = ..`. On a
773-instruction N64 drop-shadow renderer (the same sn-n64-281 -mfp32 profile) the pointer was one long-lived address that
kept the vertex buffer's `%hi` live over the whole outer loop (one spill more, frame 0xF8 against 0xF0); written through
the indexed element every member store re-forms the address as the target does: 2566 -> 1080, then 60 -> 0 with the
members stored in declaration order and the entry pointer of the same loop written the same way.

A pointer to a scalar element read as `*P` is written as the element the same way, the array possibly a member
(`p = &record.data[i]; f(*p);` as `f(record.data[i]);`), and a function with several such pointers also gets one child
with all of them inlined. An SN GCC 2.8.1 `-O2` N64 function queueing sound ids from two stack records kept both record
addresses in saved registers through the pointer locals (a frame 8 bytes too large); inlined, the target computes
`addiu $sp, 0x10` at each use. `M2C_FIELD(...)` is a field access, not a call.

The pointer may also be handed to the first call after it is set (`ent = &TABLE[count]; ent->data = p; if (load(ent, 0))`),
written `load(&TABLE[count], 0)`: the argument is evaluated before the call can change the index, and no use may follow
that call. An N64 asset loader (sn-n64-281 GCC 2.8.1, `-mfp64`, 229 instructions) went 500 -> 0 with the member store
and the argument both written as the element; either one alone through the pointer stayed at 500."""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'element_pointer_direct_index'
FAMILIES = (FAMILY,)
LIMIT = 8
SET = re.compile(rf'(?<![\w.>])(?P<p>{IDENT})\s*=\s*&\s*(?P<a>{IDENT}(?:\.{IDENT})*)(?P<i>(?:\s*\[[^\[\]();=?,]+\])+)\s*;')
SUBSCRIPT = re.compile(r'\s*\[\s*([^\[\]]*?)\s*\]')
PLAIN = re.compile(rf'(?:{IDENT}|0[xX][0-9A-Fa-f]+|\d+)(?:\s*[-+*]\s*(?:{IDENT}|0[xX][0-9A-Fa-f]+|\d+))*')
NAMES = re.compile(rf'(?<![\w.]){IDENT}')
KEYWORDS = {'if', 'while', 'for', 'switch', 'return', 'sizeof', 'do', 'else', 'M2C_FIELD'}  # (a field access)


def _python_block_end(clean, position, lo, hi):
    depth = 0
    for i in range(position, hi):
        c = clean[i]
        if c == '{':
            depth += 1
        elif c == '}':
            if depth == 0:
                return i
            depth -= 1
    return None


_block_end = _python_block_end
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _block_end(clean, position, lo, hi):
        found = _scan.enclosing_end(clean, position, hi, None)
        return _python_block_end(clean, position, lo, hi) if found is NotImplemented else found


def _modifies(text, name):
    n = re.escape(name)
    return re.search(rf'(?<![\w.>]){n}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|\+\+\s*{n}\b|--\s*{n}\b|\b{n}\s*(?:\+\+|--)', text)


def _calls(text):
    return any(m[1] not in KEYWORDS for m in re.finditer(rf'\b({IDENT})\s*\(', text))


def _passing_call(clean, position, length):
    """`(start, end)` of the call whose argument list holds the bare name at `position`, or None: the call's name and its
    closing parenthesis."""
    if not re.search(r'[(,]\s*\Z', clean[:position]) or not re.match(r'\s*[,)]', clean[position + length:]):
        return None
    depth, opening = 0, None
    for i in range(position - 1, -1, -1):
        c = clean[i]
        if c in ';{}':
            return None
        if c == ')':
            depth += 1
        elif c == '(':
            if depth == 0:
                opening = i
                break
            depth -= 1
    if opening is None:
        return None
    callee = re.search(rf'(?<![\w.>])({IDENT})\s*\Z', clean[:opening])
    if not callee or callee[1] in KEYWORDS:
        return None
    depth = 0
    for i in range(opening, len(clean)):
        if clean[i] == '(':
            depth += 1
        elif clean[i] == ')':
            depth -= 1
            if depth == 0:
                return callee.start(1), i
    return None


def variants(source, name, header='', every_deref=True):
    part = view(source, name)
    if not part:
        return []
    clean = _blank(source)
    lo, hi = part.opening + 1, part.end - 1
    body = clean[lo:hi]
    out, derefs = [], []
    for hit in SET.finditer(body):
        pointer, array = hit['p'], hit['a']
        subscripts = SUBSCRIPT.findall(hit['i'])
        if not all(PLAIN.fullmatch(sub) for sub in subscripts):
            continue
        index = ']['.join(subscripts)
        names = set(NAMES.findall(index))
        if pointer in names | {array.split('.')[0]}:
            continue
        start, after = lo + hit.start(), lo + hit.end()
        # a local of this function: declared as a pointer in its body
        if not re.search(rf'\b{IDENT}\s*\*\s*{re.escape(pointer)}\s*;', body):
            continue
        uses = [m.start() for m in re.finditer(rf'(?<![\w.>]){re.escape(pointer)}\b', clean[lo:hi])]
        uses = [lo + u for u in uses]
        declaration = [u for u in uses if re.match(rf'{re.escape(pointer)}\s*;', clean[u:]) and
                       re.search(rf'(?:\A|[;{{}}])\s*{IDENT}\s*\*\s*\Z', clean[lo:u])]
        others = [u for u in uses if u not in declaration and u != start]
        if not others or any(u < after for u in others):
            continue
        stars = {u: len(clean[lo:u].rstrip()) + lo - 1 for u in others if clean[lo:u].rstrip().endswith('*')}
        passed = {u: call for u in others
                  if u not in stars and not re.match(rf'{re.escape(pointer)}\s*->', clean[u:])
                  and (call := _passing_call(clean, u, len(pointer)))}
        if not all(u in stars or u in passed or re.match(rf'{re.escape(pointer)}\s*->\s*{IDENT}', clean[u:])
                   for u in others):
            continue
        end = _block_end(clean, after, after, hi)
        if end is None or others[-1] > end:
            continue
        region = clean[after:others[-1]]
        if passed:
            # one call takes the pointer: nothing is called before it or inside its arguments, and nothing reads after it
            calls = set(passed.values())
            call_start, call_end = next(iter(calls))
            arguments = clean[clean.index('(', call_start) + 1:call_end]
            region = clean[after:call_end]
            if len(calls) > 1 or others[-1] > call_end or call_end > end or _calls(clean[after:call_start]) or \
                    _calls(arguments) or any(_modifies(region, n) for n in names) or _modifies(region, pointer):
                continue
        elif _calls(region) or any(_modifies(region, n) for n in names) or _modifies(region, pointer):
            continue
        # a member store written through the pointer must not itself change the index (`p->n = count++`)
        tail = re.search(r'[^;]*;', clean[others[-1]:end])
        if tail and any(_modifies(tail.group(0), n) for n in names):
            continue
        edits = [(start, after + (1 if source[after:after + 1] == '\n' else 0), '')]
        line = source.rfind('\n', 0, start) + 1
        if not source[line:start].strip() and source[after:after + 1] == '\n':
            edits = [(line, after + 1, '')]
        for u in others:
            if u in stars:  # `*p`, the element itself
                edits.append((stars[u], u + len(pointer), f'{array}[{index}]'))
                continue
            if u in passed:  # the address itself, handed on
                edits.append((u, u + len(pointer), f'&{array}[{index}]'))
                continue
            arrow = re.match(rf'{re.escape(pointer)}\s*->\s*', clean[u:])
            edits.append((u, u + arrow.end(), f'{array}[{index}].'))
        for d in declaration:
            semi = clean.index(';', d) + 1
            dline = source.rfind('\n', 0, d) + 1
            dend = source.find('\n', semi)
            text = source[dline:dend]
            if re.fullmatch(rf'\s*{IDENT}\s*\*\s*{re.escape(pointer)}\s*;\s*', text):
                edits.append((dline, dend + 1, ''))
        out.append((FAMILY, edit(source, edits)))
        derefs.append(bool(stars))
    # two arms each with their own element pointer: neither alone need move the score, so all of them in one child too
    if every_deref and sum(derefs) > 1:
        every, done = source, 0
        while done < LIMIT and (children := [child for _, child in variants(every, name, header, every_deref=False)
                                             if child.count('*') < every.count('*')]):
            every, done = children[0], done + 1
        out.insert(0, (FAMILY, every))
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 900}  # the registry: no caller wiring (registry.py)
