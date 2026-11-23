"""A switch whose arms goto labels inside it, written with a copy of the run in each arm."""
import re

from decomprepair import registry
from decomprepair.switch_label_arms import FAMILIES, FAMILY, MIXED, SCOPED, variants

CODE = '''typedef int s32;
typedef unsigned int u32;
typedef unsigned char u8;
typedef struct { unsigned char pad[136]; int value; } Rec;
extern s32 gHits;
extern s32 gKeep;

void arms(void *p, s32 kind, s32 n, s32 on)
{
    u32 v;
    u32 mask;
    u8 code;
    s32 flag;
    s32 kept;
    kept = 0;
    switch (kind) {
    case 1:
        v = ((Rec *) p)->value;
        mask = 0xFE1FFFFF;
        code = 0x2F;
        goto set_code;
    case 2:
        v = ((Rec *) p)->value;
        mask = 0xFE1FFFFF;
        code = 0x2C;
        goto set_code;
    case 3:
        v = ((Rec *) p)->value;
        mask = 0xFE1FFFFF;
        code = 0x30;
        set_code:
        *(u8 *) ((char *) p + 0x82) = code;
        flag = 0x600000;
        apply:
        v &= mask;
        v |= flag;
        ((Rec *) p)->value = v;
        break;
    case 4:
        v = ((Rec *) p)->value;
        mask = 0xFE1FFFFF;
        kept = 5;
        *(u8 *) ((char *) p + 0x82) = 0x1E;
        do {
            flag = 0x800000;
            goto apply;
        } while (0);
    case 5:
        *(u8 *) ((char *) p + 0x82) = 9;
        break;
    }
    gKeep = kept;
    if ((n << 0x18) != 0) {
        gHits = on;
    }
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def arm(text, number):
    """The text of `case number:` up to the next case, squashed."""
    return squash(re.search(rf'case {number}:(.*?)(?=case \d+:|\}}\s*gKeep)', text, re.S)[1]).strip()


def test_every_arm_gets_its_own_copy_of_the_run_with_its_own_locals():
    first = [text for family, text in variants(CODE, 'arms') if family == FAMILY][0]
    assert 'goto' not in first and 'set_code' not in first and 'apply' not in first
    assert squash(arm(first, 1)) == ('{ u32 v; v = ((Rec *) p)->value; *(u8 *) ((char *) p + 0x82) = 0x2F; v &= 0xFE1FFFFF; '
                                     'v |= 0x600000; ((Rec *) p)->value = v; break; }')
    assert '= 0x2C;' in arm(first, 2) and '= 0x30;' in arm(first, 3)
    assert '{ u32 v; v = ((Rec *) p)->value;' in arm(first, 4) and 'v |= 0x800000;' in arm(first, 4)
    assert 'kept = 5;' in arm(first, 4) and 's32 kept;' in squash(first)   # still the function's, not the arm's
    assert 'u32 mask;' not in squash(first).split('switch')[1]


def test_the_mixed_child_moves_the_statements_before_the_update_inside_it():
    mixed = [text for family, text in variants(CODE, 'arms') if family == MIXED][0]
    assert squash(arm(mixed, 1)) == ('{ u32 v; v = ((Rec *) p)->value; v &= 0xFE1FFFFF; v |= 0x600000; '
                                     '*(u8 *) ((char *) p + 0x82) = 0x2F; ((Rec *) p)->value = v; break; }')
    assert 'kept = 5; *(u8 *) ((char *) p + 0x82) = 0x1E; ((Rec *) p)->value = v;' in arm(mixed, 4)


def test_a_word_update_written_as_one_expression_gets_the_compound_form_on_a_local():
    code = CODE.replace('    case 5:\n        *(u8 *) ((char *) p + 0x82) = 9;',
                        '    case 5:\n        gHits = 2;\n'
                        '        ((Rec *) p)->value = (s32) ((((Rec *) p)->value & 0xFE1FFFFF) | 0x600000);\n'
                        '        *(u8 *) ((char *) p + 0x82) = 9;')
    mixed = [text for family, text in variants(code, 'arms') if family == MIXED][0]
    assert arm(mixed, 5) == ('{ s32 word1; word1 = ((Rec *) p)->value; word1 &= 0xFE1FFFFF; word1 |= 0x600000; gHits = 2; '
                             '((Rec *) p)->value = word1; *(u8 *) ((char *) p + 0x82) = 9; break; }')


def test_the_flag_scope_of_a_parameter_is_offered_with_the_arms():
    scoped = [text for family, text in variants(CODE, 'arms') if family == SCOPED]
    assert scoped and any('do { n_flag = n << 0x18; } while (0);' in squash(text) and 'goto' not in text for text in scoped)


def test_a_goto_in_a_place_the_rewrite_cannot_reach_leaves_the_switch_alone():
    code = CODE.replace('        do {\n            flag = 0x800000;\n            goto apply;\n        } while (0);',
                        '        flag = 0x800000;\n        if (on) {\n            goto apply;\n        }\n        break;')
    assert variants(code, 'arms') == []
    assert variants(CODE.replace('goto set_code;', 'goto missing;', 1), 'arms') == []


def test_a_switch_without_labels_has_no_proposal():
    assert variants('typedef int s32;\nvoid f(s32 k)\n{\n    switch (k) {\n    case 1:\n        break;\n    }\n}\n', 'f') == []


def test_the_family_declares_itself_to_the_registry():
    [repair] = [item for item in registry.declared() if set(FAMILIES) <= set(item.families)]
    assert registry.problems(repair) == []
