"""Recover a switch from a compare tree with a goto into another case's block.

A KMC MIPS O2 MIDI dispatcher had a zero-velocity note-on path sharing the
note-off block through a label. Writing the compare tree as a switch and
retaining the jump into that block improved one linked judge from 15571 to
9066. The tree's tests are evaluated over boundaries and their intervals;
non-singleton cases, external incoming jumps, and escaping breaks are rejected.
"""
import re

from .arm_block_support import statements
from .compare_tree_default_switch import _condition, _leaf_for, _own_break, _statement_if, _walk
from .integer_repair_support import IDENT, edit, view

FAMILY = 'compare_tree_shared_label'


def _tree(clean, start, stop, variable):
    lead = len(clean[start:stop]) - len(clean[start:stop].lstrip())
    parsed = _statement_if(clean, start + lead)
    if not parsed:
        return ('leaf', (start, stop))
    condition_text = clean[parsed[0][0]:parsed[0][1]]
    condition = _condition(condition_text)
    simple = re.fullmatch(r'\s*' + re.escape(variable) + r'\s*(?:==|!=|<=|>=|<|>)\s*(0[xX][0-9a-fA-F]+|\d+)\s*', condition_text)
    if not condition or condition[0] != variable or not simple or int(simple[1], 0) > 0x7fffffff:
        return ('leaf', (start, stop))
    if not clean[parsed[3]:stop].strip():
        yes = _tree(clean, *parsed[1], variable)
        no = _tree(clean, *parsed[2], variable) if parsed[2] else ('leaf', (parsed[3], parsed[3]))
        return ('if', condition[1], condition[2], yes, no)
    if not parsed[2]:
        items = statements(clean, *parsed[1])
        if items and re.fullmatch(r'\s*(?:return\s*;|goto\s+' + IDENT + r'\s*;)\s*', clean[items[-1][0]:items[-1][1]]):
            return ('if', condition[1], condition[2], _tree(clean, *parsed[1], variable), _tree(clean, parsed[3], stop, variable))
    return ('leaf', (start, stop))


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b__(?:LINE|COUNTER)__\b', source + '\n' + header):
        return []
    clean = part.clean
    macros = set(re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+(' + IDENT + r')\b', source + '\n' + header))
    null_defs = re.findall(r'(?m)^\s*#\s*define\s+NULL\s+([^\n]+)', source + '\n' + header)
    if not re.search(r'(?m)^\s*#\s*undef\s+NULL\b', source + '\n' + header) and null_defs and all(re.fullmatch(r'\s*\(\s*\(\s*void\s*\*\s*\)\s*0\s*\)\s*', d) for d in null_defs):
        macros.discard('NULL')
    result = []
    for head in re.finditer(r'\bif\s*\(', clean[part.opening:part.end]):
        at = part.opening + head.start()
        if clean[:at].rstrip().endswith('else'):
            continue
        parsed = _statement_if(clean, at)
        if not parsed:
            continue
        condition = _condition(clean[parsed[0][0]:parsed[0][1]])
        if not condition or condition[0] in macros:
            continue
        variable = condition[0]
        declarations = re.findall(r'\b(s32|s16|s8|int|short)\s+' + re.escape(variable) + r'\b', clean[:part.end])
        if (len(declarations) != 1 or declarations[0] in macros
                or re.search(r'\b(?:unsigned|volatile)\s+(?:s32|s16|s8|int|short)\s+' + re.escape(variable) + r'\b', clean[:part.end])):
            continue
        if re.search(r'\btypedef\s+(?:unsigned|volatile)\b[^;]*\b' + re.escape(declarations[0]) + r'\s*;', source + '\n' + header):
            continue
        stop = parsed[3]
        # Empty default and return are equivalent only at the end of this void function.
        if clean[stop:part.end].strip() not in ('', '}') or not re.search(r'\bvoid\s+' + re.escape(name) + r'\s*\(', clean[:part.opening]):
            continue
        tree = _tree(clean, at, stop, condition[0])
        nodes = list(_walk(tree))
        tests = [node for node in nodes if node[0] == 'if']
        leaves = [node[1] for node in nodes if node[0] == 'leaf']
        if len(tests) < 4:
            continue
        labels = set(re.findall(r'(?<![\w?:])(' + IDENT + r')\s*:(?!:)', clean[at:stop])) - {'case', 'default'}
        jumps = set(re.findall(r'\bgoto\s+(' + IDENT + r')\s*;', clean[at:stop]))
        if not labels & jumps or any(re.search(r'\bgoto\s+' + re.escape(label) + r'\b', clean[part.opening:at] + clean[stop:part.end]) for label in labels):
            continue
        if any(_own_break(clean, span) for span in leaves):
            continue
        # Retained labels must not be duplicated or introduced by macros.
        if labels & macros or set(re.findall(IDENT, clean[at:stop])) & macros:
            continue
        def arm(value, tree=tree):
            span = _leaf_for(tree, value)
            text = clean[span[0]:span[1]].strip()
            return None if text in ('', 'return;') else span
        constants = sorted({k for node in tests for k in node[2]})
        probes = sorted({k + d for k in constants for d in (-1, 0, 1)})
        if arm(constants[0] - 100000) is not None or arm(constants[-1] + 100000) is not None:
            continue
        cases = {}
        for value in probes:
            found = arm(value)
            if found is not None:
                cases.setdefault(found, []).append(value)
        if not cases or sum(map(len, cases.values())) > 24:
            continue
        if any(arm((a + b) // 2) is not None and (a + b) // 2 not in probes for a, b in zip(constants, constants[1:]) if b - a > 2):
            continue
        chunks = []
        for span in sorted(cases, key=lambda item: min(cases[item])):
            names = ''.join(f'case {value:#x}:\n' for value in cases[span])
            chunks.append(names + '{\n' + source[span[0]:span[1]] + '\n} break;\n')
        text = 'switch (' + condition[0] + ') {\n' + ''.join(chunks) + 'default: break;\n}'
        result.append((FAMILY, edit(source, [(at, stop, text)])))
        break
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
