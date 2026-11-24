"""Calorimetric Thermal Wave Analysis Program — start here.

There is no launcher any more: the one window opens, and you choose the source
meter model when you connect.
"""

import multiprocessing

if __name__ == "__main__":
    # First thing: the frozen app spawns its analysis process. The GUI import
    # stays below this guard so a spawned child (which re-runs this file as
    # __mp_main__) never loads Qt.
    multiprocessing.freeze_support()
    from ctwa.app import main
    main()
