"""A loop index zeroed where the game declared it, above the branches that come before its loop.

m2c, and a hand rewrite, set a loop's index just before the loop:

    s32 i;                                   s32 i = 0;
    if (page == 0) { ... } else if ...       if (page == 0) { ... } else if ...
    i = 0;                              ->   while (strCompare(END, lines[i]) != 0) { ...; i++; }
    while (strCompare(END, lines[i]) != 0)

SN64 GCC 2.8.1 (`-G0 -mips3 -O2`) treats the two differently. loop.c looks for an induction variable's initial value only
back to the nearest label, and the join of an earlier `if` chain is a label: with `i = 0;` after the join it knows the
zero and sets the walking pointer to the array itself (`move $s0, $a0`); with the zero in the declaration, above the
chain, it does not, and computes the pointer from the index register, which lands beside it (`move $v0, $zero;
sll $v0, $v0, 2; addu $s0, $v0, $a0`). The target's shift of a freshly cleared register is the sign. A 107-instruction
N64 text-page scroller was 205 with the assignment before the loop and exact with it in the declaration (one function,
with `-fno-schedule-insns`; the reading of loop.c is from GCC 2.7.2's source, SN's 2.8.1 is closed).

m2c shows the same code as a literal zero index, `p = (0 * 4) + base;` with `p += 4` in the loop. `m2c_zero_index_walk`
writes that as the index the game had: `s32 index = 0;` in the declarations, `((T *)base)[index]` for `*p`, `index++`
for the step.

index_zero_in_declaration
    An integer local declared without a value, set once to a constant by a top-level statement after an `if` or
    `switch`, with a loop that uses it following, and not named before that statement. Two children when they differ:
    the value in the declaration where it stands, and that declaration moved below the last initialised one.
m2c_zero_index_walk
    A pointer local set to `(0 * K) + BASE`, stepped once by `K` (its element's size), and otherwise only read as `*p`.

The program reads the same elements. Proposals only; the compiler and the byte judge decide."""
import re

from .integer_repair_support import IDENT, INTEGER, NUMBER, _address_taken, edit, view

FAMILY = 'index_zero_in_declaration'
WALK_FAMILY = 'm2c_zero_index_walk'
FAMILIES = (FAMILY, WALK_FAMILY)
LIMIT = 6

_SIZES = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'int': 4, 'f32': 4,
          'float': 4}
_DECLARATION = re.compile(rf'\s*(?:{IDENT}\s+)*?{IDENT}[\s*]+{IDENT}\s*(?:\[[^\]]*\]\s*)*(?:=[^;{{}}]*(?:\{{[^{{}}]*\}})?)?;')
_NOT_DECLARATION = re.compile(r'\s*(?:return|goto|else|case|break|continue)\b')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = part.clean[part.opening:part.end]
    return (_late_zero(source, part, body) + _walks(source, part, body))[:LIMIT]


def _depth(body, at):
    return body.count('{', 0, at) - body.count('}', 0, at)


def _declarations(body):
    """(end of the last declaration at the function's top, end of the last initialised one or None)."""
    at, last, initialised = 1, 1, None
    while True:
        hit = _DECLARATION.match(body, at)
        if not hit or _NOT_DECLARATION.match(body, at):
            return last, initialised
        at = last = hit.end()
        if '=' in hit[0]:
            initialised = at


