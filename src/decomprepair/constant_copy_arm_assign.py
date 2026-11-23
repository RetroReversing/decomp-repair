"""A conditional copy between two locals that hold the same constant, kept alive by assigning the constant in both arms.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) split-screen setup routine (4500, 1040 points of it this
step): the target tests a TV-standard word and, on one side, copies one zeroed local into another (`beqz $v0, .L;
move $s7, $zero; move $s3, $s7`, the zero of the source local in the branch's delay slot). Written as the m2c draft
has it (`x = 0; y = 0; if (tv) { x = y; }`) the compiler deletes the whole thing: cse proves `x` and `y` are the
same constant, `x = y` is a no-op, the branch and the load of the word go with it, and every register after it
shifts. With the zero assigned in BOTH arms of the test (`x = 0; if (tv) { y = 0; x = y; } else { y = 0; }`) the
copy is not provably redundant any more, the test and the copy stay, and reorg's delay-slot fill moves the common
`y = 0` into the slot of the branch (it is the first insn of both threads) as the target has it.

constant_copy_arm_assign
    `if (c) { a = b; }` with no `else`, where `b` is a local initialised to a literal (in its declaration, or by an
    assignment statement before the test with no read of `b` between) and `a` was last set to the same literal (a
    literal, or a local that holds it) is written `if (c) { b = L; a = b; } else { b = L; }` and `b`'s earlier
    initialisation is removed. Hypothesis from the match, not from the compiler source: cse deletes a set whose
    source and destination are already in one value class (`cse_insn`, the redundant-set check); a set of `b` inside
    each arm leaves `b` with a value that is not known at the join.

The exact judge decides every child.
"""
import re

from .integer_repair_support import IDENT, view
from .pattern_repairs import close

FAMILY = 'constant_copy_arm_assign'
FAMILIES = (FAMILY,)
LIMIT = 4
_NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'
_TYPE = r'(?:unsigned\s+(?:long|int|short|char)|signed\s+(?:long|int|short|char)|[su](?:8|16|32)|int|long|short|char)'


def _value(text):
    text = re.sub(r'[uUlL]+$', '', text.strip())
    return int(text, 16 if text.lower().startswith('0x') else 10)


def _literal_of(clean, name, before, low):
    """The literal `name` holds just before offset `before` when its last set is a literal one, else None, with the
    span of that set when it is a plain statement or an initialiser: (value, (start, end) or None)."""
    last = None
    for hit in re.finditer(rf'(?<![\w.>]){re.escape(name)}\s*=(?!=)\s*({_NUMBER})\s*;', clean[low:before]):
        if clean[low:low + hit.start()].rstrip()[-1:] not in ('', ';', '{', '}'):
            continue  # the tail of a declaration (`u32 y = 0;`) or of a larger expression
        last = (_value(hit[1]), (low + hit.start(), low + hit.end(), 'statement'))
    declared = None
    for hit in re.finditer(rf'\b{_TYPE}\s+{re.escape(name)}\s*=\s*({_NUMBER})\s*;', clean[low:before]):
        declared = (_value(hit[1]), (low + hit.start(), low + hit.end(), 'declaration'))
    if declared and (not last or last[1][0] < declared[1][0]):
        return declared
    return last


def _assignments(clean, name, before, low):
    """Every assignment to `name` before `before`, as (end offset, right-hand text)."""
    return [(low + hit.end(), hit[1].strip())
            for hit in re.finditer(rf'(?<![\w.>]){re.escape(name)}\s*=(?!=)\s*([^;{{}}]+?)\s*;', clean[low:before])]


def _held(clean, name, before, low, depth=0):
    """The literal value local `name` holds at `before`, following one level of `a = seed;` copies."""
    direct = _literal_of(clean, name, before, low)
    sets = _assignments(clean, name, before, low)
    declared = re.search(rf'\b{_TYPE}\s+{re.escape(name)}\s*=\s*({_NUMBER})\s*;', clean[low:before])
    if sets and sets[-1][1] and re.fullmatch(_NUMBER, sets[-1][1]):
        return _value(sets[-1][1])
    if sets and depth == 0 and re.fullmatch(IDENT, sets[-1][1]):
        return _held(clean, sets[-1][1], before, low, 1)
    if not sets and declared:
        return _value(declared[1])
    if direct and not sets:
        return direct[0]
    return None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    low, high = part.opening + 1, part.end - 1
    result = []
    for branch in re.finditer(r'\bif\s*\(', clean[low:high]):
        start = low + branch.start()
        end_condition = close(clean, low + branch.end() - 1)
        if not end_condition:
            continue
        opening = re.match(r'\s*\{', clean[end_condition:])
        if not opening:
            continue
        brace = end_condition + opening.end() - 1
        brace_end = close(clean, brace, '{', '}')
        if not brace_end:
            continue
        body = clean[brace + 1:brace_end - 1]
        copy = re.fullmatch(rf'\s*({IDENT})\s*=\s*({IDENT})\s*;\s*', body)
        if not copy or re.match(r'\s*else\b', clean[brace_end:]) or copy[1] == copy[2]:
            continue
        target, source_name = copy[1], copy[2]
        literal_b = _literal_of(clean, source_name, start, low)
        if not literal_b or _held(clean, target, start, low) != literal_b[0]:
            continue
        # b is only read by the copy: nothing between its initialisation and the test names it
        init = literal_b[1]
        if re.search(rf'(?<![\w.>]){re.escape(source_name)}\b', clean[init[1]:start]):
            continue
        if re.search(rf'&\s*{re.escape(source_name)}\b|\bvolatile\b', clean[low:high]):
            continue
        value = source[init[0]:init[1]]
        number = re.search(_NUMBER, value[value.index('='):])[0]
        indent = re.search(r'[ \t]*$', source[:start])[0]
        step = '    ' if '\t' not in indent else '\t'
        arm = f'{indent}{step}{source_name} = {number};\n'
        replaced = (f'if ({source[low + branch.end():end_condition - 1]}) {{\n{arm}{indent}{step}{target} = {source_name};\n'
                    f'{indent}}} else {{\n{arm}{indent}}}')
        edits = [(start, brace_end, replaced)]
        if init[2] == 'declaration':
            edits.append((init[0], init[1], source[init[0]:init[1]].split('=')[0].rstrip() + ';'))
        else:
            line_start = source.rfind('\n', 0, init[0]) + 1
            if not source[line_start:init[0]].strip():
                tail = source[init[1]:init[1] + 1]
                edits.append((line_start, init[1] + (1 if tail == '\n' else 0), ''))
            else:
                edits.append((init[0], init[1], ''))
        text = source
        for edit_start, edit_end, replacement in sorted(edits, reverse=True):
            text = text[:edit_start] + replacement + text[edit_end:]
        if text != source:
            result.append((FAMILY, text))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
