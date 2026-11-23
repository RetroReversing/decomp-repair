"""Per-block locals of repeated straight-line blocks written as one scratch variable per role.

A function that does the same arithmetic for three axes (a cubic's coefficients for x, y and z, a colour's three
channels, a vertex's three offsets) is written in the original with one scratch variable per role that every block
assigns again: `a = ...; b = ...; c = ...;` three times, each block then storing what it derived. A draft names every
value of every block (`ax, bx, cx, ay, by, cy, az, bz, cz`), and each name is its own pseudo. The compiler sees a
different program for the same text: the three `a`s are ONE multi-set pseudo that the scheduler may not move across the
neighbouring block (the anti-dependence keeps x before y before z, where nine independent pseudos interleave the blocks
and keep every block's results live to the end), and that global.c, not local-alloc.c, gives a register (the same
callee-saved float register in all three blocks, `$f28`, `$f30`, `$f26`, as the target shows).

Measured on a 163-instruction float function of that shape (KMC gcc 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) whose saved
best was 8465: merging the nine coefficient locals into three and writing the derived values (`out->d = a + b + c;`) at
the point they are computed gave 3846, and with the derived values' own locals gone (the nine more pseudos the target
does not have) 4, then an exact match once the stores were written at the point of the computation. The two edits pay
off together: the merge alone leaves the derived values in more locals that are stored at the end, and the direct
stores alone leave the nine coefficients independent. So the combination is its own child.

What is offered, for the scalar locals declared at the head of the function:

* locals that differ only by an axis or counter suffix (`ax`, `ay`, `az`; `val_1`, `val_2`; m2c's `temp_2`) form a role;
  each member must start with a plain assignment (`name = ...;`, not reading itself), and the members' mentions must
  not overlap (the last mention of one before the first mention of the next); a function with a loop, a `goto`, a
  `switch` or a `volatile` is left alone, because the order of the text is then not the order of the values;
* `repeated_block_scratch_reuse`: every role merged at once into one variable (named by the role when that name is free);
* `repeated_block_scratch_reuse_role`: one role alone, when there is more than one;
* `repeated_block_scratch_reuse_direct`: every role merged, and each local that is assigned once from a pure expression
  and stored by a later whole-statement `lhs = local;` assigned straight into that store (its other reads take the
  expression in parentheses).

A candidate rewrite; the exact judge decides. The direct stores move a store earlier, so the output must not alias the
inputs.
"""
import re

from .csource import _blank, find

FAMILY = 'repeated_block_scratch_reuse'
ROLE_FAMILY = 'repeated_block_scratch_reuse_role'
DIRECT_FAMILY = 'repeated_block_scratch_reuse_direct'
FAMILIES = (FAMILY, ROLE_FAMILY, DIRECT_FAMILY)
MAX_ROLES = 6

IDENT = r'[A-Za-z_]\w*'
NAMED = r'(?<![\w.>])' + IDENT  # a name, not a member after `.` or `->`
SCALAR = (r'(?:f32|f64|float|double|s8|u8|s16|u16|s32|u32|s64|u64|char|short|int|long|'
          r'unsigned\s+(?:char|short|int|long)|signed\s+(?:char|short|int|long))')
DECLARATION = re.compile(rf'(?P<type>(?:{SCALAR})\b|{IDENT})[ \t]+(?P<rest>[A-Za-z_*][^;{{}}]*);[ \t]*\n?')
NOT_A_TYPE = {'return', 'goto', 'else', 'case', 'break', 'continue', 'default', 'sizeof'}
SUFFIX = re.compile(r'(?:_?\d+|[xyzXYZ])$')
BLOCKERS = re.compile(r'\b(?:for|while|do|goto|switch|volatile)\b')


def _function(source, name):
    """(clean, offset of the body's `{`, end of the function, start of the function) or None."""
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    head = re.search(r'\b' + re.escape(name) + r'\s*\([^{};]*\)\s*{', clean[span[0]:span[1]])
    if not head:
        return None
    return clean, span[0] + head.end() - 1, span[1], span[0]


