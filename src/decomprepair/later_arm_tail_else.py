"""A `goto` from one `if` into the tail of a later one, written as two arms that each end with that tail.

Two exclusive cases that finish the same way compile to one shared tail, and m2c writes the first case's jump into the
second's block. The default of the returned value, which the compiler put in a branch's delay slot, can land on a
variable nothing reads:

    do { kind = p->kind;                          kind = p->kind;
    if (kind == 0) {                              if (kind == 0) {
        A...                                          A...
        goto block_4;                                 *out = size; ret = total;      (the tail)
    } } while (0);                       ->       } else if (kind == 1) {
    dead = 0x20;                                      B...
    if (kind == 1) {                                  *out = size; ret = total;
        B...                                      }
    block_4:                                      return ret;
        *out = size; dead = total;
    }
    return ret;

The `do { } while (0)` around the first test is opened and the assignments of literals to locals nothing reads that sit
between the two tests are dropped. A second child also gives the returned local the dropped literal before the body's
first call, where the target keeps it in a saved register: the draft's `return ret;` read it uninitialized.

Measured on one N64 function (SN GCC 2.8.1 `-G0 -mips3 -O2`, 59 instructions): the machine draft's 1054 became 605 with
the first child and 350 with the second; with `skipped_register_parameter` and the remaining `do { } while (0)` scopes
opened the exact judge scored 0.

Needs: an `if` without `else` whose block ends in `goto L;`, followed (after at most the dead assignments) by an `if`
without `else` that holds `L:` at its own level, `L` used once, and the statements after the label holding no label,
declaration or `case`."""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'later_arm_tail_else'
FAMILIES = (FAMILY,)
_SPACE = re.compile(r'\s*')
_IF = re.compile(r'(?<![\w.>])if\s*\(')
_GOTO = re.compile(rf'(?<=[;{{}}])\s*goto\s+({IDENT})\s*;\s*\Z')
_DEAD = re.compile(rf'\s*(?P<name>{IDENT})\s*=\s*(?P<value>-?{NUMBER})\s*;')
_DO = re.compile(r'(?<![\w.>])do\s*\{')
_TAIL = re.compile(r'\s*while\s*\(\s*0\s*\)\s*;')


def _arm(clean, match):
    """(block's `{`, past its `}`) of an `if` with a braced arm and no `else`, or None."""
    closing = close(clean, match.end() - 1, '(', ')')
    brace = closing and re.compile(r'\s*\{').match(clean, closing)
    end = brace and close(clean, brace.end() - 1, '{', '}')
    if not end or re.compile(r'\s*else\b').match(clean, end):
        return None
    return brace.end() - 1, end


def _wrapper(clean, opening, first, arm_end):
    """The `do {` and `} while (0);` spans around the `if` at `first`, when it is the last statement of such a scope
    that has no `break` or `continue` of its own; else None."""
    for found in reversed(list(_DO.finditer(clean, opening + 1, first))):
        brace = found.end() - 1
        end = close(clean, brace, '{', '}')
        if not end or end <= arm_end:
            continue
        tail = _TAIL.match(clean, end)
        if (not tail or clean[arm_end:end - 1].strip()
                or re.search(r'\b(?:break|continue|case|default)\b', clean[brace:end])
                or re.search(rf'(?<![\w.>])(?:[su](?:8|16|32)|char|short|int|float|double)\s+{IDENT}\s*[;=\[]',
                             clean[brace:end])):
            return None
        return (found.start(), found.end()), (end - 1, tail.end())
    return None


def _unread(body, name):
    """Whether the local `name` is only declared and assigned in `body`."""
    declared = re.findall(rf'(?<![\w.>])(?:[su](?:8|16|32)|int|short|char)\s+{name}\s*;', body)
    assigned = re.findall(rf'(?:(?<=[;{{}}])|\A)\s*{name}\s*=(?!=)', body)
    return len(declared) == 1 and len(re.findall(rf'(?<![\w.>]){name}\b', body)) == len(assigned) + 1


def variants(source, name, header=''):
    part = view(source, name)
    if not part or 'goto' not in part.body:
        return []
    clean, opening, end = part.clean, part.opening, part.end
    body = clean[opening + 1:end - 1]
    ifs = list(_IF.finditer(clean, opening + 1, end))
    out = []
    for first in ifs:
        arm = _arm(clean, first)
        if not arm:
            continue
        jump = _GOTO.search(clean, arm[0] + 1, arm[1] - 1)
        if not jump:
            continue
        label = jump[1]
        if len(re.findall(rf'\b{label}\b', body)) != 2:
            continue
        wrapper = _wrapper(clean, opening, first.start(), arm[1])
        at = wrapper[1][1] if wrapper else arm[1]
        dead = []
        while True:
            found = _DEAD.match(clean, at)
            if not found or not _unread(body, found['name']):
                break
            dead.append(found)
            at = found.end()
        second = _IF.match(clean, _SPACE.match(clean, at).end())
        other = second and _arm(clean, second)
        if not other:
            continue
        mark = re.compile(rf'(?<=[;{{}}])\s*{label}\s*:(?!:)').search(clean, other[0] + 1, other[1] - 1)
        if not mark or clean[other[0] + 1:mark.start()].count('{') != clean[other[0] + 1:mark.start()].count('}'):
            continue
        tail = clean[mark.end():other[1] - 1]
        if re.search(rf'\b(?:case|default|goto)\b|(?:(?<=[;{{}}])|\A)\s*{IDENT}\s*:(?!:)', tail):
            continue
        if re.match(rf'\s*(?:[su](?:8|16|32)|char|short|int|float|double)\s+{IDENT}', tail):
            continue
        copy = source[mark.end():other[1] - 1].strip()
        if not copy:
            continue
        goto_at = jump.start() + len(jump[0]) - len(jump[0].lstrip())
        changes = [(goto_at, jump.end() - (len(jump[0]) - len(jump[0].rstrip())), copy),
                   (arm[1], arm[1], ' else'),
                   (mark.start(), mark.end(), '')]
        if wrapper:
            changes += [(wrapper[0][0], wrapper[0][1], ''), (wrapper[1][0], wrapper[1][1], '')]
        changes += [(found.start(), found.end(), '') for found in dead]
        out.append(edit(source, changes))
        returned = re.search(rf'\breturn\s+({IDENT})\s*;[\s}}]*\Z', body)
        call = re.compile(rf'(?m)^[ \t]*(?:do\s*\{{\s*)?(?!if\b|while\b|for\b|switch\b|return\b){IDENT}\s*\(').search(
            clean, opening + 1, first.start())
        if (dead and returned and call and _unread_before(clean[opening + 1:call.start()], returned[1])
                and len(dead) == 1):
            value = dead[0]['value']
            preset = f'    {returned[1]} = {value};\n'
            out.append(edit(source, changes + [(call.start(), call.start(), preset)]))
    return [(FAMILY, text) for text in dict.fromkeys(out)]


def _unread_before(prefix, name):
    """Whether `name` is declared in `prefix` (the body up to the first call) and not assigned there."""
    return (len(re.findall(rf'(?<![\w.>])(?:[su](?:8|16|32)|int|short|char)\s+{name}\s*;', prefix)) == 1
            and len(re.findall(rf'(?<![\w.>]){name}\b', prefix)) == 1)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # registry.py
