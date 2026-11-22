"""A function's opening `do { } while (0)` ended between the two loads of a pointer chain, and a sum's product staged
before a scope of its own.

Both read in GCC 2.7.2's source (`sched.c`, `flow.c`, `local-alloc.c`) on an 851-instruction N64 ray test (KMC GCC
2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`, scoring 2) whose opening run was already wrapped (`entry_scheduling_scope`):

- **The scope ends between the loads.** `sched_analyze_insn` makes the first insn after a loop note depend on every
  earlier register set and memory access, and every later one depend on it. The saved best read
  `sp = M2C_FIELD(M2C_FIELD(p, void **, 0x20), void **, 0x58);` inside the scope, beside `copy = p;` (a spilled
  pseudo). The copy is a free leaf for both schedulers, so it filled the load's latency and its stack store came after
  the second load (`lw; lw; sw`); the target has `lw v0,0x20(s7); sw s7,0x10c(sp); lw v0,0x58(v0)`. With the first
  load (into a new local) and the copy as the scope's last statements and the second load after `} while (0);`, the
  second load is the anchor: it depends on the copy, whose store therefore sits between the two loads, filling the
  first load's delay. 70 -> 10 in the isolated judge.
- **The sum's add and the parameter copy in a scope of their own.** `flow.c` adds `loop_depth` to a register's
  reference count for every use, and `local-alloc.c` (`qty_compare_1`) orders the quantities of a block by
  `floor_log2(refs) * refs / life`, then by quantity number (the one born first wins a tie). In
  `end.z = b[2] + a[2] * s`, the product's quantity and the loaded addend's tied (same references, same life with the
  parameter copy `v = arg;` scheduled between the add and the store), so the product, born first, got `$f0`; the target
  has the addend in `$f0` (`add.s $f0,$f0,$f2`). The product staged in a local before `do { d = b[2] + staged; v = arg; }
  while (0);` counts the addend's and the sum's references one loop deeper, and the copy stays in the scope, where the
  second scheduler still puts it between the add and the store as the target has it. 10 -> 0 (60 from the saved best
  alone: the two only pay off together, so the pair is one child).

`entry_scope_split` offers, for a function whose body opens with `do { ... } while (0);`: each two-level `M2C_FIELD`
chain assignment in it split there (the first load into `link_<p>`, the rest of the scope's statements after the
wrapper), with and without the plain copies of the chain's base moved after the first load; each `d = (x * s) + y;` or
`d = y + (x * s);` beside a plain copy `v = w;` staged with the add and the copy in a scope of their own (the copy after
or before the add); and the two together. The judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .line_scan import lines

FAMILY = 'entry_scope_split'
FAMILIES = (FAMILY,)
ARG = r'[^,()]+(?:\([^()]*\)[^,()]*)*'
CHAIN = re.compile(rf'^(?P<lhs>{IDENT}(?:\.{IDENT})*)\s*=\s*M2C_FIELD\(\s*M2C_FIELD\(\s*(?P<base>{IDENT})\s*,\s*'
                   rf'(?P<t1>[^,()]+?)\s*,\s*(?P<o1>[^,()]+?)\s*\)\s*,\s*(?P<t2>[^,()]+?)\s*,\s*(?P<o2>[^,()]+?)\s*\)\s*;$')
PRODUCT = rf'\(\s*(?P<{{p}}>{ARG}?\*\s*(?P<{{s}}>{IDENT}))\s*\)'
SUM_FIRST = re.compile(rf'^(?P<dst>{IDENT}(?:\.{IDENT})*)\s*=\s*{PRODUCT.format(p="prod", s="scale")}\s*\+\s*(?P<add>.+?);$')
SUM_LAST = re.compile(rf'^(?P<dst>{IDENT}(?:\.{IDENT})*)\s*=\s*(?P<add>.+?)\s*\+\s*{PRODUCT.format(p="prod", s="scale")};$')
STATEMENT = re.compile(rf'=|^(?:if|else|for|while|do|switch|return|goto|break|continue)\b|^{IDENT}\s*\((?!\s*\*)|^\w+\s*:')
COPY = re.compile(rf'^(?P<dst>{IDENT})\s*=\s*(?P<src>{IDENT})\s*;$')


def _scope(body):
    """(index of the opening `do {`, index of its `} while (0);`) when the body's first statement is that wrapper."""
    depth = 0
    for index, line in enumerate(body):
        text = line.stripped
        opened = depth
        depth += line.text.count('{') - line.text.count('}')
        if opened or not text:
            continue
        if text == 'do {':
            inner = 0
            for later in range(index, len(body)):
                inner += body[later].text.count('{') - body[later].text.count('}')
                if inner == 0:
                    return (index, later) if body[later].stripped == '} while (0);' else None
            return None
        if STATEMENT.search(text):
            return None
    return None


