import time


def log(msg: str) -> None:
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)
