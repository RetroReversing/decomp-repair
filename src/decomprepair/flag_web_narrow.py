"""A flag local that m2c declared as a word, narrowed to the byte the game declared, with the later reuse of its name split off.

m2c (and a saved best that kept its shape) declares every local as a word: `register s32 flag;` set to `0` before a loop,
to `1` inside it, tested with `!flag`, and then, after the loop, the same name holds an unrelated number
(`flag = end - start;`). Two things in that source are wrong for the compiler this project targets, and neither one
alone changes the code:

  * One name is one pseudo register for the whole function, so the later, unrelated value adds references to the
    flag's pseudo and lengthens its live range (`local-alloc.c`/`global.c` rank saved registers by
    `floor_log2(refs) * refs / live length`). Splitting the name (`local_web_split`) alone only shifts that priority:
    555 -> 590 on a 511-instruction display function, a loss a greedy chain never takes.
  * A flag the game kept in a byte (`s8`, `char`) is a narrow pseudo: GCC 2.7 promotes it to a word register but reads it
    through a promoted subreg, so the test of it (`!flag`) is a `move` into a temporary first, which fills the delay
    slot of the branch above it (`move $v0,$s7; bnez $v0`). Written as a word the test reads the register itself. The
    type alone changes nothing while the later reuse still stores a wide number into the byte (the compiler then
    truncates it): 555 -> 590 as well.

Together they are the target's code: 555 -> 390 (the saved registers of the loop's flag and its table pointer then come
out in the target's order after one more reference on each, which `statement_scope_weight` and `local_weight_ladder`
offer). A one-step-at-a-time search cannot see it; this family writes both as one child.

Offered only when the meaning is unchanged: the flag is a plain local (no `&flag`, no `volatile`, no array) whose every
assignment in the web that keeps the name stores a literal 0..127 and whose every read is a truth test (`!flag`, `if
(flag)`, `flag == 0`, `flag != 0`, an operand of `&&`/`||`); every other assignment (a web that stores something else) is
renamed by `local_web_split`'s analysis first, so no wide value ever reaches the byte. A flag that already has no other
web is narrowed alone (a child of its own).

`variants` gives, labelled `flag_web_narrow`: for each such local, the split (when it has another web) with the flag's
declaration written `s8` (`register` kept).
"""
import re

from . import local_web_split as split
from .case_temporary_repairs import DECLARATION, _mentions
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'flag_web_narrow'
FAMILIES = (FAMILY,)
LIMIT = 12
WORD_TYPES = ('s32', 'int', 'u32', 'unsigned int', 'signed int', 'u16', 's16', 'short', 'unsigned short')
NARROW = 's8'
LITERAL = re.compile(r'\s*=(?!=)\s*(\d{1,3})[uU]?\s*;')
TESTS = (
    re.compile(r'!\s*$'),                       # `!flag`
    re.compile(r'\bif\s*\(\s*$'),               # `if (flag)` (the read is followed by `)`, checked below)
    re.compile(r'(?:&&|\|\|)\s*$'),             # `... && flag`
)
AFTER_TESTS = (
    re.compile(r'\s*(?:==|!=)\s*[01]\b'),
    re.compile(r'\s*(?:&&|\|\|)'),
)


def _flag_like(clean, var, opening, end, skip=None):
    """True when every mention of `var` in the body (its declaration `skip` apart) is a literal 0..127 assignment or a
    truth test."""
    pattern = _mentions(var)
    seen = 0
    for m in pattern.finditer(clean, opening + 1, end):
        if skip and skip.start() <= m.start() < skip.end():
            continue
        before = clean[max(opening, m.start() - 12):m.start()]
        after = clean[m.end():m.end() + 24]
        if re.match(r'\s*=(?!=)', after):
            literal = LITERAL.match(after)
            if not literal or int(literal[1]) > 127:
                return False
            seen += 1
            continue
        if re.match(r'\s*(?:\+\+|--|[-+*/|&^%]=|<<=|>>=|\[|\.|->)', after) or re.search(r'(?:\+\+|--|&)\s*$', before):
            return False
        ok = any(t.search(before) for t in TESTS[:1]) \
            or (TESTS[1].search(before) and re.match(r'\s*\)', after)) \
            or any(t.search(before) for t in TESTS[2:]) \
            or any(t.match(after) for t in AFTER_TESTS)
        if not ok:
            return False
        seen += 1
    return seen >= 2


def _declaration(clean, var, opening):
    for m in DECLARATION.finditer(clean, opening + 1):
        if m['name'] == var and clean[opening + 1:m.start()].count('{') == clean[opening + 1:m.start()].count('}'):
            return m
    return None


def _narrow(source, name, var):
    """`source` with `var`'s declaration written `s8`, or None when it is not a flag of a word type."""
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return None
    decl = _declaration(clean, var, opening)
    if not decl or 'volatile' in decl['type'] or '*' in decl['type']:
        return None
    kind = re.sub(r'\b(?:register|signed)\b', '', decl['type']).strip()
    kind = re.sub(r'\s+', ' ', kind)
    if kind not in WORD_TYPES and kind != 'unsigned int':
        return None
    if re.search(r'&\s*' + re.escape(var) + r'\b', clean[opening:end]) or not _flag_like(clean, var, opening, end, decl):
        return None
    register = 'register ' if re.search(r'\bregister\b', decl['type']) else ''
    line = f"{decl['indent']}{register}{NARROW} {var};\n"
    return source[:decl.start()] + line + source[decl.end():]


def _declared(clean, opening, end):
    names = {}
    for m in DECLARATION.finditer(clean, opening + 1, end):
        if clean[opening + 1:m.start()].count('{') == clean[opening + 1:m.start()].count('}'):
            names.setdefault(m['name'], m)
    return names


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    out = []

    def add(text):
        if text and text != source and all(text != t for _, t in out) and len(out) < LIMIT:
            out.append((FAMILY, text))

    for var in _declared(clean, opening, end):  # a flag with no other web: narrowed alone
        add(_narrow(source, name, var))
    # a flag whose name is reused for something else: split first, then narrow what still holds only flag values
    for _, text in split.variants(source, name):
        before, after = _declared(clean, opening, end), None
        clean_after = _blank(text)
        span_after = find(text, name)
        if not span_after:
            continue
        open_after = clean_after.find('{', span_after[0], span_after[1])
        end_after = close(clean_after, open_after, '{', '}') if open_after >= 0 else None
        if not end_after:
            continue
        after = _declared(clean_after, open_after, end_after)
        for var in after:  # (the name the flag kept, or the name of the web that holds only flag values)
            if var in before and _narrow(source, name, var):
                continue  # (already a flag before the split: the narrow-alone child covers it)
            narrowed = _narrow(text, name, var)
            if narrowed:
                add(narrowed)
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 41}
