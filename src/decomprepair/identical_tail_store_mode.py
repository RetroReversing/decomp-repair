"""Two arms that end in the same float-zero store and jump to one label: the final jump pass merges their tails.

A state machine whose arms end `((T *) G)->f = 0.0f; goto block_63;` has the same last insns in each of them
(`lw $v0,G; li $a0,0x12; sw $zero,0x12c($v0); j block_63`), and the last jump pass (`jump_optimize`'s cross-jumping)
merges them into one copy, which is shorter than the target, where both arms keep their own. cross-jumping compares
the insns' patterns, which include the mode: a float-zero store is `(set (mem:SF ..) (const_double 0))` and an integer
zero store is `(set (mem:SI ..) (const_int 0))`, assembled to the same `sw $zero`, so storing one arm's zero through an
integer view keeps the tails apart at no cost in bytes. A `do { call(); } while (0);` fence an earlier search put
before the store kept the tails apart another way (its loop note stops the first scheduler from moving the `li` above
the volatile load, and puts the `li` into the call's delay slot): with the integer view the fence is not needed, and
the arm needs both changes at once (349 instructions: 60 -> 0; the fence alone removed: 650; the integer view alone: 60).

What is read: two or more statements `LHS = 0.0f;` (or `0.0`) each followed directly by `goto LABEL;` for the same label
and the same `LHS` text. `variants` gives, labelled `identical_tail_store_mode`, for each such statement:

  the store written `*(s32 *)&LHS = 0;`;
  that, with every `do { ... } while (0);` between the arm's label (or the statement before it) and the store
  unwrapped (only when the arm has one).

The program stores the same bit pattern; only the mode of the store differs.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'identical_tail_store_mode'
FAMILIES = (FAMILY,)
LIMIT = 24

STORE_GOTO = re.compile(r'(?<=[;{}])(?P<lead>\s*)(?P<lhs>[^;{}=]+?)\s*=\s*(?P<zero>0\.0f?)\s*;(?P<mid>\s*)goto\s+(?P<label>\w+)\s*;')
LABELS = re.compile(r'(?m)(?<![\w?:])(?:case\b[^:;{}\n]*|default|[A-Za-z_]\w*)[ \t]*:(?!:)(?=[ \t]*(?:\n|;|\w|\}))')
FENCE = re.compile(r'\bdo\s*\{(?P<body>[^{}]*)\}\s*while\s*\(\s*0\s*\)\s*;')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    groups = {}
    for m in STORE_GOTO.finditer(clean, opening, end):
        lhs = re.sub(r'\s+', ' ', m.group('lhs')).strip()
        if '(' in lhs and '->' not in lhs and '[' not in lhs:
            continue
        groups.setdefault((lhs, m.group('label')), []).append(m)
    result = []

    def emit(text):
        if text != source and text not in [t for _, t in result] and len(result) < LIMIT:
            result.append((FAMILY, text))

    for (lhs, _), found in groups.items():
        if len(found) < 2:
            continue
        for m in found:
            store = m.start('lhs')
            tail = m.end('zero') + 1  # past the `;`
            view = f'*(s32 *)&{m.group("lhs").strip()} = 0;'
            plain = source[:store] + view + source[tail:]
            emit(plain)
            before = [x for x in LABELS.finditer(clean, opening, store)]
            seg = before[-1].end() if before else opening + 1
            fences = list(FENCE.finditer(clean, seg, store))
            if fences:
                text = source[:store] + view + source[tail:]
                for f in reversed(fences):
                    text = text[:f.start()] + source[f.start('body'):f.end('body')].strip() + text[f.end():]
                emit(text)
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 80}
