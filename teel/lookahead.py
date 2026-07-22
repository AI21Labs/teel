from __future__ import annotations

from enum import IntEnum
import dis
import sys
from copy import copy, deepcopy
from types import CodeType, FunctionType
from weakref import WeakKeyDictionary
from functools import partial
from typing import Optional, Callable, Any, NamedTuple
from collections import deque

from .frame import Frame, Instruction, instructions_from_code
from .shadow_copy import shadow_deepcopy, Memo


class State(NamedTuple):
    frame: Frame
    shadows: dict[int, Any]
    swodahs: dict[int, Any]
    depth: int


class Call(NamedTuple):
    func: Callable
    args: list
    kwargs: dict[str, Any]
    state: State


class Pending:
    def __repr__(self):
        return "?"


class MethodType(IntEnum):
    TARGET = 1
    SAFE = 2
    SHALLOW_READ = 3
    SHALLOW_WRITE = 4
    DEEP_READ = 5


RETURN_VALUE = dis.opmap["RETURN_VALUE"]
RETURN_CONST = dis.opmap["RETURN_CONST"]
KW_NAMES = dis.opmap["KW_NAMES"]
GET_ITER = dis.opmap["GET_ITER"]
CALL = dis.opmap["CALL"]
CALL_FUNCTION_EX = dis.opmap["CALL_FUNCTION_EX"]
CACHE = dis.opmap["CACHE"]
COPY_FREE_VARS = dis.opmap["COPY_FREE_VARS"]
RESUME = dis.opmap["RESUME"]
MAKE_CELL = dis.opmap["MAKE_CELL"]
LOAD_NAME = dis.opmap["LOAD_NAME"]
LOAD_FAST = dis.opmap["LOAD_FAST"]
LOAD_FAST_CHECK = dis.opmap["LOAD_FAST_CHECK"]
LOAD_FAST_AND_CLEAR = dis.opmap["LOAD_FAST_AND_CLEAR"]
LOAD_ATTR = dis.opmap["LOAD_ATTR"]
LOAD_CONST = dis.opmap["LOAD_CONST"]
LOAD_GLOBAL = dis.opmap["LOAD_GLOBAL"]
LOAD_DEREF = dis.opmap["LOAD_DEREF"]
LOAD_CLOSURE = dis.opmap["LOAD_CLOSURE"]
STORE_NAME = dis.opmap["STORE_NAME"]
STORE_DEREF = dis.opmap["STORE_DEREF"]
STORE_FAST = dis.opmap["STORE_FAST"]
STORE_GLOBAL = dis.opmap["STORE_GLOBAL"]
STORE_SUBSCR = dis.opmap["STORE_SUBSCR"]
STORE_SLICE = dis.opmap["STORE_SLICE"]
UNARY_NEGATIVE = dis.opmap["UNARY_NEGATIVE"]
UNARY_INVERT = dis.opmap["UNARY_INVERT"]
UNARY_NOT = dis.opmap["UNARY_NOT"]
BINARY_OP = dis.opmap["BINARY_OP"]
BINARY_SUBSCR = dis.opmap["BINARY_SUBSCR"]
BINARY_SLICE = dis.opmap["BINARY_SLICE"]
COMPARE_OP = dis.opmap["COMPARE_OP"]
SET_ADD = dis.opmap["SET_ADD"]
LIST_APPEND = dis.opmap["LIST_APPEND"]
LIST_EXTEND = dis.opmap["LIST_EXTEND"]
JUMP_BACKWARD = dis.opmap["JUMP_BACKWARD"]
JUMP_FORWARD = dis.opmap["JUMP_FORWARD"]
POP_TOP = dis.opmap["POP_TOP"]
POP_EXCEPT = dis.opmap["POP_EXCEPT"]
POP_JUMP_IF_FALSE = dis.opmap["POP_JUMP_IF_FALSE"]
POP_JUMP_IF_TRUE = dis.opmap["POP_JUMP_IF_TRUE"]
POP_JUMP_IF_NONE = dis.opmap["POP_JUMP_IF_NONE"]
POP_JUMP_IF_NOT_NONE = dis.opmap["POP_JUMP_IF_NOT_NONE"]
BUILD_MAP = dis.opmap["BUILD_MAP"]
BUILD_CONST_KEY_MAP = dis.opmap["BUILD_CONST_KEY_MAP"]
BUILD_LIST = dis.opmap["BUILD_LIST"]
BUILD_TUPLE = dis.opmap["BUILD_TUPLE"]
BUILD_SET = dis.opmap["BUILD_SET"]
BUILD_STRING = dis.opmap["BUILD_STRING"]
DICT_MERGE = dis.opmap["DICT_MERGE"]
DICT_UPDATE = dis.opmap["DICT_UPDATE"]
MAP_ADD = dis.opmap["MAP_ADD"]
SWAP = dis.opmap["SWAP"]
FOR_ITER = dis.opmap["FOR_ITER"]
END_FOR = dis.opmap["END_FOR"]
PUSH_NULL = dis.opmap["PUSH_NULL"]
MAKE_FUNCTION = dis.opmap["MAKE_FUNCTION"]
CACHE = dis.opmap["CACHE"]
BEFORE_WITH = dis.opmap["BEFORE_WITH"]
FORMAT_VALUE = dis.opmap["FORMAT_VALUE"]
UNPACK_SEQUENCE = dis.opmap["UNPACK_SEQUENCE"]
EXTENDED_ARG = dis.opmap["EXTENDED_ARG"]
CONTAINS_OP = dis.opmap["CONTAINS_OP"]
IS_OP = dis.opmap["IS_OP"]
NOP = dis.opmap["NOP"]
COPY = dis.opmap["COPY"]

