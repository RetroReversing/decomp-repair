"""Four rewrites of m2c's form of a large collision sweep that its target compiler only gives with the game's shapes.

Measured on a 1337-instruction KMC GCC 2.7.2 collision sweep (`-G0 -mips3 -mgp32 -mfp32 -O2`) after
`saved_register_cascade` (3236), each from the state before it, with the exact judge:

- `pointer_base_stage`: a per-iteration pointer `p = obj->tris + (i * 6);` computed beside an index copy, written as the
  base first and the offset added after the copy (`p = obj->tris; i = n; p = (char *) p + (i * 6);`), above the other
  table read of the run (3236 -> 2516). sched1 then meets the base load first and the `i * 3` sum before the second
  table's address, as the target has them.
- `register_name_merge`: m2c's locals named for one saved register (`var_s3`, `var_s3_2`, `temp_s3`) in disjoint arms
  written as one variable (2511 -> 2521 alone, the step the next one needs). One variable is one pseudo whose priority
  (`floor_log2 (refs) * refs / live`, global.c) is that of all its uses, where a pointer per loop out-ranked the record
  pointer the target keeps in the lower saved register.
- `sibling_counter_merge`: the second loop of an `if`/`else` pair counting with its own `u16` counter, written with the
  first loop's word counter masked as the first loop reads it (`(c & 0xFFFF) * 2`, `(u32) (c & 0xFFFF) < n`), and its
  guard on the flag of the `if` it is the `else` of (2521 -> 2218).
- `goto_walk_reentry`: m2c's list walk at the end of a loop body,
  `L: s; if (c) { if (p == NULL) { return r; } if (t) { p = p->next; continue; } } p = p->next; if (p != NULL) goto L;`,
  as the game's: `goto walk; next: p = p->next; if (p == NULL) continue; walk: do { s; if (c) { if (p != NULL)
  { if (!t) goto next; p = p->next; break; } else { return r; } } p = p->next; } while (p != NULL);` (2218 -> 1048).
  Three things decide it: the do/while makes the walk a loop of its own, so loop.c hoists the `sll` of the return
  value's sign extension into its preheader, which the re-entry from `next` jumps to (the target's `j` past `next`);
  the `return` in an `else` arm is not moved out of the loop by `find_and_verify_loops` (it moves a block that ends in a
  jump out of the loop only when a conditional jump to the insn after it precedes it); and the walk pointer's references
  weighted one loop deeper keep it in a saved register.

`sibling_loop_merge` offers each name merge with the counter merge after it, and `walk_cascade` the walk with
`saved_register_cascade`'s pointer step in both arms and mask pair (the measured combinations). Candidate rewrites;
the exact judge decides each.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close as _past

BASE_STAGE = 'pointer_base_stage'
NAME_MERGE = 'register_name_merge'
COUNTER_MERGE = 'sibling_counter_merge'
WALK = 'goto_walk_reentry'
MERGE_PAIR = 'sibling_loop_merge'
WALK_CASCADE = 'walk_cascade'
FAMILIES = (BASE_STAGE, NAME_MERGE, COUNTER_MERGE, WALK, MERGE_PAIR, WALK_CASCADE)
LIMIT = 6
_DECL = re.compile(rf'(?m)^[ \t]*(?P<type>(?:unsigned\s+|signed\s+)?(?:[su](?:8|16|32)|int|short|char|void)\s*\**)\s*(?P<name>{IDENT})\s*;[ \t]*\n')


def close(text, start, left, right):
    past = _past(text, start, left, right)
    return past - 1 if past else None


def _decls(part):
    return {m['name']: m for m in _DECL.finditer(part.clean, part.opening, part.end)}


def _base_stage(source, part, fname):
    out = []
    clean = part.clean
    decls = _decls(part)
    pattern = re.compile(rf'({IDENT}) = ({IDENT});(\s*)({IDENT} = [^;]*[(\[]\1 \* \d+[)\]][^;]*;)(\s*)({IDENT}) = ([^;]*?) \+ \(\1 \* (\d+)\);')
    for hit in pattern.finditer(clean, part.opening, part.end):
        index, counter, gap, other, gap2, pointer, base, scale = hit.groups()
        if pointer not in decls or re.search(rf'\b{pointer}\b', base + other):
            continue
        void = decls[pointer]['type'].replace(' ', '') == 'void*'
        first = f'{pointer} = (void *) {base};' if void else f'{pointer} = {base};'
        step = f'{pointer} = (char *) {pointer} + ({index} * {scale});' if void else f'{pointer} = {pointer} + ({index} * {scale});'
        text = f'{first} {index} = {counter}; {step} {source[hit.start(4):hit.end(4)]}'
        out.append((BASE_STAGE, edit(source, [(hit.start(), hit.end(), text)])))
        if len(out) >= LIMIT:
            break
    return out


def _rename(source, part, names, survivor):
    edits = []
    for name in names:
        decl = _decls(part)[name]
        edits.append((decl.start(), decl.end(), ''))
        for use in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', part.clean[:part.end]):
            if use.start() > part.opening and not decl.start() <= use.start() < decl.end():
                edits.append((use.start(), use.end(), survivor))
    return edit(source, edits)


def _name_merge(source, part, fname):
    out = []
    decls = _decls(part)
    groups = {}
    for name in decls:
        reg = re.fullmatch(r'(var|temp)_(s[0-7]|fp)(?:_\d+)?', name)
        if reg:
            groups.setdefault(reg[2], []).append(name)
    for reg, names in sorted(groups.items()):
        var = [n for n in names if n.startswith('var_')]
        if len(var) >= 2 and len({decls[n]['type'].replace(' ', '') for n in var}) == 1:
            survivor = min(var, key=len)
            out.append((NAME_MERGE, _rename(source, part, [n for n in var if n != survivor], survivor)))
            merged = out[-1][1]
            for temp in [n for n in names if n.startswith('temp_')]:
                out.append((NAME_MERGE, _rename(merged, view(merged, fname), [temp], survivor)))
        if len(out) >= LIMIT:
            break
    return out


def _counter_merge(source, part, fname):
    out = []
    clean = part.clean
    decls = _decls(part)
    for name, decl in decls.items():
        if not re.fullmatch(r'u16|unsigned\s+short', decl['type'].strip()):
            continue
        base = re.fullmatch(r'(var_[a-z]\d)_\d+', name)
        if not base or base[1] not in decls or decls[base[1]]['type'].strip() not in ('s32', 'int'):
            continue
        word = base[1]
        init = re.search(rf'{name} = 0;(\s*)if \({name} < ([^;{{}}]*)\)', clean[part.opening:part.end])
        if not init:
            continue
        at = part.opening + init.start()
        flag = None
        for cond in re.finditer(rf'if \(({IDENT}) != 0\)', clean[part.opening:at]):
            flag = cond[1]
        if not flag:
            continue
        edits = [(decl.start(), decl.end(), ''),
                 (at, part.opening + init.end(), f'{word} = 0;{init[1]}if ({flag} < {source[part.opening + init.start(2):part.opening + init.end(2)]})')]
        for use in re.finditer(rf'(?<![\w.>]){name}\b', clean[:part.end]):
            if use.start() <= part.opening or at <= use.start() < part.opening + init.end() or decl.start() <= use.start() < decl.end():
                continue
            after = clean[use.end():use.end() + 3]
            before = clean[max(0, use.start() - 7):use.start()]
            if after.startswith(' * '):
                repl = f'({word} & 0xFFFF)'
            elif before.endswith('while (') and after.startswith(' <'):
                repl = f'((u32) ({word} & 0xFFFF))'
            else:
                repl = word
            edits.append((use.start(), use.end(), repl))
        out.append((COUNTER_MERGE, edit(source, edits)))
        if len(out) >= LIMIT:
            break
    return out


def _walk(source, part, fname):
    out = []
    clean = part.clean
    for label in re.finditer(rf'(?m)^([ \t]*)({IDENT})[ \t]*:(?!:)[ \t]*\n', clean[:part.end]):
        if label.start() < part.opening:
            continue
        name = label[2]
        rest = clean[label.end():part.end]
        head = re.match(r'\s*([^;{}]+;)\s*if\s*\(', rest)
        if not head:
            continue
        cond_open = label.end() + head.end() - 1
        cond_close = close(clean, cond_open, '(', ')')
        brace = re.match(r'\s*{', clean[cond_close + 1:]) if cond_close else None
        if not brace:
            continue
        body_open = cond_close + brace.end()
        body_close = close(clean, body_open, '{', '}')
        if not body_close:
            continue
        body = clean[body_open + 1:body_close]
        shape = re.fullmatch(rf'\s*if \(({IDENT}) == NULL\)\s*{{\s*(return [^;]*;)\s*}}\s*if \((.*)\)\s*{{\s*(\1 = [^;]*;)\s*continue;\s*}}\s*', body, re.S)
        if not shape:
            continue
        pointer, ret, test, nxt = shape.groups()
        tail = re.match(rf'\s*{re.escape(pointer)} = [^;]*;\s*if \({re.escape(pointer)} != NULL\)\s*{{\s*goto {name};\s*}}\s*(?=}}\s*while\b)', clean[body_close + 1:])
        if not tail or re.search(rf'\bgoto\s+{name}\b', clean[part.opening:label.start()] + clean[body_close + 1 + tail.end():part.end]):
            continue
        start_stmt = source[label.end() + head.start(1):label.end() + head.end(1)].strip()
        cond = source[cond_open + 1:cond_close].strip()
        src_test = source[body_open + 1 + shape.start(3):body_open + 1 + shape.end(3)].strip()
        src_next = source[body_open + 1 + shape.start(4):body_open + 1 + shape.end(4)].strip()
        src_ret = source[body_open + 1 + shape.start(2):body_open + 1 + shape.end(2)].strip()
        walk, nxt_label = f'{name}_walk', f'{name}_next'
        ind = label[1]
        text = (f'{ind}goto {walk};\n{ind}{nxt_label}:\n{ind}{src_next}\n{ind}if ({pointer} == NULL) continue;\n'
                f'{ind}{walk}:\n{ind}do\n{ind}{{\n{ind}  {start_stmt}\n{ind}  if ({cond})\n{ind}  {{\n'
                f'{ind}    if ({pointer} != NULL)\n{ind}    {{\n{ind}      if (!({src_test})) goto {nxt_label};\n'
                f'{ind}      {src_next}\n{ind}      break;\n{ind}    }}\n{ind}    else\n{ind}    {{\n{ind}      {src_ret}\n'
                f'{ind}    }}\n{ind}  }}\n{ind}  {src_next}\n{ind}}} while ({pointer} != NULL);\n')
        out.append((WALK, edit(source, [(label.start(), body_close + 1 + tail.end(), text)])))
        if len(out) >= LIMIT:
            break
    return out


_STEPS = (_base_stage, _name_merge, _counter_merge, _walk)


def _first(source, name, step, pick=0):
    part = view(source, name)
    children = step(source, part, name) if part else []
    return children[pick][1] if len(children) > pick else None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    out = []
    for step in _STEPS:
        try:
            out.extend(step(source, part, name))
        except (KeyError, IndexError, TypeError):
            continue
    # Measured pairs: each name merge with the counter merge after it (2511 -> 2218, and 1345 -> 1053), and the walk
    # with `saved_register_cascade`'s pointer step in both arms and mask pair (4906 -> 2065; its own tail split gave 3236).
    for family, child in [c for c in out if c[0] == NAME_MERGE]:
        later = _first(child, name, _counter_merge)
        if later:
            out.append((MERGE_PAIR, later))
    from . import saved_register_cascade as cascade
    for child in cascade._biv_arm(source, part):
        text = child[1]
        masked = cascade._then(text, name, cascade._mask_pair) or text
        walked = _first(masked, name, _walk)
        if walked:
            out.append((WALK_CASCADE, walked))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
