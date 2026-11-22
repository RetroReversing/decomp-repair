"""A loop's stepped pointers and offsets written as the counter's multiples, for a target built with strength reduction.

m2c recovers each induction variable of a loop as its own variable stepped at the end of the body, because the target
shows `addiu $s5,$s5,0x20` and `addiu $s6,$s6,0xC` beside the counter's `addiu $s4,$s4,1`:

    var_a1 = list; off = 0; i = 0;
    do { ... *var_a1 ... off ... i += 1; var_a1 += 0x20; off += 0xC; } while (*var_a1 >= 0);

A KMC GCC 2.7.2 function's project profile carried `-fno-strength-reduce` (a search found the flag lowered the score
of the stepped form), and the match was nowhere near it. The game's C indexed by the counter, and the compiler's own
strength reduction made the steps: with `-fno-strength-reduce` dropped from the profile and every use written as
`(list + i * 0x20)`, `(i * 0xC)`, the function went from 244 to byte-identical (731 instructions, `-G0 -mips3 -mgp32
-mfp32 -O2`). The reduction emits the variables' starting values after the loop invariants it hoists (`addiu $s7,$sp,0x90`
first, then the `move $s5,$v1` and `move $s6,$zero`), which no spelling of the stepped form reaches, and it gives the
givs their allocation priority from the counter, which is why the one-shot weight on the counter's start had been
needed. The two changes go together: neither the profile alone nor the source alone changes the score.

Offered for a `do { } while (cond)` whose counter is set to 0 and stepped by one at the end of the body, with other
variables set before the loop to an expression that nothing in the loop assigns and stepped by a literal at the end of the
body, read in the loop and nowhere after it. The children are the all-at-once rewrite and each variable alone; `probes`
pairs the all-at-once rewrite with the profile that drops `-fno-strength-reduce`, the way the caller must judge it.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'stepped_induction_index'
FAMILIES = (FAMILY,)
LIMIT = 6
FLAG = '-fno-strength-reduce'
_STEP = re.compile(rf'(?m)^[ \t]*(?P<v>{IDENT})\s*(?:\+=\s*(?P<k>{NUMBER})|\+\+)\s*;[ \t]*\n')
_ASSIGN = re.compile(rf'(?m)^(?P<lead>[ \t]*)(?:/\*__repair_loop_weight\*/)?(?:do \{{ ?)*(?P<v>{IDENT}) = (?P<init>[^;{{}}]+);(?: ?\}} while \(0\);)*[ \t]*\n')
_BYTE = re.compile(r'\b(?:void|char|[su]8)\s*\*\s*$')


def _declared(clean, name):
    hit = re.search(rf'(?m)^[ \t]*(?P<type>[A-Za-z_][\w ]*?)\s*(?P<star>\**)\s*\b{re.escape(name)}\s*;[ \t]*$', clean)
    return (hit['type'].strip(), hit['star']) if hit else None


def _step_run(body):
    """The step statements that end a loop body, in order, or []."""
    run = []
    for step in reversed(list(_STEP.finditer(body + '\n'))):
        between = body[step.end():run[0].start()] if run else body[step.end():]
        if between.strip():
            break
        run.insert(0, step)
    return run


def _loops(part):
    clean = part.clean
    for loop in re.finditer(r'\bdo\s*{', clean[part.opening:part.end]):
        opening = part.opening + loop.end() - 1
        end = close(clean, opening, '{', '}')
        tail = re.match(r'\s*while\s*\((?P<cond>[^;{}]*)\)\s*;', clean[end:]) if end else None
        run = _step_run(clean[opening + 1:end - 1]) if tail else []
        if not run:
            continue
        strides = {}
        for step in run:
            if step['v'] in strides:
                break
            strides[step['v']] = int(step['k'], 0) if step['k'] else 1
        else:
            if any(k == 1 for k in strides.values()):
                yield opening, end, tail, run, strides


def _plan(part, loop, counter, var, stride):
    """(statement before the loop, replacement text) for one stepped variable, or None."""
    opening, end, tail, run, strides = loop
    clean = part.clean
    before = clean[part.opening + 1:opening]
    starts = [a for a in _ASSIGN.finditer(before) if a['v'] == var]
    kind = _declared(clean[part.opening:opening], var)
    if not starts or not kind or re.search(rf'\b{var}\b', clean[end + tail.end():part.end]):
        return None
    start = starts[-1]
    init = start['init'].strip()
    inside = clean[opening + 1:end - 1]
    stepped_at = run[0].start()
    if (re.search(rf'\b{var}\b', before[start.end():]) or re.search(rf'\b{var}\b\s*(?:=(?!=)|\+\+|--|[-+*/|&^]=)|&\s*{var}\b', inside[:stepped_at])
            or any(re.search(rf'\b{w}\b\s*(?:=(?!=)|\+\+|--|[-+*/|&^]=)', inside) for w in set(re.findall(IDENT, init)))
            or not re.search(rf'\b{var}\b', inside[:stepped_at] + tail['cond'])):
        return None
    type_, star = kind
    base = f'(char *)({init})' if star and _BYTE.search(type_ + ' ' + star) else f'({init})' if star else init
    term = f'{counter} * {stride:#x}' if stride > 9 else f'{counter} * {stride}'
    return start, ('(' + term + ')') if init in ('0', '0U') and not star else f'({base} + {term})'


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    result = []
    for loop in _loops(part):
        opening, end, tail, run, strides = loop
        for counter in [v for v, k in strides.items() if k == 1]:
            zero = [a for a in _ASSIGN.finditer(part.clean[part.opening + 1:opening]) if a['v'] == counter]
            if not zero or zero[-1]['init'].strip() not in ('0', '0U'):
                continue
            plans = {var: plan for var in strides if var != counter
                     and (plan := _plan(part, loop, counter, var, strides[var]))}
            if not plans:
                continue
            for chosen in ([list(plans)] + [[v] for v in plans] if len(plans) > 1 else [list(plans)]):
                edits = []
                for var in chosen:
                    start, text = plans[var]
                    at = part.opening + 1 + start.start()
                    edits.append((at, at + len(start.group(0)), ''))
                    for use in re.finditer(rf'\b{var}\b', part.clean[opening + 1:end + tail.end()]):
                        pos = opening + 1 + use.start()
                        edits.append((pos, pos + len(var), text))
                for step in run:
                    if step['v'] in chosen:
                        pos = opening + 1 + step.start()
                        edits = [e for e in edits if not (pos <= e[0] < pos + len(step.group(0)))]
                        edits.append((pos, pos + len(step.group(0)), ''))
                result.append((FAMILY, edit(source, edits)))
                if len(result) >= LIMIT:
                    return result
    return result


def probes(proj, fn, profile):
    """The rewrites judged without `-fno-strength-reduce`: under the flag they change nothing."""
    if dict(proj).get('arch') != 'mips' or profile.get('toolchain') != 'gcc-2.7.2-kmc' or FLAG not in profile.get('flags', ()):
        return []
    flags = [flag for flag in profile['flags'] if flag != FLAG]
    return [(flags, text) for _, text in variants(fn['best_source'], fn['name'])[:4]]