PENDING = Pending()
sentinel = object()

sources: WeakKeyDictionary[CodeType, dict[int, Instruction]] = WeakKeyDictionary()
filename_sources: set[str] = set()
methods: dict[Callable, MethodType] = {
    range: MethodType.SAFE,
    isinstance: MethodType.SHALLOW_READ,
    enumerate: MethodType.SHALLOW_READ,
    sum: MethodType.SHALLOW_READ,
    len: MethodType.SHALLOW_READ,
    int: MethodType.SAFE,
    float: MethodType.SAFE,
    object: MethodType.SAFE,
    tuple: MethodType.SHALLOW_READ,
    list: MethodType.SHALLOW_READ,
    set: MethodType.SHALLOW_READ,
    partial: MethodType.SAFE,
    str.lower: MethodType.SAFE,
    str.upper: MethodType.SAFE,
    str.title: MethodType.SAFE,
    str.strip: MethodType.SAFE,
    str.find: MethodType.SAFE,
    str.split: MethodType.SAFE,
    str.rsplit: MethodType.SAFE,
    str.replace: MethodType.SAFE,
    str.splitlines: MethodType.SAFE,
    str.startswith: MethodType.SHALLOW_READ,
    str.join: MethodType.SHALLOW_READ,
    str.translate: MethodType.SHALLOW_READ,
    set.add: MethodType.SHALLOW_WRITE,
    set.pop: MethodType.SHALLOW_WRITE,
    list.append: MethodType.SHALLOW_WRITE,
    list.extend: MethodType.SHALLOW_WRITE,
    dict.get: MethodType.SHALLOW_READ,
    dict.keys: MethodType.SHALLOW_READ,
    dict.items: MethodType.SHALLOW_READ,
    dict.values: MethodType.SHALLOW_READ,
    dict.fromkeys: MethodType.SHALLOW_READ,
    dict.update: MethodType.SHALLOW_WRITE,
    min: MethodType.DEEP_READ,
    max: MethodType.DEEP_READ,
    sorted: MethodType.DEEP_READ,
    str: MethodType.DEEP_READ,
    repr: MethodType.DEEP_READ,
    format: MethodType.DEEP_READ,
    ascii: MethodType.DEEP_READ,
}


def _split_bound_method(func) -> tuple[Any, list]:
    if ((self := getattr(func, "__self__", None)) is not None) and (
        ((unbound := getattr(func, "__func__", None)) is not None)
        or (
            ((name := getattr(func, "__name__", None)) is not None)
            and ((unbound := getattr(type(self), name, None)) is not None)
        )
    ):
        return unbound, [self]
    else:
        return func, []


