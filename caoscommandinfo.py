import json

with open("commandinfo.json", "rb") as f:
    COMMAND_INFO = json.loads(f.read())

COMMAND_INFO_C3 = list(COMMAND_INFO["variants"]["c3"].values())
# TODO: fix openc2e so it has the correct command info for FACE
# FACE is apparently a command that differs depending on the expected return type
# - it can be either a string or an integer. Openc2e handles this by defining
# two different commands
i = 0
while i < len(COMMAND_INFO_C3):
    if COMMAND_INFO_C3[i]["name"] in ("FACE STRING", "FACE INT"):
        del COMMAND_INFO_C3[i]
    else:
        i += 1

COMMAND_INFO_C3.append(
    {
        "namespace": "",
        "arguments": [],
        "type": "anything",
        "match": "FACE",
        "name": "FACE",
    }
)
