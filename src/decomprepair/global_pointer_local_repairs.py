"""A global pointer the C tests and uses, held in a local from its test on.

`if (G != NULL) { M2C_FIELD(G, s32 *, 0x10) = ...; } f(G);` reloads `G` after each store through it, since the store
might change `G` itself. A source that read `G` once into a local didn't: an N64 function was 94.3% with m2c's
repeated `D_800BD554`, and exact with `p = D_800BD554;` before its test and `p` after it. The meaning changes only if
a store through the pointer can reach the global itself, which the judge's byte comparison settles.

A global the function also sets elsewhere (cleared at entry, stored in a loop) is held in the local only inside the
block its test guards, when nothing there writes it: a KMC-compiled collision routine tested its result pointer at
the end, `if ((G) != NULL) { switch (G->kind) ...; *out = G; G->flags |= f; }`, and the target read it once
(15070 -> 13685). The `(G)` spelling of the test and a `switch` in the block don't stop the child.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'global_pointer_local'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    signature = clean[span[0]:opening]
    params = set(re.findall(r'(' + IDENT + r')\s*(?:,|\))', signature))
    locals_ = set(re.findall(r'(?m)^[ \t]*(?:[\w ]+?)[\s*]+(' + IDENT + r')\s*(?:\[[^]]*\])?\s*;', body))
    result = []
    for test in re.finditer(r'(?m)^(?P<indent>[ \t]*)if\s*\(\s*(?:\(\s*(?P<p>' + IDENT + r')\s*\)|(?P<g>' + IDENT
                            + r'))\s*!=\s*(?:NULL|0)\s*\)\s*\{', body):
        g = test['g'] or test['p']
        if g in params or g in locals_ or g.startswith('__repair'):
            continue
        written = re.compile(r'(?<![\w.>])' + g + r'\s*=(?!=)|&\s*' + g + r'\b')
        rest = body[test.start():]
        if written.search(body):
            # the global is set elsewhere (cleared at entry, stored in a loop): only its own block may read the local,
            # and nothing in that block may write it
            block = close(body, body.index('{', test.end() - 1), '{', '}')
            if not block:
                continue
            rest = body[test.start():block]
            if written.search(rest):
                continue
        uses = [m.start() for m in re.finditer(r'(?<![\w.>])' + g + r'\b', rest)]
        # tested, then used through or passed on at least twice more; never assigned or its address taken
        if len(uses) < 3:
            continue
        # a call between the test and the last use could change the global: only calls that take it are allowed
        last = test.start() + uses[-1]
        between = body[test.start():last]
        calls = [c for c in re.finditer(r'\b(' + IDENT + r')\s*\(', between)
                 if c[1] not in ('M2C_FIELD', 'if', 'switch', 'while', 'for', 'return', 'sizeof')]
        start = test.start()
        if any(g not in body[start + c.end():close(body, start + c.end() - 1) or len(body)] for c in calls):
            continue
        local = '__repair_' + g
        text = source
        for p in reversed(uses):
            at = opening + test.start() + p
            text = text[:at] + local + text[at + len(g):]
        at = opening + test.start()
        text = text[:at] + f'{test["indent"]}{local} = {g};\n' + text[at:]
        text = text[:opening + 1] + f'\n    void *{local};' + text[opening + 1:]
        result.append((FAMILY, text))
        if len(result) >= 4:
            break
    return result


def _linked_insert(asm):
    if 'sw' not in asm or '%hi(' not in asm:
        return None
    from .integer_repair_support import NUMBER
    from .measured_stack_drafts import _lines

    lines = '\n'.join(' '.join(line.split()) for line in _lines(asm)
                      if not line.startswith(('glabel ', 'endlabel ')))
    return re.fullmatch(
        rf'lui \$v1, %hi\((?P<global>{IDENT})\)\nlw \$v1, %lo\((?P=global)\)\(\$v1\)\n'
        rf'lw \$v0, (?P<field>{NUMBER})\(\$v1\)\nsw \$v0, (?:0x0|0)?\(\$a0\)\n'
        r'jr \$ra\nsw \$a0, (?P=field)\(\$v1\)', lines)


def linked_insert_applies(asm):
    return _linked_insert(asm) is not None


def rewrite_linked_insert(source, name, asm, header=''):
    """Read both the base pointer and old head before storing the new link."""
    local = '__repair_link_base'
    if 'M2C_FIELD' not in source or local in source + header or not (target := _linked_insert(asm)):
        return None
    from .integer_repair_support import NUMBER, edit, integer, view

    part = view(source, name)
    if not part:
        return None
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\s*\(\s*M2C_UNK\s*\*\s*(?P<arg>{IDENT})\s*\)\s*$',
                          part.clean[:part.opening])
    if not signature:
        return None
    arg, pointer = signature['arg'], target['global']
    if arg == pointer:
        return None
    start = part.opening + 1
    end = part.clean.rfind('}', start, part.end)
    field = rf'M2C_FIELD\({pointer}, M2C_UNK \*\*, (?P<offset>{NUMBER})\)'
    same_field = rf'M2C_FIELD\({pointer}, M2C_UNK \*\*, (?P=offset)\)'
    body = ' '.join(part.clean[start:end].split())
    draft = re.fullmatch(rf'{field} = {arg}; \*{arg} = {same_field};', body)
    if not draft:
        draft = re.fullmatch(rf'\*{arg} = {field}; {same_field} = {arg};', body)
    if not draft or integer(draft['offset']) != integer(target['field']):
        return None
    access = f"M2C_FIELD({local}, M2C_UNK **, {draft['offset']})"
    return edit(source, [(start, end, f'''
    void *{local};

    {local} = {pointer};
    *{arg} = {access};
    {access} = {arg};
''')])


def _list_transfer(asm):
    if asm.count('jal') != 2 or 'bnez' not in asm:
        return None
    from .integer_repair_support import NUMBER
    from .measured_stack_drafts import _lines

    text = '\n'.join(' '.join(line.split()) for line in _lines(asm)
                     if not line.startswith(('glabel ', 'endlabel ')))
    text = re.sub(r'(?m)^addu (\$\w+), (\$\w+), \$zero$', r'move \1, \2', text)
    return re.fullmatch(
        rf'addiu \$sp, \$sp, -(?P<frame>{NUMBER})\nsw \$s1, (?P<save1>{NUMBER})\(\$sp\)\n'
        rf'move \$s1, \$a0\nsw \$ra, (?P<ret>{NUMBER})\(\$sp\)\nsw \$s0, (?P<save0>{NUMBER})\(\$sp\)\n'
        rf'lw \$s0, (?P<head>{NUMBER})\(\$s1\)\nbeqz \$s0, (?P<exit>\.L\w+)\nnop\n(?P<loop>\.L\w+):\n'
        rf'jal (?P<unlink>{IDENT})\nmove \$a0, \$s0\nmove \$a0, \$s0\njal (?P<link>{IDENT})\n'
        rf'addiu \$a1, \$s1, (?P<dest>{NUMBER})\nlw \$s0, (?P=head)\(\$s1\)\nbnez \$s0, (?P=loop)\nnop\n'
        r'(?P=exit):\nlw \$ra, (?P=ret)\(\$sp\)\nlw \$s1, (?P=save1)\(\$sp\)\n'
        r'lw \$s0, (?P=save0)\(\$sp\)\njr \$ra\naddiu \$sp, \$sp, (?P=frame)', text)


def list_transfer_applies(asm):
    target = _list_transfer(asm)
    return bool(target and target['loop'] != target['exit'])


def rewrite_list_transfer(source, name, asm, header=''):
    """Keep the original node across both calls, then reload the list head."""
    local = '__repair_transfer_node'
    if 'M2C_FIELD' not in source or local in source + header or not (target := _list_transfer(asm)):
        return None
    from .integer_repair_support import edit, integer, view
    from .stack_read_retry import _decimal

    if target['loop'] == target['exit']:
        return None
    part = view(source, name)
    if not part:
        return None
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\s*\(\s*void\s*\*\s*(?P<arg>{IDENT})\s*\)\s*$',
                          part.clean[:part.opening])
    if not signature:
        return None
    arg = signature['arg']
    head, dest = (integer(target[key]) for key in ('head', 'dest'))
    if head == dest or head % 4 or dest % 4:
        return None
    remove, insert = target['unlink'], target['link']
    field = f'M2C_FIELD({arg}, s32 *, {head})'
    start = part.opening + 1
    end = part.clean.rfind('}', start, part.end)
    draft = (f'if ({field} != 0) {{ do {{ {remove}({field}); '
             f'{insert}({field}, {arg} + {dest}); }} while ({field} != 0); }}')
    if ' '.join(_decimal(part.clean[start:end]).split()) != draft:
        return None
    return edit(source, [(start, end, f'''
    s32 {local};

    {local} = {field};
    while ({local} != 0) {{
        {remove}({local});
        {insert}({local}, {arg} + {dest});
        {local} = {field};
    }}
''')])


def _pointer_field_gaps(instructions):
    """Instruction distance from a relocated pointer load to a field read."""
    register = r'\$\w+'
    relocation = re.compile(rf'lw (?P<base>{register}), %lo\((?P<symbol>{IDENT})\)\((?P=base)\)')
    gaps = {}
    for i, instruction in enumerate(instructions):
        load = relocation.fullmatch(instruction)
        if not load:
            continue
        base, symbol = load['base'], load['symbol']
        if i == 0 or instructions[i-1] != f'lui {base}, %hi({symbol})':
            continue
        field = re.compile(rf'lw {register}, (0x[0-9a-f]+|[1-9][0-9]*)\({re.escape(base)}\)')
        for distance, op in enumerate(instructions[i+1:i+25], 1):
            if found := field.fullmatch(op):
                key = (symbol, int(found[1], 0))
                gaps[key] = max(distance, gaps.get(key, 0))
                break
            if re.match(rf'\w+ {re.escape(base)},', op) and not op.startswith(('sw ', 'sh ', 'sb ')):
                break
    return gaps


def scoped_field_reads(source, name, rows):
    """Capture a field's relocated base with the lifetime indicated by the linked diff."""
    from .integer_repair_support import edit, view
    from .loaded_byte_repairs import declarators

    if not any('%lo(' in row[1] for row in rows):
        return []
    target, candidate = (_pointer_field_gaps([row[side] for row in rows if row[side]]) for side in (1, 2))
    part = view(source, name)
    if not part:
        return []
    proposals = []
    for (symbol, field), gap in target.items():
        actual = candidate.get((symbol, field))
        if actual is None or gap <= actual or len(declarators(part.clean, symbol)) != 1:
            continue
        if not re.search(rf'(?m)^\s*extern\s+void\s*\*\s*{symbol}\s*;', part.clean[:part.opening]):
            continue
        read = re.compile(
            rf'(?m)^(?P<indent>[ \t]*){IDENT}\s*=\s*\(\s*\*\s*\(\s*(?:s32|u32|int)\s*\*\s*\)'
            rf'\s*\(\s*\(\s*char\s*\*\s*\)\s*\(\s*(?P<base>{symbol})\s*\)'
            r'\s*\+\s*(?P<field>0[xX][0-9a-fA-F]+|[1-9][0-9]*)\s*\)\s*\)\s*;'
        )
        for access in read.finditer(part.clean, part.opening + 1, part.end):
            if int(access['field'], 0) != field:
                continue
            later = part.clean[access.end():part.end]
            reuse = re.search(rf'(?<=[;{{}}])\s*(?P<local>{IDENT})\s*=\s*{symbol}\s*;', later)
            if not reuse:
                continue
            local = reuse['local']
            before = part.clean[part.opening:access.start()].rstrip()
            between = later[:reuse.start()]
            if (not before or before[-1] not in ';{}' or len(declarators(part.clean, local)) != 1
                    or not re.search(rf'(?<=[;{{}}])\s*void\s*\*\s*{local}\s*;', before)
                    or re.search(rf'\b(?:{local}|goto|return|continue|break)\b', between)
                    or re.search(rf'&\s*\(*\s*{local}\b', part.body)):
                continue
            indent = access['indent']
            capture = f'{indent}do {{\n{indent}    {local} = {symbol};\n{indent}}} while (0);\n'
            proposals.append(('measured_scoped_global_field', edit(source, [
                (access.start(), access.start(), capture), (*access.span('base'), local),
            ])))
    return proposals[:4]


