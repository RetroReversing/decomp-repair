"""A comparison tree over one variable in the middle of a function, with a range arm, written as a switch."""
import re

from decomprepair.statement_tree_switch import FAMILY, variants

CODE = '''typedef float f32;
extern int gCount;
extern unsigned char gFlag;
extern void use(f32, f32);
void run(void)
{
    f32 cx = 160.0f;
    f32 cy = 120.0f;
    int x;
    int i;
    if (gCount != 2)
    {
        if (2 <= gCount)
        {
            if (gCount < 5)
            {
                cy = 60.0f;
                cx = 80.0f;
            }
        }
    }
    else
        if (gFlag == 1)
    {
        cx = 80.0f;
    }
    else
    {
        cy = 60.0f;
    }
    for (i = 0; i < 4; i++)
    {
        if (gCount != 2)
        {
            if (gCount < 3 || gCount >= 5)
            {
                x = -4;
            }
            else
            {
                x = 8;
            }
        }
        else
        {
            x = i;
        }
        use(cx, x);
    }
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_a_range_tree_without_returns_becomes_a_switch_with_the_shared_range_arm():
    children = variants(CODE, 'run')
    assert children and all(family == FAMILY for family, _ in children)
    text = squash(children[0][1])
    assert 'switch (gCount) { case 2: if (gFlag == 1) {' in text
    assert 'case 3: case 4: cy = 60.0f; cx = 80.0f; break; }' in text
    assert 'else if (gFlag' not in text and 'if (gCount != 2) { if (2 <= gCount)' not in text


def test_a_tree_with_a_default_arm_is_offered_with_the_default_first_too():
    children = [squash(text) for _, text in variants(CODE, 'run')]
    second = [text for text in children if 'default: x = -4; break; case' in text or 'default: x = -4; break; }' in text]
    assert second, children
    assert any('switch (gCount) { default: x = -4; break; case 2: x = i; break; case 3: case 4: x = 8; break; }' in text
               for text in children)
    assert any('switch (gCount) { case 2: x = i; break; case 3: case 4: x = 8; break; default: x = -4; break; }' in text
               for text in children)


def test_trees_that_return_assign_the_variable_or_differ_at_the_ends_are_left_alone():
    returning = CODE.replace('cy = 60.0f;\n                cx', 'return;\n                cx', 1)
    assert not any('case 3: case 4: return;' in squash(text) for _, text in variants(returning, 'run'))
    assigning = CODE.replace('cx = 80.0f;\n    }\n    else', 'gCount = 3;\n    }\n    else', 1)
    assert not any('case 2: if (gFlag == 1)' in squash(text) for _, text in variants(assigning, 'run'))
    lopsided = CODE.replace('if (gCount < 5)', 'if (gFlag)')
    assert not any('switch (gCount) { case 2: if (gFlag == 1)' in squash(text) for _, text in variants(lopsided, 'run'))
    assert variants(CODE, 'missing') == []
