"""A word local that is read through `& 0xFF` or `& 0xFFFF`, declared as the byte or halfword those reads show.

m2c declares every local as a word and writes the zero-extension the target does at each use:

    u32 edge;
    edge = roll() >> 13;
    switch (edge & 0xFFFF) ...        table[(edge & 0xFFFF) * 8]

The game's local was `u16 edge;`: the compiler then writes the same `andi` before each use, `srl` for the shift that
fills it, and gives the pseudo the saved register the word form does not. On a 187-instruction N64 object spawner
(`sn-n64-281 -O2 -mips3`) this alone took a draft 2660 -> 655, and no family offered it: `masked_local_narrow` handles
a local that is *set* from a mask, `wide_local_to_halfword` does not drop the reads' masks.

Offered only when the meaning is unchanged: a plain integer local (declared once, no initialiser, not `volatile`, its
address never taken, no compound assignment, `++` or `--`) with at least one read `v & M` (M is 0xFF or 0xFFFF), where
every other read is part of a value that is masked again (`(v + 1) & 3`) or follows, as the nearest assignment before
it in the text, `v = E & K;` with K no wider than M.

A word local that only holds that read (`t = v & M;`, every assignment of `t`) is a copy of `v` once `v` is narrow:
where `v` is not assigned again after the first copy, a child also writes `v` for `t` (the switch on `t` kept the
extension ahead of the dispatch; 1635 with the copies, exact without them after the other steps).

`variants` gives, labelled `masked_read_local_narrow`, one child per such local (with and without its copies) and one
with all of them.
"""
import re

from .case_temporary_repairs import DECLARATION, _mentions
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'masked_read_local_narrow'
FAMILIES = (FAMILY,)
LIMIT = 8
WORD_TYPES = ('s32', 'int', 'u32', 'unsigned int', 'signed int', 'long', 'unsigned long', 'unsigned')
WIDTHS = {0xFF: 'u8', 0xFFFF: 'u16'}
NUMBER = r'(?P<{0}>0[xX][0-9a-fA-F]+|\d+)[uUlL]*'
READ = re.compile(r'\s*&\s*' + NUMBER.format('mask') + r'(?![\w.])')
MASKED_ASSIGN = re.compile(r'\s*=(?!=)[^;{}]*?&\s*' + NUMBER.format('mask') + r'\s*;')
REMASKED = re.compile(r'\s*(?:[-+*|^]\s*\w+\s*)*\)\s*&\s*' + NUMBER.format('mask') + r'(?![\w.])')


def _narrow(clean, var, opening, end, decl):
    """(type, [(start, stop) of each `& M` to drop]) or None."""
    kind = re.sub(r'\s+', ' ', re.sub(r'\b(?:register|signed)\b', '', decl['type'])).strip()
    if kind not in WORD_TYPES or '*' in decl['type'] or '[' in clean[decl.start():decl.end()]:
        return None
    reads, others, assigns = [], [], []
    for m in _mentions(var).finditer(clean, opening + 1, end):
        if decl.start() <= m.start() < decl.end():
            continue
        before = clean[max(opening, m.start() - 40):m.start()].rstrip()
        after = clean[m.end():end]
        if before.endswith('&') and not before.endswith('&&') and re.search(r'(?:^|[(,=;{}?:])\s*&$', before):
            return None  # address taken
        if re.match(r'\s*(?:\+\+|--|(?:[-+*/%|&^]|<<|>>)=)', after) or before.endswith(('++', '--')):
            return None
        if re.match(r'\s*=(?!=)', after):
            if not re.search(r'(?:^|[;{}])$', before):
                return None
            hit = MASKED_ASSIGN.match(after)
            assigns.append((m.start(), int(hit['mask'], 0) if hit else None))
            continue
        hit = READ.match(after)
        # `v & M` is a read of v alone only when nothing binds v tighter on its left
        if hit and int(hit['mask'], 0) in WIDTHS and (before[-1:] in '(=,[{;' or before.endswith('return')):
            reads.append((m.end(), m.end() + hit.end(), int(hit['mask'], 0)))
        else:
            others.append((m.start(), m.end()))
    if not reads or len({mask for _, _, mask in reads}) != 1:
        return None
    mask = reads[0][2]
    for start, stop in others:
        again = REMASKED.match(clean, stop, end)
        if again and int(again['mask'], 0) <= mask:
            continue
        earlier = [value for at, value in assigns if at < start]
        if not earlier or earlier[-1] is None or earlier[-1] > mask:
            return None
    return WIDTHS[mask], [(start, stop) for start, stop, _ in reads]