def _declared_type(clean, part, variable):
    hit = re.search(rf'(?m)^\s*(?P<type>[A-Za-z_][\w\s]*?\**)\s*\b{re.escape(variable)}\s*;', clean[part.opening:part.end])
    return hit['type'].strip() if hit else None


def _splits(body, opening, closing, indent):
    """[(replacement lines of the scope's inner part, declaration, lines after the wrapper)] for each chain split."""
    found = []
    for k in range(opening + 1, closing):
        hit = CHAIN.match(body[k].stripped)
        if not hit or not hit['t1'].rstrip().endswith('*'):
            continue
        base, link = hit['base'], f'link_{hit["base"]}'
        first = f'{body[k].indent}{link} = M2C_FIELD({base}, {hit["t1"]}, {hit["o1"]});'
        after = [f'{indent}{hit["lhs"]} = M2C_FIELD({link}, {hit["t2"]}, {hit["o2"]});'] + \
                [f'{indent}{body[i].source.strip()}' for i in range(k + 1, closing)]
        before = [body[i].source for i in range(opening + 1, k)]
        pointee = hit['t1'].rstrip()[:-1].rstrip()
        declaration = f'{pointee}{"" if pointee.endswith("*") else " "}{link};'
        found.append((before + [first], declaration, after))
        # the plain copies of the base just ahead of the chain after the first load, so the load is the scope's anchor
        # for nothing and the copy sits between the loads (sched.c: the insn after a loop note depends on all before)
        copies = []
        index = len(before)
        while index and COPY.match(body[opening + index].stripped) and COPY.match(body[opening + index].stripped)['src'] == base:
            copies.insert(0, before[index - 1])
            index -= 1
        if copies:
            found.append((before[:index] + [first] + copies, declaration, after))
    return found


def _stages(body, lines_in, clean, part):
    """[(new inner lines, declaration)] for each product sum beside a plain copy, staged into a scope with the copy."""
    found = []
    for k, text in enumerate(lines_in):
        stripped = text.strip()
        hit = SUM_FIRST.match(stripped) or SUM_LAST.match(stripped)
        if not hit:
            continue
        kind = _declared_type(clean, part, hit['scale'])
        if kind not in ('f32', 'float', 'f64', 'double', 's32', 'int', 'u32'):
            continue
        indent = re.match(r'\s*', text)[0]
        staged = 'staged_' + re.sub(r'\W', '_', hit['dst'])
        for neighbour in (k - 1, k + 1):
            if not 0 <= neighbour < len(lines_in) or not COPY.match(lines_in[neighbour].strip()):
                continue
            copy = lines_in[neighbour]
            for copy_first in (False, True):
                inner = [f'{indent}    {copy.strip()}'] if copy_first else []
                inner.append(f'{indent}    {hit["dst"]} = {hit["add"].strip()} + {staged};')
                if not copy_first:
                    inner.append(f'{indent}    {copy.strip()}')
                block = [f'{indent}{staged} = {hit["prod"].strip()};', f'{indent}do {{', *inner, f'{indent}}} while (0);']
                lo, hi = min(k, neighbour), max(k, neighbour)
                found.append((lines_in[:lo] + block + lines_in[hi + 1:], f'{kind} {staged};'))
    return found


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b|^\s*#', part.body, re.M):
        return []
    body = lines(part, source)
    scope = _scope(body)
    if not scope:
        return []
    opening, closing = scope
    indent = body[opening].indent
    start, end = body[opening].start, body[closing].end
    inner = [body[i].source for i in range(opening + 1, closing)]
    at = body[opening].start

    def emit(inner_lines, after, declarations):
        text = f'{indent}do {{\n' + ''.join(f'{line}\n' for line in inner_lines) + f'{indent}}} while (0);\n'
        text += ''.join(f'{line}\n' for line in after)
        decls = ''.join(f'{indent}{d}\n' for d in declarations)
        return edit(source, [(start, end, text), (at, at, decls)])

    found = []
    splits = _splits(body, opening, closing, indent)
    stages = _stages(body, inner, part.clean, part)
    for inner_lines, declaration, after in splits:
        found.append((FAMILY, emit(inner_lines, after, [declaration])))
    for inner_lines, declaration in stages:
        found.append((FAMILY, emit(inner_lines, [], [declaration])))
    # the pairs as one child: each helps the other's register order, and the stage alone is worse (60 against 10 here)
    for inner_lines, declaration, after in splits:
        for staged_lines, staged_declaration in _stages(body, inner_lines, part.clean, part):
            found.append((FAMILY, emit(staged_lines, after, [declaration, staged_declaration])))
    seen, unique = set(), []
    for family, text in found:
        if text != source and text not in seen:
            seen.add(text)
            unique.append((family, text))
    return unique
