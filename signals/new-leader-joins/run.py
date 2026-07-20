from pathlib import Path
import sys

SIGNALS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIGNALS / "common"))

from social_post_signal import run  # noqa: E402


if __name__ == "__main__":
    print(run(Path(__file__).with_name("config.json"), SIGNALS / "exports" / "signal_leads.csv", None))
