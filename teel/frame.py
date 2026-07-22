from __future__ import annotations


from teel.frameinspect import getvaluestack

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

    def __init__(
        self,
        opname: str,
        opcode: int,
        arg: int,
        argval: Any,
        positions: dis.Positions,
        next: Optional[Instruction] = None,
        jump: Optional[Instruction] = None,
    ):
        self.opname: str = opname
        self.opcode: int = opcode
        self.arg: int = arg
        self.argval: Any = argval
        self.positions: dis.Positions = positions
        self.next: Optional[Instruction] = next
        self.jump: Optional[Instruction] = jump

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
    ]

    def __init__(
        self,
        f_globals: dict[str, Any],
        f_locals: dict[str, Any],
        f_builtins: dict[str, Any],
        f_code: Any,
        stack: deque[Any],
        f_back: Optional[Frame] = None,
        instr: Optional[Instruction] = None,
        kw_names: tuple[str, ...] = (),
    ):
        self.f_globals: dict[str, Any] = f_globals
        self.f_locals: dict[str, Any] = f_locals
        self.f_builtins: dict[str, Any] = f_builtins
        self.f_code: Any = f_code
        self.stack: deque[Any] = stack
        self.f_back: Optional[Frame] = f_back
        self.instr: Optional[Instruction] = instr
        self.kw_names: tuple[str, ...] = kw_names

    @staticmethod
    def from_callable(
        func: Callable,
        *,
        args: list,
        kwargs: dict[str, Any],
        f_back: Frame,
        instructions_from_code,
    ):
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
            instr=next(iter(instructions_from_code(f_code).values()), None),
        )

    @staticmethod
    def from_frame(frame, *, instructions_from_code):
        chain = deque()
        while frame is not None:
            chain.appendleft(frame)
            frame = frame.f_back
        fr = None
        for frame in chain:
            instructions = instructions_from_code(frame.f_code)
            if instructions is None:
                fr = Frame(
                    f_back=fr,
                    f_code=None,
                    f_locals={},
                    f_globals={},
                    f_builtins={},
                    stack=deque(),
                    instr=None,
                )
            else:
                fr = Frame(
                    f_back=fr,
                    f_code=frame.f_code,
                    f_locals=dict(frame.f_locals),
                    f_globals=frame.f_globals,
                    f_builtins=frame.f_builtins,
                    stack=deque(getvaluestack(frame)),
                    instr=instructions[frame.f_lasti],
                )
        return fr

    def copy(self, *, instr):
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
            )
        fr.instr = instr
        return fr
