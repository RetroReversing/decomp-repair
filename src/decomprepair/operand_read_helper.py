"""An operand read written as a private inline helper, with the join copy kept and the constant before the dispatch.

A script-op handler (92 instructions, `gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) reads two operands the same way:
a flag selects a call, otherwise an index is masked and read from a 16-entry register file or from a global table;
then `switch (op)` compares them. The saved best (345) spelled the reads with search scaffolding (a `code` copy of the
index, a `value` carrier, a `do { } while (0)`), and left three rows after a long hand search. What the match needed,
found with the compiler's `-dr -dj -dc -ds -dt -dl -dg -dS -dR -dJ -dd` dumps (docs/learnings/finding/
join-copy-delay-slot-absorption.md in decompdecomp), is four edits that pay off only together (each alone scores the
same or worse):

- Each read is one `static __inline__ s32 NAME(Seq *p, u8 sel, u8 idx)` with a local `value` returned. The inlined
  parameters are QImode pseudos set once before the first branch, which gives the first block the target's order
  (`srl 8` before `srl 16`, the word in `$v1`); the two flag/index locals of the saved best are gone. Alone: 890.
- `value` is copied into the result at the join (`return value;` into the destination), so the copy is a move the
  allocator keeps (`lh $v0; move $a0,$v0`). cse folds it away again when the result's first reference is the copy
  itself and the dispatch follows in the same extended block (cse.c `make_regs_eqv` makes the older `value` canonical
  unless the new register lives past the block or began before it), so the last result is set to 0 before the first
  read, a reference that starts it earlier. Alone: 460 with the next two, 1300 without them.
- A constant the dispatch compares with sits in a local before the switch (`hoisted = 1;`) and the arm that compares
  with it adds `(hoisted - 1)`. The `li $v0,1` of the second compare then comes before the first branch, writes the
  copy's source, and reorg's from-above scan (`fill_simple_delay_slots`) can no longer move the copy into that
  branch's delay slot, so the paths' jumps take the copy where the target has it. Alone (with the other two): 540.
- The weight ladder (`local_weight_ladder`'s idea: `do { } while (0)` adds loop depth) on three statements: the last
  read once, the first arm's assignments twice, the final guarded store three times. 540 -> 0.

Offered, per function: `operand_read_helper` (the helper alone), `operand_read_helper_early` (helper and the early
reference), `dispatch_constant_hoist` (the constant alone, for any switch with a case of a non-zero constant) and
`operand_read_dispatch_bundle` (all four, the wraps over a small grid). The judge decides; none is a verdict. The
scaffolding (`= 0`, the hoisted constant and its zero term, the wrappers) is what no developer wrote: polishing removes
it once the match is recorded. Why these work is read from cse.c, combine.c, jump.c and reorg.c; that this exact
combination is what the original had is a hypothesis from one function (92 instructions, 345 -> 0).
"""
import itertools
import re

from .csource import find
from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'operand_read_helper'
EARLY = 'operand_read_helper_early'
HOIST = 'dispatch_constant_hoist'
BUNDLE = 'operand_read_dispatch_bundle'
FAMILIES = (FAMILY, EARLY, HOIST, BUNDLE)
HELPER = 'read_operand'
HOISTED = 'hoisted_const'
MAX_BLOCKS = 4
WRAPS = (range(0, 2), range(0, 3), range(0, 4))
HEX_FF = r'0[xX][fF][fF]'

LADDER = (
    rf'if\s*\((?P<cond>[^{{}}]+?)\)\s*\{{\s*'
    rf'(?P<x1>{IDENT})\s*=\s*(?P<callee>{IDENT})\s*\(\s*(?P<p>{IDENT})\s*,\s*(?P<ci>{IDENT})\s*&\s*{HEX_FF}\s*\)\s*;\s*\}}\s*'
    rf'else\s*\{{\s*(?P<i2>{IDENT})\s*&=\s*(?P<mask>{NUMBER})\s*;\s*'
    rf'if\s*\(\s*(?P<i3>{IDENT})\s*(?P<op><=|<)\s*(?P<n>[^(){{}};]+?|\([^(){{}};]*\))\s*\)\s*\{{\s*'
    rf'(?P<x2>{IDENT})\s*=\s*(?P<arr1>[^;{{}}\[\]]+?)\[\s*(?P<i4>{IDENT})\s*\]\s*;\s*\}}\s*'
    rf'else\s*\{{\s*(?P<x3>{IDENT})\s*=\s*(?P<arr2>[^;{{}}\[\]]+?)\[\s*(?P<i5>{IDENT})\s*\]\s*;\s*\}}\s*\}}')
