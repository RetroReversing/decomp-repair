"""A local that holds a symbol's address or a constant, read before the draft assigns it, assigned at the function's entry.

m2c writes a pointer that stands for `&D_xxxx` (or for `&D_xxxx - 4` bytes, an address before the symbol) as a
local it reads in one statement and assigns a few lines later: `temp = base - 1; base = &D_xxxx;`. The compiler
reads an uninitialised variable, so the draft is wrong C, and where the assignment goes decides what the code looks
like. Placed next to its read it is folded by cse into `lui; addiu %lo(D_xxxx-4)` (a score of 605 against 546 on a
180-instruction N64 function, `gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`). Placed at the function's entry, before
every label, cse cannot know the value inside the loop, the loop pass hoists the `base - 1` as an invariant of the
pseudo, and reload substitutes the constant it is equivalent to at the use: the target's three instructions
`lui; addiu; addiu -4` and `lui; addiu` for each later use of the address. The same entry placement is valid C, which
the read-before-assign draft was not.

For each local assigned exactly once, by a whole statement `name = &symbol;`, `name = <number>;` or `name = <parameter>;`,
whose first mention in the body is a read that comes before that statement, two candidates are offered: the assignment
moved to the first statement of the body, after the declarations, and the assignment moved to just before the
statement that reads it. A candidate for the exact judge, never a verdict."""
import re

from .integer_repair_support import IDENT, edit, view

FAMILIES = ('entry_base_init',)
LIMIT = 8
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'
RHS = rf'(?:&\s*{IDENT}|{NUMBER}|{IDENT})'
DECLARATION = re.compile(r'[ \t]*(?:volatile\s+)?[A-Za-z_][\w \t*]*[\w\]](?:\s*\[[^\]]*\])?\s*;[ \t]*')


def _entry(clean, start, end):
    """Index of the first line after the declarations that open the body."""
    at = clean.find('\n', start)
    if at < 0:
        return end
    entry = at+1
    for line in clean[entry:end].split('\n'):
        if line.strip() and not (DECLARATION.fullmatch(line) and '=' not in line and '(' not in line):
            break
        entry += len(line)+1
    return min(entry, end)


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean, opening, end = part.clean, part.opening, part.end
    entry = _entry(clean, opening+1, end-1)
    signature = clean[:opening]
    params = set(re.findall(rf'({IDENT})\s*(?:,|\))', signature[signature.rfind('('):]))
    out = []
    for assign in re.finditer(rf'(?m)^([ \t]*)({IDENT})\s*=\s*({RHS})\s*;[ \t]*\n', clean[:end-1]):
        if assign.start() < entry:
            continue
        var, value = assign[2], assign[3]
        if value.isidentifier() and value not in params:
            continue
        mentions = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(var)}\b', clean[entry:end-1])]
        sets = [m for m in mentions if re.match(r'\s*=(?!=)', clean[entry+m.end():])]
        if not mentions or len(sets) != 1 or entry+sets[0].start() != assign.start(2):
            continue
        first = entry+mentions[0].start()
        if first >= assign.start():
            continue
        if value.startswith('&') and re.search(rf'&\s*{re.escape(var)}\b', clean[entry:end]):
            continue
        statement = source[assign.start(2):assign.end()].strip()
        line = clean.rfind('\n', 0, first)+1
        indent = re.match(r'[ \t]*', clean[line:first])[0]
        gap = re.match(r'[ \t]*', clean[entry:])[0] or '  '
        for target, shown in ((entry, gap+statement+'\n'), (line, indent+statement+'\n')):
            out.append(edit(source, [(assign.start(), assign.end(), ''), (target, target, shown)]))
    result = []
    for text in out:
        if text != source and text not in result:
            result.append(text)
    return [(FAMILIES[0], c) for c in result[:LIMIT]]
