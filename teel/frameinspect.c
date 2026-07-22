/* frameinspect: expose the CPython value stack of a frame object.
 *
 * Built specifically against CPython 3.12.13. The internal frame layout
 * (_PyInterpreterFrame, _PyFrame_Stackbase) is not part of the stable ABI,
 * so this needs the internal headers and Py_BUILD_CORE. Do NOT expect this
 * to work unchanged on a different 3.x minor version.
 */

#define PY_SSIZE_T_CLEAN
#define Py_BUILD_CORE 1

#include <Python.h>
#include <frameobject.h>              /* PyFrame_Type / PyFrame_Check */
#include "internal/pycore_frame.h"    /* _PyInterpreterFrame, _PyFrame_Stackbase */
#include "internal/pycore_code.h"     /* CO_FAST_CELL / CO_FAST_FREE, _PyLocals_GetKind */

/* getvaluestack(frame) -> list
 *
 * Return a new list holding the objects currently on `frame`'s evaluation
 * (value) stack, bottom first. The value stack is the region of the frame's
 * `localsplus` array that sits above the locals/cells/frees, i.e. between
 * `_PyFrame_Stackbase(iframe)` and `iframe->localsplus + iframe->stacktop`.
 *
 * Each returned object gets a new strong reference (the list owns it), so the
 * result is safe to hold onto after the frame goes away. NULL stack slots are
 * reported as None.
 */
static PyObject *
frameinspect_getvaluestack(PyObject *self, PyObject *arg)
{
    if (!PyFrame_Check(arg)) {
        PyErr_Format(PyExc_TypeError,
                     "getvaluestack() expected a frame object, got %.200s",
                     Py_TYPE(arg)->tp_name);
        return NULL;
    }

    PyFrameObject *frame = (PyFrameObject *)arg;
    _PyInterpreterFrame *iframe = frame->f_frame;
    if (iframe == NULL) {
        PyErr_SetString(PyExc_RuntimeError,
                        "frame object has no underlying interpreter frame");
        return NULL;
    }

    PyObject **base = _PyFrame_Stackbase(iframe);
    /* stacktop is the offset of TOS-from-localsplus. It is transiently set to
     * -1 while the eval loop owns the stack pointer; treat that as empty. */
    Py_ssize_t depth = (iframe->stacktop < 0)
                           ? 0
                           : (iframe->localsplus + iframe->stacktop) - base;
    if (depth < 0) {
        depth = 0;
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
        PyList_SET_ITEM(result, i, item);  /* steals the reference we took */
    }

    return result;
}

/* getcells(frame) -> dict
 *
 * Return {name: cell} for all of the frame's cells: both its cellvars (the
 * cells this frame owns and hands down to inner functions it defines) and its
 * freevars (the cells handed to this frame by its enclosing function's
 * closure).
 *
 * In 3.12 both cellvars and freevars are stored inline in `localsplus`,
 * interleaved with the plain fast-locals. The per-slot kind is recorded in
 * `co_localspluskinds` as a bitmask, and the matching name in
 * `co_localsplusnames`. The slot itself holds a PyCellObject* (not the cell's
 * value), which is exactly what we hand back. Each cell gets a new reference
 * (owned by the dict). A slot that hasn't been initialised yet (e.g. a cellvar
 * before its MAKE_CELL has executed) is reported as None.
 */
static PyObject *
frameinspect_getcells(PyObject *self, PyObject *arg)
{
    if (!PyFrame_Check(arg)) {
        PyErr_Format(PyExc_TypeError,
                     "getcells() expected a frame object, got %.200s",
                     Py_TYPE(arg)->tp_name);
        return NULL;
    }

    PyFrameObject *frame = (PyFrameObject *)arg;
    _PyInterpreterFrame *iframe = frame->f_frame;
    if (iframe == NULL) {
        PyErr_SetString(PyExc_RuntimeError,
                        "frame object has no underlying interpreter frame");
        return NULL;
    }

    PyCodeObject *co = iframe->f_code;
    PyObject *names = co->co_localsplusnames;   /* tuple, borrowed */
    PyObject *kinds = co->co_localspluskinds;   /* bytes, borrowed */
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
        PyObject *name = PyTuple_GET_ITEM(names, i);  /* borrowed */
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
     "Return {name: cell} for all of the frame's cells: both its cellvars\n"
     "(owned by this frame and shared with inner functions) and its freevars\n"
     "(handed to this frame by its enclosing function's closure). Uninitialised\n"
     "slots are reported as None; each cell is returned with a new reference."},
    {"getvaluestack", frameinspect_getvaluestack, METH_O,
     "getvaluestack(frame) -> list\n\n"
     "Return the objects on the frame's evaluation (value) stack, bottom\n"
     "first. Each object is returned with a new reference; NULL slots become\n"
     "None."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef frameinspect_module = {
    PyModuleDef_HEAD_INIT,
    "teel.frameinspect",
    "Inspect the CPython value stack of frame objects (3.12.13 only).",
    -1,
    frameinspect_methods,
    NULL, NULL, NULL, NULL
};

PyMODINIT_FUNC
PyInit_frameinspect(void)
{
    return PyModule_Create(&frameinspect_module);
}
