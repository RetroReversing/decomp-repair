"""Inline branch-local float arguments after splitting a shared call.

A compiler can cross-jump two branch-local calls into one; m2c writes the arguments into locals and puts the call
at the join. `call_into_arms` restores the two calls but leaves other branch-local argument snapshots. On a large
N64 function, splitting alone scored 9,235 from 9,910 under KMC GCC 2.7.2 -G0 -mips3 -mgp32 -mfp32 -O1; inlining two
float arguments as well scored 8,565. This is one diagnostic observation, not a match.

Only simple float locals whose complete uses are arguments of prototyped float parameters are considered. Their
assignments must be adjacent to those calls, and cannot depend on a subsequently assigned local. The only memory
read accepted is the standard nonvolatile M2C_FIELD macro. Offer the split and inlining together as one child.
"""
import re

from . import m2cfix, tail_call_arm_repairs
from .csource import find
from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'branch_float_call_inline'
FAMILIES = (FAMILY,)
LIMIT = 8
_CALL = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<callee>{IDENT})\((?P<args>[^;\n]*)\);[ \t]*(?:\n|$)')
_ASSIGN = re.compile(rf'^(?P<indent>[ \t]*)(?P<name>{IDENT})\s*=\s*(?P<value>[^;\n]+);[ \t]*(?:\n|$)')
_FIELD = re.compile(rf'M2C_FIELD\(\s*{IDENT}\s*,\s*f32\s*\*\s*,\s*{NUMBER}\s*\)')
_MACRO = re.compile(r'(?m)^\s*#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s*'
                    r'\(\*\(type_ptr\)\(\(s8\s*\*\)\(expr\)\s*\+\s*\(offset\)\)\)[ \t]*$')


def _safe_value(value, floats, macros):
    """Float names, float literals, arithmetic, and ordinary M2C float fields only."""
    tokens = re.findall(r'\b[A-Za-z_]\w*\b', value)
    if any(name not in ('M2C_FIELD', 'f32') and
           re.search(rf'(?m)^\s*#\s*(?:define|undef)\s+{re.escape(name)}\b', macros) for name in tokens):
        return False
    text = _FIELD.sub('0.0f', value)
    if not re.fullmatch(r'[\w\s.+*/()\-]+', text) or re.search(r'\+\+|--|/\*|//', text):
        return False
    names = re.findall(r'\b[A-Za-z_]\w*\b', text)
    return all(name in floats and not re.search(rf'(?m)^\s*#\s*(?:define|undef)\s+{re.escape(name)}\b', macros)
               for name in names)


def _inline(source, name, header):
    part, span = view(source, name), find(source, name)
    if not part or not span or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean[span[0]:part.end]):
        return None
    macros = source + '\n' + (header or '')
    if (len(re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+M2C_FIELD\b', macros)) != 1 or not _MACRO.search(macros)
            or re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\bf32\s*;', macros)
            or re.search(r'(?m)^\s*#\s*(?:define|undef)\s+f32\b', macros)):
        return None
    clean = part.clean
    declarations = {}
    for decl in re.finditer(rf'(?m)^[ \t]*f32\s+(?P<name>{IDENT})\s*;[ \t]*\n', clean[part.opening:part.end]):
        declarations.setdefault(decl['name'], []).append((part.opening + decl.start(), part.opening + decl.end()))
    floats = {name for name, decl in declarations.items() if len(decl) == 1}
    sites = {}
    for call in _CALL.finditer(clean, part.opening + 1, part.end):
        if re.search(r'/[*/]|#', source[call.start():call.end()]):
            continue
        proto = re.search(rf'(?m)^[^\n;{{}}]*\b{re.escape(call["callee"])}\s*\(([^()]*)\)\s*;', clean[:span[0]])
        if not proto:
            continue
        params = [p.strip() for p in proto[1].split(',')]
        args = m2cfix._split_top_level(call['args'])
        # Moving a snapshot into a call is only safe if evaluating the other arguments cannot mutate it or
        # perform a volatile read. Keep the other arguments to simple names, addresses and literals.
        arg_text = _FIELD.sub('0.0f', call['args'])
        simple_arg = rf'(?:&\s*)?{IDENT}|-?(?:0[xX][0-9A-Fa-f]+|\d+(?:\.\d*)?[fF]?)'
        if (len(args) != len(params) or any(not re.fullmatch(simple_arg, arg.strip()) for arg in args)
                or re.search(r'\+\+|--|(?<![=!<>])=(?!=)|\b' + IDENT + r'\s*\(', arg_text)
                or any(re.search(rf'(?m)^\s*#\s*define\s+{re.escape(token)}\b', macros)
                       for token in re.findall(r'\b[A-Za-z_]\w*\b', call['args']) if token not in ('M2C_FIELD', 'f32'))
                or re.search(rf'(?m)^\s*#\s*define\s+{re.escape(call["callee"])}\b', macros)):
            continue
        preceding = []
        pos = call.start()
        while pos > part.opening:
            start = clean.rfind('\n', part.opening, pos - 1) + 1
            line = _ASSIGN.fullmatch(clean[start:pos])
            if (not line or line['indent'] != call['indent'] or line['name'] not in floats
                    or re.search(r'/[*/]|#', source[start:pos])
                    or not _safe_value(line['value'], floats, macros)):
                break
            preceding.insert(0, (start, pos, line['name'], line['value']))
            pos = start
        for index, arg in enumerate(args):
            var = arg.strip()
            if var not in floats or not re.fullmatch(r'f32(?:\s+\w+)?', params[index]):
                continue
            matches = [(a, b, value, k) for k, (a, b, target, value) in enumerate(preceding) if target == var]
            if len(matches) != 1:
                continue
            a, b, value, k = matches[0]
            later = {entry[2] for entry in preceding[k + 1:]}
            if not _safe_value(value, floats, macros) or any(re.search(rf'\b{re.escape(other)}\b', value) for other in later):
                continue
            sites.setdefault(var, []).append((call, index, a, b, value))
    eligible = {}
    for var, uses in sites.items():
        if (len(uses) < 2 or len(re.findall(rf'\b{re.escape(var)}\b', part.body)) != 1 + 2 * len(uses)
                or re.search(rf'(?m)^\s*#\s*define[^\n]*\b{re.escape(var)}\b', macros)):
            continue
        eligible[var] = uses
    if not eligible:
        return None
    changes = []
    calls = {}
    for var, uses in eligible.items():
        a, b = declarations[var][0]
        changes.append((a, b, ''))
        for call, index, start, end, value in uses:
            changes.append((start, end, ''))
            calls.setdefault((call.start('args'), call.end('args')), {})[index] = value
    for (start, end), replacements in calls.items():
        args = m2cfix._split_top_level(source[start:end])
        for index, value in replacements.items():
            args[index] = f'({value.strip()})'
        changes.append((start, end, ', '.join(arg.strip() for arg in args)))
    return edit(source, changes)


def variants(source, name, header=''):
    out = []
    for _, split in tail_call_arm_repairs.variants(source, name):
        if rewritten := _inline(split, name, header):
            out.append((FAMILY, rewritten))
            if len(out) >= LIMIT:
                break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