PLAIN = re.compile(rf'(?P<set>(?P<iv>{IDENT})\s*=\s*(?P<ie>[^;{{}}]+?)\s*;\s*)' + LADDER)
# the saved best's spelling: a carrier `value`, a copy of the index in `code`, a one-shot loop round the ladder
SCAFFOLD = re.compile(
    rf'\{{\s*(?P<vt>{IDENT})\s+(?P<val>{IDENT})\s*;\s*(?P<ct>{IDENT})\s+(?P<code>{IDENT})\s*=\s*(?P<ce>[^;{{}}]+?)\s*;\s*'
    rf'(?P<iv>{IDENT})\s*=\s*(?P<ie>[^;{{}}]+?)\s*;\s*do\s*\{{\s*'
    + LADDER.replace('(?P<x1>', '(?P<v1>').replace('(?P<x2>', '(?P<v2>').replace('(?P<x3>', '(?P<v3>')
    + rf'\s*(?P<x>{IDENT})\s*=\s*(?P<v4>{IDENT})\s*;\s*\}}\s*while\s*\(\s*0\s*\)\s*;\s*\}}')


def _count(text):
    """The integer of `16`, `(16)` or `(16 - 1)`, or None."""
    found = re.fullmatch(r'\(?\s*(\d+)\s*(?:-\s*(\d+))?\s*\)?', text.strip())
    return int(found[1]) - int(found[2] or 0) if found else None


def _selector(cond):
    """The flag expression the helper's `u8 sel` is passed for the ladder's condition, or None."""
    cond = cond.strip()
    found = re.fullmatch(r'\(?\s*(.+?)\s*\)?\s*!=\s*0', cond)
    if found:
        return found[1]
    found = re.fullmatch(rf'{HEX_FF}\s*&\s*\((.+)\)|\((.+)\)\s*&\s*{HEX_FF}', cond)
    if found:
        return f'({(found[1] or found[2]).strip()}) & 0xFF'
    return cond if re.fullmatch(rf'{IDENT}', cond) else None


def _ladder(hit, scaffold):
    """The fields of one matched read, or None when its names disagree."""
    if scaffold:
        if {hit['v1'], hit['v2'], hit['v3'], hit['v4']} != {hit['val']} or hit['ci'] not in (hit['iv'], hit['code']):
            return None
        if hit['ci'] == hit['code'] and hit['ce'].strip() != hit['ie'].strip():
            return None
        result = hit['x']
    else:
        if len({hit['x1'], hit['x2'], hit['x3']}) != 1 or hit['ci'] != hit['iv']:
            return None
        result = hit['x1']
    if len({hit['iv'], hit['i2'], hit['i3'], hit['i4'], hit['i5']}) != 1:
        return None
    limit = _count(hit['n'])
    selector = _selector(hit['cond'])
    if limit is None or selector is None:
        return None
    return {'x': result, 'callee': hit['callee'], 'p': hit['p'], 'mask': hit['mask'],
            'limit': limit + (1 if hit['op'] == '<=' else 0), 'arr1': hit['arr1'].strip(), 'arr2': hit['arr2'].strip(),
            'selector': selector, 'index': hit['ie'].strip(), 'ivar': hit['iv']}


def _blocks(source, name):
    """(part, [(start, end, fields)]) of the reads in the function, in order, or None."""
    part = view(source, name)
    if not part:
        return None
    clean = part.clean
    if re.search(r'\b(?:goto|asm|__asm__|setjmp)\b|^\s*#', clean[part.opening:part.end], re.M):
        return None
    found = []
    for scaffold, pattern in ((True, SCAFFOLD), (False, PLAIN)):
        for hit in pattern.finditer(clean, part.opening + 1, part.end):
            fields = _ladder(hit, scaffold)
            if fields and not any(hit.start() < end and start < hit.end() for start, end, _ in found):
                found.append((hit.start(), hit.end(), fields))
    found.sort(key=lambda item: item[0])
    return (part, found) if 1 <= len(found) <= MAX_BLOCKS else None


