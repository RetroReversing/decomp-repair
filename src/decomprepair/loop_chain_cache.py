"""A pointer chain read in a loop's guard, body and test, kept in one local and read again at the loop's end.

m2c writes `*(s32 *)((char *)*(s32 **)((char *)arg1 + 0x24) + 4)` wherever the game's code had a value: in a loop whose
guard, body and test all name the same chain (`arg1->list->count > 0`, `list->first + off`, `i < list->count`) the
game read the chain once before the guard and once more at the bottom of each pass, and used the register in between:
`lw $a0,0x24($s3); lhu $v0,4($a0); ... loop: lw $a0,0($a0) ... jal; lw $a0,0x24($s3); lhu $v0,4($a0); bnez`. Written with
the chain in every place gcc 2.7.2 re-reads it at each (a load, and the register pressure of the base). The first loop of an
874-instruction KMC N64 object spawner (`-G0 -mips3 -mgp32 -mfp32 -O2`) was written the cached way and its twin the other
way: caching the twin took the saved best 1551 -> 1291 (the exact judge, also the app's `compile_and_diff`; its instruction
count then equalled the target's). The reading is from the target's own loads; the judge decides.

`variants` takes a `do { BODY } while (COND);` whose test names a chain `*((T **) (((char *) P) + K))` (a pointer read from
a plain variable's field) that the body also names, P assigned nowhere in the loop, and writes
`local = CHAIN;` before the `if` guard that holds the loop (or before the loop), the chain replaced by `local` in the guard,
the body and the test, and `local = CHAIN;` again as the last statement of the body. The local is a new `T *` declared at
the top of the function. One child per loop, at most `LIMIT`."""
import re

from .integer_repair_support import IDENT, edit, view
from .run_weight_scope import _match

FAMILY = 'loop_chain_cache'
FAMILIES = (FAMILY,)
LIMIT = 6
_CHAIN = re.compile(rf'\*\(\((?P<type>(?:unsigned\s+)?{IDENT}(?:\s*\*)*)\s*\*\*\)\s*\(\(\(char\s*\*\)\s*(?P<ptr>{IDENT})\)\s*\+\s*'
                    rf'(?P<offset>0x[0-9A-Fa-f]+|\d+)\)\)')
_DO = re.compile(r'\bdo\s*{')
_GUARD = re.compile(r'\bif\s*\(')


def _loops(clean, start, end):
    """[(do_start, body_open, body_close, cond_open, cond_close, loop_end)] of every do-while in clean[start:end]."""
    found = []
    for hit in _DO.finditer(clean, start, end):
        body_open = hit.end() - 1
        body_close = _match(clean, body_open, '{', '}')
        loop = re.compile(r'\s*while\s*\(').match(clean, body_close) if body_close > 0 else None
        if not loop:
            continue
        cond_open = loop.end() - 1
        cond_close = _match(clean, cond_open, '(', ')')
        tail = re.compile(r'\s*;').match(clean, cond_close) if cond_close > 0 else None
        if tail:
            found.append((hit.start(), body_open, body_close, cond_open, cond_close, tail.end()))
    return found


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile|setjmp|longjmp)\b|^\s*#', part.clean[:part.end], re.M):
        return []
    clean = part.clean
    result = []
    for do_start, body_open, body_close, cond_open, cond_close, loop_end in _loops(clean, part.opening + 1, part.end):
        condition = clean[cond_open:cond_close]
        body = clean[body_open:body_close]
        for chain in {m[0]: m for m in _CHAIN.finditer(condition)}.values():
            if chain[0] not in body or re.search(rf'(?<![\w.>]){re.escape(chain["ptr"])}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)',
                                                    clean[body_open:cond_close]):
                continue
            # the `if` guard that holds the loop and names the chain in its test, else the loop itself
            at, guard_end = do_start, None
            for guard in _GUARD.finditer(clean, part.opening + 1, do_start):
                test_close = _match(clean, guard.end() - 1, '(', ')')
                block = re.compile(r'\s*{').match(clean, test_close) if test_close > 0 else None
                if block and chain[0] in clean[guard.end():test_close]:
                    block_close = _match(clean, block.end() - 1, '{', '}')
                    if block_close >= loop_end:
                        at, guard_end = guard.start(), test_close
            local = '__repair_chain_' + re.sub(r'\W', '_', f'{chain["ptr"]}_{chain["offset"]}')
            if re.search(rf'\b{local}\b', source):
                continue
            kind = ' '.join(chain['type'].split())
            changes = [(part.opening + 1, part.opening + 1, f'\n  {kind} *{local};')]
            changes.append((at, at, f'{local} = {chain[0]};\n{clean[:at][clean[:at].rfind(chr(10)) + 1:]}'))
            spans = [(body_open, body_close), (cond_open, cond_close)]
            if guard_end:
                spans.append((guard.end(), guard_end))
            for lo, hi in spans:
                for hit in re.finditer(re.escape(chain[0]), clean[lo:hi]):
                    changes.append((lo + hit.start(), lo + hit.end(), local))
            changes.append((body_close - 1, body_close - 1, f'{local} = {chain[0]};\n'))
            result.append((FAMILY, edit(source, changes)))
            if len(result) >= LIMIT:
                return result
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # the registry: no caller wiring (registry.py)
