"""A call argument chosen by an `if`/`else` into a local: the call written in each arm.

m2c reads two calls that cross-jumping merged into one `jal` back as one call of a local both arms set:

    if (mode != 0) { var_a0 = tableA; } else { var_a0 = tableB; }
    osViSetMode(var_a0);

The local is a register of its own (`lui $v0; addiu $a0, $v0`), where the target builds the argument in `$a0` itself.
`selected_argument_call_split` takes the form with a default before a one-armed `if`; this one takes the two-armed form.
Which way round the test is written decides the branch, so each pick is offered with the condition as it stands and
negated with the arms exchanged, alone and with every other pick split at once: on a 73-instruction N64 screen-mode
setter (SN GCC 2.8.1, `-G0 -mips3 -O2 -mfp64`) the two picks needed opposite polarities (1270 -> 835 with the draft's
flag still in a local, 0 with it split too).

Only a local every mention of which is one of its picks (and its declaration) is taken. The judge decides.
"""
import itertools
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'joined_call_arm_split'
FAMILIES = (FAMILY,)
LIMIT = 12
COMBINED = 3  # picks split together in every polarity: 2 ** 3 children

PICK = re.compile(
    rf'if\s*\((?P<c>[^{{}};]+?)\)\s*\{{\s*(?P<v>{IDENT})\s*=(?!=)\s*(?P<a>[^;{{}}=]+?)\s*;\s*\}}\s*'
    rf'else\s*\{{\s*(?P=v)\s*=(?!=)\s*(?P<b>[^;{{}}=]+?)\s*;\s*\}}\s*'
    rf'(?P<call>(?:{IDENT}\s*=\s*)?{IDENT}\s*\([^;{{}}]*\)\s*;)')


def _negated(condition):
    simple = re.fullmatch(r'([^=!<>&|?]+?)\s*(==|!=)\s*([^=!<>&|?]+)', condition)
    if simple:
        return f'{simple[1]} {"!=" if simple[2] == "==" else "=="} {simple[3]}'
    return f'!({condition})'


def _picks(source, part):
    """The picks whose local is named nowhere but in its picks and its declaration."""
    clean = part.clean
    found = [hit for hit in PICK.finditer(clean, part.opening, part.end)
             if len(re.findall(rf'(?<![\w.>]){re.escape(hit["v"])}\b', hit['call'])) == 1
             and clean[:hit.start()].rstrip()[-1:] in ';{}']
    result = []
    for hit in found:
        local = hit['v']
        name = rf'(?<![\w.>]){re.escape(local)}\b'
        declared = len(re.findall(rf'(?m)^[ \t]*(?:{IDENT}[\s*]+)+{re.escape(local)}\s*;', clean[part.opening:part.end]))
        inside = sum(len(re.findall(name, other[0])) for other in found if other['v'] == local)
        if declared == 1 and len(re.findall(name, clean[part.opening:part.end])) == inside + declared:
            result.append(hit)
    return result


def _split(source, hit, negate):
    condition = source[hit.start('c'):hit.end('c')].strip()
    first, second = (source[hit.start(arm):hit.end(arm)].strip() for arm in ('a', 'b'))
    if negate:
        condition, first, second = _negated(condition), second, first
    call = source[hit.start('call'):hit.end('call')]
    at = re.search(rf'(?<![\w.>]){re.escape(hit["v"])}\b', hit['call'])
    arms = [call[:at.start()] + value + call[at.end():] for value in (first, second)]
    indent = re.search(r'[ \t]*$', source[:hit.start()].rsplit('\n', 1)[-1])[0]
    return (f'if ({condition})\n{indent}{{\n{indent}  {arms[0]}\n{indent}}}\n{indent}else\n'
            f'{indent}{{\n{indent}  {arms[1]}\n{indent}}}')


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    picks = _picks(source, part)
    result = []
    if 1 < len(picks):
        for turns in itertools.product((False, True), repeat=min(len(picks), COMBINED)):
            edits = [(hit.start(), hit.end(), _split(source, hit, turn)) for hit, turn in zip(picks, turns)]
            result.append((FAMILY, edit(source, edits)))
    for hit in picks:
        for turn in (False, True):
            result.append((FAMILY, edit(source, [(hit.start(), hit.end(), _split(source, hit, turn))])))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60}
