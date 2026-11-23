"""m2c's outermost backward `goto` loop, whose `goto`s sit deep inside the body, written as a real loop.

m2c writes a loop it cannot structure as a label and a backward `goto` (`loop_3: ... if (p != NULL) { ...
goto loop_3; }`). GCC 2.7.2's loop pass only treats a loop that the C states (`loop.c` works from the
`NOTE_INSN_LOOP_BEG`/`END` notes `expand_start_loop` emits): with a label and a `goto` it hoists nothing, so the
float zero the body compares against is loaded inside it, where the target loads it once before the loop (and
holds it in a saved register), and every register after it moves. `goto_backward_loop` structures the plain case,
where the `goto` ends the label's block; here the `goto`s are nested in later statements of that block.

The rewrite: the label becomes `for (;;) {`, each `goto L;` a `continue;`, and the loop closes with `break; }`
after the statement that holds the last `goto`. Only when no `goto L` sits inside another loop or a `switch` (the
`continue` would bind there) and no `break`/`continue` between the label and that statement belongs to the new
loop. On a 1337-instruction KMC GCC 2.7.2 collision sweep (`-G0 -mips3 -mgp32 -mfp32 -O2`) it took 7206 -> 7045
and gave the target's hoisted `mtc1 $zero` (the loop condition the function had, `while (p != NULL)`, is the
same program to the compiler: a `do`/`while` with it scored the same)."""
import re

from .integer_repair_support import edit, view

FAMILY = 'nested_goto_loop'
FAMILIES = (FAMILY,)
LIMIT = 4
_LABEL = re.compile(r'(?m)^[ \t]*([A-Za-z_]\w*)[ \t]*:(?!:)[ \t]*\n')
_DECL = re.compile(r'\s*(?:(?:unsigned|signed|const|struct|union|register)\s+)*[A-Za-z_]\w*[\s*]+[A-Za-z_]\w*\s*[;=\[]')
_LOOP = re.compile(r'\b(?:for|while|do|switch)\b')


def _enclosing(clean, begin, at):
    """Openings of the braces still open at `at`, counted from `begin` (the label's block)."""
    stack = []
    for pos in range(begin, at):
        if clean[pos] == '{':
            stack.append(pos)
        elif clean[pos] == '}' and stack:
            stack.pop()
    return stack


def _head(clean, opening):
    """The keyword that owns the `{` at `opening`: `if`, `for`, `while`, `switch`, `else`, `do`, or ''."""
    pos = opening - 1
    while pos >= 0 and clean[pos].isspace():
        pos -= 1
    if pos >= 0 and clean[pos] == ')':
        depth = 0
        while pos >= 0:
            depth += {')': 1, '(': -1}.get(clean[pos], 0)
            if depth == 0:
                break
            pos -= 1
        pos -= 1
        while pos >= 0 and clean[pos].isspace():
            pos -= 1
    word = re.search(r'([A-Za-z_]\w*)$', clean[max(0, pos - 16):pos + 1])
    return word[1] if word else ''


def _matching(clean, opening, limit):
    """Index just past the `}` that closes the `{` at `opening`."""
    depth = 0
    for pos in range(opening, limit):
        if clean[pos] == '{':
            depth += 1
        elif clean[pos] == '}':
            depth -= 1
            if depth == 0:
                return pos + 1
    return None


def rewrite(source, name, label, part):
    clean = part.clean
    hit = re.search(r'(?m)^[ \t]*' + re.escape(label) + r'[ \t]*:(?!:)[ \t]*\n', clean[part.opening:part.end])
    if not hit:
        return None
    start, stop = part.opening + hit.start(), part.opening + hit.end()
    if len(re.findall(r'\b' + re.escape(label) + r'\s*:(?!:)', clean[part.opening:part.end])) != 1:
        return None
    gotos = [m for m in re.finditer(r'\bgoto\s+' + re.escape(label) + r'\s*;', clean[part.opening:part.end])]
    gotos = [(part.opening + m.start(), part.opening + m.end()) for m in gotos]
    if not gotos or any(g < stop for g, _ in gotos):
        return None
    block = _enclosing(clean, part.opening, start)
    if not block:
        return None
    base = block[-1]
    # every goto inside the label's block, and the statement that holds the last one
    for g, _ in gotos:
        chain = _enclosing(clean, part.opening, g)
        if chain[:len(block)] != block:
            return None
        if any(_LOOP.search(_head(clean, opening)) for opening in chain[len(block):]):
            return None
    last = gotos[-1][0]
    chain = _enclosing(clean, part.opening, last)
    level = len(block)
    unwrap = []
    # a bare `{ }` (m2c's scope around a tail) that holds the last goto is opened, so the loop can end inside it
    while len(chain) > level and _head(clean, chain[level]) == '' and not _DECL.match(clean, chain[level] + 1):
        closing = _matching(clean, chain[level], part.end)
        if closing is None:
            return None
        unwrap += [(chain[level], chain[level] + 1, ''), (closing - 1, closing, '')]
        level += 1
    outer = chain[level] if len(chain) > level else None
    if outer is None:
        end = clean.index(';', last) + 1
    else:
        # the statement in the label's block that the outermost brace belongs to
        end = _matching(clean, outer, part.end)
        if end is None:
            return None
        while True:
            following = re.match(r'\s*else\b\s*', clean[end:])
            if not following:
                break
            nxt = end + following.end()
            if clean[nxt] == '{':
                inner = _matching(clean, nxt, part.end)
            elif clean.startswith('if', nxt):
                paren = clean.index('{', nxt)
                inner = _matching(clean, paren, part.end)
            else:
                inner = clean.index(';', nxt) + 1
            if inner is None:
                return None
            end = inner
    if end is None or base >= start:
        return None
    # break/continue in the body that would bind to the new loop
    body = clean[stop:end]
    for jump in re.finditer(r'\b(?:break|continue)\s*;', body):
        chain = _enclosing(clean, part.opening, stop + jump.start())
        if not any(_LOOP.search(_head(clean, opening)) for opening in chain[len(block):]):
            return None
    indent = re.match(r'[ \t]*', source[start:stop])[0]
    edits = [(start, stop, indent + 'for (;;)\n' + indent + '{\n')]
    edits += [(g, e, 'continue;') for g, e in gotos]
    edits.append((end, end, '\n' + indent + 'break;\n' + indent + '}'))
    edits += unwrap
    return edit(source, edits)


def variants(source, name):
    part = view(source, name)
    if not part or '#' in part.clean[part.opening:part.end]:
        return []
    out = []
    for hit in _LABEL.finditer(part.clean, part.opening + 1, part.end):
        label = hit[1]
        if label in ('default',):
            continue
        text = rewrite(source, name, label, part)
        if text and text != source and text not in out:
            out.append(text)
        if len(out) == LIMIT:
            break
    return [(FAMILY, text) for text in out]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 400}  # the registry: no caller wiring (registry.py)
