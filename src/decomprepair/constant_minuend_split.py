"""A constant minus a call's result plus a step: the constant kept in a local set before an early return.

The shape (SN GCC 2.8.1, `-G0 -mips3 -O2`): m2c writes the difference as one expression

    return 0x2A - (func_X(arg0) + 3);

GCC's front end folds `c - (x + k)` to `(c - k) - x` and the combiner folds constants only inside one basic block, so a
single expression compiles to `addiu $v1, $v0, -?` and a subtract from a constant built after the call. The original kept
the constant in a local assigned in an earlier basic block (before a branch that returns early), the sum in a second local,
and subtracted them:

    h = 0x2A;  if (cond) { return 0; }  t = func_X(arg0) + 3;  return h - t;

The two blocks keep the front end from folding, and the target materialises `addiu rA, $zero, 0x2A` after the call (in
its delay slot or just after), applies `+ 3` to the result and then `subu`.

The gate is that: after a `jal`, within eight instructions, a constant built into a register (`addiu`/`ori rA, $zero, c`
with the expression's `c`), the step (`addiu rB, rB', k` with the sign of the expression's `+ k` or `- k`), and a `subu
rD, rA, rB` that subtracts the second from the first. Nothing is proposed without the assembly.

`variants` finds an early branch, a top-level `if` of the function whose body returns, and after it a statement `return
C - (CALL(...) + K);` or `LVALUE = C - (CALL(...) + K);` (`+` or `-`, `C` a literal, `CALL` a function name from the
file's prototypes that returns an integer type). Children:

- `constant_minuend_split`: `h = C;` written just before that early branch, the statement as `t = CALL(...) + K;` and the
  difference `h - t`;
- `constant_minuend_head`: the same with `h = C;` as the function's first statement.

`h` and `t` are new locals of the call's (promoted) integer type. Faithful: the constant and the sum are the same, only
named and placed. This module reads text only and never compiles or judges."""
import re

from .hand_found_support import IDENT, NUMBER, blocks, declare, fresh, instructions, number, stmts
from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'constant_minuend_split'
HEAD_FAMILY = 'constant_minuend_head'
FAMILIES = (FAMILY, HEAD_FAMILY)
LIMIT = 4
WINDOW = 8
_PROMOTED = {'s32': 's32', 'int': 's32', 'long': 's32', 'u32': 'u32', 'unsigned': 'u32', 'unsigned int': 'u32',
             'unsigned long': 'u32', 's16': 's32', 'u16': 's32', 's8': 's32', 'u8': 's32', 'short': 's32',
             'unsigned short': 's32', 'char': 's32', 'unsigned char': 's32', 'signed char': 's32', 'M2C_UNK': 's32'}
_STATEMENT = re.compile(rf'\s*(?:return\b|(?P<lhs>[^=;{{}}]+?)\s*=(?!=))\s*(?P<c>-?{NUMBER})\s*-\s*\(\s*(?P<callee>{IDENT})\s*\(')


def evidence(asm):
    """[(constant, step)] the target builds after a call: the constant, the step on the result, and the `subu` of them."""
    ops = instructions(asm)
    found = set()
    for index, (op, args) in enumerate(ops):
        if op not in ('jal', 'jalr'):
            continue
        window = ops[index + 1:index + 1 + WINDOW]
        for at, (op2, a2) in enumerate(window):
            if op2 not in ('addiu', 'ori', 'li') or len(a2) < 2 or (op2 != 'li' and (len(a2) != 3 or a2[1] != '$zero')):
                continue
            try:
                value = number(a2[-1])
            except ValueError:
                continue
            for later, (op3, a3) in enumerate(window[at + 1:], at + 1):
                if op3 != 'subu' or len(a3) != 3 or a3[1] != a2[0]:
                    continue
                for op4, a4 in window[:later]:
                    if op4 == 'addiu' and len(a4) == 3 and a4[0] == a3[2] and a4[1] != '$zero':
                        try:
                            found.add((value, number(a4[2])))
                        except ValueError:
                            pass
    return found


def _prototypes(clean, upto):
    """{function: promoted integer type its prototype returns} for the prototypes written before `upto`."""
    found = {}
    for hit in re.finditer(rf'(?m)^[ \t]*(?P<ret>(?:unsigned\s+)?{IDENT}(?:\s+{IDENT})?)\s+(?P<name>{IDENT})\s*\([^;{{}}]*\)\s*;', clean[:upto]):
        kind = _PROMOTED.get(' '.join(hit['ret'].split()))
        if kind:
            found[hit['name']] = kind
    return found


def variants(source, name, header='', arch='mips', asm=''):
    if arch != 'mips':
        return []
    wanted = evidence(asm)
    part = view(source, name) if wanted else None
    if not part:
        return []
    clean = part.clean
    top = stmts(part, part.opening + 1, part.end - 1)
    early = next((i for i, (a, b) in enumerate(top) if re.match(r'if\b', clean[a:b].lstrip()) and re.search(r'\breturn\b', clean[a:b])), None)
    if early is None:
        return []
    prototypes = _prototypes(clean + '\n' + (header or ''), part.opening)
    taken = set(re.findall(IDENT, source)) | set(re.findall(IDENT, header or ''))
    children = []
    for lo, hi in blocks(part):
        for a, b in stmts(part, lo, hi):
            hit = _STATEMENT.match(clean, a, b)
            if not hit or a < top[early][1] or hit['callee'] not in prototypes:
                continue
            closing = close(clean, hit.end() - 1)
            tail = re.fullmatch(rf'\s*(?P<sign>[+-])\s*(?P<k>{NUMBER})\s*\)\s*;\s*', clean[closing:b]) if closing else None
            if not tail:
                continue
            step = number(tail['k']) * (-1 if tail['sign'] == '-' else 1)
            if step and (number(hit['c']), step) in wanted:
                children += _children(source, part, top, early, (a, b), hit, closing, tail, prototypes[hit['callee']], taken)
    return list(dict.fromkeys(children))[:LIMIT]


def _children(source, part, top, early, span, hit, closing, tail, kind, taken):
    a, b = span
    constant, total = fresh('minuend', taken, 'c'), fresh('minuend', taken, 'sum')
    declaration = declare(source, part, [f'{kind} {constant};', f'{kind} {total};'])
    if not declaration:
        return []
    indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, a) + 1:])[0]
    head = 'return ' if hit['lhs'] is None else hit['lhs'].strip() + ' = '
    call = source[hit.start('callee'):closing]
    replaced = (a, b, f'{total} = {call} {tail["sign"]} {tail["k"]};\n{indent}{head}{constant} - {total};')
    out = []
    for family, at in ((FAMILY, top[early][0]), (HEAD_FAMILY, _first_statement(part, top))):
        if at is None or (family == HEAD_FAMILY and at == top[early][0]):
            continue
        spot = re.match(r'[ \t]*', source[source.rfind('\n', 0, at) + 1:])[0]
        out.append((family, edit(source, [declaration, (at, at, f'{constant} = {hit["c"]};\n{spot}'), replaced])))
    return out


def _first_statement(part, top):
    """The offset of the function's first statement that is not a declaration."""
    for a, b in top:
        text = part.clean[a:b]
        if re.match(rf'\s*(?:(?:unsigned|signed|const|struct|union)\s+)*{IDENT}(?:\s+{IDENT})*\s+\**\s*{IDENT}(?:\s*,\s*\**\s*{IDENT})*\s*;', text) \
                and not re.match(r'\s*(?:return|goto|break|continue)\b', text):
            continue
        return a + len(text) - len(text.lstrip())
    return None


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'arch', 'asm'),
          'order': 68, 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
