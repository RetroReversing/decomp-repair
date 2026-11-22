"""Reuse a proven reset at its stores and release unnecessary call-argument references."""

import re

from .call_lifetime_repairs import block_path
from .integer_repair_support import IDENT, edit
from .natural_pointer_spill import _WORD_FLOAT, _call_moves, _zero_phase
from .operand_lifetime_repairs import _escaped, _visible

FAMILY = 'shared_reset_rebalance'
_REG = r'\$(?:s[0-7]|fp)'
_GLOBAL = re.compile(rf'sw ({_REG}), (%lo\(({IDENT})\)\(\$\w+\))')
_STACK = re.compile(rf'sw ({_REG}), (0x[\da-f]+\(\$sp\))')
_START = re.compile(
    rf'(?m)^(?P<pad>[ \t]*)(?P<init>(?P<owner>{IDENT})\.(?P<bits>{IDENT})\s*=\s*'
    rf'(?P<value>\((?P<type>u32|unsigned\s+int)\)\s*(?P<param>{IDENT})\s*&\s*~\((?P=type)\)\s*(?P=param)))\s*;[ \t]*\n'
    rf'[ \t]*(?P<slot>{IDENT}\.{IDENT})\s*=\s*(?P<view>(?P=owner)\.(?P<float>{IDENT}))\s*;[ \t]*\n'
    rf'[ \t]*(?P<external>{IDENT})\s*=\s*(?P=view)\s*;[ \t]*\n'
    rf'[ \t]*\{{[ \t]*\n[ \t]*(?P<kind>f32|float)\s+(?P<first>{IDENT})\s*=\s*0\.0f\s*;[ \t]*\n'
    rf'[ \t]*(?P<setup>{IDENT})\(\s*(?P=param)\s*\)\s*;[ \t]*\n'
    rf'[ \t]*(?P<third>{IDENT})\s*=\s*(?P=view)\s*;[ \t]*\n'
    rf'[ \t]*(?P<second>{IDENT})\s*=\s*0\.0f\s*;[ \t]*\n'
)
_CALL = re.compile(
    rf'(?m)^[ \t]*(?P<name>{IDENT})\(\s*(?P<param>{IDENT})\s*,'
    rf'\s*(?P<argument>\(\s*(?:s32|int)\s*\)\s*{IDENT}\.{IDENT})\s*\)\s*;'
)


def _store_witnesses(rows):
    for i, (_, target, candidate) in enumerate(rows[:-1]):
        global_store = _GLOBAL.fullmatch(target)
        if not global_store or candidate != f'sw $zero, {global_store[2]}':
            continue
        stack_target, stack_candidate = rows[i + 1][1:]
        stack = _STACK.fullmatch(stack_target)
        if stack and stack[1] == global_store[1] and stack_candidate == f'sw $zero, {stack[2]}':
            yield global_store[3], stack[1]


def _unescaped_float_copies(part, setup):
    if _escaped(part.body, setup['first']):
        return False
    for role in ('second', 'third'):
        name, kind = setup[role], setup['kind']
        declarations = list(re.compile(rf'(?m)^[ \t]*{kind}\s+{name}\s*;').finditer(
            part.clean, part.opening + 1, setup.start(),
        ))
        if (len(declarations) != 1 or len(re.findall(rf'\b(?:f32|float)\s+{name}\b', part.body)) != 1
                or _escaped(part.body, name) or block_path(part, declarations[0].start()) != [part.opening]):
            return False
        if part.clean[part.opening:declarations[0].start()].rstrip()[-1:] not in ('{', '}', ';'):
            return False
    return True


def _paired_stores(part, setup, scope):
    opening, stop = scope
    slot = setup['slot']
    reset = re.compile(
        rf'(?m)^(?P<pad>[ \t]*){setup["external"]}\s*=\s*0\.0f\s*;[ \t]*\n'
        rf'[ \t]*{re.escape(slot)}\s*=\s*0\.0f\s*;[ \t]*\n'
    )
    sites = list(reset.finditer(part.clean, setup.end(), stop))
    if len(sites) != 1:
        return None
    stores = sites[0]
    bits = f'{setup["owner"]}.{setup["bits"]}'
    initial = list(re.compile(rf'(?m)^[ \t]*{re.escape(bits)}\s*=\s*0\s*;').finditer(
        part.clean, max(stores.start() - 1500, opening), stores.start(),
    ))
    if not initial:
        return None
    zero_store = initial[-1]
    between = part.clean[zero_store.end():stores.start()]
    if (block_path(part, zero_store.start()) != block_path(part, stores.start())
            or re.search(rf'\b(?:if|else|for|do|while|switch|goto|return|break|continue)\b|\b{IDENT}\s*:', between)):
        return None
    pad = stores['pad']
    return (*stores.span(), f'{pad}{bits} = {setup["value"]};\n'
            f'{pad}{setup["external"]} = {setup["view"]};\n{pad}{slot} = {setup["view"]};\n')