def _declared(clean, opening, end):
    """[(type, [names], (start, stop))] for the declarations that head the body; a declaration with an initialiser, a
    pointer or an array is stepped over with no names (its text is never edited). Each span runs from the first
    character of the statement to just past its line's end."""
    found = []
    position = opening + 1
    while True:
        start = re.compile(r'\s*').match(clean, position, end).end()
        match = DECLARATION.match(clean, start, end)
        if not match or match['type'].split()[0] in NOT_A_TYPE or match['rest'].lstrip().startswith(('=', '(')):
            return found
        rest = match['rest']
        names = [n.strip() for n in rest.split(',')]
        plain = all(re.fullmatch(IDENT, n) for n in names) and re.fullmatch(SCALAR, re.sub(r'\s+', ' ', match['type']))
        found.append((re.sub(r'\s+', ' ', match['type']), names if plain else [], match.span()))
        position = match.end()


def _mentions(clean, name, start, end):
    return [start + m.start() for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', clean[start:end])
            if not re.match(r'\s*:(?!:)', clean[start + m.end():end])]


def _begins_assignment(clean, name, at, end):
    """Whether the mention at `at` starts the statement `name = value;` and the value does not read `name`."""
    before = clean[max(0, at - 60):at]
    if not re.search(r'(?:^|[;{}])\s*$', before):
        return False
    tail = clean[at + len(name):end]
    assign = re.match(r'\s*=(?!=)', tail)
    if not assign or ';' not in tail:
        return False
    return re.search(rf'(?<![\w.>]){re.escape(name)}\b', tail[assign.end():tail.find(';')]) is None


def _roles(clean, start, opening, end, declared):
    """[(type, stem, [members in order])] for the roles whose members' mentions never overlap."""
    if not declared or BLOCKERS.search(clean[start:end]):
        return []
    first = declared[-1][2][1]
    types = {}
    for kind, names, _ in declared:
        for name in names:
            types[name] = kind
    groups = {}
    for name, kind in types.items():
        groups.setdefault((kind, SUFFIX.sub('', name) or name), []).append(name)
    roles = []
    for (kind, stem), names in groups.items():
        if len(names) < 2:
            continue
        spans = []
        for name in names:
            hits = _mentions(clean, name, first, end)
            if not hits or not _begins_assignment(clean, name, hits[0], end):
                break
            spans.append((hits[0], hits[-1], name))
        else:
            spans.sort()
            if all(spans[i][1] < spans[i + 1][0] for i in range(len(spans) - 1)):
                roles.append((spans[0][0], kind, stem, [name for _, _, name in spans]))
    return [role[1:] for role in sorted(roles)]


def _apply(source, edits):
    for start, stop, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[stop:]
    return source


def _merged(source, name, chosen):
    """`source` with each role in `chosen` written as one variable, or None."""
    body = _function(source, name)
    if not body:
        return None
    clean, opening, end, start = body
    declared = _declared(clean, opening, end)
    used = set(re.findall(IDENT, clean[opening:end]))
    rename = {}
    for kind, stem, members in chosen:
        survivor = stem if stem in members or stem not in used else members[0]
        used.add(survivor)
        rename.update({member: survivor for member in members})
    edits = []
    seen = set()
    for kind, names, (start, stop) in declared:
        if not names:
            continue
        kept = []
        for declared_name in names:
            target = rename.get(declared_name, declared_name)
            if target not in seen:
                seen.add(target)
                kept.append(target)
        edits.append((start, stop, f'{kind} {", ".join(kept)};\n' if kept else ''))
    for member, survivor in rename.items():
        if member != survivor:
            edits += [(at, at + len(member), survivor)
                      for at in _mentions(clean, member, declared[-1][2][1], end)]
    return _apply(source, edits)


