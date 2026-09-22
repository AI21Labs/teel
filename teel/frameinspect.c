#define PY_SSIZE_T_CLEAN
#define Py_BUILD_CORE 1

#include <Python.h>
#include <frameobject.h>
#include "internal/pycore_frame.h"
#include "internal/pycore_code.h"

static inline _PyInterpreterFrame *
get_iframe(PyObject *frame)
{
    if (!PyFrame_Check(frame)) {
        PyErr_Format(
            PyExc_TypeError,
            "expected a frame object, got %.200s",
            Py_TYPE(frame)->tp_name
        );
        return NULL;
    }

    _PyInterpreterFrame *iframe = ((PyFrameObject *)frame)->f_frame;
    if (iframe == NULL) {
        PyErr_SetString(
            PyExc_RuntimeError,
            "frame object has no underlying interpreter frame"
        );
        return NULL;
    }

    return iframe;
}

static PyObject *
frameinspect_getvaluestack(PyObject *self, PyObject *args)
{
    PyObject *frame;
    Py_ssize_t depth = -1;

    if (!PyArg_ParseTuple(args, "O|n:getvaluestack", &frame, &depth)) {
        return NULL;
    }

    _PyInterpreterFrame *iframe = get_iframe(frame);
    if (iframe == NULL) {
        return NULL;
    }

    PyObject **base = _PyFrame_Stackbase(iframe);

    if (depth < 0) {
        depth = (iframe->stacktop < 0) ? 0 : (iframe->localsplus + iframe->stacktop) - base;
        if (depth < 0) {
            depth = 0;
        }
    }

    if (depth > iframe->f_code->co_stacksize) {
        PyErr_Format(
            PyExc_ValueError,
            "getvaluestack() depth %zd out of range "
            "for co_stacksize %d",
            depth,
            iframe->f_code->co_stacksize
        );
        return NULL;
    }

    PyObject *result = PyList_New(depth);
    if (result == NULL) {
        return NULL;
    }

    for (Py_ssize_t i = 0; i < depth; i++) {
        PyObject *item = base[i];
        if (item == NULL) {
            item = Py_None;
        }
        Py_INCREF(item);
        PyList_SET_ITEM(result, i, item);
    }

    return result;
}

static PyObject *
frameinspect_getcells(PyObject *self, PyObject *frame)
{
    _PyInterpreterFrame *iframe = get_iframe(frame);
    if (iframe == NULL) {
        return NULL;
    }

    PyCodeObject *co = iframe->f_code;
    PyObject *names = co->co_localsplusnames;
    PyObject *kinds = co->co_localspluskinds;
    int n = co->co_nlocalsplus;

    PyObject *result = PyDict_New();
    if (result == NULL) {
        return NULL;
    }

    for (int i = 0; i < n; i++) {
        if (!(_PyLocals_GetKind(kinds, i) & (CO_FAST_CELL | CO_FAST_FREE))) {
            continue;
        }
        PyObject *cell = iframe->localsplus[i];
        if (cell == NULL) {
            cell = Py_None;
        }
        PyObject *name = PyTuple_GET_ITEM(names, i);
        if (PyDict_SetItem(result, name, cell) < 0) {
            Py_DECREF(result);
            return NULL;
        }
    }

    return result;
}

static PyMethodDef frameinspect_methods[] = {
    {"getcells", frameinspect_getcells, METH_O,
     "getcells(frame) -> dict\n\n"
     "Return the frame's cells."},
    {"getvaluestack", frameinspect_getvaluestack, METH_VARARGS,
     "getvaluestack(frame[, depth]) -> list\n\n"
     "Return the frame's value stack, top last.\n"
     "If depth is given it is used as stack depth, otherwise it is obtained from the frame.\n"},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef frameinspect_module = {
    PyModuleDef_HEAD_INIT,
    "teel.frameinspect",
    "Inspect the CPython value stack of frame objects.",
    -1,
    frameinspect_methods,
    NULL, NULL, NULL, NULL
};

PyMODINIT_FUNC
PyInit_frameinspect(void)
{
    return PyModule_Create(&frameinspect_module);
}
