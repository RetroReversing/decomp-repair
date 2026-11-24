"""A zero store from a record's initialisation run moved ahead of the run's first loads.

An initialisation run that reads a field or two into locals and then stores constants into the rest,

    a = p->f_bf;  b = 0;  p->f90 = 100;  ...  p->f8c = 0;  ...  p->f5c = 0x4000AC44;  ...  p->fbe = a;

is one basic block for KMC GCC 2.7.2's first scheduler. In a 1315-instruction sound-sequence interpreter the target
loads the two fields between the `lui` and the `ori` of the large constant (`lui $a0; lbu; lw; ori`), while every order
of the run as m2c wrote it put the `ori` right after the `lui` (165 under -G0); one zero store written before the
loads (`p->f8c = 0;` first) gave the target's order (165 -> 105, a grid of every single-statement move found only that
store, at the three places before the loads). Hypothesis: a store through the same base ahead of the loads gives them
a memory dependence that changes their launch order against the split constant (sched.c, not traced insn by insn).

Children: each constant store of the run (a `*((T *) (((char *) base) + K)) = C;` statement) moved to just before
the run's first load into a local from the same base, one at a time. Proposals only; the judge decides."""
import re

FAMILIES = ('init_store_before_loads',)
FAMILY = FAMILIES[0]
LIMIT = 12

_STORE = re.compile(r'(?m)^[ \t]*\*\(\((?:u8|s8|u16|s16|u32|s32|void \*\*) \*\) \(\(\(char \*\) (\w+)\) \+ 0x[0-9A-Fa-f]+\)\) = '
                    r'(?:0|0U|0x[0-9A-Fa-f]+U?|\d+U?|NULL);[ \t]*\n')
_LOAD = r'(?m)^[ \t]*\w+ = \*\(\((?:u8|s8|u16|s16|u32|s32) \*\) \(\(\(char \*\) {base}\) \+ 0x[0-9A-Fa-f]+\)\);[ \t]*\n'


def variants(source, name=None, header=None):
    out = []
    stores = list(_STORE.finditer(source))
    for i, store in enumerate(stores):
        base = store[1]
        # the run: the store's neighbours, consecutive store lines with no blank line or brace between
        start = store.start()
        while True:
            prev = source.rfind('\n', 0, start - 1) + 1
            line = source[prev:start]
            if not line.strip() or '{' in line or '}' in line or 'if' in line or 'for' in line:
                break
            start = prev
        loads = list(re.finditer(_LOAD.format(base=re.escape(base)), source[start:store.start()]))
        if not loads:
            continue
        at = start + loads[0].start()
        text = source[:at] + store[0] + source[at:store.start()] + source[store.end():]
        if text != source:
            out.append((FAMILY, text))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
