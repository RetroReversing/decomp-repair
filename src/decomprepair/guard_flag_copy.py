"""A flag tested by an early return, read into a byte local just before the test.

    done = 0;                                unsigned char done_test;
    if (a < 0) { done = 1; }                 done = 0;
    if (b < 0) { done = 1; }          ->     if (a < 0) { done = 1; }
    if (done) {                              if (b < 0) { done = 1; }
        return;                              done_test = done;
    }                                        if (done_test) {
                                                 return;
                                             }

The target of such a test is a register copy followed by the branch (`addu $v0,$t0,$zero; bnez $v0`), which a branch on
the flag itself never has. A word-sized copy is merged back into the flag; a byte local keeps it, and for a value that is
only ever 0 or 1 the byte costs no instruction. Two N64 sprite drawers (KMC GCC 2.7.2 `-O1`, about 800 instructions,
clip a rectangle twice and give up if either side went negative) went from 350 to 125 with the copy at both guards.

Children (`guard_flag_copy`): every `if (V) return ...;` (also `V != 0`, braced or not) whose `V` is a local that is only
ever assigned `0`, `1` or one comparison, copied at all such guards at once, each into a local of its own, and then at
one guard at a time.
"""
import re

from .csource import _blank, find

FAMILY = 'guard_flag_copy'
FAMILIES = (FAMILY,)
LIMIT = 8
GUARD = re.compile(r'(?m)^(?P<indent>[ \t]*)if \((?P<v>[A-Za-z_]\w*)(?: != 0)?\)(?=[ \t\n]*\{?[ \t\n]*return\b[^;{}]*;)')
TRUTH = re.compile(r'[01]|[^;?=]*(?:[<>]=?|[=!]=)[^;?]*')
COMPARISON = re.compile(r'(?<![<>])(?:<=?|>=?)(?![<>])|[=!]=')


def _boolean(body, flag):
    """True when every write of the flag stores 0, 1 or a comparison, so a byte holds it unchanged."""
    if re.search(rf'(?:\+\+|--|&)\s*{flag}\b|\b{flag}\s*(?:\+\+|--|[-+*/%&|^]=|<<=|>>=)', body):
        return False
    writes = re.findall(rf'(?<![\w.>]){flag}\s*=(?!=)\s*([^;]*);', body)
    return bool(writes) and all(value.strip() in ('0', '1') or
                                (COMPARISON.search(value) and not re.search(r'[?&|+*]|(?<!-)-(?!>)', value))
                                for value in writes)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    body = clean[opening:span[1]]
    guards = []
    for found in GUARD.finditer(clean, opening, span[1]):
        flag = found['v']
        declared = re.search(rf'(?m)^(?P<indent>[ \t]+)(?:(?:unsigned|signed) )?[A-Za-z_]\w*[ \t]+{flag}(?: = [01])?;\n',
                             body)
        if declared and _boolean(body, flag):
            guards.append((found, flag, opening + declared.end(), declared['indent']))
    guards = guards[:LIMIT]

    def write(chosen):
        edits = []
        number = 0
        for found, flag, at, indent in chosen:
            number += 1
            copy = f'{flag}_test{number}'
            while re.search(rf'\b{copy}\b', clean):
                copy += '_'
            edits.append((at, at, f'{indent}unsigned char {copy};\n'))
            edits.append((found.start(), found.start(), f'{found["indent"]}{copy} = {flag};\n'))
            edits.append((found.start('v'), found.end('v'), copy))
        text = source
        for start, end, new in sorted(edits, key=lambda edit: (edit[0], edit[1]), reverse=True):
            text = text[:start] + new + text[end:]
        return FAMILY, text

    if not guards:
        return []
    result = [write(guards)]
    if len(guards) > 1:
        result += [write([guard]) for guard in guards]
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
