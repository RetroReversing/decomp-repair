"""Which cases of a big switch share a temporary: split one local per case, or merge locals that never meet.

m2c and hand drafts declare every temporary once at the top, so a `u32 temp_a2;` that several cases of one switch use
is one pseudo register for the whole function. The original compiler saw whatever the programmer wrote, and for the
same value that can be one local per case (the allocator numbers each case's pseudo separately and each gets its own
live range) or a few locals shared by cases that never overlap (one pseudo, one quantity, tied by the allocator's
copy preferences). Neither is visible in the bytes except through which registers come out, and a 2,400-instruction
function with 37 cases moved from 275 differing instructions to 13 by getting this right case by case.

Only locals whose every use in a case starts with a plain assignment are touched: the first mention of the local in
that case is `name = expression;` at the case's own nesting level, with no mention of `name` on the right. Then no
value flows between cases through it, so renaming it per case (or giving two such locals one name) cannot change
the program. Anything else leaves the function alone: a local that is also used outside the switch, whose address
is taken, that is declared with an initialiser or as an array; a switch with a label inside it (`goto` into a case);
a `case` label nested in a block (Duff's device). `variants` gives:

  case_temporary_split  one local used by several cases, renamed in all of them (a new local per case), or in one
                        case alone (the others keep the original)
  case_temporary_merge  two locals of one type whose cases are disjoint, the second renamed to the first
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

SPLIT = 'case_temporary_split'
MERGE = 'case_temporary_merge'
FAMILIES = (SPLIT, MERGE)
LIMIT = 24

LABEL = re.compile(r'(?m)^[ \t]*(?:case\b[^:;{}\n]*|default)[ \t]*:(?!:)')
GOTO_LABEL = re.compile(r'(?m)^[ \t]*(?!(?:case|default)\b)([A-Za-z_]\w*)[ \t]*:(?!:)')
DECLARATION = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<type>(?!(?:return|goto|else|case|default|break|continue)\b)'
                         r'[A-Za-z_][\w \t]*?[ \t*]+)(?P<name>[A-Za-z_]\w*)[ \t]*;[ \t]*\n')


def _mentions(name):
    return re.compile(r'(?<![\w.])(?<!->)' + re.escape(name) + r'\b')


def _depth_at(clean, start, pos):
    text = clean[start:pos]
    return text.count('{') - text.count('}')


def _switches(clean, opening, end):
    """(body start, body end) of every switch in the function; the brace positions themselves."""
    out = []
    for m in re.finditer(r'\bswitch\s*\(', clean[opening:end]):
        at = opening + m.end() - 1
        stop = close(clean, at, '(', ')')
        if not stop:
            continue
        brace = clean.find('{', stop)
        if brace < 0 or clean[stop:brace].strip():
            continue
        finish = close(clean, brace, '{', '}')
        if finish:
            out.append((brace, finish))
    return out


def _groups(clean, body, nested):
    """[(label text, start, end)] of the switch's top-level case groups; None when the switch is not plain."""
    start, finish = body
    if any(m.group(1) for m in GOTO_LABEL.finditer(clean, start + 1, finish) if not any(a < m.start() < b for a, b in nested)):
        return None
    labels = []
    for m in LABEL.finditer(clean, start + 1, finish):
        if any(a < m.start() < b for a, b in nested):
            continue
        if _depth_at(clean, start + 1, m.start()) != 0:
            return None  # a case label inside a block
        labels.append(m)
    groups = []
    for k, m in enumerate(labels):
        stop = labels[k + 1].start() if k + 1 < len(labels) else finish
        groups.append((m.group().strip().rstrip(':').strip(), m.end(), stop))
    return groups


def _eligible(clean, name, group_spans, outside):
    """The indexes of the groups using `name`, or None when some use does not start with a dominating assignment."""
    pattern = _mentions(name)
    if any(pattern.search(clean, a, b) for a, b in outside):
        return None
    if re.search(r'&\s*' + re.escape(name) + r'\b', clean):
        return None
    used = []
    for k, (_, a, b) in enumerate(group_spans):
        first = pattern.search(clean, a, b)
        if not first:
            continue
        before = clean[a:first.start()].rstrip()
        if before and before[-1] not in ';{}:' or _depth_at(clean, a, first.start()) != 0:
            return None
        statement_end = clean.find(';', first.end())
        assign = re.match(r'\s*=(?!=)', clean[first.end():statement_end if statement_end >= 0 else b])
        if not assign or statement_end < 0 or pattern.search(clean, first.end() + assign.end(), statement_end):
            return None
        used.append(k)
    return used or None


