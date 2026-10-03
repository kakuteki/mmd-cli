"""Read and write VPD (Vocaloid Pose Data) files: cp932 text listing bone translations and quaternions."""
import re
from dataclasses import dataclass, field
from typing import List, Tuple

HEADER = "Vocaloid Pose Data file"
ENCODING = "cp932"

_BLOCK = re.compile(r"Bone\d+\{([^\r\n]*)\r?\n(.*?)\}", re.S)
_NUMBERS = re.compile(r"^\s*([-+0-9.eE,\s]+);", re.M)


@dataclass
class PoseBone:
    name: str
    position: Tuple[float, float, float]
    rotation: Tuple[float, float, float, float]


@dataclass
class Pose:
    model_file: str = "model.osm"
    bones: List[PoseBone] = field(default_factory=list)


def _strip_comments(text):
    return re.sub(r"//[^\r\n]*", "", text)


def loads(data):
    text = data.decode(ENCODING, "replace") if isinstance(data, (bytes, bytearray)) else data
    if not text.lstrip().startswith(HEADER):
        raise ValueError("not a VPD file (bad header)")
    body = _strip_comments(text)
    head = body.split("Bone", 1)[0]
    names = re.findall(r"^\s*([^;\r\n]+);", head, re.M)
    pose = Pose(model_file=names[0].strip() if names else "")
    for m in _BLOCK.finditer(body):
        rows = [[float(x) for x in row.split(",")] for row in _NUMBERS.findall(m.group(2))]
        if len(rows) < 2 or len(rows[0]) != 3 or len(rows[1]) != 4:
            raise ValueError("bone %r needs a translation (3 numbers) and a quaternion (4 numbers)"
                             % m.group(1).strip())
        pose.bones.append(PoseBone(m.group(1).strip(), tuple(rows[0]), tuple(rows[1])))
    return pose


def dumps(pose):
    lines = [HEADER, "", "%s;\t\t// 親ファイル名" % pose.model_file,
             "%d;\t\t\t\t// 総ポーズボーン数" % len(pose.bones), ""]
    for i, b in enumerate(pose.bones):
        lines.append("Bone%d{%s" % (i, b.name))
        lines.append("  %f,%f,%f;\t\t\t\t// trans x,y,z" % tuple(b.position))
        lines.append("  %f,%f,%f,%f;\t\t// Quatanion x,y,z,w" % tuple(b.rotation))
        lines.append("}")
        lines.append("")
    return ("\r\n".join(lines) + "\r\n").encode(ENCODING)


def load(path):
    with open(path, "rb") as f:
        return loads(f.read())


def dump(pose, path):
    with open(path, "wb") as f:
        f.write(dumps(pose))
