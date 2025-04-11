from collections import defaultdict
import json
import os
from subprocess import Popen, PIPE

try:
    from subprocess import DEVNULL
except ImportError:
    import os

    DEVNULL = open(os.devnull, "wb")


def _op(cmd, args):
    pipe = Popen(["op", cmd] + list(args), stdout=PIPE, stderr=PIPE)
    out, err = pipe.communicate()
    return out.decode("UTF-8", "replace").strip()


def item(uuid, fields):
    data = _op(
        "item", ["get", uuid, "--reveal", "--format", "json", "--fields", fields]
    )

    fields_dict = defaultdict(str)

    if len(data) == 0:
        return fields_dict
    elif data[0] == "[":
        fields_dict.update({item["id"]: item["value"] for item in json.loads(data)})
    else:
        item = json.loads(data)
        fields_dict.update({item["id"]: item["value"]})

    return fields_dict
