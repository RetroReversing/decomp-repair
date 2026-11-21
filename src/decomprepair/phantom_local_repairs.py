"""An unused 64-bit local at the start of a block, for a near miss that is only a register swap (GCC 2.7.2).

A `long long` local that nothing reads still leaves a zero-size CLOBBER of its register pair in the insn stream.
Optimisation drops the move that sets it, but the CLOBBER stays through scheduling and local allocation, where it
does two things: it is one more insn in the basic block, so the instruction order the first scheduling pass picks can
change (a shift that was hoisted above an add now sits between the add and its store), and every other value born
in the block is numbered one insn later. A register tie that the allocator breaks by length of life
(`floor_log2 (refs) * refs / (death - birth)`) can then come out the other way round. That is how a float constant
and a reloaded float, equal in priority in one case of a large switch, swapped registers (`$f0`/`$f2`) and cost four
rows of an otherwise exact 2,400-instruction function; one unused `long long` at the top of that case fixed it.

The meaning does not change: the local is never read and its initialiser is a plain integer. Which block needs it is
a guess, so `variants` gives one proposal per block start (each `case` label, each `{` that opens an if, loop or
function body), nearest to `near` (a 1-based source line, e.g. the first differing instruction's C line) first, and
for both signednesses of the local (they leave the same CLOBBER, but a different compare/extension in the
initialiser decides whether the move survives).
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'phantom_wide_local'
FAMILIES = (FAMILY,)

NAME = 'phantom_wide'
LIMIT = 48
INTEGER = re.compile(r'(?:(?:unsigned|signed|const|volatile|register)\s+)*(?:u8|s8|u16|s16|u32|s32|int|short|char|long|unsigned|signed)\b')
LABEL = re.compile(r'(?m)^[ \t]*(?:case\b[^:;{}\n]*|default)[ \t]*:(?!:)')
DECLARATION = re.compile(r'(?m)^[ \t]*(?P<type>(?:(?:unsigned|signed|const|volatile|register)\s+)*[A-Za-z_]\w*)[ \t]+'
                         r'(?P<name>[A-Za-z_]\w*)[ \t]*(?:=[^;\n]*)?;[ \t]*$')


LEADING = re.compile(r'[ \t]*(?!(?:return|goto|break|continue|else|case|default|sizeof|do|if|for|while|switch)\b)'
                     r'(?:(?:unsigned|signed|const|volatile|register|static|struct|union|enum)\s+)*[A-Za-z_]\w*[ \t]+\**[ \t]*'
                     r'[A-Za-z_]\w*(?:\[[^\]\n]*\])*[ \t]*(?:[=,][^;\n]*)?;[ \t]*')


def _after_declarations(clean, pos, end):
    """`pos` moved past the declaration lines that start a block (a statement may not come before them in C89)."""
    if clean[pos:clean.find('\n', pos) if clean.find('\n', pos) >= 0 else end].strip():
        return pos  # something follows on the opening line
    at = pos
    while at < end:
        line_end = clean.find('\n', at + 1)
        line_end = end if line_end < 0 or line_end > end else line_end
        line = clean[at:line_end].lstrip('\n')
        if line.strip() == '' or LEADING.fullmatch(line):
            at = line_end
        else:
            break
        if at >= end:
            break
    return at


def _integer_names(source, clean, opening, name_span):
    """Integer parameters and locals of the function, in declaration order: any of them will do as the initialiser."""
    head = clean[name_span[0]:opening]
    names = []
    params = head[head.find('(') + 1:head.rfind(')')] if '(' in head and ')' in head else ''
    for part in params.split(','):
        m = re.match(r'\s*(' + INTEGER.pattern + r')\s+([A-Za-z_]\w*)\s*$', part)
        if m:
            names.append(m.group(2))
    end = close(clean, opening, '{', '}') or len(clean)
    for m in DECLARATION.finditer(clean, opening + 1, end):
        if INTEGER.fullmatch(m['type'].strip()) and m['name'] not in names:
            names.append(m['name'])
    return names


def _sites(clean, opening, end):
    """(insert position, indent) of every place a statement may begin a block, in source order."""
    sites = []
    sites.append((_after_declarations(clean, opening + 1, end), '    '))
    for m in LABEL.finditer(clean, opening + 1, end):
        rest = clean[m.end():end]
        if re.match(r'\s*(?:case\b|default\b)', rest):
            continue  # stacked labels: one block start is enough
        indent = re.match(r'[ \t]*', m.group()).group()
        sites.append((m.end(), indent + '    '))
    for m in re.finditer(r'\{', clean[opening + 1:end]):
        at = opening + 1 + m.start()
        before = clean[:at].rstrip()
        if not (before.endswith(')') or re.search(r'\b(?:else|do)$', before)):
            continue  # an initialiser or a struct body
        depth, k = 0, len(before) - 1
        if before.endswith(')'):
            while k >= 0:  # the controlling `( ... )`: a switch body takes no statement before its first label
                depth += before[k] == ')'
                depth -= before[k] == '('
                if depth == 0:
                    break
                k -= 1
            if re.search(r'\bswitch\s*$', before[:k]):
                continue
        line_start = clean.rfind('\n', 0, at) + 1
        sites.append((_after_declarations(clean, at + 1, end), re.match(r'[ \t]*', clean[line_start:at]).group() + '    '))
    return sorted(set(sites))


def variants(source, name, near=None, limit=LIMIT):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    if len(re.findall(r'\b' + NAME + r'\d*\b', clean[opening:end])) >= 2:
        return []  # two already: chain them in the search, not here
    taken = len(re.findall(r'\b' + NAME + r'\d*\b', clean[opening:end]))
    local = NAME + (str(taken + 1) if taken else '')
    names = _integer_names(source, clean, opening, span)
    start = names[0] if names else '0'
    sites = _sites(clean, opening, end)
    if near is not None:
        line = lambda pos: source.count('\n', 0, pos) + 1  # noqa: E731
        sites.sort(key=lambda s: (abs(line(s[0]) - near), s[0]))
    result = []
    for pos, indent in sites:
        for kind in ('long long', 'unsigned long long'):
            if len(result) >= limit:
                return result
            block = f'{{ {kind} {local} = {start}; }}'
            line_end = source.find('\n', pos)
            if source[pos:line_end if line_end >= 0 else len(source)].strip():
                text = source[:pos] + ' ' + block + source[pos:]  # something follows on the line: stay on it
            else:
                text = source[:pos] + '\n' + indent + block + source[pos:]
            if text != source:
                result.append((FAMILY, text))
    return result
