"""A field wrapped into a range, which m2c spells with temporaries, written as the compound updates it was.

A game that wraps a position back into the world writes one `if`/`else if` per axis:

    if (p->x < -0x20C0) { p->x += 0x4180; } else if (p->x >= 0x20C1) { p->x -= 0x4180; }

m2c reads the halfword twice (signed for the compares, unsigned for the sum) and gives back one of two shapes:

    temp = LOAD;
    copy = (u16) LOAD;
    var = copy + K1;
    if ((temp < LOW) || (var = copy + K2, ((temp < HIGH) == 0))) {
        LOAD = var;
    }

or, where the `if` ends a `void` function, a guard that returns:

    temp = LOAD;
    copy = (u16) LOAD;
    if (temp < LOW) { LOAD = (s16) (copy + K1); return; }
    if (temp >= HIGH) { LOAD = (s16) (copy + K2); }

The temporaries live across the compares and take registers of their own, and a lone update spelt
`LOAD = (s16) ((u16) LOAD - 0x8000)` builds the constant with `ori` where the game had `addiu` from `$zero`. All three
are written back here: `if (LOAD < LOW) { LOAD += K1; } else if (!(LOAD < HIGH)) { LOAD += K2; }` and `LOAD -= K;`.

On a 46-instruction function of an N64 game built by SN GCC 2.8.1 (four axis wraps, a draft at 800) no one edit was
exact (960, 800, 715 and 400 alone), all four together were byte-identical, and 120 judged variants of the other
families had reached 490. So every site is offered alone and all of them as one child.

A saved best spells the same shapes differently, and is read too: the macro written out as
`(*(s16 *)((char *)(p) + 2))`, the first arm's sum moved above the copy it reads (`var = copy + K1; copy = (u16) LOAD;`,
made only when nothing set `copy` before), and the guard's store staged through a local (`v = (s16) ((s32) copy + K1);
LOAD = v; return;`). On a 22-instruction two-axis wrap of an N64 game (sn-n64-281) the saved best, left at 510 by earlier
searches, gave no child; read this way the combined child is byte-identical.

Only made when the width of the field is spelt in the expression (`M2C_FIELD(p, s16 *, 2)`, `*(s16 *) q`), when the
temporaries are plain locals whose values are not read anywhere after the rewritten statements, and, for the guard
shape, when nothing but closing braces and `else` arms follows it in the function. Only a candidate: the judge decides.
"""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'field_wrap_arms'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'
NUMBER = r'-?\s*(?:0[xX][0-9a-fA-F]+|[0-9]+)[uU]?'
LIMIT = 8

# an lvalue whose width is in its text: M2C_FIELD(base, s16 *, offset), *(s16 *) base, or the macro written out as
# (*(s16 *)((char *)(base) + offset))
PARENS = r'\((?:[^;{}=()]|\((?:[^;{}=()]|\([^;{}=()]*\))*\))*\)'
DEREF = rf'\*\s*\(\s*[su](?:8|16)\s*\*\s*\)\s*(?:{PARENS}|[A-Za-z_]\w*)'
LOAD = (r'(?:M2C_FIELD\(\s*[^;{}=()]*?(?:\([^;{}=()]*\))?\s*,\s*[su](?:8|16)\s*\*\s*,\s*-?\w+\s*\)'
        rf'|\(\s*{DEREF}\s*\)|{DEREF})')
WIDTH = re.compile(r'(?:,|\()\s*([su])(8|16)\s*\*')


def _loaded(temp, copy):
    """`temp = LOAD;` (alone or in a one-shot scope) then `copy = (uN) LOAD;`."""
    return (rf'(?P<indent>[ \t]*)(?:do\s*\{{\s*)?(?P<temp>{IDENT})\s*=\s*(?P<load>{LOAD})\s*;'
            rf'(?:\s*\}}\s*while\s*\(\s*0\s*\)\s*;)?\s*'
            rf'(?P<copy>{IDENT})\s*=\s*\(\s*u(?P<bits>8|16)\s*\)\s*(?P=load)\s*;\s*')


