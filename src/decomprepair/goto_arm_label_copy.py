"""goto_arm_label_copy: the run behind a label at the head of an `if` arm, copied in place of each `goto` to it.

m2c writes a shared block the way the machine code reads it, as one labelled arm that a sibling case jumps into:

    case 0: if (draw) goto draw_box;  ...
    case 1: if (draw) {
    draw_box:   w = f(obj) * 12 & 0xFC;  g(a, b, w);  ...  break;
            }

A KMC-compiled N64 menu function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`, 117 instructions) sat at 120 with one
difference: the three argument setups of `g` came in the wrong order (`lhu; lbu` ahead of the `sll; addu; sll` that
the target has first). Writing the block in both cases, so the call is two call sites that cross-jumping merges again
after register allocation, made it exact (120 -> 0): that is the whole edit.

Why (sched.c's `birthing_insn_p` and `adjust_priority` read, `-dS` ready lists confirm): the first scheduler works
backwards and an insn that makes a register live, `reg_n_sets[regno] == 1`, gets the launch priority and is picked
as soon as it is ready. `reg_n_sets` of a HARD register counts every set in the whole function, so the move into
`$a2` for a third argument is a birth whenever this is the only call in the function with three arguments, and is
placed right before the call ahead of the loads of the other two. With two call sites `$a2` is set twice, the insn
is not a birth, and the loads' own priorities decide, which is what the target shows. (Hypothesis for the general
case: the same holds for any argument or result register that one call site alone uses.) The original macro-written
source had the block twice; one label makes it one site.

The run is what follows the label up to the end of its block, which must end in a jump (`break;`, `return`, `goto`,
`continue`) so the copy needs no landing; no labels, declarations, `case`s or inner loops in it, and when it ends in
`break;`/`continue;` the `goto` has to sit in the same innermost switch or loop as the label's block. Every outside
`goto L;` is replaced at once (the label, now unused, goes), and when there are several, each alone too. A proposal;
the judge decides."""
import re

from .join_tail_arm_split_repairs import _blocks, _body, _cut, _gotos, _label

FAMILY = 'goto_arm_label_copy'
FAMILIES = (FAMILY,)
LIMIT = 6
RUN_LIMIT = 40

IDENT = r'[A-Za-z_]\w*'
_JUMP_END = re.compile(r'(?:break|continue|return\b[^;]*|goto\s+\w+)\s*;')
_BAD_RUN = re.compile(rf'\b(?:case|default|while|for|do|switch)\b|(?:^|[;{{}}])\s*{IDENT}\s*:(?!:)')
_DECL = re.compile(rf'(?:const\s+|volatile\s+|unsigned\s+|signed\s+|struct\s+)*{IDENT}\s+\**\s*{IDENT}\s*(?:=|;|\[)')


def _breakable(clean, pos):
    """The `{` of the innermost switch or loop body around `pos`, or None."""
    depth = 0
    i = pos - 1
    while i >= 0:
        c = clean[i]
        if c == '}':
            depth += 1
        elif c == '{':
            if depth == 0:
                head = clean[:i].rstrip()
                if head.endswith('do'):
                    return i
                if head.endswith(')'):
                    level, j = 0, len(head) - 1
                    while j >= 0:
                        if head[j] == ')':
                            level += 1
                        elif head[j] == '(':
                            level -= 1
                            if level == 0:
                                break
                        j -= 1
                    if j > 0 and re.search(r'\b(?:switch|while|for)\s*$', head[:j]):
                        return i
            else:
                depth -= 1
        i -= 1
    return None


def _sites(source, name):
    """(label, label's block start, run text, jumps) for each label at the head of a block whose run ends in a jump."""
    part, end, clean = _body(source, name)
    if not part:
        return []
    blocks = _blocks(clean, part.opening + 1, end - 1)
    if not blocks:
        return []
    out = []
    for lo, hi, items in blocks[1:]:
        if len(items) < 2:
            continue
        found = _label(clean, *items[0])
        if not found:
            continue
        run = items[1:]
        text = clean[run[0][0]:run[-1][1]]
        if (len(run) > RUN_LIMIT or _BAD_RUN.search(text) or any(_DECL.match(clean[a:b]) for a, b in run)
                or not _JUMP_END.fullmatch(clean[run[-1][0]:run[-1][1]])):
            continue
        jumps = [m for m in _gotos(clean, part, found) if not run[0][0] <= part.opening + m.start() < run[-1][1]]
        if not jumps:
            continue
        if re.search(r'\b(?:break|continue)\b', text):
            owner = _breakable(clean, items[0][0])
            jumps = [m for m in jumps if _breakable(clean, part.opening + m.start()) == owner]
            if not jumps:
                continue
        out.append((found, items[0], run, jumps))
    return out


def _copy(source, name, label, item, run, jumps, all_jumps):
    part, end, clean = _body(source, name)
    run_text = source[run[0][0]:run[-1][1]]
    first_line = source.rfind('\n', 0, run[0][0]) + 1
    was = re.match(r'[ \t]*', source[first_line:])[0]
    edits = []
    for jump in jumps:
        at, stop = part.opening + jump.start(), part.opening + jump.end()
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, at) + 1:])[0]
        rows = run_text.strip().split('\n')
        body = '\n'.join([rows[0]] + [indent + '  ' + row[len(was):] if row.startswith(was) and row.strip() else row
                                      for row in rows[1:]])
        prefix = clean[:at].rstrip()
        braced = prefix[-1:] == ')' or prefix.endswith('else')
        edits.append((at, stop, '{\n' + indent + '  ' + body + '\n' + indent + '}' if braced else body))
    if all_jumps:
        edits.append(_cut(source, item[0], item[1]))  # nothing jumps to the label any more
    for start, stop, replacement in sorted(edits, key=lambda e: e[0], reverse=True):
        source = source[:start] + replacement + source[stop:]
    return source


def variants(source, name):
    """The copy for every `goto` of a label at once, then for each `goto` alone when there are several."""
    out = []
    for label, item, run, jumps in _sites(source, name):
        part, _, clean = _body(source, name)
        every = len(_gotos(clean, part, label))
        text = _copy(source, name, label, item, run, jumps, len(jumps) == every)
        if text != source:
            out.append((FAMILY, text))
        if len(jumps) > 1:
            for jump in jumps:
                text = _copy(source, name, label, item, run, [jump], False)
                if text != source and (FAMILY, text) not in out:
                    out.append((FAMILY, text))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 96}  # the registry: no caller wiring (registry.py)