def _rename(source, clean, spans, old, new):
    pattern = _mentions(old)
    edits = [m.span() for a, b in spans for m in pattern.finditer(clean, a, b)]
    for a, b in sorted(edits, reverse=True):
        source = source[:a] + new + source[b:]
    return source


def _identifiers(source):
    return set(re.findall(r'[A-Za-z_]\w*', source))


def _fresh(var, label, k, taken):
    """`var` plus the case's label (`temp_a2_0x16`, `temp_a2_default`), or its number, never a name already in use."""
    text = re.sub(r'\W+', '_', re.sub(r'^case\b', '', label).strip()).strip('_')
    name = f'{var}_{text or k}'
    while name in taken:
        name += '_'
    return name


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    declarations = {}
    for m in DECLARATION.finditer(clean, opening + 1, end):
        if _depth_at(clean, opening + 1, m.start()) == 0 and ('(' not in m['type']):
            declarations.setdefault(m['name'], m)
    taken = _identifiers(source)
    switches = _switches(clean, opening, end)
    result = []

    def emit(family, text):
        if text != source and text not in [t for _, t in result] and len(result) < 2 * LIMIT:
            result.append((family, text))

    for body in switches:
        nested = [s for s in switches if body[0] < s[0] and s[1] < body[1]]
        groups = _groups(clean, body, nested)
        if not groups or len(groups) < 2:
            continue
        outside = [(opening, body[0]), (body[1], end)]
        uses = {}
        for var, decl in declarations.items():
            if decl.start() > body[0]:
                continue
            apart = [(a, b) for a, b in outside if not (a <= decl.start() < b)] + \
                    [piece for a, b in outside if a <= decl.start() < b
                     for piece in ((a, decl.start()), (decl.end(), b))]
            used = _eligible(clean, var, [(g[0], g[1], g[2]) for g in groups], apart)
            if used:
                uses[var] = used
        # one local per case: all together, then each case alone
        for var, used in uses.items():
            if len(used) < 2:
                continue
            decl = declarations[var]
            line = source[decl.start():decl.end()]
            names = {k: _fresh(var, groups[k][0], k, taken) for k in used}
            if len(set(names.values())) != len(names):
                continue
            plans = [('all', used)] + [('one', [k]) for k in used]
            for kind, chosen in plans:
                text, created = source, []
                # right to left, so earlier offsets stay valid
                for k in sorted(chosen, reverse=True):
                    text = _rename(text, _blank(text), [(groups[k][1], groups[k][2])], var, names[k])
                    # the group's offsets are unchanged to its left; renames to the right already happened
                    created.append(names[k])
                cut = line.rindex(var)
                new_lines = ''.join(line[:cut] + n + line[cut + len(var):] for n in reversed(created))
                if kind == 'all':
                    text = text[:decl.start()] + new_lines + text[decl.end():]
                else:
                    text = text[:decl.end()] + new_lines + text[decl.end():]
                emit(SPLIT, text)
        # two locals that never share a case, one name for both
        order = list(uses)
        for i, first in enumerate(order):
            for second in order[i + 1:]:
                if set(uses[first]) & set(uses[second]):
                    continue
                kind_a = re.sub(r'\s+', ' ', declarations[first]['type']).strip()
                kind_b = re.sub(r'\s+', ' ', declarations[second]['type']).strip()
                if kind_a != kind_b:
                    continue
                decl = declarations[second]
                text = _rename(source, clean, [(groups[k][1], groups[k][2]) for k in uses[second]], second, first)
                emit(MERGE, text[:decl.start()] + text[decl.end():])
    split = [r for r in result if r[0] == SPLIT][:LIMIT]
    merge = [r for r in result if r[0] == MERGE][:LIMIT]
    return split + merge
