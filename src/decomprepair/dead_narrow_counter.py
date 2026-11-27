"""A narrow local counted in an empty arm inside a loop: loop.c sees a longer loop and leaves its constants in place.

GCC's loop pass moves an invariant out of a loop only when `threshold * savings * lifetime >= insn_count`, where the
threshold is `(loop_has_call ? 1 : 2) * (1 + n_non_fixed_regs)` and drops by 3 after every move (loop.c,
`move_movables`; read in the gcc-2.8.1 sources). A message loop's switch compares its value with small literals; a
literal held in a register for one compare has savings 1 and lifetime 1, so whether `li $s2, 2` goes in front of the
loop or `addiu $v0, $zero, 2` stays at the compare is decided by the loop's length *at loop time* alone.

A local the program counts and never reads is that length. Arithmetic on a `u8` local is SImode arithmetic through
subregs: `(set t (plus (subreg n) 1))` and `(set n (subreg t))`, two registers each used by the other's set, so
cse's dead-insn pass (`delete_dead_from_cse`, which drops only sets of registers with no uses left, a register's own
update not counted) keeps them; a plain `s32 n; n++;` is deleted there. They count in loop.c's `insn_count`, and flow
deletes them afterwards (no read is live), so the final code has no trace of them except the constants the loop pass
left alone. The original program's version is probably a counter whose debug print was compiled out.

Measured on an 83-instruction N64 message thread (SN GCC 2.8.1, `-G0 -mips3 -O2`): the loop held 55 real insns and
loop.c moved the outer switch's constants 2 and 1 into saved registers where the target recomputes them per pass;
`u8 n++` in the empty `if (mode == 10) { }` arm made 58 (1 still moved), `n = (n + 1) & 7` or two counted locals 59-60
and the function byte-identical (with its data relocations; the threshold reading is the loop dump's, `-dL`). A dead
`long long` does the same but leaves a CLOBBER that takes an 8-byte frame slot.

`variants` offers, for every empty compound statement (`{ }`) inside a `for`, `while` or `do` body, a counter local
declared at the top of the function and updated there: masked (`c = (c + 1) & 7;`), plain (`c++;`) and two counters.
The arm stays a no-op for the program's behaviour: the local is never read. Candidates for the exact judge only.

`dead_loop_length` is the same lever for a loop with no empty arm, where the length needed is larger. An N64 asset
list loop (SN GCC 2.8.1, `-G0 -mips3 -O2`) held 36 real insns, and loop.c moved the addresses a guarded call reads in
front of the loop (two more saved registers than the target, an 8-byte larger frame). One counter in a new `else` of
the guard (which also keeps cse from carrying an address past the join) and four counted at the end of the loop body
made 51, and those two addresses stayed where the target has them (judged 1548 to 10). Four counters in all did not
reach it. For each loop whose body makes a call it offers several counts of trailing counters, with and without the
new `else`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'dead_narrow_counter'
LENGTH = 'dead_loop_length'
FAMILIES = (FAMILY, LENGTH)
NAME = 'dead_count'
LIMIT = 12
LENGTH_LIMIT = 30
COUNTS = (4, 3, 5, 6, 2)  # counters at the end of the loop body
LOOP = re.compile(r'\b(?:for|while)\s*\(|\bdo\s*\{')
EMPTY = re.compile(r'\{\s*\}')
IF = re.compile(r'\bif\s*\(')
JUMP = re.compile(r'\b(?:continue|break|return|goto)\b')
CALL = re.compile(r'\b(?!(?:if|for|while|switch|return|sizeof)\b)[A-Za-z_]\w*\s*\(')
LAST_JUMP = re.compile(r'(?:\b(?:continue|break|goto\s+\w+)|\breturn\b[^;{}]*)\s*;\s*$')


def _loop_bodies(clean, opening, end):
    """[start, stop) spans of every loop body (`{ ... }`) in the function."""
    bodies = []
    for m in LOOP.finditer(clean, opening, end):
        if m.group().startswith('do'):
            brace = m.end() - 1
        else:
            stop = close(clean, m.end() - 1, '(', ')')
            rest = re.match(r'\s*\{', clean[stop:end]) if stop else None
            if not rest:
                continue  # a do-while's tail `while (x);` or an unbraced body
            brace = stop + rest.end() - 1
        last = close(clean, brace, '{', '}')
        if last:
            bodies.append((brace, last))
    return bodies


def _fresh(clean, base):
    taken = set(re.findall(r'\b' + base + r'\d*\b', clean))
    if base not in taken:
        return base
    k = 2
    while f'{base}{k}' in taken:
        k += 1
    return f'{base}{k}'


def _plain_arms(clean, lo, hi):
    """Closing braces of the `if (...) { ... }` blocks without an `else` in the loop body, those that jump out last."""
    arms = []
    for m in IF.finditer(clean, lo, hi):
        stop = close(clean, m.end() - 1, '(', ')')
        brace = re.match(r'\s*\{', clean[stop:hi]) if stop else None
        if not brace:
            continue
        start = stop + brace.end() - 1
        last = close(clean, start, '{', '}')
        if last and not re.match(r'\s*else\b', clean[last:hi]):
            arms.append((bool(JUMP.search(clean, start, last)), last))
    return [last for _, last in sorted(arms)]


def _indent_at(source, at):
    line = source.rfind('\n', 0, at) + 1
    return re.match(r'[ \t]*', source[line:]).group()


def _lengthened(source, clean, opening, bodies):
    """The loop made longer by counters nothing reads: at its end, with one more in a new `else` arm or without."""
    prefix = _fresh(clean, NAME)
    result = []
    loops = [(lo, hi) for lo, hi in bodies if CALL.search(clean, lo, hi)][:3]
    for lo, hi in loops:
        tail = hi - 1  # the loop's closing brace
        jump = LAST_JUMP.search(clean[lo + 1:tail])
        at = lo + 1 + jump.start() if jump else tail
        at = len(source[:at].rstrip(' \t'))
        inner = _indent_at(source, tail) + '    '
        for count in COUNTS:
            for arm in _plain_arms(clean, lo + 1, tail)[:2] + [None]:
                for kind in ('u8', 's16'):
                    names = [f'{prefix}_{k}' for k in range(count + (arm is not None))]
                    text = source[:at] + ''.join(f'{inner}{n}++;\n' for n in names[-count:]) + source[at:]
                    if arm is not None:  # before `at`, so its offset still holds
                        pad = _indent_at(source, arm - 1)
                        text = text[:arm] + f' else {{\n{pad}    {names[0]}++;\n{pad}}}' + text[arm:]
                    decls = ''.join(f'\n    {kind} {n} = 0;' for n in names)
                    result.append((LENGTH, text[:opening + 1] + decls + text[opening + 1:]))
                    if len(result) >= LENGTH_LIMIT:
                        return result
    return result


def variants(source, name, limit=LIMIT):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    bodies = _loop_bodies(clean, opening + 1, end)
    if not bodies:
        return []
    sites = [m for m in EMPTY.finditer(clean, opening + 1, end)
             if any(lo < m.start() and m.end() <= hi for lo, hi in bodies)
             and re.search(r'(?:\)|\belse)\s*$', clean[:m.start()])]  # an if/else/loop arm, not an initialiser
    first = _fresh(clean, NAME)
    second = _fresh(clean, NAME + '_b')
    result = []
    for m in sites:
        line_start = clean.rfind('\n', 0, m.start()) + 1
        indent = re.match(r'[ \t]*', source[line_start:m.start()]).group() + '    '
        outer = re.match(r'[ \t]*', source[line_start:m.start()]).group()
        for decl, body in ((f'u8 {first} = 0;', f'{first} = ({first} + 1) & 7;'),
                           (f'u8 {first} = 0;', f'{first}++;'),
                           (f'u8 {first} = 0, {second} = 0;', f'{first}++;\n{indent}{second}++;')):
            arm = '{\n' + indent + body + '\n' + outer + '}'
            text = source[:m.start()] + arm + source[m.end():]
            text = text[:opening + 1] + '\n    ' + decl + text[opening + 1:]
            result.append((FAMILY, text))
            if len(result) >= limit:
                break
        if len(result) >= limit:
            break
    return result + _lengthened(source, clean, opening, bodies)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60}  # the registry: no caller wiring (registry.py)
