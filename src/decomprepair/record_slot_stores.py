"""Writes to a record array's slot stored through a pointer to the slot, the values still read by index.

The target computes the slot's address into a register that both stores use (`addu $v0,$a1,$v0; sb $v1,0($v0); ...
sb $v1,0xc($v0)`) while each value is loaded by index again (`lui $v1; addu $v1,$v1,$a1; lbu $v1,%lo(table)($v1)`).
`table[i].count++; table[i].total++;` gives the address from `$at` instead. The source shape (KMC GCC 2.7.2 -O1, a
99-instruction counter update over 100-byte records, 645 -> 0 once the tested byte was held):

    table[i].count = v + 1;          ->   { Rec *__repair_slot = &table[i];
    table[i].total--;                       __repair_slot->count = v + 1;
                                            __repair_slot->total = table[i].total - 1; }

`record_slot_held_test` is the step before it: a member the condition of an `if` reads and its block updates, held in a
local for the test and the update (`{ s32 h = table[i].count; if ((u32) (h - 6) < 6) { table[i].count = h + 1; ...`),
where the target keeps the loaded value in a register for both (965 -> 645).

`record_slot_base_pointer` holds the array's address in a pointer local of its own before the slot's:

    Rec *p = &table[i];              ->   Rec *__repair_base = table;
                                          Rec *p = &__repair_base[i];

The address is then an insn loop.c sees apart from the index arithmetic, with a life long enough to hoist out of the
loop (`lui $t0; addiu $t0` before it, `addu $v1,$v1,$t0` inside), where `&table[i]` loads it again each iteration
("move-insn ... not desirable" in the .loop dump). KMC GCC 2.7.2 -O1, a 149-instruction initialiser over 5-byte records,
465 -> 0 from direct member writes through `record_slot_store_pointer`. It is offered for a declaration already in the
source and for each slot pointer `record_slot_store_pointer` makes, as one child.

Offered for `extern T table[];` arrays and runs of two or more writes to one `table[i]`: all updating runs together
(runs of numbers stay indexed), all runs, and each run alone. The candidate is never a verdict: the judge decides.
"""
import re

from .c_scan import close
from .csource import _blank, find

FAMILY = 'record_slot_store_pointer'
HELD = 'record_slot_held_test'
BASE = 'record_slot_base_pointer'
FAMILIES = (FAMILY, HELD, BASE)
LIMIT = 8
_ID = r'[A-Za-z_]\w*'
_ARRAY = re.compile(rf'\bextern\s+({_ID})\s+({_ID})\s*\[\s*\w*\s*\]\s*;')
_WRITE = re.compile(rf'(?P<table>{_ID})\s*\[(?P<index>[^\[\];{{}}]+)\]\s*\.\s*(?P<member>{_ID})\s*'
                    r'(?:(?P<step>\+\+|--)|(?P<op>[+\-&|^])?=(?!=)\s*(?P<value>[^;{}]+?))\s*;')
_IF = re.compile(r'\bif\s*\(')
_SLOT = re.compile(rf'\b(?P<kind>{_ID})\s*\*\s*(?P<pointer>{_ID})\s*=\s*&\s*(?P<table>{_ID})\s*'
                   r'\[(?P<index>[^\[\];{}]+)\]\s*;')


def _runs(clean, source, lo, hi, tables):
    """Runs of two or more consecutive writes to one `table[i]`, as lists of matches."""
    runs, current = [], []
    for m in _WRITE.finditer(clean, lo, hi):
        before = clean[:m.start()].rstrip()
        if m['table'] not in tables or not before or before[-1] not in '{};':
            continue
        same = (current and not clean[current[-1].end():m.start()].strip()
                and (m['table'], m['index'].strip()) == (current[-1]['table'], current[-1]['index'].strip()))
        if same:
            current.append(m)
            continue
        if len(current) > 1:
            runs.append(current)
        current = [m]
    if len(current) > 1:
        runs.append(current)
    return runs


def _is_constant(m, source):
    """A plain store of a number: the target keeps these indexed (`sb $zero,%lo(table)($at)`)."""
    return not m['step'] and not m['op'] and re.fullmatch(r'\s*-?(0[xX][0-9A-Fa-f]+|\d+)\s*', source[m.start('value'):m.end('value')]) is not None


