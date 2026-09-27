# Loaded at interpreter start-up by every child of tools/supervise.py, which puts this folder
# first on the child's PYTHONPATH. It caps OpenCV's worker threads at PSF_CV_THREADS.
#
# Why here and not an environment variable: the OpenCV build in the piu-annotate venv (5.0,
# parallel framework "Concurrency") ignores OMP_NUM_THREADS and OPENCV_FOR_THREADS_NUM alike
# and starts one worker per core (20 on the owner's machine), so a decode job would take the
# whole CPU from the game he is playing. Only cv2.setNumThreads() inside the process caps it.
# The hook costs nothing for a child that never imports cv2: it waits on the import system and
# calls setNumThreads the moment cv2 finishes loading, then steps aside.
import os
import sys


def _install():
    try:
        n = int(os.environ.get("PSF_CV_THREADS", ""))
    except ValueError:
        return
    if n < 1:
        return
    import importlib.abc
    import importlib.util

    class _CapCv2Threads(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name != "cv2":
                return None
            sys.meta_path.remove(self)                 # one shot; cv2's own bootstrap re-imports itself
            spec = importlib.util.find_spec("cv2")
            if spec is None or spec.loader is None:
                return spec
            run = spec.loader.exec_module

            def exec_module(module):
                run(module)
                cv2 = sys.modules.get("cv2", module)
                try:
                    cv2.setNumThreads(n)
                except Exception:                       # never break a child over a thread cap
                    pass
            spec.loader.exec_module = exec_module
            return spec

    sys.meta_path.insert(0, _CapCv2Threads())


def _chain():
    # If the interpreter has a sitecustomize of its own further down sys.path, still run it.
    here = os.path.normcase(os.path.dirname(os.path.abspath(__file__)))
    import importlib.machinery
    rest = [p for p in sys.path if os.path.normcase(os.path.abspath(p or ".")) != here]
    spec = importlib.machinery.PathFinder.find_spec("sitecustomize", rest)
    if spec is not None and spec.loader is not None:
        import importlib.util
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)


_install()
_chain()
