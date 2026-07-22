from teel import jit, cacheable, Teel
import time

DELAY = 0.5


@cacheable
def f1():
    time.sleep(DELAY)
    return "f1()"


@cacheable
def f2(x):
    time.sleep(DELAY)
    return f"f2({x})"


@cacheable
def f3(x):
    time.sleep(DELAY)
    return f"f3({x})"


@cacheable
def f4(y, z):
    time.sleep(DELAY)
    return f"f4({y}, {z})"


@jit
def g():
    x = f1()
    y = f2(x)
    z = f3(x)
    return f4(y, z)


def time_it():
    before = time.perf_counter()
    assert g() == "f4(f2(f1()), f3(f1()))"
    after = time.perf_counter()
    return after - before


def main(trace_path="teel-trace.json"):
    print(f"Without Teel: {time_it():.1f}s")
    with Teel(trace_path=trace_path):
        print(
            f"With Teel: {time_it():.1f}s (open {trace_path} at https://ui.perfetto.dev/ for timeline)"
        )


if __name__ == "__main__":
    main()
