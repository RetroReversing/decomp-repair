"""A loop that ends on a literal, in a one-shot scope: the hoisted constant outranks the locals it was behind.

GCC 2.x hoists a loop's literal compare operand (`while (id != 0xFFFF)`: MIPS compares a register with a register,
so the literal is an `ori` the loop pass moves in front of the loop) into a pseudo of its own, and the register
allocator ranks pseudos by `floor_log2(refs) * refs / live length` (global.c). Two things hold that pseudo down
(read in the 2.7.2 sources' local-alloc.c and flow.c, and seen in the `-dl -dg` tables of one function):

- local-alloc doubles the live length of a pseudo set once to a constant (`reg_live_length *= 2`: the REG_EQUIV note
  the loop pass leaves on the hoisted set), and
- flow.c counts a reference once per loop depth.

A local set once before the loop and compared inside it (the id a function searches for) then beats the constant on
the live length alone: the target gave the saved register to the constant and the next to the id, the source's
order was the reverse. `do { <the loop> } while (0);` is one loop more round everything in it at no instruction
cost, so the constant's set (counted twice) and its test gain weight while the id, set outside, gains only its use
(3 refs / 42 live against 3 / 37 became 5 / 42 against 4 / 37 in the table of the function this came from).

The wrapper also weighs the body's references, so the flag the body sets overtakes the outer counter, which then
needs weight of its own: the counter's bump in a one-shot scope too. In its scope the bump comes before the load of
the global the loop's guard compares with, where the target has it after, so the global is read into a local first
(a local the function never reads again, the return value's for one: the choice moves the temporary's register, so
each is offered). The three edits are no better one at a time (the wrap alone went 20 -> 50, with the bump 60,
with the bump and a different temporary 15) and exact together (0, `gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`, one
function): `variants` offers the combination as one child beside each part.

- wrap: every do-while that ends on `x != LITERAL` or `x == LITERAL` (a non-zero literal), in one or two scopes;
- bump: the run of `x += n;` statements before an `if (x <rel> GLOBAL)`, in a scope, with and without the global
  read into a temporary first;
- both, for every temporary.

A local qualifies as the temporary when every mention of it is a plain assignment `t = ...;` or a `return t;` right
after one. Candidates for the exact judge, never equivalence claims; the compiler's reasons are hypotheses."""
import re

from .integer_repair_support import IDENT, edit, locals_for, refs, view
from .pattern_repairs import close

FAMILY = 'hoisted_constant_loop_scope'
FAMILIES = (FAMILY,)
MARK = '/*__repair_hoisted_constant*/'
TEMPS = 6
WIDE = {'s32', 'u32', 'int', 'unsigned int', 'signed int'}
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)'
_LITERAL = re.compile(r'(?:0[xX]0*[0-9a-fA-F]*[1-9a-fA-F][0-9a-fA-F]*|[1-9][0-9]*)[uUlL]*')
_CONDITION = re.compile(rf'[ \t(]*(?:\([^()]*\)[ \t]*)?{IDENT}[ \t)]*(?:!=|==)[ \t]*(?P<literal>[0-9a-fA-FxXuUlL]+)[ \t]*')
_IF = re.compile(rf'\bif[ \t]*\([ \t]*(?P<var>{IDENT})[ \t]*(?:>=|<=|<|>|!=|==)(?:[ \t(]*\((?:u32|s32|int|unsigned int)\)[ \t]*|[ \t(]*)(?P<global>{IDENT})[ \t]*\)')
_RUN = re.compile(rf'(?P<run>(?:\s*{IDENT}[ \t]*\+=[ \t]*{NUMBER}[ \t]*;){{1,3}})\s*$')


def _loops(clean, base, end):
    """(start of `do`, just past the `;`) of each do-while whose condition compares a name with a non-zero literal."""
    found = []
    for hit in re.finditer(r'\bdo\s*\{', clean[base:end]):
        opening = base + hit.end() - 1
        stop = close(clean, opening, '{', '}')
        tail = re.match(r'\s*while\s*\((?P<c>[^;]*)\)\s*;', clean[stop:end]) if stop else None
        condition = _CONDITION.fullmatch(tail['c']) if tail else None
        if condition and _LITERAL.fullmatch(condition['literal']):
            found.append((base + hit.start(), stop + tail.end()))
    return found


def _scoped(statements):
    return MARK + 'do { ' + ' '.join(statements.split()) + ' } while (0);'


def _dead_temps(part):
    """Integer locals every mention of which is a plain assignment or a `return t;` right after one."""
    clean = part.clean
    names = []
    for decl in locals_for(part):
        if decl['type'].strip() not in WIDE:
            continue
        name = decl['name']
        for hit in refs(part, decl):
            before, after = clean[max(0, hit.start() - 60):hit.start()], clean[hit.end():hit.end() + 12]
            if re.match(r'\s*=(?!=)', after) and re.search(r'(?:^|[;{}:])\s*$', before):
                continue
            if re.search(r'\breturn\s*$', before) and re.match(r'\s*;', after):
                earlier = clean[:hit.start()].rsplit('return', 1)[0].rstrip()
                if re.search(rf'(?:^|[;{{}}:])\s*{re.escape(name)}\s*=(?!=)[^;{{}}]*;(?:\s*{IDENT}:)?$', earlier):
                    continue
            break
        else:
            names.append(name)
    return names


def _extern_integer(source, header, name):
    return re.search(rf'(?m)^[ \t]*extern[ \t]+(?:s32|u32|int|unsigned int)[ \t]+{re.escape(name)}[ \t]*;', header + '\n' + source)


def variants(source, name, header=''):
    part = view(source, name)
    if not part or MARK in source:
        return []
    clean, base, end = part.clean, part.opening + 1, part.end
    out = []
    wraps = {}
    for depth in (1, 2):
        edits = [(start, stop, MARK + 'do { ' * depth + source[start:stop] + ' } while (0);' * depth) for start, stop in _loops(clean, base, end)]
        if edits:
            wraps[depth] = edits
            out.append((FAMILY, edit(source, edits)))
    bumps = []
    for hit in _IF.finditer(clean, base, end):
        run = _RUN.search(clean[max(base, hit.start() - 200):hit.start()])
        if not run or not _extern_integer(source, header, hit['global']):
            continue
        shift = max(base, hit.start() - 200)
        start, stop = shift + run.start('run'), shift + run.end('run')
        if not re.search(rf'(?<![\w.>*]){re.escape(hit["var"])}[ \t]*\+=', clean[start:stop]):
            continue
        bumps.append((hit, start + len(run['run']) - len(run['run'].lstrip()), stop))
    if not bumps:
        return out
    temps = _dead_temps(part)[:TEMPS]
    for hit, start, stop in bumps:
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:start])[0]
        scope = _scoped(source[start:stop])
        out.append((FAMILY, edit(source, [(start, stop, scope)])))
        if wraps.get(1):
            out.append((FAMILY, edit(source, wraps[1] + [(start, stop, scope)])))
        for temp in temps:
            load = [(start, stop, f'{temp} = {hit["global"]};\n{indent}{scope}'),
                    (hit.start('global'), hit.end('global'), temp)]
            out.append((FAMILY, edit(source, load)))
            if wraps.get(1):
                out.append((FAMILY, edit(source, wraps[1] + load)))
    return out
