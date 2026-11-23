"""A value every arm of a switch computes the same way, tested once after the switch.

m2c writes `v = e;` at the end of each arm (and `goto L;` from the arms that share the default's tail, `default: L: v = e;`)
and then `if (v != 0)` after the switch. The original tested `e` where the arms meet. KMC gcc 2.7.2
(`-G0 -mips3 -mgp32 -mfp32 -O2`) treats the two differently: `v` set in several arms and read at the join is one
pseudo that global.c colours (the arms' `andi` ran in `$v1` where the target has `$v0`, three rows, beside a jump table's
temporaries), and the arms' copies of the join's `andi` are what reorg's delay slots take from the join in the target
when the join is its own block. Written as the join's own expression the arms' assignments, the labels and the gotos go
(a 445-instruction N64 target picker: 705 -> 685, and the three `$v0` rows were the last of its register rows but a
priority tie).

The rewrite needs `v` assigned only by the same `v = e;` statements inside the switch and read only by the condition of
the statement right after it, and none of `e`'s operands changed between an arm's assignment and the end of the arm.
A candidate for the exact judge, never a verdict.
"""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'switch_join_condition'
FAMILIES = (FAMILY,)
_SWITCH = re.compile(r'\bswitch\s*\(')
_ASSIGN = re.compile(r'(?m)^[ \t]*([A-Za-z_]\w*)[ \t]*=[ \t]*([^;{}=][^;{}]*);[ \t]*\n')
_IDENT = re.compile(r'[A-Za-z_]\w*')


def _writes(text, name):
    return re.search(rf'\b{re.escape(name)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{re.escape(name)}\b|\b{re.escape(name)}\s*(?:\+\+|--)', text)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    result = []
    for hit in _SWITCH.finditer(clean, part.opening, part.end):
        brace = clean.find('{', close(clean, hit.end() - 1) or 0)
        end = close(clean, brace, '{', '}') if brace >= 0 else None
        if not end:
            continue
        inside = clean[brace:end]
        # the statement after the switch: `if (cond)`
        after = re.match(r'\s*if\s*\(', clean[end:])
        if not after:
            continue
        cond_open = end + after.end() - 1
        cond_end = close(clean, cond_open)
        if not cond_end:
            continue
        # the join label of the default arm: `default: L: v = e;` last in the switch
        tail = re.search(r'default\s*:\s*(?:(\w+)\s*:\s*)?([A-Za-z_]\w*)[ \t]*=[ \t]*([^;{}]+);\s*}\s*$', inside)
        if not tail:
            continue
        label, var, expr = tail[1], tail[2], tail[3].strip()
        operands = set(_IDENT.findall(expr))
        if re.search(rf'\b{re.escape(var)}\b', clean[end:cond_open]) or not re.search(rf'\b{re.escape(var)}\b', clean[cond_open:cond_end]):
            continue
        # no other mention of `var` in the function outside the switch's assignments and the condition
        declaration = re.search(rf'(?m)^[ \t]*[A-Za-z_][\w \t*]*[ \t*]{re.escape(var)}[ \t]*;[ \t]*\n', clean[part.opening:brace])
        outside = clean[part.opening:brace] + clean[cond_end:part.end]
        if declaration:
            outside = outside.replace(declaration[0], '', 1)
        if re.search(rf'\b{re.escape(var)}\b', outside):
            continue
        edits = []
        if declaration:
            edits.append((part.opening + declaration.start(), part.opening + declaration.end(), ''))
        body_start = brace
        for assign in _ASSIGN.finditer(inside):
            if assign[1] != var:
                if re.search(rf'\b{re.escape(var)}\b', assign[0]):
                    edits = None
                    break
                continue
            if assign[2].strip() != expr:
                edits = None
                break
            after_text = inside[assign.end():]
            arm = re.split(r'\bbreak\s*;|\bgoto\s+\w+\s*;|\bcase\b|\bdefault\b|}\s*$', after_text, maxsplit=1)[0]
            if any(_writes(arm, ident) for ident in operands):
                edits = None
                break
            edits.append((body_start + assign.start(), body_start + assign.end(), ''))
        if not edits:
            continue
        # the default arm's own assignment (and its label) stands for the join: nothing to run there
        default = re.search(r'default\s*:\s*(?:(\w+)\s*:\s*)?([A-Za-z_]\w*)[ \t]*=[ \t]*([^;{}]+);', inside)
        drop = [e for e in edits if e[0] >= body_start + default.start()]
        edits = [e for e in edits if e not in drop]
        edits.append((body_start + default.start(), body_start + default.end(), 'default:\n            break;'))
        if label:
            for goto in re.finditer(rf'\bgoto\s+{re.escape(label)}\s*;', inside):
                edits.append((body_start + goto.start(), body_start + goto.end(), 'break;'))
            if re.search(rf'\b{re.escape(label)}\s*:', clean[part.opening:brace] + clean[end:part.end]):
                continue
        condition = source[cond_open + 1:cond_end - 1]
        edits.append((cond_open + 1, cond_end - 1, re.sub(rf'\b{re.escape(var)}\b', f'({expr})', condition)))
        result.append((FAMILY, edit(source, edits)))
    return result[:4]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 100}  # the registry: no caller wiring (registry.py)
