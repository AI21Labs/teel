import unittest
import copy
from functools import partial
from teel import lookahead


def target(x):
    return x


lookahead.add_target(target)

_GLOBAL_COUNTER = 37


class TestLookahead(unittest.TestCase):
    def _search(self):
        if self.results is not None:
            for call in lookahead.search():
                self.results.append(call.args[0])

    @lookahead.add_source
    def search(self, x=None):
        self._search()
        return x

    def assert_lookahead(self, inner, *args, expected=None):
        def outer():
            result = inner(*args)
            target(result)
            return result

        lookahead.add_source(inner)
        lookahead.add_source(outer)

        self.results = None
        result = copy.deepcopy(outer())
        self.results = []
        assert outer() == result
        assert result in self.results
        if expected is not None:
            assert all(x in expected for x in self.results)
            assert all(x in self.results for x in expected)
        else:
            assert self.results == [result]

    def test_const(self):

        def mine():
            self.search()
            return 666

        self.assert_lookahead(mine)

    def test_local_assignment_before(self):

        def mine():
            y = 444
            self.search()
            return y

        self.assert_lookahead(mine)

    def test_local_assignment_after(self):

        def mine():
            self.search()
            y = 555
            return y

        self.assert_lookahead(mine)

    def test_local_assignment_before_and_after(self):

        def mine():
            y = 444
            self.search()
            y = 555
            return y

        self.assert_lookahead(mine)

    def test_dict_setitem(self):

        def mine():
            x = {}
            self.search()
            x["l"] = "L"
            return ("l" in x, "l" not in x, "p" in x, "p" not in x)

        self.assert_lookahead(mine)

    def test_list_mutate_branch(self):

        def mine(y):
            x = []
            self.search()
            if y:
                x[len(x) :] = [1]
            else:
                x[len(x) :] = [-1]
            return (tuple(x), len(x))

        self.assert_lookahead(mine, False)
        self.assert_lookahead(mine, True)

    def test_str_join(self):
        def mine():
            x = []
            self.search()
            x[:] = ["hello"]
            return "".join(x)

        self.assert_lookahead(mine)

    def test_dict_update(self):
        def mine():
            x = {}
            self.search()
            x.update({f"a{len(x)}": f"b{len(x)}"})
            return x

        self.assert_lookahead(mine)

    def test_list_creation(self):
        def hidden(toggle):
            return toggle

        def mine(toggle):
            return [
                self.search(),
                (
                    vec := (1, [2, 3], 4, [5, 6])
                    if hidden(toggle)
                    else (7, [8], 9, [10])
                )[0],
                *(vec[1]),
                vec[2],
                *(vec[3]),
            ]

        expected = [
            [None, 1, 2, 3, 4, 5, 6],
            [None, 7, 8, 9, 10],
        ]
        self.assert_lookahead(mine, False, expected=expected)
        self.assert_lookahead(mine, True, expected=expected)

    def test_set_creation(self):
        def mine():
            x = 0
            self.search()
            return {x, x + 1}

        self.assert_lookahead(mine)

    def test_list_append_search_inside(self):
        def mine():
            x = [1]
            x.append(self.search())
            return x

        self.assert_lookahead(mine)

    def test_list_creation_after_mutation(self):
        def mine():
            self.search()
            x = []
            y = [2, 666]
            y[-1] = 3
            x[:] = y
            return [1, *x, 4]

        self.assert_lookahead(mine)

    def test_tuple_creation(self):
        def mine():
            x = [1]
            self.search()
            x.append(2)
            return tuple(x)

        self.assert_lookahead(mine)

    def test_list_compare(self):
        def mine():
            y1 = [6, -7]
            y2 = [6, 7]
            x1 = [5, y1]
            x2 = [5, y2]
            self.search()
            y1[1] = 777
            return x1 < x2

        self.assert_lookahead(mine)

    def test_list_not_empty_after_mutation(self):
        def mine():
            x = []
            self.search()
            x.append(1)
            return 666 if x else 777

        self.assert_lookahead(mine)

    def test_list_add(self):
        def mine():
            x = []
            y = []
            self.search()
            x.append(1)
            y.append(2)
            return x + y

        self.assert_lookahead(mine)

    def test_list_iadd(self):
        def mine():
            x = [1]
            y = [4]
            self.search()
            x += [2, 3]
            y += [5, 6]
            return x + y

        self.assert_lookahead(mine)

    def test_unaries(self):
        def mine(x):
            y = []
            self.search()
            y.append(len(y))
            return -x, ~x, not x, y, not y

        self.assert_lookahead(mine, 5)

    def test_call(self):
        @lookahead.add_source
        def sub():
            return 666

        def mine():
            self.search()
            return sub()

        self.assert_lookahead(mine)

    def test_set_add(self):
        def hidden(toggle):
            return toggle

        def mine(x):
            y = {0}
            self.search()
            y.add(len(y) if hidden(x) else -len(y))
            return y

        expected = [{0, 1}, {0, -1}]
        self.assert_lookahead(mine, False, expected=expected)
        self.assert_lookahead(mine, True, expected=expected)

    def test_dict_comprehension(self):
        def mine():
            self.search()
            return {i: i * 2 for i in range(4)}

        self.assert_lookahead(mine)

    def test_min_max(self):
        def mine():
            x = [1, 2]
            y = [1, 3]
            self.search()
            x[1] *= -1
            y[1] *= -1
            return (min(x, y) is x, min(x, y) is y, max(x, y) is x, max(x, y) is y)

        self.assert_lookahead(mine)

    def test_binary_subscr_after_store(self):
        def mine():
            x = [1, 2, 3]
            self.search()
            x[1] = 99
            return x[1]

        self.assert_lookahead(mine)

    def test_binary_slice_read(self):
        def mine():
            x = [1, 2, 3, 4]
            self.search()
            x[0] = 9
            return x[0:2]

        self.assert_lookahead(mine)

    def test_fstring(self):
        def mine():
            x = [1]
            self.search()
            x.append(2)
            return f"list={x}"

        self.assert_lookahead(mine)

    def test_for_loop_accumulate(self):
        def mine():
            x = []
            self.search()
            for i in range(3):
                x.append(i)
            return sum(x)

        self.assert_lookahead(mine)

    def test_nested_dict_setitem(self):
        def mine():
            d = {"a": {}}
            self.search()
            d["a"]["b"] = 1
            inner = d["a"]
            return ("b" in inner, inner["b"])

        self.assert_lookahead(mine)

    def test_contains_after_mutation(self):
        def mine():
            x = [1]
            self.search()
            x.append(2)
            return (2 in x, 3 in x, 2 not in x)

        self.assert_lookahead(mine)

    def test_is_op(self):
        def mine():
            x = None
            self.search()
            return (x is None, x is not None)

        self.assert_lookahead(mine)

    def test_build_map(self):
        def mine():
            k = "a"
            v = 1
            self.search()
            return {k: v, "b": v + 1}

        self.assert_lookahead(mine)

    def test_build_const_key_map(self):
        def mine():
            x = 1
            self.search()
            return {"a": x, "b": x + 1}

        self.assert_lookahead(mine)

    def test_str_upper_safe(self):
        def mine():
            s = "hello"
            self.search()
            return s.upper()

        self.assert_lookahead(mine)

    def test_str_replace_safe(self):
        def mine():
            self.search()
            s = "a-b-c"
            return s.replace("-", "_")

        self.assert_lookahead(mine)

    def test_partial_call(self):
        @lookahead.add_source
        def add(a, b):
            return a + b

        def mine():
            self.search()
            p = partial(add, 10)
            return p(5)

        self.assert_lookahead(mine)

    def test_call_kwargs(self):
        @lookahead.add_source
        def sub(a, b=0):
            return a - b

        def mine():
            self.search()
            return sub(10, b=3)

        self.assert_lookahead(mine)

    def test_unpack_sequence_after_mutation(self):
        def mine():
            p = [1, 2]
            self.search()
            p[0] = 9
            a, b = p
            return a + b

        self.assert_lookahead(mine)

    def test_swap_tuple_assign(self):
        def mine():
            a = 1
            b = 2
            self.search()
            a, b = b, a
            return (a, b)

        self.assert_lookahead(mine)

    def test_global_read(self):
        def mine():
            self.search()
            return _GLOBAL_COUNTER + 5

        self.assert_lookahead(mine)

    def test_dict_merge_star(self):
        def mine():
            a = {"x": 1}
            self.search()
            return {**a, "y": 2}

        self.assert_lookahead(mine)

    def test_nested_branch_multiple(self):
        def hidden(t):
            return t

        def mine(t):
            x = 0
            self.search()
            if hidden(t):
                x = 1
            else:
                x = 2
            return x

        self.assert_lookahead(mine, True, expected=[1, 2])
        self.assert_lookahead(mine, False, expected=[1, 2])

    def test_sorted_deep_read(self):
        def mine():
            x = [3, 1, 2]
            self.search()
            x.append(0)
            return sorted(x)

        self.assert_lookahead(mine)

    def test_list_slice_assign_read(self):
        def mine():
            x = [0, 0, 0, 0]
            self.search()
            x[1:3] = [7, 8, 9]
            return (len(x), x[2])

        self.assert_lookahead(mine)

    def test_dict_get(self):
        def mine():
            x = []
            y = []
            z = {}
            self.search()
            x.append("x")
            y.append("y")
            z["X"] = x
            return (z.get("X") is x, z.get("Y", y) is y)

        self.assert_lookahead(mine)


if __name__ == "__main__":
    unittest.main()