def _late_zero(source, part, body):
    out = []
    top, initialised = _declarations(body)
    for decl in re.finditer(rf'(?<=[;{{}}])\n(?P<indent>[ \t]*)(?P<type>{INTEGER})\s+(?P<name>{IDENT})\s*;', body[:top]):
        local = decl['name']
        if _address_taken(body, local):
            continue
        mentions = [hit.start() for hit in re.finditer(rf'(?<![\w.])(?<!->){re.escape(local)}\b', body)
                    if hit.start() != decl.start('name')]
        if not mentions:
            continue
        sets = re.compile(rf'(?<=[;{{}}])(?P<space>\s*){re.escape(local)}\s*=\s*(?P<value>-?{NUMBER})\s*;')
        start = next((hit for hit in sets.finditer(body)
                      if hit.start() <= mentions[0] < hit.end() and _depth(body, mentions[0]) == 1), None)
        if start is None or not re.search(r'\b(?:if|switch)\b', body[top:start.start()]):
            continue
        after = body[start.end():]
        loop = re.search(r'\b(?:for|while|do)\b|(?m:^[ \t]*[A-Za-z_]\w*:(?!:))', after)
        if not loop or not re.search(rf'\b{re.escape(local)}\b', after[loop.start():]):
            continue
        removed = (part.opening + start.start(), part.opening + start.end(), '')
        line = f'{decl["type"]} {local} = {start["value"]};'
        out.append((FAMILY, edit(source, [removed, (part.opening + decl.start('type'),
                                                    part.opening + decl.end(), line)])))
        if initialised is not None and initialised > decl.end():
            out.append((FAMILY, edit(source, [removed,
                                              (part.opening + decl.start(), part.opening + decl.end(), ''),
                                              (part.opening + initialised, part.opening + initialised,
                                               f'\n{decl["indent"]}{line}')])))
    return out


def _walks(source, part, body):
    out = []
    zero = rf'\(\s*0\s*\*\s*(?P<step>{NUMBER})\s*\)'
    cast = rf'(?:\(\s*{IDENT}[\s*]*\*\s*\)\s*)?'
    pattern = re.compile(rf'(?<=[;{{}}:])(?P<space>\s*)(?P<pointer>{IDENT})\s*=\s*{cast}(?:{zero}\s*\+\s*{cast}'
                         rf'(?P<base>&?{IDENT})|(?P<base2>&?{IDENT})\s*\+\s*{zero.replace("<step>", "<step2>")})\s*;')
    top, _ = _declarations(body)
    for hit in pattern.finditer(body):
        pointer, base = hit['pointer'], hit['base'] or hit['base2']
        step = int((hit['step'] or hit['step2']).rstrip('uUlL'), 0)
        decl = re.search(rf'\n[ \t]*(?P<type>{IDENT}(?:\s+{IDENT})*?\s*\**?)\s*\*\s*{re.escape(pointer)}\s*;', body[:top])
        if not decl or _address_taken(body, pointer):
            continue
        element = decl['type'].strip()
        if (4 if element.endswith('*') else _SIZES.get(element)) != step:
            continue
        stepped = re.compile(rf'(?<![\w.]){re.escape(pointer)}\s*(?:\+=\s*{step}|\+\+)\s*;')
        steps = list(stepped.finditer(body))
        reads = list(re.finditer(rf'\*\s*{re.escape(pointer)}\b(?!\s*(?:\[|->|\.|\+|-|=[^=]))', body[top:]))
        uses = len(re.findall(rf'(?<![\w.])(?<!->){re.escape(pointer)}\b', body))
        # the declaration, this assignment, the one step (`p += K` names it once) and the reads: nothing else
        if len(steps) != 1 or not reads or uses != 3 + len(reads):
            continue
        if re.search(rf'(?<![\w.]){re.escape(base.lstrip("&"))}\s*(?:=[^=]|\+\+|--|\+=|-=)', body[hit.end():]):
            continue
        counter = next((f'{pointer}_index{n or ""}' for n in range(20)
                        if not re.search(rf'\b{pointer}_index{n or ""}\b', source)), None)
        if counter is None:
            continue
        element_read = f'(({element}{"" if element.endswith("*") else " "}*){base})[{counter}]'
        edits = [(part.opening + top, part.opening + top, f'\n    s32 {counter} = 0;'),
                 (part.opening + decl.start(), part.opening + decl.end(), ''),
                 (part.opening + hit.start('pointer'), part.opening + hit.end(), ';' if hit[0] and
                  body[:hit.start()].rstrip().endswith(':') else ''),
                 (part.opening + steps[0].start(), part.opening + steps[0].end(), f'{counter}++;')]
        edits += [(part.opening + top + read.start(), part.opening + top + read.end(), element_read) for read in reads]
        out.append((WALK_FAMILY, edit(source, edits)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 40}
