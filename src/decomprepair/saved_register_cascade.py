"""Five source shapes that move a large function's saved registers, offered one by one and all together.

A 1337-instruction KMC GCC 2.7.2 collision sweep (`-G0 -mips3 -mgp32 -mfp32 -O2`: an outer list loop, a u16 and a u8
triangle loop, a cell walk at the end) went 5207 -> 3236 with these edits. Each changes which pseudo global.c or
local-alloc ranks first, and the last three only paid off together (each alone made it worse):

- `condition_call_scope`: a call tested in an `if` (`if ((f(..) << 0x18) != 0)`) assigned to a local in a one-shot
  `do { t = f(..); } while (0);` before the test. The scope is a loop to flow.c, so the call's argument temporaries
  are weighted one loop deeper; local-alloc orders a block's quantities by `floor_log2 (refs) * refs / life`, and
  the deeper weight lifts the shared base pointer above the second index (5207 -> 5162: the argument registers and
  reload's spill registers became the target's).
- `loop_reread_split`: a local read at the head of a loop body and later assigned an unrelated value in the same body
  (m2c's `sp166 = obj->verts;` reusing a mask local's name for a vertex base). A read of the earlier value in the next
  iteration then sees the new one, so this is not the same program; the rename gives the value a local of its own
  (5162 -> 4906). `reused_temp_split` declines it because the reaching definitions change.
- `biv_arm_increment`: a pointer stepped after an `if` that the step does not depend on (`if (c) { ... } p += 3;`)
  stepped in both arms (`if (c) { ... p += 3; } else { p += 3; }`). loop.c (`strength_reduce`) subtracts the cost of
  an add per increment of the biv from each giv's benefit, so a second increment leaves an address giv like
  `*(p - 1)` "not worth while" and it stays `-1($s3)` off the biv instead of taking a saved register of its own
  (read in loop.c; jump2 cross-jumps the two adds back into one).
- `goto_loop_tail_split`: m2c's walk `L: s; if (c) { ..continue;.. } next; if (p) goto L; } while (..);` at the end
  of a loop body as `for (;;)` with the tail written out in the arm that skips the `if`'s body
  (`if (!(c)) { next; if (p) continue; break; }`) and the outer `continue` as `break`. A real loop weights the walk
  pointer's references one level deeper and the copied tail adds its own, which lifted it above a spilled stack
  pointer (0.075 -> 0.166) so it took the saved register the target has.
- `mask_pair_halfword`: two locals set from one value with the masks `& 0xFF` and `& 0xFF00`, the second `u16` and
  the first wider: both `u16` (the target spills both with `sh`/`lhu`, and an `s32` one outranked the cell pointer).

The family `saved_register_cascade` offers the measured combination of the last three as one child per stepped
pointer (4906 -> 3236). Candidate rewrites; the exact judge decides each.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close as _past

FAMILY = 'saved_register_cascade'
CALL_SCOPE = 'condition_call_scope'
REREAD_SPLIT = 'loop_reread_split'
BIV_ARM = 'biv_arm_increment'
TAIL_SPLIT = 'goto_loop_tail_split'
MASK_PAIR = 'mask_pair_halfword'
FAMILIES = (CALL_SCOPE, REREAD_SPLIT, BIV_ARM, TAIL_SPLIT, MASK_PAIR, FAMILY)
LIMIT = 6
_KEYWORDS = {'if', 'while', 'for', 'switch', 'return', 'sizeof', 'do', 'else'}
_TYPES = r'(?:unsigned\s+|signed\s+)?(?:[su](?:8|16|32)|int|short|char|long)'


def close(text, start, left, right):
    """The index of the bracket that closes the one at `start`, or None."""
    past = _past(text, start, left, right)
    return past - 1 if past else None


def _fresh(clean, base):
    name = base
    while re.search(rf'\b{name}\b', clean):
        name += '_'
    return name


def _declare(source, part, decl):
    """Insert a declaration after the opening brace of the function."""
    at = part.opening + 1
    return (at, at, '\n  ' + decl)


def _call_scope(source, part):
    out = []
    clean = part.clean
    hits = []
    for hit in re.finditer(r'\bif\s*\(\s*\(\s*(' + IDENT + r')\s*\(', clean[:part.end]):
        if hit.start() < part.opening or hit[1] in _KEYWORDS:
            continue
        args_open = hit.end() - 1
        args_close = close(clean, args_open, '(', ')')
        if not args_close:
            continue
        rest = re.match(r'\s*<<\s*0x18\s*\)\s*!=\s*0\s*\)', clean[args_close + 1:])
        if not rest:
            continue
        hits.append((hit, args_close, args_close + 1 + rest.end()))
    if not hits:
        return out
    temp = _fresh(clean, 'callResult')

    def rewrite(chosen):
        edits = [_declare(source, part, f's32 {temp};')]
        for hit, args_close, cond_end in chosen:
            call = source[hit.start(1):args_close + 1]
            edits.append((hit.start(), cond_end, f'do {{ {temp} = {call}; }} while (0); if (({temp} << 0x18) != 0)'))
        return edit(source, edits)

    for one in hits[:LIMIT]:
        out.append((CALL_SCOPE, rewrite([one])))
    if len(hits) > 1:
        out.insert(0, (CALL_SCOPE, rewrite(hits)))
    return out[:LIMIT]


def _block_of(clean, at, opening, end):
    """The innermost `{ }` around `at`."""
    depth = 0
    i = at
    while i > opening:
        i -= 1
        if clean[i] == '}':
            depth += 1
        elif clean[i] == '{':
            if depth == 0:
                return i, close(clean, i, '{', '}')
            depth -= 1
    return opening, end


def _loop_body_start(clean, at, opening):
    """The opening brace of the nearest enclosing loop body, or None."""
    depth = 0
    i = at
    while i > opening:
        i -= 1
        if clean[i] == '}':
            depth += 1
        elif clean[i] == '{':
            if depth == 0:
                head = clean[max(opening, i - 400):i].rstrip()
                if re.search(r'\bdo$', head) or re.search(r'\b(?:for|while)\s*\(.*\)$', head.split('\n')[-1]):
                    return i
            else:
                depth -= 1
    return None


def _reread_split(source, part):
    out = []
    clean = part.clean
    decls = {m['name']: m for m in re.finditer(rf'^[ \t]*(?P<type>{_TYPES})\s+(?P<name>{IDENT})\s*;', clean[part.opening:part.end], re.M)}
    for name, decl in decls.items():
        for hit in re.finditer(rf'(?<![\w.>]){re.escape(name)}\s*=(?!=)\s*([^;]*);', clean[:part.end]):
            if hit.start() < part.opening or re.search(rf'\b{re.escape(name)}\b', hit[1]):
                continue
            body = _loop_body_start(clean, hit.start(), part.opening)
            if body is None:
                continue
            before = clean[body:hit.start()]
            if not re.search(rf'(?<![\w.>]){re.escape(name)}\b(?!\s*=[^=])', before):
                continue
            block_start, block_end = _block_of(clean, hit.start(), part.opening, part.end)
            if not block_end:
                continue
            span = clean[hit.start():block_end]
            uses = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', span)]
            if len(uses) < 2 or re.search(rf'(?<![\w.>]){re.escape(name)}\s*=(?!=)', span[hit.end() - hit.start():]):
                continue
            fresh = _fresh(clean, name + '_b1')
            edits = [(hit.start() + m.start(), hit.start() + m.end(), fresh) for m in uses]
            edits.append(_declare(source, part, f's32 {fresh};'))
            out.append((REREAD_SPLIT, edit(source, edits)))
            if len(out) >= LIMIT:
                return out
    return out


def _biv_arm(source, part):
    out = []
    clean = part.clean
    for hit in re.finditer(r'\bif\s*\(', clean[:part.end]):
        if hit.start() < part.opening or not _loop_body_start(clean, hit.start(), part.opening):
            continue
        cond_close = close(clean, hit.end() - 1, '(', ')')
        if not cond_close:
            continue
        brace = re.match(r'\s*{', clean[cond_close + 1:])
        if not brace:
            continue
        body_open = cond_close + brace.end()
        body_close = close(clean, body_open, '{', '}')
        if not body_close:
            continue
        step = re.match(rf'\s*({IDENT})\s*\+=\s*(\d+|0x[0-9A-Fa-f]+)\s*;', clean[body_close + 1:])
        if not step or re.match(r'\s*else\b', clean[body_close + 1:]):
            continue
        pointer = step[1]
        inner = clean[body_open:body_close]
        if not re.search(rf'\b{re.escape(pointer)}\b', inner) or re.search(rf'\b{re.escape(pointer)}\s*(?:[-+]?=|\+\+|--)', inner):
            continue
        text = source[body_close + 1 + step.start(1):body_close + 1 + step.end()]
        out.append((BIV_ARM, edit(source, [(body_close, body_close + 1 + step.end(), f'{text} }} else {{ {text} }}')])))
        if len(out) >= LIMIT:
            break
    return out


def _tail_split(source, part):
    out = []
    clean = part.clean
    for label in re.finditer(rf'(?m)^[ \t]*({IDENT})[ \t]*:(?!:)[ \t]*\n', clean[:part.end]):
        if label.start() < part.opening:
            continue
        name = label[1]
        jumps = list(re.finditer(rf'\bgoto\s+{name}\s*;', clean[:part.end]))
        if len(jumps) != 1:
            continue
        # The tail: `X; if (C) { goto L; }` (or without braces), then the enclosing loop's closing brace.
        tail = re.compile(rf'\s*([^;{{}}]+;)\s*if\s*\(([^;{{}}]*)\)\s*{{?\s*goto\s+{name}\s*;\s*}}?\s*(}}\s*while\b)')
        start = label.end()
        first = re.match(r'\s*[^;{}]+;', clean[start:])
        if not first:
            continue
        stmt_end = start + first.end()
        cond = re.match(r'\s*if\s*\(', clean[stmt_end:])
        if not cond:
            continue
        cond_open = stmt_end + cond.end() - 1
        cond_close = close(clean, cond_open, '(', ')')
        if not cond_close:
            continue
        brace = re.match(r'\s*{', clean[cond_close + 1:])
        if not brace:
            continue
        body_open = cond_close + brace.end()
        body_close = close(clean, body_open, '{', '}')
        if not body_close or re.match(r'\s*else\b', clean[body_close + 1:]):
            continue
        end = tail.match(clean, body_close + 1)
        if not end or end.end(2) + 1 > jumps[0].start():
            continue
        inner = source[body_open + 1:body_close]
        if re.search(r'\b(?:for|while|do|switch)\b', clean[body_open:body_close]) or 'break' in clean[body_open:body_close]:
            continue
        inner = re.sub(r'\bcontinue\s*;', 'break;', inner)
        nxt = source[end.start(1):end.end(1)].strip()
        test = source[end.start(2):end.end(2)].strip()
        condition = source[cond_open + 1:cond_close].strip()
        head = source[start:stmt_end].strip()
        text = (f'for (;;)\n  {{\n    {head}\n    if (!({condition}))\n    {{\n      {nxt}\n      if ({test})\n'
                f'      {{\n        continue;\n      }}\n      break;\n    }}\n{inner}\n    {nxt}\n    if (!({test}))\n'
                f'    {{\n      break;\n    }}\n  }}\n  ')
        out.append((TAIL_SPLIT, edit(source, [(label.start(), end.start(3), '  ' + text)])))
        if len(out) >= LIMIT:
            break
    return out


def _mask_pair(source, part):
    out = []
    clean = part.clean
    decls = {m['name']: m for m in re.finditer(rf'^[ \t]*(?P<type>{_TYPES})\s+(?P<name>{IDENT})\s*;', clean[part.opening:part.end], re.M)}
    for low in re.finditer(rf'\b({IDENT})\s*=\s*({IDENT})\s*&\s*0xFF\s*;\s*', clean[:part.end]):
        if low.start() < part.opening:
            continue
        high = re.compile(rf'\b({IDENT})\s*=\s*{re.escape(low[2])}\s*&\s*0xFF00\s*;').search(clean, low.end(), low.end() + 400)
        if not high or low[1] not in decls or high[1] not in decls:
            continue
        wide, narrow = decls[low[1]], decls[high[1]]
        if not re.fullmatch(r'u16|unsigned\s+short', narrow['type']) or re.fullmatch(r'u16|unsigned\s+short', wide['type']):
            continue
        at = part.opening + wide.start('type')
        out.append((MASK_PAIR, edit(source, [(at, part.opening + wide.end('type'), 'u16')])))
        if len(out) >= LIMIT:
            break
    return out


_STEPS = (_call_scope, _reread_split, _biv_arm, _tail_split, _mask_pair)


def _then(source, name, step):
    part = view(source, name)
    children = step(source, part) if part else []
    return children[0][1] if children else None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    out = []
    for step in _STEPS:
        out.extend(step(source, part))
    # The measured combination: the biv stepped in both arms (each site in turn), the walk's tail split and the
    # mask pair narrowed, together (alone each one was worse: 7413, 5551 and 5225 from 4906; together 3236).
    combined = []
    for family, child in [c for c in out if c[0] == BIV_ARM]:
        text, applied = child, 1
        for step in (_tail_split, _mask_pair):
            later = _then(text, name, step)
            if later:
                text, applied = later, applied + 1
        if applied > 1:
            combined.append((FAMILY, text))
    return combined + out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
