"""A literal stored into one field of every record of a run, as one local per field set at the function's entry.

SN64 GCC 2.8.1 (`-G0 -mips3 -O2 ... -mfp64`), a 262-instruction N64 display-list builder: after its last calls it fills
four vertices (`v[0].ob[0] = -size; ... v[0].cn[0] = 0xFF; ...`), sixteen colour bytes of 0xFF. The target loads the
0xFF once, `li $t6, 0xFF`, after every other value of the block, in the register reload uses for the function's `mflo`
copies; the literal is one block-local pseudo with 17 references, which local-alloc colours first (`$v1`), and every
other value of the block came out one register round (470 in the app, 50 register rows). The original held the
colour in variables set at the top of the function, one per channel (`r = g = b = a = 0xFF` as four statements): each is
a global pseudo with five references live across the seven calls, so global.c ranks it below every other saved-register
candidate (floor_log2 (refs) * refs / live length), finds the call-saved registers taken, and caller-save is not
profitable (4 * calls >= refs): the pseudo gets no register. Its REG_EQUIV constant is then reloaded at each store into
the spill register, and reload inheritance keeps the one `li` (read in the `-dl -dg` dumps: the four pseudos are absent
from global.c's dispositions). With the channel locals the function was 82; with the vertex stores in field order
(`ob`, `cn`, `tc` for each vertex in turn, where the saved best had a store order tuned to the old allocation) it is 0.

A run of at least eight statements `BASE[i].field = value;` / `BASE[i].field[j] = value;`, after a call, in which one
non-zero literal is stored into at least two fields (`cn[0]`, `cn[1]`, ...) at least twice each: one child with a local
per field set at the entry (before the first statement, and after the opening run of `name = number;` statements when
there is one), each also with the run in record order and each record's fields in the order of their first
appearance in the run (a field's elements in index order). The run's values must not call, step or read the records,
so the reordering keeps the program.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'constant_channel_locals'
FAMILIES = (FAMILY,)

STORE = re.compile(r'(?m)^([ \t]*)([A-Za-z_]\w*)\[(\d+)\]\.([A-Za-z_]\w*)(?:\[(\d+)\])?\s*=\s*([^;=]+?)\s*;[ \t]*$')
NUMBER = re.compile(r'^(?:0[xX][0-9A-Fa-f]+|[0-9]+)[uU]?$')
DECLARATION = re.compile(r'^[ \t]*(?:(?:const|unsigned|signed|struct|volatile|register)\s+)*[A-Za-z_]\w*'
                         r'(?:\s*\*+\s*|\s+)[A-Za-z_]\w*(?:\s*\[[^\]]*\])*\s*;[ \t]*$')
ASSIGN_NUMBER = re.compile(r'^[ \t]*[A-Za-z_]\w*\s*=\s*-?(?:0[xX][0-9A-Fa-f]+|[0-9]+)\s*;[ \t]*$')
CALL = re.compile(r'\b[A-Za-z_]\w*\s*\(')
MIN_RUN = 8


def _value(text):
    text = text.rstrip('uU')
    return int(text, 16 if text.lower().startswith('0x') else 10)


def _runs(clean, start, end):
    """Maximal runs of record stores to one base, as lists of (match, absolute start, absolute end)."""
    runs, current = [], []
    position = start
    for hit in STORE.finditer(clean, start, end):
        between = clean[position:hit.start()]
        same = current and current[-1][0][2] == hit[2] and not between.strip()
        if not same:
            if len(current) >= MIN_RUN:
                runs.append(current)
            current = []
        current.append((hit, hit.start(), hit.end()))
        position = hit.end()
    if len(current) >= MIN_RUN:
        runs.append(current)
    return runs


def _entry_places(clean, opening, end):
    """Where the entry assignments go: before the first statement, and after the opening `name = number;` run."""
    lines = []
    position = opening + 1
    for line in clean[opening + 1:end].split('\n'):
        lines.append((position, line))
        position += len(line) + 1
    index = 0
    while index < len(lines) and (not lines[index][1].strip() or DECLARATION.match(lines[index][1])):
        index += 1
    if index >= len(lines):
        return []
    first = lines[index][0]
    places = [first]
    after = index
    while after < len(lines) and ASSIGN_NUMBER.match(lines[after][1]):
        after += 1
    if after > index and after < len(lines):
        places.append(lines[after][0])
    return places, first


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    clean = part.clean
    found = []
    for run in _runs(clean, part.opening + 1, part.end):
        base = run[0][0][2]
        if not CALL.search(clean, part.opening + 1, run[0][1]):
            continue  # the locals only lose their register when they live across calls
        if any(CALL.search(hit[6]) or '++' in hit[6] or '--' in hit[6] or re.search(rf'\b{base}\b', hit[6])
               for hit, _, _ in run):
            continue
        channels = {}
        for hit, _, _ in run:
            if NUMBER.match(hit[6]) and _value(hit[6]):
                channels.setdefault(hit[6], {}).setdefault((hit[4], hit[5]), []).append(hit)
        for literal, fields in channels.items():
            if len(fields) < 2 or any(len(hits) < 2 for hits in fields.values()):
                continue
            names = {}
            for field, index in fields:
                local = f'{field}{index or ""}_k'
                if re.search(rf'\b{local}\b', clean):
                    break
                names[(field, index)] = local
            else:
                entry = _entry_places(clean, part.opening, part.end)
                if not entry:
                    continue
                places, first = entry
                declarations = ''.join(f'    s32 {local};\n' for local in names.values())
                replace = [(hit.start(6), hit.end(6), names[(hit[4], hit[5])])
                           for hits in fields.values() for hit in hits]
                # the run in record order, each record's fields in the order the run first names them
                order = {}
                for hit, _, _ in run:
                    order.setdefault(hit[4], len(order))
                keyed = sorted(run, key=lambda item: (int(item[0][3]), order[item[0][4]], int(item[0][5] or 0)))
                text = {id(hit): (names[(hit[4], hit[5])] if (hit[4], hit[5]) in names and hit[6] == literal
                                  else hit[6]) for hit, _, _ in run}
                lines = '\n'.join(f'{hit[1]}{hit[2]}[{hit[3]}].{hit[4]}' + (f'[{hit[5]}]' if hit[5] else '')
                                  + f' = {text[id(hit)]};' for hit, _, _ in keyed)
                sorted_run = [(run[0][1], run[-1][2], lines)]
                for place in places:
                    assigns = ''.join(f'    {local} = {literal};\n' for local in names.values())
                    declare = (first, first, declarations) if place != first else None
                    head = [(place, place, (declarations if place == first else '') + assigns)]
                    head += [declare] if declare else []
                    found.append((FAMILY, edit(source, head + replace)))
                    found.append((FAMILY, edit(source, head + sorted_run)))
    return found


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