def _through_pointer(source, run, kind, slot):
    first = run[0]
    table, index = first['table'], source[first.start('index'):first.end('index')].strip()
    lines = [f'{{ {kind} *{slot} = &{table}[{index}];']
    for m in run:
        member = m['member']
        read = f'{table}[{index}].{member}'
        if m['step']:
            value = f'{read} {m["step"][0]} 1'
        else:
            value = source[m.start('value'):m.end('value')]
            if m['op']:
                value = f'{read} {m["op"]} ({value})'
        lines.append(f'{slot}->{member} = {value};')
    return ' '.join(lines) + ' }'


def _pointer_children(source, clean, lo, hi, tables):
    runs = _runs(clean, source, lo, hi, tables)
    if not runs or '__repair_slot' in clean:
        return []
    updates = [run for run in runs if not all(_is_constant(m, source) for m in run)]
    picks = ([updates] if len(updates) > 1 else []) + ([runs] if len(runs) > max(1, len(updates)) else []) + [[run] for run in runs]
    out = []
    for pick in picks[:LIMIT]:
        edited = source
        for run in reversed(pick):
            text = _through_pointer(source, run, tables[run[0]['table']], '__repair_slot')
            edited = edited[:run[0].start()] + text + edited[run[-1].end():]
        out.append((FAMILY, edited))
    return out


def _held_edits(source, clean, lo, hi, tables):
    """(start, end, replacement) for each `if` whose condition reads a member its block's first write updates."""
    edits = []
    for m in _IF.finditer(clean, lo, hi):
        depth, i = 0, m.end() - 1
        while i < hi:
            depth += (clean[i] == '(') - (clean[i] == ')')
            i += 1
            if depth == 0:
                break
        body = re.match(r'\s*\{\s*', clean[i:hi])
        if not body:
            continue
        opening = clean.index('{', i)
        tail = close(clean, opening)
        write = _WRITE.match(clean, i + body.end())
        if tail < 0 or not write or write['table'] not in tables or re.match(r'\s*else\b', clean[tail + 1:hi]):
            continue
        if not (write['step'] or write['op'] in ('+', '-')):
            continue
        read = source[write.start():write.end('member')]
        condition = source[m.start():i]
        if condition.count(read) != 1:
            continue
        sign, amount = (write['step'][0], '1') if write['step'] else (write['op'], source[write.start('value'):write.end('value')])
        text = (f'{{ s32 __repair_held = {read}; {condition.replace(read, "__repair_held")}'
                f'{source[i:write.start()]}{read} = __repair_held {sign} {amount};{source[write.end():tail + 1]} }}')
        edits.append((m.start(), tail + 1, text))
    return edits


def _held_children(source, clean, lo, hi, tables):
    if '__repair_held' in clean:
        return []
    edits = _held_edits(source, clean, lo, hi, tables)
    picks = ([edits] if len(edits) > 1 else []) + [[edit] for edit in edits]
    out = []
    for pick in picks[:LIMIT]:
        edited = source
        for start, end, text in reversed(pick):
            edited = edited[:start] + text + edited[end:]
        out.append((HELD, edited))
    return out


def _based(text, tables):
    """Each `T *p = &table[index];` of the text, with the table's address in a pointer local declared before it."""
    clean = _blank(text)
    if '__repair_base' in clean:
        return []
    found = [m for m in _SLOT.finditer(clean)
             if tables.get(m['table']) == m['kind'] and clean[:m.start()].rstrip().endswith(('{', ';', '}'))]
    picks = ([found] if len(found) > 1 else []) + [[m] for m in found]
    out = []
    for pick in picks[:LIMIT]:
        edited = text
        for number, m in reversed(list(enumerate(pick))):
            base = f'__repair_base{number or ""}'
            index = text[m.start('index'):m.end('index')].strip()
            edited = (edited[:m.start()] + f'{m["kind"]} *{base} = {m["table"]}; {m["kind"]} *{m["pointer"]} = &{base}[{index}];'
                      + edited[m.end():])
        out.append((BASE, edited))
    return out


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    tables = {m[2]: m[1] for m in _ARRAY.finditer(clean)}
    if opening < 0 or not tables:
        return []
    pointers = _pointer_children(source, clean, opening, span[1], tables)
    based = _based(source, tables)
    for _, slotted in pointers:
        based += _based(slotted, tables)[:1]
    return pointers + _held_children(source, clean, opening, span[1], tables) + based[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
