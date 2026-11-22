from decomprepair.permuter_gen import supported_methods


def test_skip_native_random_predicate_insertion():
    def perm_var_cond_block():
        raise AssertionError('Native mutation can read a local before initialization')

    def perm_inequalities():
        pass

    assert supported_methods([(perm_var_cond_block, 4), (perm_inequalities, 8)]) == [
        (perm_inequalities, 8),
    ]
