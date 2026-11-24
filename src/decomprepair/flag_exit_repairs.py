"""Five rewrites from a large collision sweep's last rows (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`).

Measured on a 1337-instruction collision sweep with the exact judge, each from the state before it:

- `flag_signed_byte`: an `u8` flag local that is only ever set to 0 or 1 declared `s8` (390 -> 180). Its tests then
  sign-extend it; combine knows its nonzero bits (only bit 0) and rewrites the extension as a paradoxical subreg
  (`(set r (subreg:SI (reg:QI flag) 0))`), which reload cannot replace with the spilled flag's stack slot (reload1.c
  forces a reload for a paradoxical subreg of a value that extends when loaded), so it loads the byte into a spill
  register and copies it: the target's `lbu $t2, 0x147($sp); move $v0, $t2` before each test. Each reload also turns
  reload's round-robin over its spill registers one step, so later `$t1`/`$t2` choices follow.
- `loop_break_return`: `if (p == NULL) { break; } goto L;` whose `break` leaves for the function's closing
  `return E;`, written as `return E;` there (180 -> 110). The copy of the return the jump optimizer later merges with
  the closing one still took its spill register in reload (the next `$t1`/`$t2` swap back), and the shorter path ends
  a float argument's life two insns earlier, which reorders its priority against its neighbour (`$f28`/`$f30`).
- `call_arm_scope`: the arm of `if ((hit << 0x18) != 0) { .. }` after a call's `do { hit = f(..); } while (0);`
  (decomp-repair `condition_call_scope`) as `{ do { .. } while (0); }` (110 -> 10). The loop notes weigh the arm's
  references one loop deeper in flow's counts, so local-alloc's quantity order (`floor_log2 (refs) * refs / life`)
  gives a sum's load the second float register, as the same arm of the sibling loop has it, and sched2 keeps the flag
  store where the target has it. Scaffolding (an empty loop); report it when it decides a match.
- `counter_step_last`: a loop body ending in `i += 1; p += 6; q += 3;` as `p += 6; q += 3; i += 1;` (450 -> 390):
  the counter's increment last, as a `for` loop's step is emitted after the body's own pointer steps.
- `index_local_split`: `t = i;` copied from a counter and used as an index (`(t * 6)`, `(t * 2)`) where `t` is m2c's
  temporary reused from another loop, given a local of its own (`t_idx`, `u16`), as the source had one per loop
  (475 -> 450 with the base staging of `pointer_base_stage`).

Candidate rewrites; the exact judge decides each.
"""
import re

from .integer_repair_support import IDENT, edit, view

SIGNED_FLAG = 'flag_signed_byte'
BREAK_RETURN = 'loop_break_return'
ARM_SCOPE = 'call_arm_scope'
STEP_LAST = 'counter_step_last'
INDEX_SPLIT = 'index_local_split'
FAMILIES = (SIGNED_FLAG, BREAK_RETURN, ARM_SCOPE, STEP_LAST, INDEX_SPLIT)
LIMIT = 4


