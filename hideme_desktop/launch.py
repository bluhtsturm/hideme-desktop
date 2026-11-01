"""Startskript für ``python3 -I`` (isolierter Modus, kein Import aus dem Arbeitsverzeichnis)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if len(sys.argv) > 1 and sys.argv[1] == "--ctl":
    from hideme_desktop.ctl import main as ctl_main
    sys.argv = ["hidemectl"] + sys.argv[2:]
    sys.exit(ctl_main())

from hideme_desktop.main import main  # noqa: E402

sys.exit(main())
