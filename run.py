import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from calibration_tool.gui import App
from seed_data import seed_sample_data


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "data")

    seed_sample_data(data_dir)

    app = App(data_dir=data_dir)
    app.mainloop()


if __name__ == "__main__":
    main()
