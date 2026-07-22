"""Build the frameinspect C extension.

All package metadata lives in pyproject.toml (PEP 621). This file exists only
to declare the ext_modules, which PEP 621 cannot express. See teel/frameinspect.c.
"""

from setuptools import Extension, setup

setup(
    ext_modules=[
        Extension(
            "teel.frameinspect",
            sources=["teel/frameinspect.c"],
            # Internal headers (internal/pycore_frame.h) require Py_BUILD_CORE.
            define_macros=[("Py_BUILD_CORE", "1")],
        )
    ],
)
