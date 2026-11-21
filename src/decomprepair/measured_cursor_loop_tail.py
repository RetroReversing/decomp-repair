"""Recover a bottom-tested cursor loop from a branch-likely boolean back edge."""

import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'measured_cursor_loop_tail'
REG = r'\$\w+'
EDGE = re.compile(
    rf'and (?P<test>{REG}), {REG}, {REG}\n'
    rf'beql (?P=test), \$zero, [^\n]+\n'
    rf'move (?P<cursor>{REG}), (?!\$zero\b){REG}'
)
ENTRY = re.compile(
    rf'\bif\s*\(\s*(?P<cursor>{IDENT})\s*!=\s*(?P<null>NULL|0)\s*\)\s*{{\s*'
    rf'(?P<loop>for\s*\(\s*;\s*;\s*\))\s*{{\s*'
    rf'(?P<next>{IDENT})\s*=\s*(?P=cursor)\s*->\s*{IDENT}\s*;\s*'
    r'if\s*\(\s*(?P=next)\s*==\s*(?P=null)\s*\)\s*{'
)


def _tail(cursor, successor):
    return re.compile(
        rf'\s*(?P<if>if\s*\(\s*\(\s*\(\s*{cursor}\s*<\s*(?P<node>{IDENT})\s*\)\s*&\s*'
        rf'\(\s*(?P=node)\s*<\s*{successor}\s*\)\s*\)\s*!=\s*1\s*\))\s*{{'
        rf'(?P<step>\s*{cursor}\s*=\s*{successor}\s*;)\s*continue\s*;\s*}}'
        rf'(?P<stores>(?:\s*(?:{cursor}|{successor}|(?P=node))\s*->\s*{IDENT}\s*=\s*'
        rf'(?:{cursor}|{successor}|(?P=node))\s*;){{2,6}}\s*break\s*;)\s*}}\s*'
    )


def _pointer_local(part, identifier):
    declarations = list(re.finditer(
        rf'(?<=[;{{}}])\s*(?:struct\s+)?{IDENT}\s*\*\s*{identifier}\s*;',
        part.clean[part.opening:part.end],
    ))
    if len(declarations) != 1:
        return False
    prefix = part.clean[part.opening:part.opening + declarations[0].start()]
    return prefix.count('{') == prefix.count('}') + 1


def _capture_current_node(source, name, rows):
    """Preserve the current call argument while advancing the cursor in its delay slot."""
    if not any(mark != ' ' for mark, _, _ in rows):
        return None
    target = '\n'.join(row[1] for row in rows if row[1])
    edge = re.search(
        rf'move \$a0, (?P<reg>\$s[0-7])\njal (?P<callee>{IDENT})\n'
        rf'lw (?P=reg), (?P<offset>0x[0-9a-f]+|[1-9]\d*)\((?P=reg)\)\n'
        r'bnez (?P=reg), [^\n]+\nmove \$a0, (?P=reg)', target)
    if not edge or not (part := view(source, name)):
        return None
    signature = re.search(rf'\b{re.escape(name)}\s*\(\s*void\s*\*\s*({IDENT})\s*\)\s*$',
                          part.clean[:part.opening])
    if not signature:
        return None
    argument = signature[1]
    callee = edge['callee']
    body = re.fullmatch(
        rf'\s*void\s*\*\s*(?P<current>{IDENT})\s*;\s*void\s*\*\s*(?P<cursor>{IDENT})\s*;'
        rf'\s*(?P=cursor)\s*=\s*{argument}\s*;\s*if\s*\(\s*(?P=cursor)\s*!=\s*NULL\s*\)\s*{{'
        rf'\s*if\s*\(\s*(?P=current)\s*\)\s*{{\s*(?P=current)\s*=\s*(?P=cursor)\s*;\s*}}'
        rf'\s*else\s*{{\s*(?P=current)\s*=\s*(?P=cursor)\s*;\s*}}\s*do\s*{{'
        rf'\s*(?P=cursor)\s*=\s*\*\s*\(\s*\(\s*void\s*\*\*\s*\)\s*\(\s*'
        rf'\(\s*\(\s*char\s*\*\s*\)\s*(?P=cursor)\s*\)\s*\+\s*(?P<offset>0x[0-9a-fA-F]+|[1-9]\d*)\s*\)\s*\)\s*;'
        rf'\s*{callee}\s*\(\s*(?P=current)\s*\)\s*;\s*(?P=current)\s*=\s*(?P=cursor)\s*;\s*}}'
        rf'\s*while\s*\(\s*(?P=cursor)\s*!=\s*NULL\s*\)\s*;\s*}}\s*}}\s*',
        part.clean[part.opening + 1:part.end])
    if (not body or len({body['current'], body['cursor'], argument}) != 3
            or int(body['offset'], 0) != int(edge['offset'], 0)):
        return None
    if re.search(rf'(?m)^\s*#\s*define\s+(?:{body["current"]}|{body["cursor"]}|{argument}|{callee}|NULL)\b', part.clean):
        return None
    current = body['current']
    rewritten = (
        f'\n    if ({argument} != NULL) do {{\n'
        f'        void *{current} = {argument};\n'
        f'        {argument} = *((void **)(((char *){argument}) + {body["offset"]}));\n'
        f'        {callee}({current});\n'
        f'    }} while ({argument} != NULL);\n'
    )
    return edit(source, [(part.opening + 1, part.clean.rfind('}', part.opening, part.end), rewritten)])


