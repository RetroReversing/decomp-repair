"""Two locals that always hold the same value (each set is followed by a copy into the other), a read moved between them.

m2c names each register of a value and writes the copies it sees: an effect spawner keeps a screen size twice
(`width = 160.0f; var_fs2 = width;` at entry, `width = (var_fs2 = 80.0f);` and `var_fs2 = 80.0f; ...; width = var_fs2;`
in a switch's arms), and its reads name one or the other the way the draft's registers happened to fall. Which variable
a read names decides each pseudo's references and live length, so global.c's order between the two (floor_log2(refs) *
refs / live), and which register of the pair cse keeps the constant in. On the spawner (KMC GCC 2.7.2) the reads chosen
for the vertical pair took 85 -> 80 and, with the entry's constant set apart from its copy, 80 -> 70.

Taken only when the pair really is one value at every read: every assignment to either local is completed by the
copy into the other before anything else mentions them, in the same straight-line run (no brace, label, jump or
`if` between), or is the nested `a = (b = x);`; the first mention of either is such an assignment; neither has its
address taken. With up to six reads every assignment of them to the two names is offered, and the pairs' assignments
together when that stays within `PRODUCT` children (the spawner's two dimensions only paid off changed at once);
with more reads, each read alone. The judge decides; the values read are the same either way.
"""
import itertools
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'copy_pair_read_switch'
FAMILIES = (FAMILY,)
LIMIT = 600
PRODUCT = 600  # children when the pairs' combinations are taken together
COMBINE = 6  # reads per pair up to which every combination is offered (2**6 children)
_DECL = re.compile(rf'(?m)^[ \t]*(?:register[ \t]+)?(?P<type>(?:unsigned[ \t]+)?(?:s8|u8|s16|u16|s32|u32|f32|f64|int|float|double))'
                   rf'[ \t]+(?P<name>{IDENT})[ \t]*;')
_BARRIER = re.compile(r'[{}]|\b(?:if|else|goto|return|break|continue|case|default|switch|while|for|do)\b|^\s*\w+\s*:', re.M)


def _mentions(clean, start, end, a, b):
    """[(position, name, kind, partner end)] of every mention of a or b: kind 'set' (`x = ...`), 'copy' (`x = y;`),
    'nested' (`x = (y = ...)`), 'read'."""
    out = []
    for hit in re.finditer(rf'(?<![\w.>]){re.escape(a)}\b|(?<![\w.>]){re.escape(b)}\b', clean[start:end]):
        at = start + hit.start()
        name = hit[0]
        other = b if name == a else a
        rest = clean[at + len(name):]
        if re.match(r'\s*=(?!=)', rest):
            value = re.match(r'\s*=\s*([^;]*);', rest)
            text = value[1].strip() if value else ''
            if re.fullmatch(rf'\(?\s*{re.escape(other)}\s*\)?', text):
                out.append((at, name, 'copy'))
            elif re.match(rf'\(\s*{re.escape(other)}\s*=(?!=)', text):
                out.append((at, name, 'nested'))
            else:
                out.append((at, name, 'set'))
        elif re.match(r'\s*(?:[-+*/%&|^]|<<|>>)=|\s*\+\+|\s*--', rest) or re.search(r'(?:\+\+|--|&)\s*$', clean[:at]):
            out.append((at, name, 'other'))
        else:
            out.append((at, name, 'read'))
    return out


def _one_value(clean, mentions):
    """The read positions when the pair is one value at every read (module docstring), else None."""
    reads, pending, skip = [], None, set()
    for index, (at, name, kind) in enumerate(mentions):
        if index in skip:
            continue
        if kind == 'other':
            return None
        if pending is not None:
            if kind != 'copy' or name == pending[1] or _BARRIER.search(clean[pending[0]:at]):
                return None
            pending = None
            skip.add(index + 1)  # the copy's source operand
            continue
        if kind == 'nested':
            # `x = (y = ...)`: the inner mention of y follows as a set
            if index + 1 >= len(mentions) or mentions[index + 1][1] == name:
                return None
            skip.add(index + 1)
            continue
        if kind == 'set':
            pending = (at, name)
            continue
        if kind == 'copy':
            if index == 0:
                return None
            skip.add(index + 1)
            continue
        if index == 0:
            return None
        reads.append((at, name))
    return reads if pending is None else None


def _leading_declarations_end(part):
    pos = part.clean.find('\n', part.opening) + 1
    while pos < part.end:
        line_end = part.clean.find('\n', pos)
        line = part.clean[pos:line_end if line_end >= 0 else part.end]
        if line.strip() and not re.fullmatch(r'\s*(?:register\s+|const\s+|volatile\s+|unsigned\s+|signed\s+)*[A-Za-z_]\w*'
                                             r'(?:\s*\*+\s*|\s+)[A-Za-z_]\w*(?:\s*\[[^\]]*\])?\s*;\s*', line):
            return pos
        pos = (line_end if line_end >= 0 else part.end) + 1
    return pos


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = part.clean[part.opening:part.end]
    declared = {}
    for hit in _DECL.finditer(body):
        declared.setdefault(hit['type'], []).append(hit['name'])
    pairs = []
    for type_, names in declared.items():
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                if re.search(rf'&\s*(?:{re.escape(a)}|{re.escape(b)})\b', body):
                    continue
                decl_end = _leading_declarations_end(part)
                mentions = _mentions(part.clean, decl_end, part.end, a, b)
                if len(mentions) < 4 or not any(k == 'read' for _, _, k in mentions):
                    continue
                reads = _one_value(part.clean, mentions)
                if reads:
                    pairs.append((a, b, reads))
    out = []
    options = []
    for a, b, reads in pairs:
        if len(reads) <= COMBINE:
            # every assignment of the reads to the two names: the allocator's order comes from all of them at once
            choices = []
            for choice in itertools.product((a, b), repeat=len(reads)):
                choices.append([(at, at + len(who), pick) for (at, who), pick in zip(reads, choice) if pick != who])
            options.append(choices)
        else:
            for at, who in reads:
                other = b if who == a else a
                out.append(edit(source, [(at, at + len(who), other)]))
    total = 1
    for choices in options:
        total *= len(choices)
    if options and total <= PRODUCT:
        # the pairs together (two screen dimensions needed both changed at once: 85 -> 80)
        for combo in itertools.product(*options):
            spans = [span for part_spans in combo for span in part_spans]
            if spans:
                out.append(edit(source, spans))
    else:
        for choices in options:
            for spans in choices:
                if spans:
                    out.append(edit(source, spans))
    return [(FAMILY, text) for text in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
