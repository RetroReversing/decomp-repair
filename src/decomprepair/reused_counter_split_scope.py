"""A loop counter's name reused by an earlier value: split it and weight the counter's start in one step.

m2c names one variable for every use of a saved register, so the byte offset that a loop steps by a structure's size
(`var_s6 += 0xC`) was also the name of a value computed in a switch arm above it (`var_s6 = (n * 3) + 2;`). The compiler
saw one pseudo with the uses of both, which put the counter ahead of the loop's matrix pointer in the allocation order
(counter in `$s6`, pointer in `$s7`, as the target has them), at the price of putting the arm's short-lived value in
`$s6` where the target keeps it in `$v0`. Splitting the arm's value into a variable of its own (`reused_temp_split`)
gives the value its `$v0` but takes the counter's two extra references away, and the two pseudos tie (0.1475 against
0.1481) and swap: 619 -> 814 on a 731-instruction KMC N64 function. Alone the split is worse. With the counter's start
wrapped in a one-shot scope (`do { var_s6 = 0; } while (0);`, one more loop depth on that reference, weight 2 instead of
1, no instruction) the counter outranks the pointer again and no row differs but the preheader's order: 814 -> 519.
Neither step improves on its own, so this offers both at once: every `reused_temp_split` result, with each single-depth
wrapper `loop_weight_scope` puts round a counter start (`name = <literal>;` stepped by a literal later).
"""
import re

from . import loop_weight_repairs, reused_temp_split_repairs

FAMILY = 'reused_counter_split_scope'
FAMILIES = (FAMILY,)
LIMIT = 6
_SINGLE = re.compile(r'/\*__repair_loop_weight\*/do \{ ([A-Za-z_]\w*) = (?:0[xX][0-9A-Fa-f]+|\d+); \} while \(0\);')
_WORD = re.compile(r'[A-Za-z_]\w*')


def variants(source, name, header=''):
    result = []
    for family, split in reused_temp_split_repairs.variants(source, name):
        if family != reused_temp_split_repairs.FAMILY:
            continue
        # the name `reused_temp_split` made up for the loop's side of the split: its start is the counter to weight
        created = set(_WORD.findall(split)) - set(_WORD.findall(source))
        for kind, weighted in loop_weight_repairs.variants(split, name, header):
            wrapped = _SINGLE.search(weighted) if kind == loop_weight_repairs.FAMILIES[0] else None
            if wrapped and wrapped[1] in created and weighted.count('/*__repair_loop_weight*/') == 1:
                result.append((FAMILY, weighted))
                if len(result) >= LIMIT:
                    return result
    return result
