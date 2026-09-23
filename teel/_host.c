/* Guest side of the teel host ABI, built only into the WASI interpreter.
 *
 * The guest owns its linear memory: the host never allocates in it and only
 * writes into buffers the guest passes in. A response is fetched in two steps
 * (teel.next reports its length, teel.read copies it), so the guest needs no
 * exported allocator and the host never re-enters the guest.
 *
 *   submit(req_ptr, req_len) -> token >= 0, or < 0 on failure
 *   next(token_out_ptr)      -> response length >= 0, or < 0 on failure;
 *                               blocks until any submitted request completes
 *   read(buf_ptr, buf_len)   -> bytes copied, or < 0 on failure
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdint.h>

#define TEEL_IMPORT(name) \
    __attribute__((import_module("teel"), import_name(name)))

TEEL_IMPORT("submit") int32_t teel_submit(const char *req, int32_t req_len);
TEEL_IMPORT("next") int32_t teel_next(int32_t *token_out);
TEEL_IMPORT("read") int32_t teel_read(char *buf, int32_t buf_len);

static PyObject *
host_submit(PyObject *self, PyObject *arg)
{
    char *req;
    Py_ssize_t req_len;

    if (PyBytes_AsStringAndSize(arg, &req, &req_len) < 0) {
        return NULL;
    }
    if (req_len > INT32_MAX) {
        PyErr_SetString(PyExc_OverflowError, "request too large");
        return NULL;
    }

    int32_t token = teel_submit(req, (int32_t)req_len);
    if (token < 0) {
        PyErr_Format(PyExc_OSError, "teel.submit failed (%d)", (int)token);
        return NULL;
    }
    return PyLong_FromLong(token);
}

static PyObject *
host_next(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    int32_t token = -1;
    int32_t length;

    Py_BEGIN_ALLOW_THREADS
    length = teel_next(&token);
    Py_END_ALLOW_THREADS

    if (length < 0) {
        PyErr_Format(PyExc_OSError, "teel.next failed (%d)", (int)length);
        return NULL;
    }

    PyObject *response = PyBytes_FromStringAndSize(NULL, length);
    if (response == NULL) {
        return NULL;
    }
    int32_t copied = teel_read(PyBytes_AS_STRING(response), length);
    if (copied != length) {
        Py_DECREF(response);
        PyErr_Format(
            PyExc_OSError, "teel.read copied %d of %d bytes",
            (int)copied, (int)length
        );
        return NULL;
    }

    return Py_BuildValue("(iN)", (int)token, response);
}

static PyMethodDef host_methods[] = {
    {"submit", host_submit, METH_O,
     "submit(request: bytes) -> int\n\n"
     "Hand a request to the host and return its token without waiting."},
    {"next", host_next, METH_NOARGS,
     "next() -> tuple[int, bytes]\n\n"
     "Block until any submitted request completes; return (token, response)."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef host_module = {
    PyModuleDef_HEAD_INIT,
    "_teel_host",
    "Calls from the WASI guest to its embedding host.",
    -1,
    host_methods,
    NULL, NULL, NULL, NULL
};

PyMODINIT_FUNC
PyInit__teel_host(void)
{
    return PyModule_Create(&host_module);
}
