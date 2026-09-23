from __future__ import annotations


try:
    from teel.frameinspect import getvaluestack
except ImportError:  # linked into the interpreter, e.g. the WASI build
    from _teel_frameinspect import getvaluestack  # type: ignore[no-redef]

import dis
import operator
from collections import deque
from types import CodeType
from typing import Optional, Any, Callable
from inspect import signature


BINARY_OP = dis.opmap["BINARY_OP"]
COMPARE_OP = dis.opmap["COMPARE_OP"]

BINARY_OPS = tuple(
    {
        "+": (operator.add, False),
        "+=": (operator.iadd, True),
        "&": (operator.and_, False),
        "&=": (operator.iand, True),
        "//": (operator.floordiv, False),
        "//=": (operator.ifloordiv, True),
        "<<": (operator.lshift, False),
        "<<=": (operator.ilshift, True),
        "@": (operator.matmul, False),
        "@=": (operator.imatmul, True),
        "*": (operator.mul, False),
        "*=": (operator.imul, True),
        "%": (operator.mod, False),
        "%=": (operator.imod, True),
        "|": (operator.or_, False),
        "|=": (operator.ior, True),
        "**": (operator.pow, False),
        "**=": (operator.ipow, True),
        ">>": (operator.rshift, False),
        ">>=": (operator.irshift, True),
        "-": (operator.sub, False),
        "-=": (operator.isub, True),
        "/": (operator.truediv, False),
        "/=": (operator.itruediv, True),
        "^": (operator.xor, False),
        "^=": (operator.ixor, True),
    }[op]
    for _, op in dis._nb_ops
)

COMPARE_OPS = tuple(
    {
        "<": operator.lt,
        "<=": operator.le,
        "==": operator.eq,
        "!=": operator.ne,
        ">": operator.gt,
        ">=": operator.ge,
    }[op]
    for op in dis.cmp_op
)


class Instruction:
    __slots__ = [
        "opname",
        "opcode",
        "arg",
        "argval",
        "positions",
        "next",
        "jump",
        "opfunc",
        "inplace",
    ]

    next: Instruction
    jump: Instruction

    def __init__(
        self,
        opname: str,
        opcode: int,
        arg: int,
        argval: Any,
        positions: dis.Positions,
    ):
        self.opname: str = opname
        self.opcode: int = opcode
        self.arg: int = arg
        self.argval: Any = argval
        self.positions: dis.Positions = positions

        if self.opcode == BINARY_OP:
            self.opfunc, self.inplace = BINARY_OPS[arg]
        elif self.opcode == COMPARE_OP:
            self.opfunc = COMPARE_OPS[arg >> 4]


def instructions_from_code(code: CodeType) -> dict[int, Instruction]:
    instructions = {
        instr.offset: Instruction(
            opname=instr.opname,
            opcode=instr.opcode,
            arg=instr.arg,
            argval=instr.argval,
            positions=instr.positions,
        )
        for instr in dis.get_instructions(code, show_caches=True)
    }
    if (prev_i := next(inst_iter := iter(instructions.values()), None)) is not None:
        for next_i in inst_iter:
            prev_i.next = next_i
            prev_i = next_i
    for offset, instr in instructions.items():
        if (instr.opcode in dis.hasjrel) or (instr.opcode in dis.hasjabs):
            instr.jump = instructions[instr.argval]
    return instructions


class Frame:
    __slots__ = [
        "f_globals",
        "f_locals",
        "f_builtins",
        "f_code",
        "stack",
        "f_back",
        "instr",
        "kw_names",
        "index",
    ]

    def __init__(
        self,
        *,
        f_globals: dict[str, Any],
        f_locals: dict[str, Any],
        f_builtins: dict[str, Any],
        f_code: Any,
        stack: deque[Any],
        f_back: Optional[Frame] = None,
        instr: Instruction,
        kw_names: tuple[str, ...] = (),
        index: int,
    ):
        self.f_globals: dict[str, Any] = f_globals
        self.f_locals: dict[str, Any] = f_locals
        self.f_builtins: dict[str, Any] = f_builtins
        self.f_code: Any = f_code
        self.stack: deque[Any] = stack
        self.f_back: Optional[Frame] = f_back
        self.instr: Instruction = instr
        self.kw_names: tuple[str, ...] = kw_names
        self.index = index

    @staticmethod
    def from_callable(
        func: Callable,
        *,
        args: list,
        kwargs: dict[str, Any],
        f_back: Frame,
        instructions_from_code: Callable,
    ) -> Frame:
        bound = signature(func, follow_wrapped=False).bind_partial(*args, **kwargs)
        bound.apply_defaults()
        f_locals = dict(bound.arguments)
        f_code = func.__code__
        closure = func.__closure__
        if closure:
            f_locals.update(
                {
                    name: cell.cell_contents
                    for name, cell in zip(f_code.co_freevars, closure)
                }
            )
        return Frame(
            f_back=f_back,
            f_code=f_code,
            f_locals=f_locals,
            f_globals=func.__globals__,
            f_builtins=func.__builtins__,
            stack=deque(),
            instr=next(iter(instructions_from_code(f_code).values())),
            index=f_back.index + 1,
        )

    @staticmethod
    def from_frame(frame: Any, *, instructions_from_code: Callable) -> Optional[Frame]:
        chain = deque()
        while frame is not None:
            chain.appendleft(frame)
            frame = frame.f_back
        fr = None
        for index, frame in enumerate(chain):
            if (instructions := instructions_from_code(frame.f_code)) is not None:
                fr = Frame(
                    f_back=fr,
                    f_code=frame.f_code,
                    f_locals=dict(frame.f_locals),
                    f_globals=frame.f_globals,
                    f_builtins=frame.f_builtins,
                    stack=deque(getvaluestack(frame)),
                    instr=instructions[frame.f_lasti],
                    index=index,
                )
        return fr

    def copy(self, *, instr: Optional[Instruction]) -> Frame:
        chain = deque()
        frame = self
        while frame is not None:
            chain.appendleft(frame)
            frame = frame.f_back
        fr = None
        for frame in chain:
            fr = Frame(
                f_globals=frame.f_globals,
                f_locals=dict(frame.f_locals),
                f_builtins=frame.f_builtins,
                f_code=frame.f_code,
                stack=deque(frame.stack),
                f_back=fr,
                instr=frame.instr,
                kw_names=frame.kw_names,
                index=frame.index,
            )
        fr.instr = instr
        return fr
