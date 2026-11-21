"""A global pointer the C tests and uses, held in a local from its test on.

`if (G != NULL) { M2C_FIELD(G, s32 *, 0x10) = ...; } f(G);` reloads `G` after each store through it, since the store
might change `G` itself. A source that read `G` once into a local didn't: an N64 function was 94.3% with m2c's
repeated `D_800BD554`, and exact with `p = D_800BD554;` before its test and `p` after it. The meaning changes only if
a store through the pointer can reach the global itself, which the judge's byte comparison settles.
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
    for test in re.finditer(r'(?m)^(?P<indent>[ \t]*)if\s*\(\s*(?P<g>' + IDENT + r')\s*!=\s*(?:NULL|0)\s*\)\s*\{', body):
        g = test['g']
        if g in params or g in locals_ or g.startswith('__repair'):
            continue
        rest = body[test.start():]
        uses = [m.start() for m in re.finditer(r'(?<![\w.>])' + g + r'\b', rest)]
        # tested, then used through or passed on at least twice more; never assigned or its address taken
        if len(uses) < 3 or re.search(r'(?<![\w.>])' + g + r'\s*=(?!=)|&\s*' + g + r'\b', body):
            continue
        # a call between the test and the last use could change the global: only calls that take it are allowed
        last = test.start() + uses[-1]
        between = body[test.start():last]
        calls = [c for c in re.finditer(r'\b(' + IDENT + r')\s*\(', between) if c[1] not in ('M2C_FIELD', 'if')]
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
