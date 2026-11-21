"""Recover a null-result loop edge and its successful call's delay-slot store."""

import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'measured_null_iteration_store'
REG = r'\$\w+'
VALUE = r'(?:0[xX][0-9a-fA-F]+|[0-9]+)'
EDGE = re.compile(
    rf'move (?P<object>{REG}), \$v0\n'
    rf'beql (?P=object), \$zero, [^\n]+\n'
    rf'addiu (?P<count>{REG}), (?P=count), 1\n'
    rf'lw (?P<inner>{REG}), (?P<inner_offset>{VALUE})\((?P=object)\)\n'
    rf'addiu \$a0, \$zero, (?P<arg>{VALUE})\n'
    rf'addiu (?P<value_reg>{REG}), \$zero, (?P<value>{VALUE})\n'
    rf'sh \$zero, (?P<zero>{VALUE})\((?P=object)\)\n'
    rf'jal (?P<call>{IDENT})\n'
    rf'sh (?P=value_reg), (?P<field>{VALUE})\((?P=object)\)\n'
    rf'addiu (?P<result>{REG}), \$v0, (?P<bonus>{VALUE})\n'
    rf'sh (?P=result), (?P<result_field>{VALUE})\((?P=inner)\)'
)
ENTRY = re.compile(
    rf'\bdo\s*{{\s*(?P<object>{IDENT})\s*=\s*{IDENT}\s*\([^;{{}}]+\)\s*;\s*'
    rf'(?P<guard>if\s*\(\s*(?P=object)\s*!=\s*NULL\s*\)\s*){{'
)


def _halfword(base, offset):
    return rf'\(\s*\*\s*\(\s*s16\s*\*\s*\)\s*\(\s*\(\s*char\s*\*\s*\)\s*\(\s*{base}\s*\)\s*\+\s*{offset}\s*\)\s*\)'


def _stores(obj):
    return re.compile(
        rf'\s*(?P<inner>{IDENT})\s*=\s*\(\s*\*\s*\(\s*void\s*\*\*\s*\)'
        rf'\s*\(\s*\(\s*char\s*\*\s*\)\s*\(\s*{obj}\s*\)\s*\+\s*(?P<inner_offset>{VALUE})\s*\)\s*\)\s*;'
        rf'\s*{_halfword(obj, f"(?P<zero>{VALUE})")}\s*=\s*0\s*;'
        rf'\s*(?P<result_store>{_halfword("(?P=inner)", f"(?P<result_field>{VALUE})")}\s*=\s*'
        rf'\(\s*s16\s*\)\s*\(\s*(?P<call>{IDENT})\(\s*(?P<arg>{VALUE})\s*\)'
        rf'\s*\+\s*(?P<bonus>{VALUE})\s*\)\s*;)'
        rf'(?P<space>\s*)(?P<field_store>{_halfword(obj, f"(?P<field>{VALUE})")}\s*=\s*(?P<value>{VALUE})\s*;)'
    )


def variants(source, name, rows):
    """Move a measured store before the call and split the null-result increment."""
    if 'NULL' not in source or not any('beql ' in row[1] for row in rows):
        return []
    target = '\n'.join(' '.join(row[1].split()) for row in rows if row[1])
    evidence = list(EDGE.finditer(target))
    part = view(source, name) if evidence else None
    if not part or re.search(r'\b(?:goto|asm|__asm__)\b', part.body):
        return []
    result = []
    for entry in ENTRY.finditer(part.clean, part.opening + 1, part.end):
        opening = entry.end() - 1
        end = close(part.clean, opening, '{', '}')
        if not end:
            continue
        tail = re.match(
            rf'\s*(?P<step>(?P<count>{IDENT})\s*\+=\s*1\s*;)\s*}}\s*while\s*\(',
            part.clean[end:part.end],
        )
        if not tail or re.search(r'\b(?:break|continue)\b', part.clean[opening+1:end-1]):
            continue
        count = tail['count']
        if not re.search(rf'(?<=[;{{}}])\s*(?:int|s32|u32)\s+{count}\s*;', part.clean[part.opening:entry.start()]):
            continue
        stores = _stores(entry['object']).match(part.clean, opening + 1, end)
        if not stores or not any(
            stores['call'] == edge['call'] and all(
                int(stores[key], 0) == int(edge[key], 0) for key in ('inner_offset', 'arg', 'value', 'zero', 'field', 'bonus', 'result_field')
            ) for edge in evidence
        ):
            continue
        step = tail['step']
        guard = f'if (!{entry["object"]}) {{ {step} continue; }}\n'
        indent = source[source.rfind('\n', 0, entry.start('guard'))+1:entry.start('guard')]
        if indent.strip():
            continue
        swap = (
            source[slice(*stores.span('field_store'))] + source[slice(*stores.span('space'))]
            + source[slice(*stores.span('result_store'))]
        )
        result.append((FAMILY, edit(source, [
            (*entry.span('guard'), guard + indent),
            (stores.start('result_store'), stores.end('field_store'), swap),
            (end + tail.start('step'), end + tail.end('step'), f'do {{ {step} }} while (0);'),
        ])))
    return result[:4]
