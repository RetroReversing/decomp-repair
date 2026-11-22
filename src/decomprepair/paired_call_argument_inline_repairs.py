"""A local set on one line and used only as an argument of the call on the next, written into the call.

m2c gives one name to what a game computed in each arm of a switch (`var_a1 = flag + 0x6F;` in one arm, `var_a1 =
flag + 0x6D;` in another), then masks it where it is passed:

    case 1:
        var_a1 = *(u8 *)(rec + 0x1E) + 0x6F;
        send(ctx, var_a1 & 0xFF);
        break;
    case 2:
        var_a1 = *(u8 *)(rec + 0x1E) + 0x6D;
        send(ctx, var_a1 & 0xFF);
        break;

A named local is a user variable to GCC 2.7.2, and a user variable is never tied to the register the value goes to
next: the sum, the mask and the argument each get a register of their own, where the game's expression computed the
whole thing in the argument register (`lbu $a1; addiu $a1, $a1, 0x6F; andi $a1, $a1, 0xFF`). Written into the call,
the expression has only compiler temporaries and the chain stays in `$a1`.

`single_use_inline` needs a local assigned once, or an assignment followed by a plain store. This family covers the
other m2c shape: the same local assigned in several places, each assignment read only by the call right after it. It
never moves an expression across a statement, past a call, or into a call whose other arguments call anything, and
the expression may only read memory through m2c's own field macro. Offered for each pair alone and for all of one
local's pairs together.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'paired_call_argument_inline'
FAMILIES = (FAMILY,)

LIMIT = 8
_PAIR = re.compile(
    r'(?m)^(?P<indent>[ \t]*)(?P<local>' + IDENT + r')[ \t]*=(?!=)[ \t]*(?P<expr>[^;{}=\n][^;{}\n]*);[ \t]*\n'
    r'(?P<next>[ \t]*(?P<callee>' + IDENT + r')[ \t]*\()')
_FIELD = 'M2C_FIELD'


def _plain(expression):
    """Arithmetic on names, numbers and m2c field reads: no assignment, step, call or address-of."""
    stripped = re.sub(rf'\b{_FIELD}\b', '', expression)
    if re.search(r'\+\+|--|\w\s*\(|(?<![=!<>])=(?!=)|(?<!&)&(?![&\s\d(])', stripped):
        return False
    return bool(re.fullmatch(r'[\w\s()+\-*/%&|^~<>!,.\[\]]+', expression))


def _arguments(text):
    """Top-level comma-separated pieces of a call's argument text."""
    pieces, depth, start = [], 0, 0
    for index, char in enumerate(text):
        depth += (char in '([') - (char in ')]')
        if char == ',' and depth == 0:
            pieces.append(text[start:index])
            start = index + 1
    pieces.append(text[start:])
    return pieces


def _simple(argument):
    """An argument that evaluates without a call, so moving the expression in cannot reorder effects."""
    return not re.search(rf'\b(?!{_FIELD}\b){IDENT}\s*\(', argument) and not re.search(r'\+\+|--|(?<![=!<>])=(?!=)', argument)


def _declared(clean, opening, name):
    return re.search(rf'(?m)^[ \t]*[A-Za-z_][\w \t]*?[ \t*]{re.escape(name)}[ \t]*;', clean[opening:]) is not None


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.clean):
        return []
    clean, base = part.clean, part.opening + 1
    pairs = {}
    for hit in _PAIR.finditer(clean, base, part.end):
        local = hit['local']
        if not _declared(clean, part.opening, local) or not _plain(source[hit.start('expr'):hit.end('expr')]):
            continue
        # the call that follows: balanced, ends the statement, one argument reads the local, the rest call nothing
        opening = hit.end('next') - 1
        closing = close(clean, opening)
        if not closing or not re.match(r'\s*;', clean[closing:]):
            continue
        inner = clean[opening + 1:closing - 1]
        arguments = _arguments(inner)
        reading = [i for i, a in enumerate(arguments) if re.search(rf'(?<![\w.>]){re.escape(local)}\b', a)]
        if len(reading) != 1 or not all(_simple(a) for i, a in enumerate(arguments) if i != reading[0]):
            continue
        argument = arguments[reading[0]]
        if len(re.findall(rf'(?<![\w.>]){re.escape(local)}\b', argument)) != 1 or not _simple(argument):
            continue
        use = opening + 1 + sum(len(a) + 1 for a in arguments[:reading[0]]) + re.search(
            rf'(?<![\w.>]){re.escape(local)}\b', argument).start()
        pairs.setdefault(local, []).append((hit, use))
    result = []
    for local, items in pairs.items():
        mentions = [m.start() for m in re.finditer(rf'(?<![\w.>]){re.escape(local)}\b', clean[base:part.end])]
        # every mention of the local is one of the pairs' two (the declaration has no initializer to count)
        covered = len(items) * 2
        declaration = len(re.findall(rf'(?m)^[ \t]*[A-Za-z_][\w \t]*?[ \t*]{re.escape(local)}[ \t]*;', clean[base:part.end]))
        if len(mentions) - declaration != covered:
            continue
        edits = []
        for hit, use in items:
            expression = source[hit.start('expr'):hit.end('expr')].strip()
            spelled = expression if re.fullmatch(rf'(?:{_FIELD}\((?:[^()]|\([^()]*\))*\)|\w+)', expression) else f'({expression})'
            edits.append([(use, use + len(local), spelled), (hit.start(), hit.start('next'), '')])
        groups = edits + ([[e for group in edits for e in group]] if len(edits) > 1 else [])
        for group in groups:
            result.append((FAMILY, edit(source, group)))
    return result[:LIMIT]
