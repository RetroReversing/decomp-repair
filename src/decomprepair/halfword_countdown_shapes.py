"""A halfword countdown timer and its guarded loop, as the game wrote them where m2c wrote word arithmetic.

A menu function (GCC 2.7.2, KMC, N64) sat at 310 with two instructions wrong; three edits were needed together and
only the three matched it (COMPILER_MATCHING_LEARNINGS.md):

- The unsigned entry test of a loop that runs while a halfword timer is zero. m2c writes `(u32) t + 1 <= n` (the
  `do { } while` loop's own test, copied above the loop), which GCC folds with the known `t == 0` into a test of `n`
  alone, so the compare's `sltu $v0, $v1, $v0` is missing. `(u32) t < n` keeps the compare (310 -> 314 alone, which
  is why a step-at-a-time search drops it). `unsigned_successor_compare`.
- The loop counter. m2c declares a word counter and masks every read (`(v & 0xFFFF)`); the game's was a `u16`. With
  the compare kept, the `u16` counter's `move $a2, $zero` fills the entry branch's delay slot, which the word
  counter's does not (310 -> 310 alone). `masked_halfword_counter`.
- A countdown held in a field of a record. m2c reads the field into a temp, tests `(s16) temp > 0`, stores `temp - 1`
  and tests `(temp2 << 0x10) == 0`; the source was `if (F > 0) { F -= 1; if (F == 0) { ... } }`, which GCC reads
  back as a load, a copy and a decrement with no zero-extension (an `unsigned short` temp adds an `andi`, an `s16`
  temp drops the copy and the frame: 455 alone, exact with the other two). `field_countdown_compound`.

`halfword_countdown_combo` proposes every edit that applies as one child, which is what a beam that keeps only
improving children needs. Only MIPS is proposed (the compare fold and the delay slot are GCC 2.7.2's).
"""
import re

from .csource import _blank, find

FAMILY = 'halfword_countdown_combo'
SUCCESSOR = 'unsigned_successor_compare'
COUNTER = 'masked_halfword_counter'
COUNTDOWN = 'field_countdown_compound'
FAMILIES = (FAMILY, SUCCESSOR, COUNTER, COUNTDOWN)

_ID = r'[A-Za-z_]\w*'
_UNSIGNED = r'(?:u32|unsigned(?:\s+int)?)'
_WORD = r'(?:s32|int|u32|unsigned(?:\s+int)?|signed(?:\s+int)?)'
_HALF = r'(?:s16|short|signed\s+short)'


def _close(clean, start, left='(', right=')'):
    depth = 0
    for pos in range(start, len(clean)):
        depth += (clean[pos] == left) - (clean[pos] == right)
        if depth == 0:
            return pos + 1
    return None


# (E + 1) <= F is E < F, and (E + 1) > F is E >= F, for an unsigned E that cannot wrap
_SUCCESSOR = re.compile(
    r'\(\s*(?P<e>\(\s*\(\s*' + _UNSIGNED + r'\s*\)\s*' + _ID + r'\s*\)|\(\s*' + _UNSIGNED + r'\s*\)\s*' + _ID + r')'
    r'\s*\+\s*1\s*\)\s*(?P<op><=|>)(?!=)')


def _successor(source, body):
    clean = _blank(source)
    hits = list(_SUCCESSOR.finditer(clean, *body))
    if not hits:
        return None
    out = source
    for hit in reversed(hits):
        op = '<' if hit['op'] == '<=' else '>='
        out = out[:hit.start()] + source[hit.start('e'):hit.end('e')] + ' ' + op + out[hit.end():]
    return out


def _counter(source, body):
    """A word local read only through `& 0xFFFF` (written by constants and `+= 1`), declared `u16` instead."""
    clean = _blank(source)
    text = clean[body[0]:body[1]]
    edits = []
    for decl in re.finditer(r'(?m)^(?P<ind>[ \t]*)(?P<type>' + _WORD + r')\s+(?P<name>' + _ID + r')\s*;[ \t]*$', text):
        name = decl['name']
        rest = text[:decl.start()] + ' ' * (decl.end() - decl.start()) + text[decl.end():]
        reads = re.findall(r'(?<![\w.>])' + name + r'\s*&\s*0x[fF]{4}\b', rest)
        if not reads:
            continue
        # every other mention must be a plain write: `v = <digits>;`, `v += 1;`, `v++;` or `v = v + 1;`
        left = re.sub(r'(?<![\w.>])' + name + r'\s*&\s*0x[fF]{4}\b', '', rest)
        left = re.sub(r'(?<![\w.>])' + name + r'\s*(?:=\s*\d+|\+=\s*1|=\s*' + name + r'\s*\+\s*1|\+\+)\s*;', '', left)
        left = re.sub(r'\+\+\s*' + name + r'\s*;', '', left)
        if re.search(r'(?<![\w.>])' + name + r'\b', left):
            continue
        if not re.search(r'(?<![\w.>])' + name + r'\s*(?:\+=\s*1|=\s*' + name + r'\s*\+\s*1|\+\+)|\+\+\s*' + name, rest):
            continue
        edits.append((body[0] + decl.start('type'), body[0] + decl.end('type')))
    if not edits:
        return None
    out = source
    for a, b in reversed(edits):
        out = out[:a] + 'u16' + out[b:]
    return out