def _declared_type(part, name):
    """The type `name` is declared with in the function (a parameter or a local), as written."""
    head = part.clean[:part.opening]
    signature = head[head.rindex('(') + 1:head.rindex(')')] if '(' in head else ''
    for piece in signature.split(',') + part.clean[part.opening + 1:part.end].split(';'):
        found = re.fullmatch(rf'\s*(?:register\s+)?(?P<type>(?:{IDENT}\s+)*{IDENT}(?:\s*\*+)?)\s*(?:\*\s*)*(?P<name>{IDENT})\s*', piece)
        if found and found['name'] == name:
            text = piece.strip()
            return re.sub(r'^register\s+', '', text[:text.rindex(name)]).strip()
    return None


def _helper_text(name, fields, pointer_type, result_type):
    star = '' if pointer_type.endswith('*') else ' '
    return (f'static __inline__ {result_type} {name}({pointer_type}{star}{fields["p"]}, u8 sel, u8 idx)\n{{\n'
            f'  {result_type} value;\n  if (sel)\n  {{\n    value = {fields["callee"]}({fields["p"]}, idx & 0xFF);\n  }}\n'
            f'  else\n  {{\n    idx &= {fields["mask"]};\n    if (idx < {fields["limit"]})\n    {{\n'
            f'      value = {fields["arr1"]}[idx];\n    }}\n    else\n    {{\n      value = {fields["arr2"]}[idx];\n    }}\n  }}\n'
            f'  return value;\n}}\n')


def _outline(source, name):
    """(source with every read a helper call, [result names], first block start, last call span) or None."""
    shape = _blocks(source, name)
    if not shape or HELPER in source:
        return None
    part, blocks = shape
    helpers, texts, edits, results = {}, [], [], []
    last = None
    for start, end, fields in blocks:
        pointer_type = _declared_type(part, fields['p'])
        result_type = _declared_type(part, fields['x'])
        if not pointer_type or not result_type:
            return None
        key = tuple(fields[k] for k in ('callee', 'p', 'mask', 'limit', 'arr1', 'arr2')) + (pointer_type, result_type)
        if key not in helpers:
            helpers[key] = HELPER if not helpers else f'{HELPER}_{len(helpers) + 1}'
            texts.append(_helper_text(helpers[key], fields, pointer_type, result_type))
        call = f'{fields["x"]} = {helpers[key]}({fields["p"]}, {fields["selector"]}, {fields["index"]});'
        edits.append((start, end, call))
        results.append(fields['x'])
        last = (start, start + len(call), fields['x'])
    span = find(source, name)
    if not span:
        return None
    revised = edit(source, edits + [(span[0], span[0], '\n'.join(texts) + '\n')])
    return revised, results, blocks[0][0], last


def _locate(text, call):
    return text.index(call)


def variants_helper(source, name):
    out = _outline(source, name)
    return [(FAMILY, out[0])] if out else []


def _early(revised, first_call, result):
    """`result = 0;` immediately before the first read's call statement."""
    at = revised.index(first_call)
    line = revised.rfind('\n', 0, at) + 1
    indent = re.match(r'[ \t]*', revised[line:]).group()
    return revised[:line] + f'{indent}{result} = 0;\n' + revised[line:]


def _helper_children(source, name):
    out = _outline(source, name)
    if not out:
        return None
    revised, results, _, _ = out
    first = re.search(rf'^[ \t]*{re.escape(results[0])} = {HELPER}(?:_\d+)?\(.*;$', revised, re.M)
    return revised, results, first[0].strip() if first else None


def variants_early(source, name):
    got = _helper_children(source, name)
    if not got or not got[2]:
        return []
    revised, results, first = got
    children, seen = [], set()
    for chosen in (results[-1:], results[:1], results):
        key = tuple(dict.fromkeys(chosen))
        if key in seen:
            continue
        seen.add(key)
        text = revised
        for variable in reversed(key):
            text = _early(text, first, variable)
        children.append((EARLY, text))
    return children


def _switch(part):
    """(switch start, the case constants and their label starts) of the first `switch` with two or more cases."""
    clean = part.clean
    for hit in re.finditer(r'\bswitch\s*\([^;{}]*\)\s*\{', clean[part.opening:part.end]):
        start = part.opening + hit.start()
        depth, at = 0, part.opening + hit.end() - 1
        end = None
        for index in range(at, part.end):
            depth += (clean[index] == '{') - (clean[index] == '}')
            if depth == 0:
                end = index
                break
        if end is None:
            continue
        labels = [(int(found[1], 0), found.start(), found.end())
                  for found in re.finditer(rf'\bcase\s+({NUMBER})\s*:', clean[at:end])]
        labels = [(value, at + a, at + b) for value, a, b in labels]
        if len(labels) >= 2:
            return start, end, labels
    return None