def _statements(clean, start, end):
    spans = []
    position = start
    while True:
        stop = clean.find(';', position, end)
        if stop < 0:
            return spans
        spans.append((position, stop + 1))
        position = stop + 1


def _direct_one(source, name):
    """The source with the first local that can be written straight into its store so, or None."""
    body = _function(source, name)
    if not body:
        return None
    clean, opening, end, start = body
    declared = _declared(clean, opening, end)
    if not declared:
        return None
    statements = _statements(clean, declared[-1][2][1], end - 1)
    text = [clean[a:b] for a, b in statements]
    for _, names, _ in declared:
        for local in names:
            sets = [i for i, t in enumerate(text) if re.match(rf'\s*{re.escape(local)}\s*=(?!=)', t)]
            stores = [i for i, t in enumerate(text)
                      if re.fullmatch(rf'\s*[^=;]*(?:->|\[)[^=;]*=\s*{re.escape(local)}\s*;', t)]
            if len(sets) != 1 or len(stores) != 1 or stores[0] < sets[0]:
                continue
            value = re.match(rf'\s*{re.escape(local)}\s*=\s*(?P<value>[^;]*);', text[sets[0]])['value'].strip()
            if re.search(rf'{IDENT}\s*\(|=|\+\+|--', value):
                continue
            lhs = re.fullmatch(rf'\s*(?P<lhs>[^=;]*?)\s*=\s*{re.escape(local)}\s*;', text[stores[0]])['lhs']
            reads = [i for i, t in enumerate(text)
                     if i not in (sets[0], stores[0]) and _mentions(t, local, 0, len(t))]
            if any(i < sets[0] for i in reads):
                continue
            used = set(re.findall(NAMED, value))
            # the expression is written again where the other reads are: its operands must still hold their values
            # there; the store itself moves up to the assignment, where they do
            span = range(sets[0] + 1, max(reads + [sets[0]]) + 1)
            guarded = used if reads else set()
            if any(re.match(rf'\s*{re.escape(u)}\s*=(?!=)', text[i]) for u in guarded for i in span if i != stores[0]):
                continue
            if any(re.match(rf'\s*{re.escape(u)}\s*=(?!=)', text[i])
                   for u in set(re.findall(NAMED, lhs)) for i in range(sets[0], stores[0])):
                continue
            wrapped = value if re.fullmatch(r'[\w.]+', value) else f'({value})'
            a, b = statements[sets[0]]
            lead = re.match(r'\s*', source[a:b])[0]
            edits = [(a, b, f'{lead}{lhs} = {value};'), statements[stores[0]] + ('',)]
            for i in reads:
                ra, rb = statements[i]
                edits += [(at, at + len(local), wrapped) for at in _mentions(clean, local, ra, rb)]
            for kind, declared_names, (start, stop) in declared:
                if local in declared_names:
                    kept = [n for n in declared_names if n != local]
                    edits.append((start, stop, f'{kind} {", ".join(kept)};\n' if kept else ''))
            return re.sub(r'\n[ \t]*\n(?=[ \t]*\S)', '\n', _apply(source, edits))
    return None


def _direct(source, name):
    """Every local that is assigned once from a pure expression and stored by a later `lhs = local;`, assigned into
    the store instead."""
    for _ in range(64):
        step = _direct_one(source, name)
        if step is None or step == source:
            break
        source = step
    return source


def variants(source, name):
    body = _function(source, name)
    if not body:
        return []
    clean, opening, end, start = body
    roles = _roles(clean, start, opening, end, _declared(clean, opening, end))
    if not roles:
        return []
    out = []
    merged = _merged(source, name, roles)
    if merged and merged != source:
        out.append((FAMILY, merged))
        direct = _direct(merged, name)
        if direct != merged:
            out.append((DIRECT_FAMILY, direct))
    if len(roles) > 1:
        for role in roles[:MAX_ROLES]:
            one = _merged(source, name, [role])
            if one and one != source:
                out.append((ROLE_FAMILY, one))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