def _setup_edit(setup):
    pad = setup['pad']
    return (*setup.span(), f'{pad}{{\n{pad}{setup["kind"]} {setup["first"]};\n'
            f'{pad}{setup["init"]};\n{pad}{setup["setup"]}(({setup["slot"]} = {setup["view"]}, '
            f'{setup["external"]} = {setup["view"]}, {setup["param"]}));\n'
            f'{pad}{setup["first"]} = 0.0f;\n'
            f'{pad}{setup["second"]} = {setup["view"]};\n'
            f'{pad}{setup["third"]} = 0.0f;\n')


def variants(source, name, rows, header='', max_bytes=65536):
    witnesses = set(_store_witnesses(rows))
    visible = _visible(source, name, header) if witnesses else None
    if not visible:
        return []
    part, context = visible
    macros = set(re.findall(rf'(?m)^\s*#\s*(?:define|undef)\s+({IDENT})', context))
    signature = part.clean[part.clean.rfind('}', 0, part.opening) + 1:part.opening]
    for setup in _START.finditer(part.clean, part.opening + 1, part.end):
        if (macros & set(re.findall(IDENT, setup[0]))
                or not re.search(rf'[(,]\s*void\s*\*\s*{setup["param"]}\s*[,)]', signature)
                or not _unescaped_float_copies(part, setup)):
            continue
        global_name = setup['external']
        if (len(re.findall(rf'(?m)^[ \t]*extern\s+{setup["kind"]}\s+{global_name}\s*;', context)) != 1
                or len(re.findall(rf'\b(?:f32|float)\s+{global_name}\b', context)) != 1
                or any(' '.join(kind.split()) != 'float'
                       for kind in re.findall(r'\btypedef\s+([^;{}]+?)\s+f32\s*;', context))):
            continue
        expected = tuple(setup[key] for key in ('owner', 'bits', 'float', 'kind', 'type'))
        words = [word for word in _WORD_FLOAT.finditer(part.clean, part.opening + 1, setup.start())
                 if tuple(word[key] for key in ('owner', 'word', 'number', 'float', 'type')) == expected]
        if len(words) != 1 or not (phase := _zero_phase(part, words[0], setup['param'], shared=True)):
            continue
        _, opening, stop = phase
        if (not (stores := _paired_stores(part, setup, (opening, stop)))
                or len({setup['first'], setup['second'], setup['third']}) != 3):
            continue
        calls = {}
        for call in _CALL.finditer(part.clean, setup.end(), stop):
            if (call['name'] not in macros and call['param'] == setup['param']
                    and re.fullmatch(rf'\([ \t]*(?:s32|int)[ \t]*\)[ \t]*{setup["owner"]}\.{setup["bits"]}', call['argument'])):
                calls.setdefault(call['name'], []).append(call)
        choices = []
        for symbol, reg in sorted(witnesses):
            if symbol != global_name or not any(a == b == f'jal {setup["setup"]}' for _, a, b in rows):
                continue
            moves = _call_moves(rows, 'move $a1, $zero', f'move $a1, {reg}')
            for callee, sites in calls.items():
                prototype = rf'\b{callee}\s*\(\s*void\s*\*\s*(?:{IDENT}\s*)?,\s*(?:s32|int)(?:\s+{IDENT})?\s*\)\s*;'
                if not 4 <= len(sites) <= min(8, moves[callee]) or not re.search(prototype, context):
                    continue
                # The extra two reset stores and the setup copy retain the
                # value. Try removing every argument and keeping two for
                # allocation when the remaining pressure still matters.
                for keep in ((), (0, 1), (len(sites) - 2, len(sites) - 1)):
                    replaced = [(*site.span('argument'), '0') for i, site in enumerate(sites) if i not in keep]
                    variant = edit(source, [_setup_edit(setup), stores, *replaced])
                    if len(variant.encode()) <= max_bytes:
                        choices.append((FAMILY, variant))
        if choices:
            return choices[:6]
    return []
