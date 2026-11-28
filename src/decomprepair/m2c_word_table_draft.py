"""A raw m2c draft over word tables, repaired as one child: the steps that each leave the score worse alone.

Written out one at a time, the repairs of such a draft do not climb: `goto_paths_written_out` copies the two calls
into each path and scores worse until the stray argument is gone from both, and the temporaries cannot be written out
until the paths are. A greedy search keeps neither.

m2c_word_table_draft
    In order: the word tables declared and indexed (`word_symbol_array_index`), the stored members' signedness
    (`member_immediate_signedness`), the narrowed word read (`word_low_byte_read`), the jumps written as their paths
    (`goto_paths_written_out`), the repeated trailing argument (`repeated_index_argument`) and the temporaries
    (`m2c_value_temporaries`, with the members read back, then without). A step with nothing to do is skipped.

An SN GCC 2.8.1 (`-G0 -mips3 -O2`) N64 label update went from the machine draft's 8555 to 0 with this child (one
function, a controlled result).
"""
from . import (
    goto_paths_written_out,
    m2c_value_temporaries,
    member_immediate_signedness,
    repeated_index_argument,
    word_low_byte_read,
    word_symbol_array_index,
)

FAMILY = 'm2c_word_table_draft'
FAMILIES = (FAMILY,)


def variants(source, name, asm, arch='mips'):
    first = word_symbol_array_index.variants(source, name)
    if not first or not asm or arch not in ('mips', 'mipsel'):
        return []
    text = first[0][1]
    for step in (lambda t: member_immediate_signedness.variants(t, name, asm),
                 lambda t: word_low_byte_read.variants(t, name, asm, arch),
                 lambda t: goto_paths_written_out.variants(t, name),
                 lambda t: repeated_index_argument.variants(t, name)):
        found = step(text)
        if found:
            text = found[0][1]
    result = [(FAMILY, new) for _, new in m2c_value_temporaries.variants(text, name)]
    return result or [(FAMILY, text)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'arch')}
