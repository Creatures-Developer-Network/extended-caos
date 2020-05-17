import json

with open("commandinfo.json", "rb") as f:
    COMMAND_INFO = json.loads(f.read())
