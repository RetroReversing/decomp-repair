"""A literal a loop's condition compares with, set into a local just before the loop.

`beq`/`bne` take no immediate on MIPS, so `while (list[j] != 0xFFFF)` needs the constant in a register. loop.c moves a
literal out of the loop, but in a loop nested in another it can be merged with the outer loop's copy of the same constant
and moved further out, where it loses its register and is rebuilt before every compare (`ori $t2` where the target keeps
one `ori $a2` in the inner preheader). A local set before the loop gives the constant a register of its own there.

Measured on one N64 function (KMC GCC 2.7.2 `-O1`, 323 instructions): 215 -> 30, and 0 with `statement_scope_weight`
after it. A `u16` local scored 30 where an `s32` one scored 60, so both are offered. The mechanism is a hypothesis from
the dumps (`-dL`: "done move-insn matches"); the scores are the evidence."""
import re

from .integer_repair_support import NUMBER, edit, view

FAMILIES = ('loop_condition_literal_local',)
FAMILY = FAMILIES[0]
LIMIT = 12
DO = re.compile(r'\bdo\s*\{')
TAIL = re.compile(r'\s*while\s*\(')
HEAD = re.compile(r'\bwhile\s*\(')
COMPARE = re.compile(rf'(?:==|!=)\s*(?P<lit>-\s*{NUMBER}|{NUMBER})(?![\w.])')


def _closing(text, opening):
    pair = {'(': ')', '{': '}'}[text[opening]]
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == text[opening]:
            depth += 1
        elif text[index] == pair:
            depth -= 1
            if not depth:
                return index
    return -1


def _statement_start(text, at):
    """Whether a statement may be written in front of `at`: not the unbraced body of an `if`, `else` or label."""
    before = text[:at].rstrip()
    return before.endswith(('{', '}', ';'))


def _loops(text, start, end):
    """(where the loop begins, where its condition begins, where it ends) of each `do ... while` and `while` loop."""
    tails = set()
    for match in DO.finditer(text, start, end):
        close = _closing(text, match.end() - 1)
        tail = TAIL.match(text, close + 1) if close >= 0 else None
        if tail:
            tails.add(text.index('while', tail.start()))
            yield match.start(), tail.end() - 1, _closing(text, tail.end() - 1)
    for match in HEAD.finditer(text, start, end):
        if match.start() not in tails:
            yield match.start(), match.end() - 1, _closing(text, match.end() - 1)


def _value(text):
    text = re.sub(r'\s', '', text).rstrip('uUlL')
    digits = text.lstrip('-')
    number = int(digits, 16 if digits[:2].lower() == '0x' else 8 if len(digits) > 1 and digits[0] == '0' else 10)
    return -number if text.startswith('-') else number


def _types(value):
    """The types the local may have: each holds the value, so the compare means what it did."""
    if -0x8000 <= value < 0:
        return ('s16', 's32')
    if 0 < value <= 0x7FFF:
        return ('s16', 's32')
    if 0x7FFF < value <= 0xFFFF:
        return ('u16', 's32')
    return ('s32',) if -0x80000000 <= value <= 0x7FFFFFFF else ()


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    text, result = part.clean, []
    index = 0
    while re.search(rf'\bloop_literal{index}\b', source):
        index += 1
    local = f'loop_literal{index}'
    for loop, opening, close in sorted(_loops(text, part.opening, part.end)):
        if close < 0 or not _statement_start(text, loop):
            continue
        for match in COMPARE.finditer(text, opening, close):
            value = _value(match['lit'])
            if not value:
                continue
            for kind in _types(value):
                if kind != 's32' and not re.search(rf'\b{kind}\b', source + header):
                    continue
                declaration = (part.opening + 1, part.opening + 1, f'\n    {kind} {local};')
                assign = (loop, loop, f'{local} = {match["lit"]};\n    ')
                use = (match.start('lit'), match.end('lit'), local)
                result.append((FAMILY, edit(source, [declaration, assign, use])))
                if len(result) >= LIMIT:
                    return result
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
