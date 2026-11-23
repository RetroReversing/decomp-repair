"""A copy between two locals holding the same constant, kept by assigning the constant in both arms (4500, 1040 of it)."""
from decomprepair.constant_copy_arm_assign import FAMILY, variants

SEEDED = """void setup(void)
{
    unsigned long seed = 0;
    u32 x;
    u32 y = 0;

    x = seed;
    if (osTvType) {
        x = y;
    }
    use(x, y);
}
"""

STATEMENTS = """void setup(void)
{
    u32 x;
    u32 y;

    x = 0;
    y = 0;
    if (osTvType) {
        x = y;
    }
    use(x, y);
}
"""


def children(source):
    return [text for family, text in variants(source, 'setup') if family == FAMILY]


def test_the_constant_is_assigned_in_both_arms_and_the_declaration_initialiser_goes():
    found = children(SEEDED)
    assert len(found) == 1
    assert '    u32 y;\n' in found[0] and 'u32 y = 0;' not in found[0]
    assert ('    if (osTvType) {\n        y = 0;\n        x = y;\n    } else {\n        y = 0;\n    }\n    use(x, y);'
            in found[0].replace('\n\n', '\n') or 'if (osTvType) {\n        y = 0;\n        x = y;\n    } else {\n        y = 0;\n    }' in found[0])


def test_an_assignment_statement_is_moved_into_the_arms_too():
    found = children(STATEMENTS)
    assert len(found) == 1
    assert '    y = 0;\n    if' not in found[0]
    assert 'x = 0;\n' in found[0]
    assert 'if (osTvType) {\n        y = 0;\n        x = y;\n    } else {\n        y = 0;\n    }' in found[0]


def test_no_child_when_the_locals_hold_different_values_or_an_else_exists_or_b_is_read_between():
    assert not children(STATEMENTS.replace('x = 0;', 'x = 1;'))
    assert not children(STATEMENTS.replace('        x = y;\n    }', '        x = y;\n    } else {\n        x = 2;\n    }'))
    assert not children(STATEMENTS.replace('    y = 0;\n    if', '    y = 0;\n    use(y);\n    if'))
