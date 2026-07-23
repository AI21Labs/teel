from setuptools import Extension, setup

setup(
    ext_modules=[
        Extension(
            "teel.frameinspect",
            sources=["teel/frameinspect.c"],
            define_macros=[("Py_BUILD_CORE", "1")],
        )
    ],
)