def _without_copies(text, name, var):
    """`text` (with `var` already narrow) with each word local that only copies `var` written as `var`, or None."""
    clean = _blank(text)
    span = find(text, name)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}')
    edits = []
    for decl in DECLARATION.finditer(clean, opening + 1, end):
        copy = decl['name']
        if copy == var or re.sub(r'\s+', ' ', decl['type']).strip() not in WORD_TYPES:
            continue
        mentions = [m for m in _mentions(copy).finditer(clean, opening + 1, end)
                    if not decl.start() <= m.start() < decl.end()]
        statement = re.compile(rf'(?<![\w.>]){copy}\s*=\s*\(?\s*{var}\s*\)?\s*;')
        sets, reads = [], []
        for m in mentions:
            found = statement.match(clean, m.start())
            if found:
                sets.append((found.start(), found.end()))
            elif re.match(r'\s*(?:=(?!=)|\+\+|--|(?:[-+*/%|&^]|<<|>>)=)', clean[m.end():end]) or \
                    clean[:m.start()].rstrip().endswith(('++', '--')) or re.search(r'[(,=]\s*&$', clean[:m.start()].rstrip()):
                reads = None
                break
            else:
                reads.append((m.start(), m.end()))
        if not sets or not reads or reads[0][0] < sets[0][0]:
            continue
        later = clean[sets[0][1]:end]
        if re.search(rf'(?<![\w.>]){var}\s*(?:=(?!=)|\+\+|--|(?:[-+*/%|&^]|<<|>>)=)', later):
            continue
        edits += [(a, b, '') for a, b in sets] + [(a, b, var) for a, b in reads]
        edits.append((decl.start('type'), clean.index(';', decl.end('name')) + 1, ''))
    if not edits:
        return None
    for start, stop, new in sorted(edits, reverse=True):
        if not new:  # a removed statement takes its line with it
            left, right = text.rfind('\n', 0, start) + 1, text.find('\n', stop)
            if right >= 0 and not text[left:start].strip() and not text[stop:right].strip():
                start, stop = left, right + 1
        text = text[:start] + new + text[stop:]
    return text


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    names = {}
    for m in DECLARATION.finditer(clean, opening + 1, end):
        names[m['name']] = None if m['name'] in names else m
    changes, narrowed = [], []
    for var, decl in names.items():
        if decl is None:
            continue
        found = _narrow(clean, var, opening, end, decl)
        if found:
            kind = ('register ' if 'register' in decl['type'] else '') + found[0]
            edits = [(decl.start('type'), decl.start('name'), kind + ' ')] + [(a, b, '') for a, b in found[1]]
            changes.append(edits)
            narrowed.append(var)
    if not changes:
        return []

    def apply(edits):
        text = source
        for start, stop, new in sorted(edits, reverse=True):
            text = text[:start] + new + text[stop:]
        return text

    result = []
    for edits, var in list(zip(changes, narrowed))[:LIMIT - 1]:
        text = apply(edits)
        copied = _without_copies(text, name, var)
        result += ([(FAMILY, copied)] if copied else []) + [(FAMILY, text)]
    if len(changes) > 1:
        result.append((FAMILY, apply(sum(changes, []))))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
