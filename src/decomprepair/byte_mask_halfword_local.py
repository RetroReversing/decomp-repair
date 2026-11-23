"""A byte value masked twice (`andi $v1, $v0, 0x3f; andi $s4, $v1, 0xff`): a halfword local set from a `(u8)` cast.

    u8 b; s32 lo; int v;                       u16 b; s32 lo; s16 v;
    b = (x & 0x3F) & 0xFF;                     b = (u8) (x & 0x3F);
    lo = (u8) (b & 0x1F);              ->      lo = (b & 0x1F);
    ...                                        ...
    v = b + n;  *((s16 *) p) = v;              v = b + n;  *((s16 *) p) = v;

KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) does not promote `u8`/`u16` locals: a byte local is a QImode pseudo
and a halfword local a HImode one (`reg/v:QI` in the `.rtl` dump). Assigning a masked value to a byte local, or to a
wide one through `& 0xFF`, leaves one `andi` (combine knows the value's nonzero bits and drops the extension). The
target's pair is a QImode value zero-extended into a HImode local: `(set (reg:HI b) (zero_extend:HI (subreg:QI
(and:SI x 63))))`, which combine keeps (observed in toy functions: every `u8`, `s8`, `u32` and `s32` destination
folded, every `u16`/`s16` one written from a byte kept the pair; the reason in combine.c is not traced). A 616-
instruction audio command builder had eight such sites that no spelling of a byte or word local reached; the
halfword local with `(u8) (x & M)` gave the pair at all of them. Two edits go with it: a wide local copied from the
halfword through `(u8) (b & K)` loses the cast (it otherwise becomes a `move` plus a second register), and an `int`
local set from the halfword and only stored as a halfword is `s16` (an `int` multi-set local reads the halfword
through an `andi 0xffff`). Measured with the exact judge from the saved best, 2555: the retyping alone 3660, with the
copy 1825, with the halfword result 1495 (and 1270 once a read of the local before its set was put right by hand).

Children, for a function whose locals (`u8`, `unsigned char`, `unsigned`, `u32`, `s32`, `int`) are set as
`v = (E & M) & 0xFF;`, `v = (u8) (E & M);` or `t = E & M; v = t & 0xFF;` (M a constant below 0x100): all such
locals `u16` with those assignments `v = (u8) (E & M);` (one child), that with the `(u8)` copies uncast (a second)
and with the halfword results narrowed (a third, the measured one); and the third for each local alone when there
are several. MIPS only (`archs`). The judge decides every child.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'byte_mask_halfword_local'
FAMILIES = (FAMILY,)
_DECL = re.compile(rf'(?m)(?<=[;{{}}\n])(?P<lead>[ \t]*)(?P<type>u8|unsigned\s+char|unsigned\s+int|unsigned|u32|s32|int)'
                   rf'\s+(?P<name>{IDENT})\s*;')
_WIDE = {'unsigned int', 'unsigned', 'u32', 's32', 'int'}


def _mask(text):
    """`E & M` at the top level of `text` (M below 0x100), as (E, M), or None."""
    depth, at = 0, None
    for i, char in enumerate(text):
        depth += (char == '(') - (char == ')')
        if depth == 0 and char == '&' and text[i + 1:i + 2] != '&' and text[i - 1:i] != '&':
            at = i
    if at is None:
        return None
    left, right = text[:at].strip(), text[at + 1:].strip()
    if not left or not re.fullmatch(NUMBER, right):
        return None
    value = int(re.sub(r'[uUlL]+$', '', right), 0)
    return (left, right) if 0 < value < 0x100 else None


def _group(text):
    """The inside of `text` when all of it is one parenthesised group."""
    text = text.strip()
    if not text.startswith('('):
        return None
    depth = 0
    for i, char in enumerate(text):
        depth += (char == '(') - (char == ')')
        if depth == 0:
            return text[1:i] if i == len(text) - 1 else None
    return None


def _byte_of(rhs):
    """(E, M) for `(E & M) & 0xFF` or `(u8) (E & M)`; ('', name) for `T & 0xFF` with T a plain name."""
    rhs = rhs.strip()
    cast = re.match(r'\(\s*(?:u8|unsigned\s+char)\s*\)\s*', rhs)
    if cast:
        inner = _group(rhs[cast.end():])
        return _mask(inner) if inner is not None else None
    hit = re.fullmatch(r'(?P<e>.*?)\s*&\s*(?:0[xX]0*[fF]{2}|255)[uU]?', rhs, re.S)
    if not hit:
        return None
    inner = _group(hit['e'])
    if inner is not None:
        return _mask(inner)
    return ('', hit['e']) if re.fullmatch(IDENT, hit['e']) else None


def _statements(part, name):
    for hit in re.finditer(rf'(?<![\w.>]){re.escape(name)}\s*=(?!=)\s*(?P<rhs>[^;{{}}]*);', part.clean):
        if part.opening < hit.start() < part.end:
            yield hit


def _staged(part, temp, before):
    """The statement `temp = E & M;` that a `v = temp & 0xFF;` at `before` reads, when nothing else reads it."""
    sets = [hit for hit in _statements(part, temp) if hit.end() <= before]
    if not sets:
        return None
    last = sets[-1]
    between = part.clean[last.end():before]
    if re.search(rf'(?<![\w.>]){re.escape(temp)}\b', between) or '{' in between or '}' in between:
        return None
    mask = _mask(part.source[last.start('rhs'):last.end('rhs')])
    if not mask:
        return None
    after = part.clean[before:part.end]
    later = re.search(rf'(?<![\w.>]){re.escape(temp)}\b(?P<set>\s*=(?!=))?', after[after.index(';') + 1:])
    if later and not later['set']:
        return None
    return last, mask


def _rewrite(source, name):
    """All byte-mask locals as halfwords set through `(u8)`, with the edits and the names, or None."""
    part = view(source, name)
    if not part:
        return None
    decls = {d['name']: d for d in _DECL.finditer(part.clean, part.opening, part.end)}
    edits, names = [], []
    for var, decl in decls.items():
        if re.search(rf'&\s*{re.escape(var)}\b|(?<![\w.>]){re.escape(var)}\s*(?:\+\+|--|[-+*/%&|^]=|<<=|>>=)',
                     part.clean[part.opening:part.end]):
            continue
        local = []
        for hit in _statements(part, var):
            rhs = part.source[hit.start('rhs'):hit.end('rhs')]
            found = _byte_of(rhs)
            if not found or (re.match(r'\(\s*(?:u8|unsigned\s+char)\s*\)', rhs) and decl['type'] in _WIDE):
                continue  # a wide local set through `(u8)` is a copy (`_copies`), not a byte local
            if found[0] == '':
                staged = _staged(part, found[1], hit.start())
                if not staged or staged[0].start() < decl.end():
                    continue
                stage, (expr, mask) = staged
                local.append((stage.start(), stage.end() + _space(part.clean, stage.end()), ''))
                local.append((hit.start('rhs'), hit.end('rhs'), f'(u8) ({expr} & {mask})'))
            else:
                expr, mask = found
                local.append((hit.start('rhs'), hit.end('rhs'), f'(u8) ({expr} & {mask})'))
        if local:
            edits += local + [(decl.start('type'), decl.end('type'), 'u16')]
            names.append(var)
    return (edits, names, part) if names else None


def _space(clean, at):
    """The blanks after a removed statement up to the next one on its line."""
    gap = re.match(r'[ \t]*', clean[at:])
    return gap.end() if gap else 0


def _copies(part, names):
    """`(u8)` dropped from wide copies `L = (u8) (V & K);` of a retyped local."""
    out = []
    for decl in _DECL.finditer(part.clean, part.opening, part.end):
        if decl['type'] not in _WIDE or decl['name'] in names:
            continue
        for hit in _statements(part, decl['name']):
            rhs = part.source[hit.start('rhs'):hit.end('rhs')]
            cast = re.match(r'\(\s*(?:u8|unsigned\s+char)\s*\)\s*', rhs)
            if cast and _group(rhs[cast.end():]) is not None and any(
                    re.search(rf'(?<![\w.>]){re.escape(n)}\b', rhs) for n in names):
                out.append((hit.start('rhs'), hit.start('rhs') + cast.end(), ''))
    return out


def _results(part, names):
    """`int`/`s32` locals set from a retyped local and only stored through `(s16 *)`/`(u16 *)`, as `s16`."""
    out = []
    body = part.clean[part.opening:part.end]
    for decl in _DECL.finditer(part.clean, part.opening, part.end):
        if decl['type'] not in ('int', 's32') or decl['name'] in names:
            continue
        var = re.escape(decl['name'])
        sets = list(_statements(part, decl['name']))
        if not sets or not all(any(re.search(rf'(?<![\w.>]){re.escape(n)}\b', h['rhs']) for n in names) for h in sets):
            continue
        reads = [r for r in re.finditer(rf'(?<![\w.>]){var}\b', body)
                 if not re.match(r'\s*=(?!=)', body[r.end():]) and part.opening + r.start() != decl.start('name')]
        if reads and all(re.search(r'\*\s*\(\s*\(\s*[su]16\s*\*\s*\)[^;=]*\)\s*=\s*$', body[:r.start()])
                         and re.match(r'\s*;', body[r.end():]) for r in reads):
            out.append((decl.start('type'), decl.end('type'), 's16'))
    return out


def variants(source, name):
    found = _rewrite(source, name)
    if not found:
        return []
    edits, names, part = found
    copies, results = _copies(part, names), _results(part, names)
    out = [edit(source, edits), edit(source, edits + copies), edit(source, edits + copies + results)]
    if len(names) > 1:
        for one in names:
            single = _rewrite(source, name)
            mine = [e for e in single[0] if _owner(part, e, one, names)]
            own_copies, own_results = _copies(part, [one]), _results(part, [one])
            out.append(edit(source, mine + own_copies + own_results))
    return [(FAMILY, child) for child in dict.fromkeys(out) if child != source]


def _owner(part, change, one, names):
    """Whether an edit from `_rewrite` belongs to the local `one` (its declaration or one of its statements)."""
    start = change[0]
    text = part.clean[start:start + 400]
    declared = re.match(rf'(?:u8|unsigned\s+char|unsigned\s+int|unsigned|u32|s32|int)\s+{re.escape(one)}\s*;', text)
    if declared:
        return True
    head = part.clean[:start]
    statement = re.search(rf'(?<![\w.>])({IDENT})\s*=(?!=)\s*$', head)
    if statement:
        return statement.group(1) == one
    # A removed staging statement belongs to the local set right after it.
    following = re.match(rf'[^;]*;\s*(?P<v>{IDENT})\s*=', text)
    return bool(following) and following['v'] == one


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
