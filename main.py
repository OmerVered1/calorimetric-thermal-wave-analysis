"""Calorimetric Thermal Wave Analysis Program — start here.

There is no launcher any more: the one window opens, and you choose the source
meter model when you connect.
"""

import multiprocessing

from ctwa.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()  # first thing: the frozen app spawns its analysis process
    main()