def _after_declarations(clean, part):
    """The offset just after the last line of the function's leading run of plain declarations."""
    position, last = part.opening + 1, part.opening + 1
    declaration = re.compile(rf'^[ \t]*(?:(?:register|volatile)\s+)*(?:{IDENT}\s+)+\**\s*{IDENT}(?:\[\d+\])?\s*(?:=[^;]*)?;[ \t]*$')
    for line in clean[part.opening + 1:part.end].splitlines(keepends=True):
        text = line.strip()
        if text and not declaration.match(line.rstrip('\n')):
            break
        position += len(line)
        if text:
            last = position
    return last


def _hoist(source, name):
    part = view(source, name)
    if not part or HOISTED in source or re.search(r'\b(?:goto|asm|__asm__)\b', part.clean[part.opening:part.end]):
        return None
    shape = _switch(part)
    if not shape:
        return None
    start, end, labels = shape
    nonzero = [item for item in labels if item[0] > 0]
    if not nonzero:
        return None
    value, _, body = max(nonzero, key=lambda item: item[0])
    clean = part.clean
    after = [item[1] for item in labels if item[1] > body]
    stop = min(after) if after else end
    assignment = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<lhs>[^;{}=\n]+?)\s*=\s*(?P<rhs>[^;{}=][^;{}]*?)\s*;').search(clean, body, stop)
    if not assignment:
        return None
    line = clean.rfind('\n', 0, start) + 1
    indent = re.match(r'[ \t]*', clean[line:]).group()
    rewrite = f'{assignment["indent"]}{assignment["lhs"].strip()} = ({assignment["rhs"]}) + ({HOISTED} - {value});'
    anchor = _after_declarations(clean, part)
    return edit(source, [(assignment.start(), assignment.end(), rewrite), (line, line, f'{indent}{HOISTED} = {value};\n'),
                         (anchor, anchor, f'  s32 {HOISTED};\n')])


def variants_hoist(source, name):
    out = _hoist(source, name)
    return [(HOIST, out)] if out else []


def _wrap(text, depth):
    for _ in range(depth):
        text = f'do {{ {text} }} while (0);'
    return text


def _wrap_statements(revised, name, last_call, depths):
    """The bundle's source with the wrappers of one grid point, or None when a target statement is missing."""
    part = view(revised, name)
    if not part:
        return None
    clean = part.clean
    changes = []
    one, two, three = depths
    if one:
        at = revised.index(last_call)
        changes.append((at, at + len(last_call), _wrap(last_call, one)))
    shape = _switch(part)
    if two:
        if not shape:
            return None
        _, end, labels = shape
        first = min(labels, key=lambda item: item[1])
        later = [item[1] for item in labels if item[1] > first[1]]
        stop = min(later) if later else end
        statements = [hit for hit in re.finditer(r'(?<![=!<>])\b[A-Za-z_]\w*\s*=\s*[^;{}=][^;{}]*;', clean[first[2]:stop])]
        if not statements:
            return None
        for hit in statements:
            changes.append((first[2] + hit.start(), first[2] + hit.end(), _wrap(hit[0], two)))
    if three:
        guarded = list(re.finditer(r'if\s*\([^{}]*\)\s*\{\s*(?P<s>[^;{}]+=[^;{}]+;)\s*\}', clean[part.opening:part.end]))
        if not guarded:
            return None
        hit = guarded[-1]
        begin = part.opening + hit.start('s')
        changes.append((begin, part.opening + hit.end('s'), _wrap(hit['s'], three)))
    return edit(revised, changes)


def variants_bundle(source, name):
    got = _helper_children(source, name)
    if not got or not got[2]:
        return []
    revised, results, first = got
    revised = _early(revised, first, results[-1])
    hoisted = _hoist(revised, name)
    if not hoisted:
        return []
    last = re.findall(rf'(?m)^[ \t]*({re.escape(results[-1])} = {HELPER}(?:_\d+)?\(.*;)$', hoisted)
    if not last:
        return []
    children = []
    for depths in itertools.product(*WRAPS):
        if not any(depths):
            continue
        text = _wrap_statements(hoisted, name, last[-1], depths)
        if text:
            children.append((BUNDLE, text))
    return [(BUNDLE, hoisted)] + children


def variants(source, name):
    found = variants_helper(source, name) + variants_early(source, name) + variants_hoist(source, name)
    return found + variants_bundle(source, name)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