_COMMA_IF = (
    rf'if\s*\(\s*\(?\s*(?P=temp)\s*<\s*(?P<low>{NUMBER})\s*\)?\s*\|\|\s*\(\s*(?P=var)\s*=\s*(?P=copy)\s*'
    rf'(?P<op2>[+-])\s*(?P<k2>{NUMBER})\s*,\s*\(\s*\(\s*(?P=temp)\s*<\s*(?P<high>{NUMBER})\s*\)\s*==\s*0\s*\)\s*\)\s*\)'
    rf'\s*\{{\s*(?P=load)\s*=\s*(?:\(\s*[su](?:8|16)\s*\)\s*)?(?P=var)\s*;\s*\}}[ \t]*\n?')

COMMA = re.compile(
    _loaded('temp', 'copy')
    + rf'(?P<var>{IDENT})\s*=\s*(?P=copy)\s*(?P<op1>[+-])\s*(?P<k1>{NUMBER})\s*;\s*' + _COMMA_IF)

# the same gate with the first arm's sum moved above the copy it reads (a saved best keeps that order)
HOISTED = re.compile(
    rf'(?P<indent>[ \t]*)(?P<temp>{IDENT})\s*=\s*(?P<load>{LOAD})\s*;\s*'
    rf'(?P<var>{IDENT})\s*=\s*(?P<copy>{IDENT})\s*(?P<op1>[+-])\s*(?P<k1>{NUMBER})\s*;\s*'
    rf'(?P=copy)\s*=\s*\(\s*u(?P<bits>8|16)\s*\)\s*(?P=load)\s*;\s*' + _COMMA_IF)


def _stored(number):
    """The guard arm's store of `copy op K`: direct, or through a local (`v = ...; LOAD = v;`)."""
    value = (rf'(?:\(\s*[su](?:8|16)\s*\)\s*)?\(\s*(?:\(\s*s32\s*\)\s*)?(?P=copy)\s*'
             rf'(?P<op{number}>[+-])\s*(?P<k{number}>{NUMBER})\s*\)\s*;')
    return (rf'(?:(?:(?P<staged{number}>{IDENT})\s*=\s*|(?P=load)\s*=\s*){value}'
            rf'(?(staged{number})\s*(?P=load)\s*=\s*(?P=staged{number})\s*;))')


GUARD = re.compile(
    _loaded('temp', 'copy')
    + rf'if\s*\(\s*(?P=temp)\s*<\s*(?P<low>{NUMBER})\s*\)\s*\{{\s*' + _stored(1)
    + rf'\s*return\s*;\s*\}}\s*if\s*\(\s*(?P=temp)\s*>=\s*(?P<high>{NUMBER})\s*\)\s*\{{\s*' + _stored(2)
    + r'\s*\}[ \t]*\n?')

# LOAD = (sN) ((uN) LOAD - K);
UPDATE = re.compile(
    rf'(?P<load>{LOAD})\s*=\s*(?:\(\s*[su](?:8|16)\s*\)\s*)?\(\s*\(\s*u(?P<bits>8|16)\s*\)\s*(?P=load)\s*'
    rf'(?P<op>[+-])\s*(?P<k>{NUMBER})\s*\)\s*;')


def _term(op, number):
    return f'{op}= {number.replace(" ", "")}'


def _value(load, signed_needed):
    """The load as a compare operand: m2c compared a signed temporary, so an unsigned field is read through a cast."""
    kind = WIDTH.search(load)
    return load if not signed_needed or kind[1] == 's' else f'(s{kind[2]}) {load}'


