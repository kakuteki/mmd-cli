"""Describe and classify the windows MMD opens on top of its main window.

This module has no Win32 calls: guard.py builds Dialog objects from live windows and uses
classify() to decide how to answer them.
"""

FILE_NAME_EDIT_IDS = (1148, 1001)   # old style open dialog / new style save dialog

_TITLE_KINDS = {
    "モデル情報": "model_info",
    "モーションデータ読込": "motion_confirm",
    "新規作成": "new_confirm",
    "AVI出力設定": "avi_settings",
    "出力画面サイズ変更": "output_size",
}


class Dialog:
    def __init__(self, hwnd, cls, title, controls):
        self.hwnd = hwnd
        self.cls = cls
        self.title = title
        self.controls = controls

    @property
    def message(self):
        return "\n".join(c["text"] for c in self.controls if c["cls"] == "Static" and c["text"])

    @property
    def buttons(self):
        return [(c["id"], c["text"]) for c in self.controls
                if c["cls"] == "Button" and c["text"] and c.get("visible", True)]

    def find_button(self, label_or_id):
        for c in self.controls:
            if c["cls"] != "Button":
                continue
            if isinstance(label_or_id, int):
                if c["id"] == label_or_id:
                    return c
            elif c["text"] and c["text"].startswith(label_or_id):
                return c
        return None

    def find_control(self, cid, cls=None):
        for c in self.controls:
            if c["id"] == cid and (cls is None or c["cls"] == cls):
                return c
        return None

    def file_name_edit(self):
        for cid in FILE_NAME_EDIT_IDS:
            c = self.find_control(cid, "Edit")
            if c is not None:
                return c
        return None

    @property
    def kind(self):
        return classify(self)

    def to_json(self):
        return {"hwnd": self.hwnd, "kind": self.kind, "title": self.title, "message": self.message,
                "buttons": [text for _, text in self.buttons]}


def classify(dialog):
    if dialog.cls == "RecWindow":
        return "recording"
    if dialog.cls != "#32770":
        return "unknown"
    if dialog.file_name_edit() is not None and dialog.find_button(1) is not None:
        return "file_dialog"
    kind = _TITLE_KINDS.get(dialog.title)
    if kind:
        return kind
    if dialog.controls and all(c["cls"] in ("Static", "Button") for c in dialog.controls):
        return "message"
    return "unknown"
