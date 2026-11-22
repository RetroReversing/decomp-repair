"""Give a sentinel literal compared with `==`/`!=` in several places a local of its own.

GCC 2.7 on MIPS has no compare-with-immediate for `beq`/`bne`, so every `x == -1` needs the constant in a register.
cse shares one register for the constant across the compares it can see (a taken branch into an arm, a call in
between: pseudos survive calls), and that shared pseudo is live from the first compare to the last, so global
allocation gives it a callee-saved register that the target spent elsewhere (a 10th pseudo in 9 saved registers
spilled the lowest-priority loop variable). A constant held in a *local* that is set once at entry is the same pseudo
with a REG_EQUIV note: if it loses the allocation it is not spilled but rematerialised before each compare
(`addiu $t1,$zero,-1` right before the `bne`), which is what the target has. Two locals keep jump threading from
merging two compares of one value (the second compare of an if-chain stayed a real compare in the target).

Measured (one controlled function, KMC GCC 2.7.2 `-O2`): a PS2-free N64 voice-allocation function went 3312 -> 2965
with one local (frame back to its size), and the compare after a `||` chain stayed a compare (not a dead `bne v0,v0`)
only with a different local for each of the two compares. A hypothesis about the mechanism (REG_EQUIV rematerialisation
in reload.c) is from reading the compiler; the scores are the evidence."""
import re

from .integer_repair_support import NUMBER, edit, view

FAMILIES = ('sentinel_constant_local', 'sentinel_constant_split')
SHARED, SPLIT = FAMILIES
LIMIT = 12
LITERAL = rf'(?:\(\s*-\s*{NUMBER}\s*\)|-\s*{NUMBER}|{NUMBER})'
COMPARE = re.compile(rf'(?P<op>==|!=)\s*(?P<lit>{LITERAL})(?![\w.])|(?<![\w.)])(?P<lit2>{LITERAL})\s*(?P<op2>==|!=)')


def _value(text):
    text = re.sub(r'[()\s]', '', text).rstrip('uUlL')
    negative = text.startswith('-')
    digits = text.lstrip('-')
    number = int(digits, 16 if digits[:2].lower() == '0x' else 10)
    return -number if negative else number


def _sites(part):
    """(literal start, literal end, value) of each `x == C` / `x != C` against a literal the MIPS compare cannot encode."""
    found = []
    for match in COMPARE.finditer(part.body):
        group = 'lit' if match['lit'] is not None else 'lit2'
        value = _value(match[group])
        if value == 0:
            continue
        base = part.opening + 1
        found.append((base + match.start(group), base + match.end(group), value))
    return found


def _fresh(source, stem):
    index = 0
    while re.search(rf'\b{stem}{index}\b', source):
        index += 1
    return f'{stem}{index}'


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    sites = _sites(part)
    by_value = {}
    for site in sites:
        by_value.setdefault(site[2], []).append(site)
    result = []
    for value, group in sorted(by_value.items(), key=lambda item: -len(item[1])):
        if len(group) < 2:
            continue
        stem = 'sentinel_neg' if value < 0 else 'sentinel_const'
        local = _fresh(source, stem)
        declaration = f'\n  s32 {local} = {value};'
        opening = part.opening + 1
        # a declaration is only legal before the first statement: the new one goes first in the block.
        result.append((SHARED, edit(source, [(opening, opening, declaration)] + [(a, b, local) for a, b, _ in group])))
        # two locals: one compare apart from the rest, for each compare (its own pseudo cannot be threaded or shared)
        other = _fresh(source + declaration, stem)
        for index in range(len(group)):
            if len(result) >= LIMIT:
                return result
            edits = [(opening, opening, declaration + f'\n  s32 {other} = {value};')]
            edits += [(a, b, other if i == index else local) for i, (a, b, _) in enumerate(group)]
            result.append((SPLIT, edit(source, edits)))
    return result[:LIMIT]
