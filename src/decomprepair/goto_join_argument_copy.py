"""A call's first argument copied into a local on every path that reaches its `goto` join, and the call made on the copy.

m2c writes a shared tail as a label every arm `goto`s (or falls into) and calls the function there with the argument
it already had: `block_N: f(obj, var_a1, var_a2);`, where `var_a1` and `var_a2` are assigned on every arm. A source
that gave the first argument the same treatment (`var_a0 = obj;` on each arm, `f(var_a0, ...)`) allocates the copy to
the argument register at each set: the `move $a0, obj` sits at the end of each arm, where the delay slot of the arm's
`j` takes it, and the join keeps only the call (hypothesis, read from the target's three `j` slots; `sched.c` and
`reorg.c` not re-read for it). cse folds a copy only inside one extended basic block, and a pseudo with several sets
on different paths is never folded back into `obj`.

Found on a 157-instruction KMC N64 effect spawner (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2
-fno-strength-reduce`): a three-arm switch whose arms set the second and third argument and jump to a shared call.
With the copy on all three paths the function went 225 -> 160 (the callee's parameter width and the debug statement
boundary then gave 100 and 0; those are the library's `callee_parameter_width` and `debug_statement_boundary`).
`arm_argument_copy_join` has the same idea for a `switch` of `break` arms; this is the goto spelling m2c writes.

Offered when a label that two or more `goto`s name (plus the path that falls into it) is followed by a call whose
first argument is a plain local or parameter: two children, the copy set beside the call's other arguments on every path (the first statement that sets one of
them) or just before every `goto` and before the label.
A candidate for the exact judge, never a verdict."""
import re

from .arm_argument_copy_join import _after_declarations
from .integer_repair_support import IDENT, edit, view

FAMILY = 'goto_join_argument_copy'
FAMILIES = (FAMILY,)
COPY = 'join_arg'
KEYWORDS = {'sizeof', 'switch', 'if', 'for', 'while', 'return', 'do', 'case', 'default', 'goto', 'break', 'continue',
            'else'}
LABEL = re.compile(rf'(?P<name>{IDENT})[ \t]*:(?!:)\s*(?P<callee>{IDENT})\s*\(\s*(?P<arg>{IDENT})\s*(?=[,)])')
JUMPS = re.compile(r'(?:^|[;{}])\s*(?:goto|return|break|continue)\b[^;{}]*;$')


def _declared_type(clean, part, arg):
    """The declared type of `arg` (a local on its own line, or a parameter), or None."""
    local = re.search(rf'(?m)^[ \t]*(?P<type>(?:{IDENT}[ \t]+)*{IDENT}[ \t]*\**)[ \t]*{re.escape(arg)}[ \t]*;',
                      clean[part.opening:part.end])
    if local and local['type'].split()[0] not in KEYWORDS:
        found = local['type']
    else:
        head = clean[:part.opening]
        signature = head[head.rfind('(') + 1:head.rfind(')')] if ')' in head else ''
        found = None
        for piece in signature.split(','):
            m = re.fullmatch(rf'\s*(?P<type>(?:{IDENT}\s+)*{IDENT}\s*\**)\s*{re.escape(arg)}\s*', piece)
            if m:
                found = m['type']
    if not found:
        return None
    base, stars = re.fullmatch(r'(.*?)\s*(\**)', found.strip(), re.S).groups()
    return re.sub(r'\s+', ' ', base) + (' ' + stars if stars else '')


NOT_LABELS = {'if', 'while', 'for', 'switch', 'return', 'else', 'do', 'goto', 'break', 'continue'}
LABELISH = re.compile(rf'(?<![\w.>])(?:case\b[^:;{{}}]*|default|{IDENT})[ \t]*:(?!:)')


def _insertion(clean, part, site, others):
    """Where the copy goes for the path ending at `site`: ahead of the first statement of the path that sets one of the
    call's other arguments (so the copy is set beside them), or None."""
    start = part.opening + 1
    for m in LABELISH.finditer(clean, start, site):
        if m.group().split(':')[0].split()[0] not in NOT_LABELS:
            start = m.end()
    for m in re.finditer(rf'(?<![\w.>])(?P<lhs>{IDENT})\s*=(?!=)', clean[start:site]):
        if m['lhs'] in others:
            return start + m.start('lhs')
    return None


def _place(clean, at, arg):
    line = clean.rfind('\n', 0, at) + 1
    lead = clean[line:at]
    return f'{COPY} = {arg};\n{lead}' if not lead.strip() else f'{COPY} = {arg}; '


def variants(source, name):
    part = view(source, name)
    if not part or re.search(rf'\b{COPY}\b', source):
        return []
    clean = part.clean
    for label in LABEL.finditer(clean, part.opening, part.end):
        label_name, callee, arg = label['name'], label['callee'], label['arg']
        if label_name in KEYWORDS or callee in KEYWORDS or arg in KEYWORDS:
            continue
        before = clean[part.opening + 1:label.start()].rstrip()
        if before and before[-1] not in ';{}':
            continue  # `case 1:` or `else` before it: not a plain statement label
        gotos = list(re.finditer(rf'\bgoto\s+{re.escape(label_name)}\s*;', clean[part.opening:part.end]))
        if len(gotos) < 2:
            continue
        kind = _declared_type(clean, part, arg)
        if not kind:
            continue
        call_end = clean.find(';', label.end())
        others = set(re.findall(IDENT, clean[label.end('arg'):call_end])) - KEYWORDS
        sites = []
        for g in gotos:
            at = part.opening + g.start()
            prev = clean[:at].rstrip()
            if not prev or prev[-1] not in ';{}':
                sites = None  # `if (c) goto L;`: a statement inserted here would change the branch
                break
            sites.append(at)
        if sites is None:
            continue
        if not JUMPS.search(before) or before.endswith('}'):
            sites.append(label.start())
        found = []
        for beside in (True, False):
            edits = []
            for site in sites:
                at = site
                if beside:
                    first = _insertion(clean, part, site, others)
                    at = first if first is not None else site
                edits.append((at, at, _place(clean, at, arg)))
            edits.append((label.start('arg'), label.end('arg'), COPY))
            at = _after_declarations(clean, part)
            edits.append((at, at, f'    {kind}{"" if kind.endswith("*") else " "}{COPY};\n'))
            text = edit(source, sorted(edits))
            if text != source and text not in [t for _, t in found]:
                found.append((FAMILY, text))
        if found:
            return found
    return []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 80}  # the registry: no caller wiring (registry.py)
