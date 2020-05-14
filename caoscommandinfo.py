import json

with open("commandinfo.json", "rb") as f:
    COMMAND_INFO = json.loads(f.read())

COMMAND_INFO_C3 = COMMAND_INFO["variants"]["c3"]
COMMAND_NAMESPACES = { _.get("namespace") for _ in COMMAND_INFO_C3.values() if _.get("namespace") }