def _close(text, opening):
    """Index of the brace closing the one at `opening`, or None."""
    depth = 0
    for i in range(opening, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return i
    return None


def _signed_flag(source, part):
    out = []
    body = part.clean[part.opening:part.end]
    for decl in re.finditer(rf'(?m)^([ \t]*)(?:u8|unsigned char)([ \t]+)({IDENT})[ \t]*;', part.clean[:part.end]):
        if decl.start() < part.opening:
            continue
        name = decl[3]
        sets = re.findall(rf'(?<![\w.>])\b{name}\s*(=(?!=)|\+=|-=|\|=|&=|\+\+|--)\s*([^;]*);', body)
        if not sets or any(op != '=' or value.strip() not in ('0', '1') for op, value in sets):
            continue
        if re.search(rf'&\s*{name}\b', body):
            continue
        out.append((SIGNED_FLAG, edit(source, [(decl.start(), decl.end(), f'{decl[1]}s8{decl[2]}{name};')])))
        if len(out) >= LIMIT:
            break
    return out


def _break_return(source, part):
    clean = part.clean
    final = None
    for hit in re.finditer(r'\breturn\b([^;]*);\s*}\s*$', clean[part.opening:part.end + 1]):
        final = hit
    if not final:
        return []
    value = final[1].strip()
    if not value or not re.fullmatch(rf'(?:\(\s*\w+\s*\)\s*)?{IDENT}', value):
        return []
    out = []
    pattern = re.compile(rf'if\s*\([^;{{}}]*\)\s*{{(\s*)break;(\s*)}}(\s*)goto\s+{IDENT}\s*;')
    for hit in pattern.finditer(clean, part.opening, part.end):
        start = hit.start(1) + len(hit[1])
        out.append((BREAK_RETURN, edit(source, [(start, start + len('break;'), f'return {value};')])))
        if len(out) >= LIMIT:
            break
    return out


def _arm_scope(source, part):
    clean = part.clean
    out = []
    pattern = re.compile(rf'}}\s*while\s*\(\s*0\s*\)\s*;\s*if\s*\(\s*\(\s*({IDENT})\s*<<\s*0x18\s*\)\s*!=\s*0\s*\)\s*{{')
    for hit in pattern.finditer(clean, part.opening, part.end):
        opening = hit.end() - 1
        end = _close(clean, opening)
        if end is None or not clean[opening + 1:end].strip():
            continue
        if re.match(r'\s*do\s*{', clean[opening + 1:end]):
            continue
        out.append((ARM_SCOPE, edit(source, [(end, end, ' } while (0); '), (opening + 1, opening + 1, ' do { ')])))
        if len(out) >= LIMIT:
            break
    return out


def _step_last(source, part):
    clean = part.clean
    out = []
    step = rf'({IDENT})\s*\+=\s*(\w+)\s*;'
    pattern = re.compile(rf'(?m)^([ \t]*)({IDENT})\s*\+=\s*1\s*;[ \t]*\n((?:[ \t]*{step}[ \t]*\n)+)(?=[ \t]*}})')
    for hit in pattern.finditer(clean, part.opening, part.end):
        rest = hit[3]
        if re.search(rf'\b{hit[2]}\b', rest):
            continue
        counter = clean[hit.start(1):hit.start(3)]
        out.append((STEP_LAST, edit(source, [(hit.start(1), hit.end(3), source[hit.start(3):hit.end(3)] + counter)])))
        if len(out) >= LIMIT:
            break
    return out


def _index_split(source, part):
    clean = part.clean
    out = []
    decls = {m[2]: m for m in re.finditer(rf'(?m)^[ \t]*(s32|u32|int|s16|u16)[ \t]+({IDENT})[ \t]*;', clean[:part.end])
             if m.start() > part.opening}
    for hit in re.finditer(rf'\b({IDENT}) = ({IDENT});', clean[part.opening:part.end]):
        name = hit[1]
        if name not in decls:
            continue
        start = part.opening + hit.start()
        # The copy's uses up to the end of its statement line: an index (`(t * 6)`, `(t * 2)`).
        line_end = clean.find('\n', start)
        line_end = part.end if line_end < 0 else line_end
        uses = [m for m in re.finditer(rf'\b{name}\b', clean[start:line_end])]
        if len(uses) < 3 or not re.search(rf'\(\s*{name}\s*\*\s*\w+\s*\)', clean[start:line_end]):
            continue
        # Only a temporary used somewhere else too (m2c's reuse), not one this line owns.
        if not re.search(rf'\b{name}\b', clean[part.opening:start] + clean[line_end:part.end]):
            continue
        fresh = f'{name}_idx'
        if re.search(rf'\b{fresh}\b', clean):
            continue
        decl = decls[name]
        edits = [(start + m.start(), start + m.end(), fresh) for m in uses]
        edits.append((decl.end(), decl.end(), f'\n  u16 {fresh};'))
        out.append((INDEX_SPLIT, edit(source, edits)))
        if len(out) >= LIMIT:
            break
    return out


_STEPS = (_signed_flag, _break_return, _arm_scope, _step_last, _index_split)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    out = []
    for step in _STEPS:
        try:
            out.extend(step(source, part))
        except (KeyError, IndexError, TypeError):
            continue
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
