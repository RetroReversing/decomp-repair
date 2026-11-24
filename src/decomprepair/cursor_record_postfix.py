"""A display-list cursor: `p = G; G += K;` written as the postfix step of a global pointer to a K-byte word record.

The shape (SN GCC 2.8.1, `-G0 -mips2 -O2`; a 10-instruction N64 command writer, 110 -> 0): m2c writes a command into the
slot a global cursor points at, and moves the cursor on, as byte arithmetic on an untyped pointer

    extern void *G;
    void *p;
    p = G;
    G += 8;
    M2C_FIELD(p, s32 *, 0) = 0xFA000000;
    M2C_FIELD(p, s32 *, 4) = word;

The original kept the cursor as a pointer to a two-word record, read and stepped in one expression and written through
the record's members:

    typedef struct { u32 w0; u32 w1; } Rec;
    extern Rec *G;
    Rec *p;
    p = G++;
    p->w0 = 0xFA000000;
    p->w1 = word;

The two spellings compile to different code: with the byte step the cursor load is copied (`move $t0,$v0`) before the sum,
and the sum goes into a second register; `p = G++` on the typed pointer keeps the loaded value in the register the sum is
built from. Every neighbour spelling measured stayed at 110 or worse (the copy before the increment on `void *` byte
arithmetic, which folds away; `G = p + 1`, `G++;` after the copy and `G += 1;` on the typed pointer; `do { } while (0)`
fences, 770): only the postfix form in the initialiser on the typed pointer reached 0. The register effect is a hypothesis
from the allocator's behaviour (the old value is the postfix expression's own value, so there is no separate copy to
coalesce); the judge decides each child.

`variants` finds a global `G` the source (not the header) declares `extern T G;` with `T` a pointer or a 32-bit integer,
and statements `p = G;` followed at once by `G += K;` (also `G = G + K;` and `G = p + K;`, with the casts m2c writes), `p`
a local of its own that the function only reads and writes through 32-bit fields (`M2C_FIELD(p, T *, off)`, `*(T *)(p + off)`
and `((T *) p)[i]`, `T` a 32-bit integer or float type, the offset a word inside the record). `K` is the same for every such
pair of the global, a multiple of 4 up to 32, and the global is named nowhere else in the function or the file. Children:

- `cursor_record_postfix`: the global declared `extern Rec *G;` after a `typedef struct { T w0; ... } Rec;` of `K` bytes
  (a member per word, typed by how the function reads or writes it), `p` declared `Rec *p;`, each pair written
  `p = G++;`, each access `p->wN`;
- `cursor_record_view`: the same retype and members, the pair kept as two statements with the step `G += 1;` (what the
  typed pointer's byte step becomes), for the cases where the postfix form is not what the target wants;
- the postfix form for all such globals together (one edit), when there are several.

Faithful and bounded: the records are the bytes the function already touched, `G` moves by `K` bytes exactly as before,
nothing else changes, and at most MAX_GLOBALS globals and MAX_CHILDREN children are offered. This module reads text only
and never compiles or judges; a global the header declares is declined (its type is shared with other functions, and a
redeclaration here would conflict), as is one the file names elsewhere.
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'cursor_record_postfix'
VIEW_FAMILY = 'cursor_record_view'
FAMILIES = (FAMILY, VIEW_FAMILY)

MAX_GLOBALS = 3
MAX_CHILDREN = 8
MIN_BYTES, MAX_BYTES = 4, 32
MAX_GAP = 4  # (stores through the cursor between its load and its step)

_INT32 = r'(?:s32|u32|int|unsigned(?:\s+int)?|signed(?:\s+int)?|long|unsigned\s+long)'
_WORD = rf'(?:{_INT32}|f32|float)'
_BYTE_PTR = r'(?:void|[su]8|char|(?:unsigned|signed)\s+char)'
_GLOBAL = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)extern[ \t]+(?P<type>{_BYTE_PTR}[ \t]*\*|{_INT32}|{IDENT}[ \t]*\*)[ \t]*(?P<name>{IDENT})[ \t]*;')
_LOCAL = rf'(?:{_BYTE_PTR}\s*\*|{_INT32}|{IDENT}\s*\*)'
# `p = G;`, up to MAX_GAP plain statements, then the step: `G += K;`, `G = G + K;` or `G = p + K;` (with the casts m2c writes)
_PAIR = re.compile(
    rf'(?P<head>(?P<p>{IDENT})\s*=\s*(?P<g>{IDENT})\s*;)(?P<gap>(?:[^;{{}}]*;){{0,{MAX_GAP}}}?)'
    rf'(?P<tail>\s*(?P=g)\s*(?:\+=\s*(?P<k1>{NUMBER})'
    rf'|=\s*(?:\([^()]*\)\s*)?\(?\s*(?:(?P=g)|(?P=p))\s*\+\s*(?P<k2>{NUMBER})\s*\)?)\s*;)')


def _plain_gap(gap, g, local):
    """True for statements that only store through `local`: no call, no other mention of the global, no branch."""
    calls = re.findall(rf'({IDENT})\s*\(', gap)
    return not re.search(rf'\b{re.escape(g)}\b', gap) and all(call == 'M2C_FIELD' for call in calls)


def _word_type(text):
    """The record member type for an access type: 32-bit signed, unsigned or float; None for anything else."""
    text = re.sub(r'\s+', ' ', text.strip())
    if text in ('f32', 'float'):
        return 'f32'
    if text.startswith('unsigned') or text == 'u32':
        return 'u32'
    return 's32' if re.fullmatch(_INT32, text) else None


def _accesses(clean, lo, hi, local):
    """Every dereference of `local` as `(start, end, byte offset, type)`, none inside another."""
    p = re.escape(local)
    field = re.compile(rf'M2C_FIELD\(\s*{p}\s*,\s*({_WORD})\s*\*\s*,\s*({NUMBER})\s*\)')
    cast = re.compile(rf'\*\(\s*({_WORD})\s*\*\)\s*\(\s*(?:\(\s*(?:u8|s8|char)\s*\*\)\s*)?{p}(?:\s*\+\s*({NUMBER}))?\s*\)')
    # the printed spellings a saved source carries: `*((T *) (((char *) p) + off))` and `(((Field_T *) (((char *) p) + off))->v)`
    address = rf'\(\(\(\s*(?:char|u8|s8)\s*\*\)\s*{p}\s*\)\s*\+\s*({NUMBER})\s*\)'
    printed = re.compile(rf'\*\(\(\s*({_WORD})\s*\*\)\s*{address}\)')
    member = re.compile(rf'\(\(\s*Field_({_WORD})\s*\*\)\s*{address}\)\s*->\s*v\b')
    index = re.compile(rf'\(\(\s*({_WORD})\s*\*\)\s*{p}\s*\)\s*\[\s*({NUMBER})\s*\]')
    found = []
    for pattern, scale in ((field, None), (cast, None), (index, 4), (printed, None), (member, None)):
        for hit in pattern.finditer(clean, lo, hi):
            offset = int(re.sub(r'[uUlL]+$', '', hit.group(2) or '0'), 0) * (scale or 1)
            found.append((hit.start(), hit.end(), offset, hit.group(1)))
    found.sort()
    return [site for index_, site in enumerate(found) if not index_ or site[0] >= found[index_ - 1][1]]


def _is_store(clean, end):
    return re.match(r'\s*\)?\s*=(?!=)', clean[end:end + 8]) is not None  # (a `)` closes the printed member form)


def _plan(source, part, g, kind, hit, pairs):
    """The edits for one global, or None when the function does not fit the shape. `pairs` are the `_PAIR` matches."""
    clean = part.clean
    lo, hi = part.opening + 1, part.end - 1
    steps = {int(re.sub(r'[uUlL]+$', '', pair['k1'] or pair['k2']), 0) for pair in pairs}
    if len(steps) != 1:
        return None
    step = steps.pop()
    if step % 4 or not MIN_BYTES <= step <= MAX_BYTES:
        return None
    # the global is read and stepped only by the pairs
    if not all(_plain_gap(pair['gap'], g, pair['p']) for pair in pairs):
        return None
    covered = sum(len(re.findall(rf'\b{re.escape(g)}\b', pair['head'] + pair['tail'])) for pair in pairs)
    if len(re.findall(rf'\b{re.escape(g)}\b', clean[lo:hi])) != covered:
        return None
    words, loads, edits = {}, set(), []
    for local in sorted({pair['p'] for pair in pairs}):
        if local == g:
            return None
        mine = [pair for pair in pairs if pair['p'] == local]
        declared = list(re.finditer(rf'(?:^|(?<=[;{{}}]))\s*(?P<type>{_LOCAL})\s*\b{re.escape(local)}\s*;', clean[lo:hi]))
        if len(declared) != 1:
            return None
        sites = _accesses(clean, lo, hi, local)
        total = len(re.findall(rf'(?<![\w.]){re.escape(local)}\b(?!\s*->)', clean[lo:hi]))
        inside = sum(len(re.findall(rf'(?<![\w.]){re.escape(local)}\b', clean[a:b])) for a, b, _, _ in sites)
        pairs_used = sum(len(re.findall(rf'(?<![\w.]){re.escape(local)}\b', pair['head'] + pair['tail'])) for pair in mine)
        rest = list(clean)
        for a, b, _, _ in sites:
            rest[a:b] = ' ' * (b - a)
        arguments = len(re.findall(rf'(?:(?<!M2C_FIELD)\(|,)\s*{re.escape(local)}\s*(?=[,)])', ''.join(rest)[lo:hi]))  # (handed to a call as it is)
        used = 1 + pairs_used + inside + arguments  # (the declaration, the pairs' own mentions, each access, each argument)
        if not sites or total != used or any(pair.start() < part.opening for pair in mine):
            return None
        for a, b, offset, kind_ in sites:
            word = _word_type(kind_)
            if word is None or offset % 4 or offset >= step:
                return None
            index = offset // 4
            if not _is_store(clean, b):
                loads.add(index)
            words.setdefault(index, set()).add(word)
            edits.append((a, b, f'{local}->w{index}'))
        decl = declared[0]
        edits.append((lo + decl.start('type'), lo + decl.end('type'), '@RECORD@ *'))
    typed = []
    for index in range(step // 4):
        seen = words.get(index, {'u32'})
        if len(seen) > 1:
            if index in loads or not seen <= {'s32', 'u32'}:
                return None
            seen = {'u32'}
        typed.append(f'{next(iter(seen))} w{index};')
    return step, typed, edits


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    outside = _blank(source[:part.opening]) + ' ' + _blank(source[part.end:])
    body = part.clean[part.opening + 1:part.end - 1]
    seen = {m['g'] for m in _PAIR.finditer(body)}
    found = []
    for hit in _GLOBAL.finditer(_blank(source)):
        g = hit['name']
        if len(found) >= MAX_GLOBALS:
            break
        if hit.start() >= part.opening or g not in seen or g == name or re.search(rf'\b{re.escape(g)}\b', header or ''):
            continue
        declarations = len(re.findall(rf'\b{re.escape(g)}\b', outside))
        if declarations != len(re.findall(rf'\bextern\b[^;{{}}]*\b{re.escape(g)}\b[ \t]*;', outside)):
            continue  # another function (or a definition) names it
        pairs = [m for m in _PAIR.finditer(part.clean, part.opening + 1, part.end - 1) if m['g'] == g
                 and re.search(r'(?:^|[;{}])\s*$', part.clean[:m.start()])]
        plan = _plan(source, part, g, hit['type'], hit, pairs) if pairs else None
        if plan:
            found.append((g, hit, pairs, plan))
    if not found:
        return []

    def render(entry, postfix):
        g, hit, pairs, (step, typed, edits) = entry
        taken = set(re.findall(IDENT, source)) | set(re.findall(IDENT, header or ''))
        record = f'CursorRec{step}'
        while record in taken:
            record += '_'
        declaration = (f'{hit["indent"]}typedef struct {{ {" ".join(typed)} }} {record};\n'
                       f'{hit["indent"]}extern {record} *{g};')
        out = [(hit.start(), hit.end(), declaration)]
        out += [(a, b, text.replace('@RECORD@', record)) for a, b, text in edits]
        for pair in pairs:
            local = pair['p']
            if postfix:
                out += [(pair.start('head'), pair.end('head'), f'{local} = {g}++;'), (pair.start('tail'), pair.end('tail'), '')]
            else:
                out.append((pair.start('tail'), pair.end('tail'), re.match(r'\s*', pair['tail'])[0] + f'{g} += 1;'))
        return out

    children = []
    for entry in found:
        children.append((FAMILY, edit(source, render(entry, True))))
        children.append((VIEW_FAMILY, edit(source, render(entry, False))))
    if len(found) > 1:
        children.append((FAMILY, edit(source, [e for entry in found for e in render(entry, True)])))
    return list(dict.fromkeys(children))[:MAX_CHILDREN]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'),
          'order': 64, 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