_FIELD = r'\*\s*\(\(\s*' + _HALF + r'\s*\*\)'


def _countdown(source, body):
    """`t = *F; if ((s16) t > 0) { u = t - 1; *F = u; if ((u << 0x10) == 0)` as the compound decrement of `*F`."""
    clean = _blank(source)
    edits = []
    for load in re.finditer(r'(?m)^(?P<ind>[ \t]*)(?P<t>' + _ID + r')\s*=\s*(?=' + _FIELD + r')', clean[:body[1]]):
        if load.start() < body[0]:
            continue
        start = load.end()
        end = _close(clean, clean.find('(', clean.find('*', start) + 1))
        if not end:
            continue
        field = source[start:end].strip()
        t = load['t']
        operand = (r'(?:\(\s*\(\s*' + _HALF + r'\s*\)\s*' + t + r'\s*\)|\(\s*' + _HALF + r'\s*\)\s*' + t + r'|' + t + r')')
        guard = re.compile(r'\s*;\s*if\s*\(\s*' + operand + r'\s*>\s*0\s*\)\s*\{\s*').match(clean, end)
        if not guard:
            continue
        step = re.compile(r'(?P<u>' + _ID + r')\s*=\s*' + t + r'\s*-\s*1\s*;\s*').match(clean, guard.end())
        if not step:
            continue
        u = step['u']
        stored = _match_field(clean, step.end(), field)
        if stored is None:
            continue
        value = re.compile(r'\s*=\s*(?:\(\s*' + _WORD + r'\s*\)\s*)?' + u + r'\s*;\s*').match(clean, stored)
        if not value:
            continue
        test = re.compile(r'if\s*\(\s*\(\s*' + u + r'\s*<<\s*0x10\s*\)\s*==\s*0\s*\)').match(clean, value.end())
        if not test:
            continue
        # the two temps belong to this statement group alone
        outside = clean[body[0]:load.start()] + ' ' * (test.end() - load.start()) + clean[test.end():body[1]]
        if any(re.search(r'(?<![\w.>])' + name + r'\b', _strip_decls(outside, name)) for name in (t, u)):
            continue
        pad = load['ind']
        edits.append((load.start(), test.end(),
                      f'{pad}if ({field} > 0)\n{pad}{{\n{pad}  {field} -= 1;\n{pad}  if ({field} == 0)'))
    if not edits:
        return None
    out = source
    for a, b, text in reversed(edits):
        out = out[:a] + text + out[b:]
    return out


def _norm_field(field):
    return re.sub(r'\s+', '', field)


def _strip_decls(text, name):
    """The text without the local's own declaration, so a mention elsewhere is a use."""
    return re.sub(r'(?m)^[ \t]*[A-Za-z_][\w ]*?\b' + re.escape(name) + r'\s*;[ \t]*$', '', text)


def _match_field(clean, cursor, field):
    """Index past `field` (the same dereference, whitespace aside) at `cursor`, or None."""
    wanted = _norm_field(field)
    got, pos = '', cursor
    while pos < len(clean) and len(got) < len(wanted):
        if not clean[pos].isspace():
            got += clean[pos]
        pos += 1
    return pos if got == wanted else None


def variants(source, name, arch=None):
    if arch not in (None, 'mips'):
        return []
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = _close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = (opening, end)
    result, applied = [], []
    for family, edit in ((SUCCESSOR, _successor), (COUNTER, _counter), (COUNTDOWN, _countdown)):
        text = edit(source, body)
        if text and text != source:
            result.append((family, text))
            applied.append(edit)
    if len(applied) > 1:
        text = source
        for edit in applied:
            clean = _blank(text)
            opening = clean.find('{', find(text, name)[0], find(text, name)[1])
            text = edit(text, (opening, _close(clean, opening, '{', '}'))) or text
        result.append((FAMILY, text))
    return result