def search(
    max_jump_width=2, max_jump_depth=4, ret=PENDING, state: Optional[State] = None
):

    def do_call():
        nonlocal instr, stack, frame, f_globals
        if opcode == CALL:
            kw_names = frame.kw_names
            frame.kw_names = ()
            pos_args_count = instr.arg - len(kw_names)
            assert pos_args_count >= 0
            kwargs = dict(zip(kw_names, [stack.pop() for _ in kw_names][::-1]))
            args = [stack.pop() for _ in range(pos_args_count)][::-1]
        else:  # CALL_FUNCTION_EX
            if instr.arg & 1:
                kwargs = stack.pop()
            else:
                kwargs = {}
            args = stack.pop()
        caller_2 = stack.pop()
        caller_1 = stack.pop()
        if args is PENDING:
            args = []
        if kwargs is PENDING:
            kwargs = {}
        if (
            (caller_1 is not PENDING)
            and (caller_1 is not None)
            and (args is not PENDING)
        ):
            args = [caller_2, *args]
            caller_2 = caller_1
            caller_1 = None
        if (caller_1 is None) and (caller_2 is not PENDING) and (args is not PENDING):
            caller_2, prefix = _split_bound_method(caller_2)
            args = [*prefix, *args]
        if (
            (caller_1 is None)
            and (caller_2 is not PENDING)
            and isinstance(caller_2, partial)
            and (args is not PENDING)
            and (kwargs is not PENDING)
        ):
            args = [*caller_2.args, *args]
            kwargs = {**caller_2.keywords, **kwargs}
            caller_2 = caller_2.func
        if (
            (caller_1 is None)
            and (caller_2 is not PENDING)
            and isinstance(caller_2, FunctionType)
            and ((code := getattr(caller_2, "__code__", None)) is not None)
            and ((code in sources) or (code.co_filename in filename_sources))
            and (args is not PENDING)
            and (kwargs is not PENDING)
        ):
            frame.instr = instr
            args = shadows.get(id(args), args)
            kwargs = shadows.get(id(kwargs), kwargs)
            frame = Frame.from_callable(
                caller_2,
                args=args,
                kwargs=kwargs,
                f_back=frame,
                instructions_from_code=_instructions_from_code,
            )
            stack, instr = frame.stack, frame.instr
            if (f_globals := shadows.get(id(frame.f_globals), sentinel)) is sentinel:
                shadows[id(frame.f_globals)] = f_globals = dict(frame.f_globals)
                swodahs[id(f_globals)] = frame.f_globals
        elif (
            (caller_1 is None)
            and (caller_2 is not PENDING)
            and ((method_type := methods.get(caller_2, None)) is not None)
            and (args is not PENDING)
            and (kwargs is not PENDING)
            and all(x is not PENDING for x in args)
            and all(v is not PENDING for v in kwargs.values())
        ):
            if (method_type == MethodType.TARGET) or (
                method_type == MethodType.DEEP_READ
            ):
                memo = Memo(shadows=shadows)
                args = [shadow_deepcopy(x, memo) for x in args]
                kwargs = {k: shadow_deepcopy(v, memo) for k, v in kwargs.items()}
            elif method_type == MethodType.SHALLOW_READ:
                args = [shadows.get(id(x), x) for x in args]
                kwargs = {k: shadows.get(id(v), v) for k, v in kwargs.items()}
            elif method_type == MethodType.SHALLOW_WRITE:
                if (sh := shadows.get(id(args[0]), sentinel)) is sentinel:
                    shadows[id(args[0])] = sh = copy(args[0])
                    swodahs[id(sh)] = args[0]
                args = [sh, *[shadows.get(id(x), x) for x in args[1:]]]
                kwargs = {k: shadows.get(id(v), v) for k, v in kwargs.items()}
            if method_type == MethodType.TARGET:
                copied_shadows = {}
                copied_swodahs = {}
                for k, v in shadows.items():
                    copied_shadows[k] = copied_v = copy(v)
                    copied_swodahs[id(copied_v)] = swodahs[id(v)]
                yield Call(
                    func=caller_2,
                    args=args,
                    kwargs=kwargs,
                    state=State(
                        frame=frame.copy(instr=instr),
                        shadows=copied_shadows,
                        swodahs=copied_swodahs,
                        depth=depth,
                    ),
                )
                stack.append(PENDING)
            else:
                result = caller_2(*args, **kwargs)
                if method_type == MethodType.DEEP_READ:
                    r_memo = {
                        id(v): obj
                        for k, v in memo.items()
                        if (obj := swodahs.get(k, None)) is not None
                    }
                    result = deepcopy(result, r_memo)
                elif method_type != MethodType.SAFE:
                    result = swodahs.get(id(result), result)
                stack.append(result)
            instr = instr.next
        else:
            stack.append(PENDING)
            instr = instr.next

    def do_return(value=PENDING):
        nonlocal instr, stack, frame, f_globals, shadows, swodahs, depth
        frame = frame.f_back
        if frame is not None:
            frame.stack.append(value)
            frame = _skip_frames(frame)
        if frame is None:
            if not jump_frames:
                return True
            frame, shadows, swodahs, depth = jump_frames.popleft()
            stack, instr = frame.stack, frame.instr
        else:
            stack, instr = frame.stack, frame.instr.next
        if (f_globals := shadows.get(id(frame.f_globals), sentinel)) is sentinel:
            shadows[id(frame.f_globals)] = f_globals = dict(frame.f_globals)
            swodahs[id(f_globals)] = frame.f_globals
        return False

    if state is None:
        shadows = {}
        swodahs = {}
        frame = Frame.from_frame(
            sys._getframe().f_back, instructions_from_code=_instructions_from_code
        )
        depth = 0
    else:
        frame, shadows, swodahs, depth = state

    if depth > max_jump_depth:
        return []
    frame.stack.append(ret)
    frame = _skip_frames(frame)
    if frame is None:
        return []
    stack, instr = frame.stack, frame.instr.next
    if (f_globals := shadows.get(id(frame.f_globals), sentinel)) is sentinel:
        shadows[id(frame.f_globals)] = f_globals = copy(frame.f_globals)
        swodahs[id(f_globals)] = frame.f_globals
    jump_frames: deque[State] = deque()

    while True:
        opcode = instr.opcode
        try:
            if (
                (opcode == STORE_FAST)
                or (opcode == STORE_DEREF)
                or (opcode == STORE_NAME)
            ):
                frame.f_locals[instr.argval] = stack.pop()
                instr = instr.next
            elif opcode == STORE_GLOBAL:
                value = stack.pop()
                f_globals[instr.argval] = value
                instr = instr.next
            elif opcode == STORE_SUBSCR:
                key = stack.pop()
                container = stack.pop()
                value = stack.pop()
                if (
                    (container is not PENDING)
                    and (key is not PENDING)
                    and (value is not PENDING)
                ):
                    if (sh := shadows.get(id(container), sentinel)) is sentinel:
                        shadows[id(container)] = sh = copy(container)
                        swodahs[id(sh)] = container
                    sh[key] = value
                instr = instr.next
            elif opcode == STORE_SLICE:
                end = stack.pop()
                start = stack.pop()
                container = stack.pop()
                values = stack.pop()
                if (
                    (container is not PENDING)
                    and (start is not PENDING)
                    and (end is not PENDING)
                    and (values is not PENDING)
                ):
                    if (sh := shadows.get(id(container), sentinel)) is sentinel:
                        shadows[id(container)] = sh = copy(container)
                        swodahs[id(sh)] = container
                    sh[start:end] = shadows.get(id(values), values)
                instr = instr.next
            elif opcode == LOAD_NAME:
                argval = instr.argval
                if argval in frame.f_locals:
                    stack.append(frame.f_locals[argval])
                elif argval in f_globals:
                    stack.append(f_globals[argval])
                elif argval in frame.f_builtins:
                    stack.append(frame.f_builtins[argval])
                else:
                    stack.append(PENDING)
                instr = instr.next
            elif opcode == LOAD_GLOBAL:
                argval = instr.argval
                if instr.arg & 1:
                    stack.append(None)
                if argval in f_globals:
                    stack.append(f_globals[argval])
                elif argval in frame.f_builtins:
                    stack.append(frame.f_builtins[argval])
                else:
                    stack.append(PENDING)
                instr = instr.next
            elif (
                (opcode == LOAD_FAST)
                or (opcode == LOAD_FAST_CHECK)
                or (opcode == LOAD_CLOSURE)
            ):
                stack.append(frame.f_locals.get(instr.argval, PENDING))
                instr = instr.next
            elif opcode == LOAD_FAST_AND_CLEAR:
                argval = instr.argval
                stack.append(frame.f_locals.get(argval, PENDING))
                frame.f_locals[argval] = PENDING
                instr = instr.next
            elif opcode == LOAD_CONST:
                stack.append(instr.argval)
                instr = instr.next
            elif (opcode == CALL) or (opcode == CALL_FUNCTION_EX):
                yield from do_call()
            elif (
                (opcode == BINARY_OP)
                or (opcode == COMPARE_OP)
                or (opcode == CONTAINS_OP)
            ):
                operand2 = stack.pop()
                operand1 = stack.pop()
                if (operand1 is PENDING) or (operand2 is PENDING):
                    stack.append(PENDING)
                elif opcode == COMPARE_OP:
                    memo = Memo(shadows=shadows)
                    operand2 = shadow_deepcopy(operand2, memo)
                    operand1 = shadow_deepcopy(operand1, memo)
                    stack.append(instr.opfunc(operand1, operand2))
                elif opcode == BINARY_OP:
                    operand2 = shadows.get(id(operand2), operand2)
                    if instr.inplace:
                        if (sh := shadows.get(id(operand1), sentinel)) is sentinel:
                            shadows[id(operand1)] = sh = copy(operand1)
                            swodahs[id(sh)] = operand1
                        operand1 = sh
                    else:
                        operand1 = shadows.get(id(operand1), operand1)
                    stack.append(instr.opfunc(operand1, operand2))
                else:  # CONTAINS_OP
                    operand2 = shadows.get(id(operand2), operand2)
                    operand1 = shadows.get(id(operand1), operand1)
                    if instr.arg:
                        stack.append(operand1 not in operand2)
                    else:
                        stack.append(operand1 in operand2)
                instr = instr.next
            elif opcode == IS_OP:
                operand2 = stack.pop()
                operand1 = stack.pop()
                if (operand1 is PENDING) or (operand2 is PENDING):
                    stack.append(PENDING)
                elif instr.arg:
                    stack.append(operand1 is not operand2)
                else:
                    stack.append(operand1 is operand2)
                instr = instr.next
            elif opcode == UNARY_NEGATIVE:
                operand = stack[-1]
                if operand is not PENDING:
                    stack[-1] = -shadows.get(id(operand), operand)
                instr = instr.next
            elif opcode == UNARY_INVERT:
                operand = stack[-1]
                if operand is not PENDING:
                    stack[-1] = ~shadows.get(id(operand), operand)
                instr = instr.next
            elif opcode == UNARY_NOT:
                operand = stack[-1]
                if operand is not PENDING:
                    stack[-1] = not shadows.get(id(operand), operand)
                instr = instr.next
            elif opcode == LOAD_ATTR:
                value = stack[-1]
                if instr.arg & 1:
                    stack[-1] = None
                    if value is PENDING:
                        stack.append(PENDING)
                    else:
                        stack.append(getattr(value, instr.argval))
                elif value is PENDING:
                    stack[-1] = PENDING
                else:
                    stack[-1] = getattr(value, instr.argval)
                instr = instr.next
            elif (opcode == RETURN_VALUE) or (opcode == RETURN_CONST):
                value = stack.pop() if opcode == RETURN_VALUE else instr.argval
                if do_return(value):
                    break
            elif opcode == BUILD_MAP:
                pairs = [(stack.pop(), stack.pop())[::-1] for _ in range(instr.arg)][
                    ::-1
                ]
                if any((y is PENDING) for x in pairs for y in x):
                    stack.append(PENDING)
                else:
                    stack.append(dict(pairs))
                instr = instr.next
            elif opcode == BUILD_CONST_KEY_MAP:
                keys = stack.pop()
                values = [stack.pop() for _ in range(instr.arg)][::-1]
                if (keys is PENDING) or any(v is PENDING for v in values):
                    stack.append(PENDING)
                else:
                    stack.append(dict(zip(keys, values)))
                instr = instr.next
            elif (
                (opcode == BUILD_LIST)
                or (opcode == BUILD_TUPLE)
                or (opcode == BUILD_SET)
            ):
                elems = [stack.pop() for _ in range(instr.arg)][::-1]
                if any((x is PENDING) for x in elems):
                    stack.append(PENDING)
                else:
                    stack.append(
                        tuple(elems)
                        if opcode == BUILD_TUPLE
                        else set(elems)
                        if opcode == BUILD_SET
                        else elems
                    )
                instr = instr.next
            elif opcode == BUILD_STRING:
                elems = [stack.pop() for _ in range(instr.arg)][::-1]
                if any((x is PENDING) for x in elems):
                    stack.append(PENDING)
                else:
                    stack.append("".join(elems))
                instr = instr.next
            elif opcode == MAP_ADD:
                value = stack.pop()
                key = stack.pop()
                target = stack[-instr.argval]
                if (
                    (value is not PENDING)
                    and (key is not PENDING)
                    and (target is not PENDING)
                ):
                    if (target_sh := shadows.get(id(target), sentinel)) is sentinel:
                        shadows[id(target)] = target_sh = copy(target)
                        swodahs[id(target_sh)] = target
                    target_sh[key] = value
                instr = instr.next
            elif (opcode == DICT_UPDATE) or (opcode == DICT_MERGE):
                source = stack.pop()
                target = stack[-instr.argval]
                if (source is not PENDING) and (target is not PENDING):
                    source = shadows.get(id(source), source)
                    if (target_sh := shadows.get(id(target), sentinel)) is sentinel:
                        shadows[id(target)] = target_sh = copy(target)
                        swodahs[id(target_sh)] = target
                    if (opcode == DICT_UPDATE) or source.keys().isdisjoint(
                        target_sh.keys()
                    ):
                        target_sh.update(source)
                instr = instr.next
            elif opcode == SWAP:
                argval = instr.argval
                stack[-argval], stack[-1] = stack[-1], stack[-argval]
                instr = instr.next
            elif opcode == COPY:
                argval = instr.argval
                stack.append(stack[-argval])
                instr = instr.next
            elif opcode == FOR_ITER:
                if stack[-1] is PENDING:
                    stack.append(PENDING)
                    instr = instr.jump
                else:
                    if (it := shadows.get(id(stack[-1]), sentinel)) is sentinel:
                        shadows[id(stack[-1])] = it = copy(stack[-1])
                        swodahs[id(it)] = stack[-1]
                    try:
                        value = next(it)
                    except StopIteration:
                        stack.append(PENDING)
                        instr = instr.jump
                    else:
                        stack.append(value)
                        instr = instr.next
            elif opcode == END_FOR:
                stack.pop()
                stack.pop()
                instr = instr.next
            elif (
                (opcode == LIST_APPEND)
                or (opcode == LIST_EXTEND)
                or (opcode == SET_ADD)
            ):
                ext = stack.pop()
                container = stack[-instr.argval]
                if (container is not PENDING) and (ext is not PENDING):
                    if (sh := shadows.get(id(container), sentinel)) is sentinel:
                        shadows[id(container)] = sh = copy(container)
                        swodahs[id(sh)] = container
                    if opcode == LIST_APPEND:
                        sh.append(ext)
                    elif opcode == SET_ADD:
                        sh.add(ext)
                    else:
                        sh.extend(shadows.get(id(ext), ext))
                instr = instr.next
            elif (opcode == JUMP_BACKWARD) or (opcode == JUMP_FORWARD):
                instr = instr.jump
            elif opcode == BEFORE_WITH:
                stack.pop()
                stack.append(PENDING)
                stack.append(PENDING)
                instr = instr.next
            elif (opcode == POP_TOP) or (opcode == POP_EXCEPT):
                stack.pop()
                instr = instr.next
            elif (
                (opcode == POP_JUMP_IF_TRUE)
                or (opcode == POP_JUMP_IF_FALSE)
                or (opcode == POP_JUMP_IF_NONE)
                or (opcode == POP_JUMP_IF_NOT_NONE)
            ):
                value = stack.pop()
                if value is PENDING:
                    copied_shadows = {}
                    copied_swodahs = {}
                    for k, v in shadows.items():
                        copied_shadows[k] = copied_v = copy(v)
                        copied_swodahs[id(copied_v)] = swodahs[id(v)]
                    if (len(jump_frames) < max_jump_width) and (depth < max_jump_depth):
                        jump_frames.append(
                            State(
                                frame=frame.copy(instr=instr.jump),
                                shadows=copied_shadows,
                                swodahs=copied_swodahs,
                                depth=depth + 1,
                            )
                        )
                    instr = instr.next
                elif (
                    (opcode == POP_JUMP_IF_TRUE and shadows.get(id(value), value))
                    or (
                        opcode == POP_JUMP_IF_FALSE
                        and not shadows.get(id(value), value)
                    )
                    or (opcode == POP_JUMP_IF_NONE and (value is None))
                    or (opcode == POP_JUMP_IF_NOT_NONE and (value is not None))
                ):
                    instr = instr.jump
                else:
                    instr = instr.next
            elif opcode == PUSH_NULL:
                stack.append(None)
                instr = instr.next
            elif opcode == MAKE_FUNCTION:
                flags = instr.arg
                code = stack.pop()
                closure = stack.pop() if flags & 0x08 else None
                annotations = stack.pop() if flags & 0x04 else None
                kwdefaults = stack.pop() if flags & 0x02 else None
                defaults = stack.pop() if flags & 0x01 else None
                if any(
                    (x is PENDING)
                    for x in (code, closure, annotations, kwdefaults, defaults)
                ):
                    stack.append(PENDING)
                else:
                    func = FunctionType(
                        code, frame.f_globals, code.co_name, defaults, closure
                    )
                    if kwdefaults is not None:
                        func.__kwdefaults__ = kwdefaults
                    if annotations is not None:
                        func.__annotations__ = dict(
                            zip(annotations[::2], annotations[1::2])
                        )
                    stack.append(func)
                instr = instr.next
            elif opcode == KW_NAMES:
                frame.kw_names = instr.argval
                instr = instr.next
            elif opcode == LOAD_DEREF:
                stack.append(frame.f_locals[instr.argval])
                instr = instr.next
            elif opcode == BINARY_SLICE:
                end = stack.pop()
                start = stack.pop()
                container = stack.pop()
                if (container is PENDING) or (start is PENDING) or (end is PENDING):
                    stack.append(PENDING)
                else:
                    stack.append(shadows.get(id(container), container)[start:end])
                instr = instr.next
            elif opcode == UNPACK_SEQUENCE:
                count = instr.arg
                arr = stack.pop()
                if arr is PENDING:
                    stack.extend([PENDING for _ in range(count)])
                else:
                    arr = shadows.get(id(arr), arr)
                    assert len(arr) == count
                    stack.extend(arr[: -count - 1 : -1])
                instr = instr.next
            elif opcode == BINARY_SUBSCR:
                key = stack.pop()
                container = stack.pop()
                if (container is PENDING) or (key is PENDING):
                    stack.append(PENDING)
                else:
                    stack.append(shadows.get(id(container), container)[key])
                instr = instr.next
            elif opcode == FORMAT_VALUE:
                conv, with_spec = instr.argval
                fmt_spec = stack.pop() if with_spec else ""
                value = stack.pop()
                if (value is PENDING) or (fmt_spec is PENDING):
                    stack.append(PENDING)
                else:
                    value = shadow_deepcopy(value, Memo(shadows=shadows))
                    if conv is not None:
                        value = conv(value)
                    stack.append(format(value, fmt_spec))
                instr = instr.next
            elif opcode == GET_ITER:
                stack[-1] = iter(stack[-1]) if stack[-1] is not PENDING else PENDING
                instr = instr.next
            elif (
                (opcode == CACHE)
                or (opcode == RESUME)
                or (opcode == MAKE_CELL)
                or (opcode == COPY_FREE_VARS)
                or (opcode == EXTENDED_ARG)
                or (opcode == NOP)
            ):
                instr = instr.next
            else:
                if do_return():
                    break
        except Exception:
            if do_return():
                break


def _skip_frames(frame: Optional[Frame]) -> Optional[Frame]:
    if frame is None:
        return
    while not (
        (frame.f_code is not None)
        and (
            (frame.f_code in sources) or (frame.f_code.co_filename in filename_sources)
        )
    ):
        frame = frame.f_back
        if frame is None:
            return
        frame.stack.append(PENDING)
    return frame


def _instructions_from_code(code: CodeType):
    instructions = sources.get(code)
    if instructions is not None:
        return instructions
    if code.co_filename not in filename_sources:
        return None
    sources[code] = instructions = instructions_from_code(code)
    return instructions


def add_source(src: FunctionType | CodeType | str):
    if isinstance(src, FunctionType):
        sources[src.__code__] = instructions_from_code(src.__code__)
    elif isinstance(src, CodeType):
        sources[src] = instructions_from_code(src)
    elif isinstance(src, str):
        filename_sources.add(src)
    else:
        raise TypeError(
            f"Expected a function or code object or filename, got {type(src).__name__}"
        )
    return src


def add_inline(func: Callable):
    methods[func] = MethodType.DEEP_READ
    return func


def add_target(func: Callable):
    methods[func] = MethodType.TARGET
    return func
