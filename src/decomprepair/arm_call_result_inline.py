"""A call made in each arm, with the arm's other call written into it: the shape a game's `if (c) { f(a(x), b(1)); }
else { f(a(x), b(2)); }` had, where m2c names what the arms differ in.

m2c reads gcc's cross-jumped tail back as one call after the `if`/`else`, with a variable per arm:

    if (flag) { name = lookup(id | 0x9000); k = 0xA2; } else { name = lookup(id | 0x9000); k = 0x16A; }
    sprintf(buf, fmt, name, lookup(k));

gcc compiles that with the first call's result copied into the variable's register inside each arm (`jal; move $s0,
$v0` twice). The game wrote the whole `sprintf` in each arm (`call_into_arms` does that), and its first call's result
was an argument and not a variable: gcc then keeps the value in `$v0` until the arms meet and copies it once, in the
tail (`jal lookup; move $s0, $v0`, the copy in the delay slot). Moving the call into the arms leaves the variable in
place, still a copy in each arm, so neither step changes the code alone; both together are the game's shape.

This family offers that combination as one child: the call moved into each arm (`tail_call_arm_repairs`), then each
local that an arm sets from a call on the line right before the call that reads it written into that call. It also
offers the second half alone, for arms m2c already wrote with a call each (`name = lookup(id); sprintf(buf, fmt, name,
lookup(1));` in each arm). The call-result expression only moves into an argument when no argument to its left calls
anything, so the order the calls ran in does not change (gcc evaluates arguments left to right).

Hypothesis, not a compiler fact read from the source: the copy in the tail comes from the argument being held in the
return register across the join; the measured evidence is docs/learnings/function/arm-calls-with-nested-lookup.md in
decompdecomp (a 440-instruction handler, 1605 -> 0 together with the other steps of its chain).
"""
import re

from . import tail_call_arm_repairs
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'call_into_arms_inline'
FAMILIES = (FAMILY,)

LIMIT = 6
_PAIR = re.compile(
    r'(?m)^(?P<indent>[ \t]*)(?P<local>' + IDENT + r')[ \t]*=(?!=)[ \t]*(?P<expr>' + IDENT + r'[ \t]*\([^;{}\n]*\));[ \t]*\n'
    r'(?P<next>[ \t]*(?P<callee>' + IDENT + r')[ \t]*\()')


def _python_arguments(text):
    """Top-level comma-separated pieces of a call's argument text."""
    pieces, depth, start = [], 0, 0
    for index, char in enumerate(text):
        depth += (char in '([') - (char in ')]')
        if char == ',' and depth == 0:
            pieces.append(text[start:index])
            start = index + 1
    pieces.append(text[start:])
    return pieces


_arguments = _python_arguments
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _arguments(text):
        return _scan.top_pieces(text, ',', 2)


def _calls(text):
    return re.search(rf'{IDENT}\s*\(', text) is not None


def _effects(text):
    return re.search(r'\+\+|--|(?<![=!<>])=(?!=)', text) is not None


def _mentions(clean, local):
    return re.findall(rf'(?<![\w.>]){re.escape(local)}\b', clean)


def _inlined(source, name):
    """Every local that arms set from a call and pass to the next call: [(source, locals)] with all of them written
    into their calls, and one source per local alone is not offered (the arms of one local only pay off together)."""
    part = view(source, name)
    if not part:
        return None
    clean, base = part.clean, part.opening + 1
    pairs = {}
    for hit in _PAIR.finditer(clean, base, part.end):
        local = hit['local']
        expression = source[hit.start('expr'):hit.end('expr')]
        if _effects(expression[expression.index('('):]):
            continue
        opening = hit.end('next') - 1
        closing = close(clean, opening)
        if not closing or not re.match(r'\s*;', clean[closing:]):
            continue
        arguments = _arguments(clean[opening + 1:closing - 1])
        reading = [i for i, a in enumerate(arguments) if re.search(rf'(?<![\w.>]){re.escape(local)}\b', a)]
        if len(reading) != 1:
            continue
        index = reading[0]
        argument = arguments[index]
        # the local is the whole argument; nothing to its left calls or sets anything, so the order is unchanged
        if argument.strip() != local or any(_calls(a) or _effects(a) for a in arguments[:index]):
            continue
        if any(_effects(a) for a in arguments[index + 1:]):
            continue
        use = opening + 1 + sum(len(a) + 1 for a in arguments[:index]) + argument.index(local)
        pairs.setdefault(local, []).append((hit, use))
    group, handled = [], []
    for local, items in pairs.items():
        mentions = len(_mentions(clean[base:part.end], local))
        declared = len(re.findall(
            rf'(?m)^[ \t]*[A-Za-z_][\w \t*]*?[ \t*]{re.escape(local)}[ \t]*;[ \t]*\n', clean[base:part.end]))
        # every mention is a declaration or one of the pairs' two
        if len(items) < 2 or mentions - declared != 2 * len(items):
            continue
        for hit, use in items:
            expression = source[hit.start('expr'):hit.end('expr')].strip()
            group += [(use, use + len(local), expression), (hit.start(), hit.start('next'), '')]
        for declaration in re.finditer(
                rf'(?m)^[ \t]*[A-Za-z_][\w \t*]*?[ \t*]{re.escape(local)}[ \t]*;[ \t]*\n', clean[base:part.end]):
            group.append((base + declaration.start(), base + declaration.end(), ''))
        handled.append(local)
    if not group:
        return None
    return edit(source, group), handled


def variants(source, name):
    result = []
    bases = [source] + [text for _, text in tail_call_arm_repairs.variants(source, name)]
    for base in bases:
        made = _inlined(base, name)
        if made and made[0] != source and made[0] not in [text for _, text in result]:
            result.append((FAMILY, made[0]))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
