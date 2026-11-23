from decomprepair.fence_break_unwrap import FAMILY, variants

SOURCE = '''void f(void *p, s32 mode)
{
    s32 var;
    switch (mode)
    {
        case 9:
            if (tick(p) >= 0x79)
            {
                do
                {
                    do
                    {
                        var = 8;
                        call(p, var);
                        break;
                    }
                    while (0);
                }
                while (0);
            }
            if (flag(p))
            {
                var = 2;
                call(p, var);
            }
            break;
        case 3:
            do
            {
                for (var = 0; var < 3; var++)
                {
                    if (stop(var))
                    {
                        break;
                    }
                }
            }
            while (0);
            break;
    }
}
'''


def unwrapped(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_a_break_inside_nested_fences_leaves_the_switch_once_they_are_gone():
    texts = unwrapped()
    assert len(texts) == 1
    text = texts[0]
    assert 'while (0)' in text, 'the fence whose only break belongs to an inner loop stays'
    assert text.count('while (0)') == 1
    assert 'var = 8;\n                        call(p, var);\n                        break;\n' in text


def test_a_fence_with_no_break_of_its_own_is_left_alone():
    assert not unwrapped(SOURCE.replace('                        break;\n                    }\n                    while (0);', '                    }\n                    while (0);', 1))
