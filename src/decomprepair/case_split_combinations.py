"""A switch's case temporaries split per case and its byte-flag updates folded, in one child.

`case_temporary_split` (one local per case) and `split_read_modify_write` (a load, update and store through a local
folded or collapsed into the update) act on the same few statements of a switch case: the temporary a case loads a
flag into is the one both rewrite. In an N64 four-case switch (KMC gcc 2.7.2) each step alone was a partial gain
(850 to 240 by the split, 610 by the folds), and their pair was exact; where a case shares one temporary with another
case, folding it before the split changes which pseudo every case gets, so the two need to be judged together, not
one after the other (a pass that keeps only improvements stops after the first when the second alone scores worse).
This offers each split child with each fold of it as one variant; both families keep their own soundness rules.
"""
from . import case_temporary_repairs, compound_global_update_repairs

FAMILY = 'case_temporary_split_combined'
FAMILIES = (FAMILY,)
SPLITS = 4  # the split children combined (all cases first, then one case at a time)
FOLDS = 6
LIMIT = 12


def variants(source, name):
    """[(FAMILY, source)]: each case-temporary split with each read-modify-write fold applied to it."""
    out, seen = [], {source}
    splits = [text for family, text in case_temporary_repairs.variants(source, name)
              if family == case_temporary_repairs.SPLIT][:SPLITS]
    for split in splits:
        for _, folded in compound_global_update_repairs.variants(split, name)[:FOLDS]:
            if folded not in seen:
                seen.add(folded)
                out.append((FAMILY, folded))
                if len(out) >= LIMIT:
                    return out
    return out
