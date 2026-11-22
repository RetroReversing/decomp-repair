"""Line layouts for legacy MIPS debug builds, where the assembler decides a jump's delay slot and a hazard nop.

KMC GCC 2.7.2 with `-g` writes a line entry (`.LN: .section .line ... .previous`) before the first instruction of
every new source line, and leaves unfilled branches to the assembler in `.set reorder` mode. Read from its output and
from the pinned `as` (hypothesis for other GNU MIPS assemblers of the same age):

* reorg never puts a load in a delay slot (mips.md: `dslot` is "yes" for type `load`), so an unconditional `j` whose
  slot holds the then-arm's `lw` was left unfilled by cc1 and filled by gas, which swaps the preceding instruction
  in. Gas does that only when no line entry sits between the load and the `j` (the label stops it) and the
  instruction before the load was not in a `.set noreorder` block (that is, a line entry precedes the load). The
  then-arm's statement therefore shares its physical line with `} else {`. When reorg can fill the jump from its
  target (the first instruction of the join), it does, and gas never sees an unfilled `j`; an independent assignment
  written just before the `if` and sunk past it changed which instruction the join begins with in the measured case.
* A section switch makes gas emit the HI/LO hazard nops it owes and forget the history; a plain label after it does
  not. `mflo; nop; nop; sra; nop; mult` is therefore a line entry after the `mflo` and another one between the `sra`
  and the `mult`: the multiply's operand was computed on a line of its own (`t = e >> 10;` then `d = t * v;`).

Measured on a 2,103-instruction N64 vehicle update (`gcc-2.7.2-kmc -O2 -g3`): the three edits together took the
judge from 870 to 0; each alone or any two scored 730, 2900 or 3570, so a one-step search cannot see them and this
family offers the combination as one child. Every child keeps the program's behaviour (a sink only moves a pure
assignment no arm or condition reads or writes); the judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILIES = ('debug_operand_line', 'debug_else_jump_layout', 'debug_assembler_layout')
LIMIT = 24
_TYPE = r'(?:(?:unsigned|signed|const)\s+)*(?:[us](?:8|16|32|64)|f32|f64|int|long|short|char|AddrWord)'
_PURE = re.compile(r'[\w\s()+\-*/%<>&|^~!?:]*')
_KEYWORDS = {'if', 'while', 'for', 'switch', 'return', 'sizeof', 'else', 'do'}


def _debug(flags):
    debug = [f for f in flags or () if re.fullmatch(r'-g(?:[0-3]|gdb[0-3]?)?', f)]
    return bool(debug) and debug[-1] not in {'-g0', '-ggdb0'}


def _indent(text, pos):
    start = text.rfind('\n', 0, pos)+1
    return re.match(r'[ \t]*', text[start:])[0]


def _starts_statement(clean, pos, opening):
    return clean[opening:pos].rstrip()[-1:] in (';', '{', '}')


def operand_lines(part, source):
    """`T d = (e) * v;` as `T d_operand = e;` and `T d = d_operand * v;` on its own line (also `/`, `%`)."""
    found = []
    names = set(re.findall(IDENT, part.clean))
    pattern = re.compile(rf'(?P<type>{_TYPE})\s+(?P<name>{IDENT})\s*=\s*\(')
    for hit in pattern.finditer(part.clean, part.opening+1, part.end):
        if not _starts_statement(part.clean, hit.start(), part.opening):
            continue
        stop = close(part.clean, hit.end()-1)
        tail = re.match(r'\s*(?P<op>[*/%])\s*(?P<rest>[^;{}]+);', part.clean[stop:]) if stop else None
        inner = part.clean[hit.end():stop-1] if stop else ''
        if not tail or not re.search(r'[-+*/%<>&|^]', inner) or '\n' in part.clean[hit.start():stop+tail.end()]:
            continue
        temp = hit['name']+'_operand'
        if temp in names:
            continue
        indent = _indent(part.clean, hit.start())
        text = (f"{hit['type']} {temp} = {source[hit.end():stop-1].strip()};\n{indent}"
                f"{hit['type']} {hit['name']} = {temp} {tail['op']} {source[stop+tail.start('rest'):stop+tail.end('rest')].strip()};")
        found.append((hit.start(), stop+tail.end(), text))
    return found


def _writes(text, ident):
    e = re.escape(ident)
    return re.search(rf'(?<![=!<>])\b{e}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|\+\+\s*{e}\b|--\s*{e}\b|\b{e}\s*(?:\+\+|--)|&\s*{e}\b', text)


def if_sites(part, source):
    """Each `if (c) { one statement; } else { ... }`: the edit joining `} else {` to the then-arm's line, and the
    edit sinking a pure assignment written just before the `if` to just after the `else` block (or None)."""
    sites = []
    for hit in re.finditer(r'\bif\s*\(', part.clean[:part.end]):
        if hit.start() <= part.opening or not _starts_statement(part.clean, hit.start(), part.opening):
            continue
        if re.search(r'\belse\s*$', part.clean[:hit.start()]):
            continue
        cond_end = close(part.clean, hit.end()-1)
        then = re.match(r'\s*{', part.clean[cond_end:]) if cond_end else None
        if not then:
            continue
        then_open = cond_end+then.end()-1
        then_end = close(part.clean, then_open, '{', '}')
        other = re.match(r'\s*else\s*{', part.clean[then_end:]) if then_end else None
        if not other:
            continue
        else_open = then_end+other.end()-1
        else_end = close(part.clean, else_open, '{', '}')
        body = part.clean[then_open+1:then_end-1]
        statement = re.fullmatch(r'\s*([^;{}]+;)(\s*)', body)
        if not else_end or not statement or '\n' not in statement[2]:
            continue
        join = (then_open+1+statement.end(1), then_end-1, ' ')
        sink = None
        # The statement just before the `if`: from the boundary before its `;` to that `;`.
        prior = part.clean[:hit.start()].rstrip()
        boundary = max(prior.rfind(c, 0, len(prior)-1) for c in ';{}') if prior.endswith(';') else -1
        before = (re.fullmatch(rf'(?P<lead>\s*)(?P<stmt>(?P<name>{IDENT})\s*=(?!=)\s*(?P<value>[^;{{}}]+);)',
                               part.clean[boundary+1:len(prior)]) if boundary > part.opening else None)
        if before:
            start = boundary+1+before.start('stmt')
            name, value = before['name'], before['value']
            region = part.clean[hit.start():else_end]
            idents = set(re.findall(IDENT, value))-{name}
            calls = {m[1] for m in re.finditer(rf'\b({IDENT})\s*\(', value)} - _KEYWORDS
            if (_PURE.fullmatch(value) and not calls and not re.search(rf'\b{re.escape(name)}\b', region)
                    and name not in idents and not any(_writes(region, ident) for ident in idents)
                    and not re.search(r'\b(?:goto|return|break|continue)\b|\w+\s*:(?!:)', region)):
                line_end = start+len(before['stmt'])
                gap = re.match(r'[ \t]*\n', part.clean[line_end:])
                cut_end = line_end+(gap.end() if gap else 0)
                cut_start = part.clean.rfind('\n', 0, start)+1
                if part.clean[cut_start:start].strip() == '':
                    stmt = source[start:line_end]
                    indent = _indent(part.clean, hit.start())
                    sink = [(cut_start, cut_end, ''), (else_end, else_end, f'\n{indent}{stmt}')]
        sites.append((join, sink))
    return sites


def variants(source, name, flags=(), header='', arch='', *, limit=LIMIT):
    if arch and arch != 'mips' or not _debug(flags):
        return []
    if re.search(r'\b__LINE__\b|^\s*#\s*(?:line\b|\d)', header+'\n'+source, re.M):
        return []
    part = view(source, name)
    if not part:
        return []
    splits = operand_lines(part, source)
    sites = if_sites(part, source)
    result, seen = [], {source}

    def add(family, edits):
        text = edit(source, edits)
        if text not in seen and (limit is None or len(result) < limit):
            seen.add(text)
            result.append((family, text))

    # The combination first: the measured match needed a sink, a join and an operand line at once.
    for join, sink in sites:
        if sink:
            for split in splits:
                add('debug_assembler_layout', [join, *sink, split])
    for join, sink in sites:
        if sink and splits:
            add('debug_assembler_layout', [join, *sink, *splits])
    for join, sink in sites:
        add('debug_else_jump_layout', [join, *(sink or ())])
    for split in splits:
        add('debug_operand_line', [split])
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'flags', 'header', 'arch'),
          'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
