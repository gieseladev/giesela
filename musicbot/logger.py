from datetime import datetime

from .config import ConfigDefaults

logger_version = "1.0"

logs = []


def save_logs():
    global logs
    if logs is None or len(logs) < 1:
        return

    file_loc = ConfigDefaults.log_file + datetime.now().date().isoformat() + ".txt"
    log_str = ""

    for l in logs:
        log_str += "[{}:{}] {}\n".format(l[0].hour, l[0].minute, l[1])

    with open(file_loc, "a+") as f:
        f.write(log_str)

    logs = []


def log(msg = "\n"):
    s_msg = str(msg)
    logs.append((datetime.now(), msg))
    print(msg)
    save_logs()
