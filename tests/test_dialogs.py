import unittest

from mmd_cli import dialogs


def ctl(cid, cls, text=""):
    return {"id": cid, "cls": cls, "text": text, "hwnd": 1000 + cid, "visible": True}


def make(title, controls, cls="#32770"):
    return dialogs.Dialog(hwnd=1, cls=cls, title=title, controls=controls)


# descriptions captured from MMD v9.32 on Windows 11 (Japanese UI)
MODEL_INFO = make("モデル情報", [ctl(1, "Button", "OK"), ctl(2, "Button", "キャンセル"),
                                ctl(65535, "Static", "PolyMo用モデルデータ：初音ミク ver.1.3\n(物理演算対応モデル)")])
MOTION_CONFIRM = make("モーションデータ読込", [
    ctl(1, "Button", "OK"), ctl(2, "Button", "キャンセル"),
    ctl(65535, "Static", "このファイルは test用のモーションデータです\n同じボーン名のモーションのみを取り込む事になります\n続行しますか？")])
NEW_CONFIRM = make("新規作成", [ctl(1, "Button", "OK"), ctl(2, "Button", "キャンセル"),
                               ctl(65535, "Static", "現在の状態は破棄されます\n\nよろしいですか？")])
SAVE_DIALOG = make("ファイルを保存する", [ctl(0, "ComboBox"), ctl(1001, "Edit"), ctl(1, "Button", "保存(&S)"),
                                         ctl(2, "Button", "キャンセル"), ctl(1038, "Button", "ヘルプ(&H)")])
OPEN_DIALOG = make("ファイルを開く", [ctl(1148, "ComboBoxEx32"), ctl(1148, "ComboBox"), ctl(1148, "Edit"),
                                      ctl(1136, "ComboBox"), ctl(1, "Button", "開く(&O)"), ctl(2, "Button", "キャンセル")])
AVI_SETTINGS = make("AVI出力設定", [ctl(612, "Edit", "  640"), ctl(613, "Edit", "  360"), ctl(611, "Edit", "30"),
                                   ctl(609, "Edit"), ctl(610, "Edit"), ctl(628, "ComboBox", "未圧縮"),
                                   ctl(1, "Button", "OK"), ctl(2, "Button", "ｷｬﾝｾﾙ")])
OUTPUT_SIZE = make("出力画面サイズ変更", [ctl(621, "Edit", "640"), ctl(622, "Edit", "360"),
                                         ctl(1, "Button", "OK"), ctl(2, "Button", "ｷｬﾝｾﾙ")])
RECORDING = make("録画中(0 frame)", [], cls="RecWindow")
ABOUT = make("About", [ctl(2, "Button", "OK"), ctl(65535, "Static", "MikuMikuDance Ver.9.32")])
D3D_ERROR = make("Direct3D::Init", [ctl(2, "Button", "OK"), ctl(65535, "Static", "CreateDevice Failed!")])
NUMERIC = make("数値入力(カメラ)", [ctl(637, "Edit", "  0.000"), ctl(1, "Button", "OK"), ctl(2, "Button", "ｷｬﾝｾﾙ")])


class ClassifyTest(unittest.TestCase):
    def test_known_dialogs(self):
        cases = [(MODEL_INFO, "model_info"), (MOTION_CONFIRM, "motion_confirm"), (NEW_CONFIRM, "new_confirm"),
                 (SAVE_DIALOG, "file_dialog"), (OPEN_DIALOG, "file_dialog"), (AVI_SETTINGS, "avi_settings"),
                 (OUTPUT_SIZE, "output_size"), (RECORDING, "recording")]
        for dialog, want in cases:
            self.assertEqual(dialogs.classify(dialog), want, dialog.title)

    def test_plain_message_boxes_are_messages(self):
        self.assertEqual(dialogs.classify(ABOUT), "message")
        self.assertEqual(dialogs.classify(D3D_ERROR), "message")

    def test_dialogs_with_inputs_that_are_not_known_are_unknown(self):
        self.assertEqual(dialogs.classify(NUMERIC), "unknown")

    def test_a_file_dialog_is_recognised_by_its_controls_not_its_title(self):
        renamed = make("画像ファイル出力", SAVE_DIALOG.controls)
        self.assertEqual(dialogs.classify(renamed), "file_dialog")


class DialogTest(unittest.TestCase):
    def test_message_joins_the_static_texts(self):
        self.assertEqual(NEW_CONFIRM.message, "現在の状態は破棄されます\n\nよろしいですか？")

    def test_buttons_lists_labels_with_ids(self):
        self.assertEqual(MODEL_INFO.buttons, [(1, "OK"), (2, "キャンセル")])

    def test_find_button_by_label_prefix_or_id(self):
        self.assertEqual(SAVE_DIALOG.find_button("保存")["id"], 1)
        self.assertEqual(SAVE_DIALOG.find_button(2)["text"], "キャンセル")
        self.assertIsNone(SAVE_DIALOG.find_button("はい"))

    def test_file_name_edit_prefers_the_known_ids(self):
        self.assertEqual(SAVE_DIALOG.file_name_edit()["id"], 1001)
        self.assertEqual(OPEN_DIALOG.file_name_edit()["cls"], "Edit")

    def test_to_json_is_what_the_cli_reports(self):
        self.assertEqual(ABOUT.to_json(), {"hwnd": 1, "kind": "message", "title": "About",
                                           "message": "MikuMikuDance Ver.9.32", "buttons": ["OK"]})


if __name__ == "__main__":
    unittest.main()
