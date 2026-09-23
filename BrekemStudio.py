"""BREKEM STUDIO - top entry point.

Behaviours (one binary, several roles):
  BrekemStudio.exe                       -> launch the GUI
  BrekemStudio.exe -m demucs ...         -> act as `python -m demucs`
  BrekemStudio.exe <path-to>.py <args>   -> run that engine script as __main__
  BrekemStudio.exe cli <subcommand> ...  -> run the headless orchestrator
The .py / -m dispatch is what lets the frozen build call its own engine
scripts as child processes without a separate Python interpreter.
"""
import os
import sys
import runpy


def _dispatch():
    a = sys.argv[1:]
    if not a:
        return False
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
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    if _dispatch():
        return
    import brekem_env as E
    E.apply_env()
    import brekem_gui
    brekem_gui.main()


if __name__ == "__main__":
    main()
