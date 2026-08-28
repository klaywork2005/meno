"""Entry point shim so ``python main.py`` starts the application.

Equivalent to ``python -m meno``, or the ``meno`` command after installation.
Also the entry script named by ``meno.spec``: PyInstaller executes its entry
script as a top-level module, which a module using relative imports cannot be.
"""

from meno.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