_TABLE_WALK = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<local>{IDENT})\s*=\s*&(?P<table>{IDENT})\s*;\s*'
    rf'(?P=local)\s*\+=\s*{IDENT}\s*;\s*(?P=local)\s*\+=\s*{IDENT}\s*;\s*'
    rf'{IDENT}\s*=\s*{IDENT}\s*;\s*if\s*\(\s*\(\s*\*(?P=local)\s*\)\s*==')
_TABLE_BASE = re.compile(r'lui (\$\w+), %hi\(([A-Za-z_]\w*)\)')


def _table_register_swaps(rows):
    found = set()
    for i, (_, target, candidate) in enumerate(rows[:-1]):
        a, b = _TABLE_BASE.fullmatch(target), _TABLE_BASE.fullmatch(candidate)
        if not a or not b or a[1] == b[1] or a[2] != b[2]:
            continue
        _, left, right = rows[i + 1]
        if (left == f'addiu {a[1]}, {a[1]}, %lo({a[2]})'
                and right == f'addiu {b[1]}, {b[1]}, %lo({b[2]})'):
            found.add(a[2])
    return found


def measured_table_compare_pointer(source, name, rows, header=''):
    """Give one guarded table walk its own pointer through the final comparison."""
    from .call_lifetime_repairs import block_path
    from .frame_padding_repairs import declaration_ends
    from .integer_repair_support import edit, view

    tables = _table_register_swaps(rows)
    part = view(source, name) if tables else None
    fresh = '__repair_table_compare'
    if not part or fresh in source + header or re.search(r'\b(?:asm|__asm|__asm__|goto|setjmp|longjmp)\b', part.body):
        return []
    macros = re.findall(r'(?m)^[ \t]*#\s*(?:define|undef)\s+([^\n]+)',
                        (_blank(header) + '\n' + part.clean).replace('\\\n', ' '))
    declarations = set()
    begin = part.opening + 1
    for end in declaration_ends(part):
        decl = re.fullmatch(rf'\s*s32\s*\*\s*({IDENT})\s*;', part.clean[begin:end])
        if decl:
            declarations.add(decl[1])
        begin = end

    guards = set()
    for m in re.finditer(r'\bif\s*\(', part.body):
        end = close(part.clean, part.opening + m.end())
        brace = re.match(r'\s*\{', part.clean[end:]) if end else None
        if brace:
            guards.add(end + brace.end() - 1)
    switches = set()
    for m in re.finditer(r'\bswitch\s*\(', part.body):
        prefix = part.body[:m.start()].rstrip()
        if prefix and prefix[-1] not in ';{}':
            continue
        end = close(part.clean, part.opening + m.end())
        brace = re.match(r'\s*\{', part.clean[end:]) if end else None
        if brace:
            switches.add(end + brace.end() - 1)

    out = []
    for hit in _TABLE_WALK.finditer(part.clean, part.opening + 1, part.end):
        local, table = hit['local'], hit['table']
        if local not in declarations or table not in tables:
            continue
        if any({local, table} & set(re.findall(IDENT, macro)) or re.match(r's32\b', macro) for macro in macros):
            continue
        if re.search(rf'(?<!&)\&(?!&)\s*\(*\s*{local}\b', part.body):
            continue
        path = block_path(part, hit.start())
        if len(path) != 3 or path[1] not in switches or path[2] not in guards:
            continue
        prefix = part.clean[path[2] + 1:hit.start()].rstrip()
        shadow = rf'\b{IDENT}(?:\s+\**\s*|\s*\*+\s*){local}\s*(?=[;=,\[])'
        if (prefix and prefix[-1] not in ';{}') or len(re.findall(shadow, part.body)) != 1:
            continue
        if re.search(rf'\b{local}\b', prefix):
            continue
        if re.search(rf'\b{local}\b', part.clean[hit.end():part.end]):
            continue
        prior = part.clean[part.opening + 1:path[2]]
        if len(re.findall(rf'\b{local}\b', prior)) < 2 or re.search(
                rf'\b{IDENT}(?:\s+\**\s*|\s*\*+\s*){local}\s*(?=[;=,\[])', part.clean[path[2] + 1:hit.start()]):
            continue
        if hit[0] != source[hit.start():hit.end()]:
            continue
        moved = re.sub(rf'\b{local}\b', fresh, hit[0])
        earliest = re.search(r'\S', part.clean[path[2] + 1:hit.start()])
        declaration = f"s32 *{fresh};"
        edits = [(hit.start(), hit.end(), moved)]
        if earliest:
            insert = path[2] + 1 + earliest.start()
            edits.append((insert, insert, declaration + '\n' + hit['indent']))
        else:
            edits.append((hit.start(), hit.start(), hit['indent'] + declaration + '\n'))
        out.append(('table_compare_pointer_scope', edit(source, edits)))
    return out[:2]
