import json
import os
import threading

from .models import EmailWebStoredConfig


CONFIG_FILE = "/home/root/.ne/email_web.json"
_lock = threading.Lock()


def load_config(path=CONFIG_FILE) -> EmailWebStoredConfig:
    with _lock:
        try:
            with open(path, "r", encoding="utf-8") as config_file:
                return EmailWebStoredConfig(**json.load(config_file))
        except (FileNotFoundError, OSError, TypeError, ValueError,
                json.JSONDecodeError):
            return EmailWebStoredConfig()


def save_config(config: EmailWebStoredConfig, path=CONFIG_FILE) -> None:
    directory = os.path.dirname(path)
    temporary = path + ".tmp"
    with _lock:
        os.makedirs(directory, exist_ok=True)
        try:
            with open(temporary, "w", encoding="utf-8") as config_file:
                json.dump(config.dict(), config_file, sort_keys=True)
                config_file.write("\n")
                config_file.flush()
                os.fsync(config_file.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        except OSError:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