def variants(source, name, rows):
    """Try the guarded cursor loop only when the target moves the cursor in the likely slot."""
    if candidate := _capture_current_node(source, name, rows):
        return [('measured_linked_loop_current_node', candidate)]
    if 'continue' not in source or not any('beql ' in row[1] for row in rows):
        return []
    target = '\n'.join(' '.join(row[1].split()) for row in rows if row[1])
    if not EDGE.search(target):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:goto|asm|__asm__)\b', part.body):
        return []
    result = []
    for entry in ENTRY.finditer(part.clean, part.opening + 1, part.end):
        start = entry.end() - 1
        guard_end = close(part.clean, start, '{', '}')
        if not guard_end:
            continue
        guard = part.clean[start+1:guard_end-1]
        stop = re.search(r'(?:^|[;}])\s*break\s*;\s*$', guard)
        if (not stop or guard[:stop.end()].count('{') != guard[:stop.end()].count('}')
                or re.search(r'\b(?:goto|continue)\b', guard)):
            continue
        cursor, successor = entry['cursor'], entry['next']
        if cursor == successor or not all(_pointer_local(part, x) for x in (cursor, successor)):
            continue
        tail = _tail(cursor, successor).match(part.clean, guard_end, part.end)
        if not tail or tail['node'] in (cursor, successor):
            continue
        at = tail.start('if')
        indent = source[source.rfind('\n', 0, at)+1:at]
        loop_start = entry.start('loop')
        loop_indent = source[source.rfind('\n', 0, loop_start)+1:loop_start]
        nested_indent = indent[len(loop_indent):]
        if not indent or indent.strip() or not indent.startswith(loop_indent) or not nested_indent:
            continue
        # The successor was just checked for null. The bottom test preserves
        # the original continue edge, with the cursor update in its delay slot.
        node, null = tail['node'], entry['null']
        step = source[slice(*tail.span('step'))]
        stores = source[slice(*tail.span('stores'))].strip()
        stores = '\n'.join(indent + nested_indent + line.strip() for line in stores.splitlines())
        replacement = (
            f'if ((u8)(({cursor} < {node}) & ({node} < {successor})) == 0) {{'
            f'{step}\n{indent}}} else {{\n{stores}\n{indent}}}\n'
            f'{loop_indent}}} while ({cursor} != {null});'
        )
        stop_at = tail.start() + len(tail[0].rstrip())
        result.append((FAMILY, edit(source, [(*entry.span('loop'), 'do'), (at, stop_at, replacement)])))
    return result[:4]
