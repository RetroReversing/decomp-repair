"""A switch case's early-exit guard with its arm and the rest of the case exchanged.

    case 2:                                         case 2:
        if (n >= p->hold) {          ->                 if (n < p->hold) {
            p->phase = next;                                p->level = p->top + (s32) (p->rate * n);
            return;                                         return;
        }                                               }
        p->level = p->top + (s32) (p->rate * n);        p->phase = next;
        return;                                         return;

gcc 2.7.2 lays the arm a test falls into right after it, so which of the two exits is written inside the `if` decides
the branch sense (`bnez` over one, or `beql` to the other with its first instruction in the delay slot), the block order
and which tail the cross-jump keeps. m2c writes the polarity its own recovery found, and puts the label of a case that
only returns inside whichever arm shares that `return` (`if (c) { ...; case 3: return; } REST`). `guard_shape` makes the
exchange at a function body's top level and `tail_guard_else` in a tail `if`/`else`; neither reads a switch.

Measured on one N64 envelope stepper (KMC GCC 2.7.2 `-G0 -mips3 -O2`, 119 instructions). By hand from a draft at 1765,
one such case alone gave 1090, the other (the label inside its arm) 1305, and both together 490. In a chain of library
children the label-inside case took it 1765 -> 1585 and, after `fence_open` and `compound_pair_swap`, the other
1270 -> 475; `case_temporary_split` and `local_web_split` finished it at 0.

Bare blocks around a guard that declare nothing are opened first (`{ { if (c) {...return;} } v = x; } ...`). One child
per guard of a case, and one with all of them: both the `if` block and what follows it up to the next label
must leave the case (`return`, `break`, `continue` or `goto`), so neither side can fall into the other and the program
is the same. A `case` label inside the arm moves out with it. The exact judge decides every child; the layout reason
above is a hypothesis about the compiler, not read from its source.
"""
import re

from .branch_polarity_repairs import negate_any
from .c_scan import close, enclosing_block, header_before
from .guard_shape_repairs import opposite
from .integer_repair_support import edit, view

FAMILY = 'case_guard_arm_swap'
FAMILIES = (FAMILY,)
LIMIT = 8
_IF = re.compile(r'\bif\s*\(')
_BRACE = re.compile(r'[{}]')
_MARK = re.compile(r'[{}]|\b(?:case\b[^:;{}]*|default\s*):')
_EXIT = re.compile(r'(?:\A|[;{}:])\s*(?:return\b[^;{}]*|break|continue|goto\s+\w+)\s*;\Z')
_DECLARATION = re.compile(r'(?m)^\s*(?:(?:const|static|volatile|unsigned|signed|struct|union)\s+)*'
                          r'(?!(?:return|goto|else|case|break|continue)\b)[A-Za-z_]\w*(?:\s+|\s*\*+\s*)[A-Za-z_]\w*'
                          r'\s*(?:\[[^\]]*\])?\s*(?:=[^;]*)?;')


def _leaves(text):
    """True when control cannot run off the end of the statements `text`: its last one is an exit, or it ends in a bare
    block (not the body of an `if`, `else` or loop) whose last one is."""
    text = text.rstrip()
    while text.endswith('}'):
        opened = []
        for brace in _BRACE.finditer(text, 0, len(text) - 1):
            if brace[0] == '{':
                opened.append(brace.start())
            elif opened:
                opened.pop()
        if not opened:
            return False
        before = text[:opened[-1]].rstrip()
        if before and before[-1] not in ';{}:':
            return False
        text = text[opened[-1] + 1:-1].rstrip()
    return bool(_EXIT.search(text))


def _case_end(clean, start, block_end):
    """Where the case holding `start` ends: the next `case`/`default` label of this block, else the block's `}`."""
    depth = 0
    for hit in _MARK.finditer(clean, start, block_end):
        if hit[0] == '{':
            depth += 1
        elif hit[0] == '}':
            depth -= 1
        elif not depth:
            return hit.start()
    return block_end


def _flatten(source, name):
    """`source` with the braces of the bare blocks around a guard removed, where the block declares nothing: m2c and the
    search leave `{ { if (c) {...} } v = x; }`, whose braces would end the guard's "rest" too early."""
    for _ in range(LIMIT):
        part = view(source, name)
        if not part or part.opening < 0:
            break
        clean = part.clean
        for hit in _IF.finditer(clean, part.opening, part.end):
            outer = enclosing_block(clean, hit.start(), part.opening)
            if outer <= part.opening or clean[:outer].rstrip()[-1:] not in (';', '{', '}', ':'):
                continue
            end = close(clean, outer, '{', '}')
            if end < 0 or _DECLARATION.search(clean[outer + 1:end]):
                continue
            source = edit(source, [(outer, outer + 1, ''), (end, end + 1, '')])
            break
        else:
            break
    return source


def variants(source, name):
    if len(source) > 128000:
        return []
    source = _flatten(source, name)
    part = view(source, name)
    if not part or part.opening < 0:
        return []
    clean, body = part.clean, part.opening
    found = []
    for hit in _IF.finditer(clean, body, part.end):
        closing = close(clean, hit.end() - 1, '(', ')')
        block = re.compile(r'\s*\{').match(clean, closing + 1) if closing >= 0 else None
        if not block or clean[:hit.start()].rstrip()[-1:] not in (';', '{', '}', ':'):
            continue
        opening = block.end() - 1
        after = close(clean, opening, '{', '}')
        outer = enclosing_block(clean, hit.start(), body)
        if after < 0 or outer <= body:
            continue
        header = header_before(clean, outer).strip()
        if not (header.startswith('switch') or header.endswith(':')):
            continue
        outer_end = close(clean, outer, '{', '}')
        if outer_end < 0:
            continue
        end = _case_end(clean, after + 1, outer_end)
        arm, rest = clean[opening + 1:after], clean[after + 1:end]
        if re.match(r'\s*else\b', rest) or not _leaves(arm) or not _leaves(rest):
            continue
        condition = source[hit.end():closing].strip()
        inverse = opposite(condition) or negate_any(condition)
        if not inverse:
            continue
        indent = re.search(r'[ \t]*$', source[:hit.start()])[0]
        first = source[opening + 1:after].strip('\n').rstrip()
        second = source[after + 1:end].strip('\n').rstrip()
        shift = len(first) - len(first.lstrip(' \t')) - (len(second) - len(second.lstrip(' \t')))
        second = re.sub(r'(?m)^(?=[ \t]*\S)', ' ' * max(shift, 0), second)
        if _DECLARATION.search(arm):
            first = f'{indent}{{\n{first}\n{indent}}}'
        tail = re.search(r'[ \t]*$', source[:end])[0]
        found.append((hit.start(), end, f'if ({inverse}) {{\n{second}\n{indent}}}\n{first}\n{tail}'))
    out = [(FAMILY, edit(source, [item])) for item in found[:LIMIT]]
    apart, last = [], -1
    for item in found:
        if item[0] >= last:
            apart.append(item)
            last = item[1]
    if len(apart) > 1:
        out.insert(0, (FAMILY, edit(source, apart)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
