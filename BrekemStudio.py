"""BREKEM STUDIO - top entry point.

Behaviours (one binary, several roles):
  BrekemStudio.exe                       -> launch the GUI
  BrekemStudio.exe -m demucs ...         -> act as `python -m demucs`
  BrekemStudio.exe <path-to>.py <args>   -> run that engine script as __main__
  BrekemStudio.exe cli <subcommand> ...  -> run the headless orchestrator
  BrekemStudio.exe -c "<code>"           -> act as `python -c` (libraries that spawn helpers)
The .py / -m dispatch is what lets the frozen build call its own engine
scripts as child processes without a separate Python interpreter.
BrekemStudioCLI.exe is the same program built as a console app: the engines run
through it so their output (and progress bars) always has a real stdout.
"""
import os
import sys
import runpy


def _dispatch():
    a = sys.argv[1:]
    if not a:
        return False
    if a[0] == "-c" and len(a) >= 2:
        sys.argv = ["-c"] + a[2:]
        exec(compile(a[1], "<string>", "exec"), {"__name__": "__main__"})
        return True
    if a[0] == "-m" and len(a) >= 2:
        mod = a[1]
        sys.argv = [mod] + a[2:]
        runpy.run_module(mod, run_name="__main__", alter_sys=True)
        return True
    if a[0].lower().endswith(".py") and os.path.exists(a[0]):
        script = a[0]
        sys.argv = [script] + a[1:]
        sys.path.insert(0, os.path.dirname(os.path.abspath(script)))
        runpy.run_path(script, run_name="__main__")
        return True
    if a[0] == "cli":
        sys.argv = ["brekem_cli"] + a[1:]
        import brekem_cli
        brekem_cli._cli()
        return True
    return False


def main():
    import multiprocessing
    multiprocessing.freeze_support()          # a frozen multiprocessing child never reaches the GUI
    for k in ("stdout", "stderr"):            # windowed build: no console -> give print/tqdm a sink
        if getattr(sys, k) is None:
            setattr(sys, k, open(os.devnull, "w"))
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    if _dispatch():
        return
    if len(sys.argv) > 1:                     # unknown args (a helper process): never open the GUI
        sys.exit(f"BrekemStudio: unknown arguments {sys.argv[1:]!r}")
    import brekem_env as E
    E.apply_env()
    import brekem_gui
    brekem_gui.main()


if __name__ == "__main__":
    main()
