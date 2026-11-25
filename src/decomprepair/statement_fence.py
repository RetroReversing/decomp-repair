"""One-shot `do { ... } while (0);` fences round straight-line statements: a run of initialisers together, a counter's
step, a statement several deep.

flow.c counts a reference once more for every loop it sits in, and `do { S } while (0);` is one loop more round `S`, at no
instruction or run-time cost: it adds one reference to every pseudo `S` names, and the allocator ranks pseudos by
`floor_log2 (refs) * refs / live length`. `local_weight_ladder` wraps the statements of one local against a rival, `loop_weight_set`
the steps of loop locals and `call_weight_ladder` the calls; two hand matches on SN/KMC GCC code needed the same
scaffolding round statements none of them offers (a counter's step in its own fence is `run_weight_scope`'s and
`loop_weight_scope`'s):
- two initialisers written together in ONE fence (`do { mask = 0; cm = 2; } while (0);`: fencing `cm = 2;` alone scored the
  same as nothing, the pair moved the weight of both);
- a statement that computes a value several statements later use, fenced four deep (`do { do { do { do { t = g * 2; }
  while (0); } while (0); } while (0); } while (0);`: depth is the weight, and each depth is a different priority).
The fences are scaffolding no developer wrote; polishing removes them once the match is recorded.

Children (`LIMIT` in all, the runs first): `fence_initialiser_run` (the first run of two or three consecutive constant
assignments of a block, as one fence), `fence_statement_deep` (an assignment of an arithmetic expression that reads a global or a field, no call, whose local is read twice or more after it, as a fence four
deep and as one two deep: the first two such statements). A statement that is already in a fence, a function with `volatile`,
`asm`, `goto` or a preprocessor line, and a run that holds a declaration are left alone. Proposals only; the byte judge
decides."""
import re

from .integer_repair_support import IDENT, edit, view
from .statement_across_call import _blocks, _has_call, _statements

FAMILY_RUN = 'fence_initialiser_run'
FAMILY_DEEP = 'fence_statement_deep'
FAMILIES = (FAMILY_RUN, FAMILY_DEEP)
LIMIT = 8
_LVALUE = rf'(?:\*\s*)?{IDENT}(?:\s*(?:->|\.)\s*{IDENT}|\s*\[[^\];{{}}]*\])*'
_CONSTANT = re.compile(rf'{_LVALUE}\s*=(?!=)\s*-?\s*(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d*)?[fFuU]*)\s*;')
_ARITHMETIC = re.compile(rf'{_LVALUE}\s*=(?!=)\s*[^;{{}}=]*[-+*/<>&|][^;{{}}=]*;')
_FENCE = re.compile(r'do\s*\{[^{}]*\}\s*while\s*\(\s*0\s*\)\s*;')


def _fence(text, depth, indent):
    inner = text
    for _ in range(depth):
        inner = f'do {{ {inner} }} while (0);'
    return inner


def _in_fence(clean, start, part_opening):
    """Whether the statement at `start` sits directly inside a `do { } while (0)` fence."""
    depth, at = 0, start
    for char in reversed(clean[part_opening:start]):
        at -= 1
        depth += {'}': 1, '{': -1}.get(char, 0)
        if depth < 0:
            if not re.search(r'\bdo\s*$', clean[part_opening:at].rstrip()):
                return False
            level = 0
            for close in range(at, len(clean)):
                level += {'{': 1, '}': -1}.get(clean[close], 0)
                if level == 0:
                    return bool(re.match(r'\s*while\s*\(\s*0\s*\)', clean[close + 1:]))
            return False
    return False


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    if re.search(r'\b(?:volatile|asm|__asm__|goto)\b|^\s*#', clean[part.opening:part.end], re.M):
        return []
    runs, deep = [], []
    for lo, hi in _blocks(clean, part.opening + 1, part.end):
        items = [item for item in _statements(clean, lo, hi) if item[2] == 'simple']
        # statements directly after one another in the source (compound statements split a run)
        everything = _statements(clean, lo, hi)
        index = 0
        while index < len(everything):
            start, end, kind = everything[index]
            text = clean[start:end].strip()
            if kind == 'simple' and _CONSTANT.fullmatch(text) and not _in_fence(clean, start, part.opening):
                last = index
                while (last + 1 < len(everything) and last - index < 2 and everything[last + 1][2] == 'simple'
                       and _CONSTANT.fullmatch(clean[everything[last + 1][0]:everything[last + 1][1]].strip())):
                    last += 1
                if last > index:
                    runs.append((start, everything[last][1]))
                index = last + 1
                continue
            index += 1
        for start, end, kind in items:
            text = clean[start:end].strip()
            if _in_fence(clean, start, part.opening) or _has_call(clean, start, end):
                continue
            if (_ARITHMETIC.fullmatch(text) and not _CONSTANT.fullmatch(text)
                  and re.search(r'\bD_\w+|->|\*\s*\(', text.partition('=')[2])
                  and len(re.findall(rf'(?<![\w.>]){re.escape(text.partition("=")[0].strip())}\b', clean[end:part.end])) >= 2):
                deep.append((start, end))
    out = []
    for start, end in runs[:2]:
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:])[0]
        body = source[start:end].strip().replace('\n' + indent, ' ')
        out.append((FAMILY_RUN, edit(source, [(start, end, _fence(re.sub(r'\s+', ' ', body), 1, indent))])))
    for start, end in deep[:2]:
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:])[0]
        for depth in (4, 2):
            out.append((FAMILY_DEEP, edit(source, [(start, end, _fence(source[start:end].strip(), depth, indent))])))
    return list(dict.fromkeys(item for item in out if item[1] != source))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