def _dead_after(part, names, start, end):
    """Whether the values the removed statements gave `names` are read nowhere else."""
    for name in names:
        refs = list(re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', part.clean[part.opening:part.end]))
        places = [(part.opening + hit.start(), part.opening + hit.end()) for hit in refs]

        def written(stop):
            return re.match(r'\s*=(?!=)', part.clean[stop:]) is not None

        declared = re.compile(rf'\b[su](?:8|16|32)\s+{re.escape(name)}\s*;')
        body = [(a, b) for a, b in places
                if not any(m.start() <= a < m.end() for m in declared.finditer(part.clean))
                and not start <= a < end]  # the removed statements' own reads go with them
        if not any(m for m in declared.finditer(part.clean, part.opening, part.end)):
            return False  # a parameter or a global: its value is seen elsewhere
        if re.search(rf'&\s*{re.escape(name)}\b', part.clean[part.opening:part.end]):
            return False
        if body and not written(body[0][1]):
            return False  # read before it is written: a loop could carry the value round
        later = [(a, b) for a, b in body if a >= end]
        if later and not written(later[0][1]):
            return False
    return True


def _ends_function(part, at):
    """Only closing braces and whole `else { }` arms stand between `at` and the function's end."""
    clean, space = part.clean, re.compile(r'\s*')
    while True:
        at = space.match(clean, at).end()
        if at >= part.end:
            return True
        if clean[at] != '}':
            return False
        at += 1
        arm = re.compile(r'\s*else\s*\{').match(clean, at)
        if arm:
            at = close(clean, arm.end() - 1, '{', '}')
            if not at:
                return False
        elif re.compile(r'\s*else\b').match(clean, at):
            return False


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    void = re.search(rf'\bvoid\s+{re.escape(name)}\s*\(', part.clean) is not None
    edits = []

    def free(start, end):
        return all(end <= a or start >= b for a, b, _ in edits)

    for pattern, guard in ((COMMA, False), (HOISTED, False), (GUARD, True)):
        for hit in pattern.finditer(part.clean, part.opening, part.end):
            load, bits = hit['load'], hit['bits']
            if not free(hit.start(), hit.end()) or WIDTH.search(load)[2] != bits:
                continue
            temps = [hit['temp'], hit['copy']] + ([] if guard else [hit['var']])
            if guard:
                temps += sorted({v for v in (hit['staged1'], hit['staged2']) if v})
            # a copy summed before it is loaded must hold nothing yet, or the sum meant something
            if pattern is HOISTED and re.search(rf'\b{re.escape(hit["copy"])}\s*=(?!=)',
                                                part.clean[part.opening:hit.start()]):
                continue
            if len(set(temps)) != len(temps) or any(re.search(rf'\b{re.escape(t)}\b', load) for t in temps):
                continue
            if not _dead_after(part, temps, hit.start(), hit.end()):
                continue
            if guard and not (void and _ends_function(part, hit.end())):
                continue
            indent = hit['indent']
            low, high = hit['low'].replace(' ', ''), hit['high'].replace(' ', '')
            value = _value(load, True)
            second = f'{value} >= {high}' if guard else f'!({value} < {high})'
            text = (f'{indent}if ({value} < {low}) {{\n{indent}    {load} {_term(hit["op1"], hit["k1"])};\n'
                    f'{indent}}} else if ({second}) {{\n{indent}    {load} {_term(hit["op2"], hit["k2"])};\n'
                    f'{indent}}}\n')
            edits.append((hit.start(), hit.end(), text))
    for hit in UPDATE.finditer(part.clean, part.opening, part.end):
        load = hit['load']
        if free(hit.start(), hit.end()) and WIDTH.search(load)[2] == hit['bits']:
            edits.append((hit.start(), hit.end(), f'{load} {_term(hit["op"], hit["k"])};'))
    edits.sort()
    result = [(FAMILY, edit(source, [change])) for change in edits[:LIMIT]]
    if len(edits) > 1:
        result.insert(0, (FAMILY, edit(source, edits)))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
