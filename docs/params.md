# 調整した値の一覧（tools/param_inventory.py が作る。手で直さない）

- 作り方: `python tools/param_inventory.py`（コードの構文木から。走らせない）。確かめ: `python tools/param_inventory.py --check`。
- 何を拾うか: 大文字の名の定数で数を持つもの（辞書はキーごと）、コマンドの引数の既定、関数の数の既定。注釈はその行と続きの行、すぐ上の注釈の塊から。拾わないもの: 関数の中に書いた数（比べの閾値など。a05 の浮きの 4 cm、fq の拍の窓 13 コマ）、クラスの属性、look・cues の JSON（hinata の look_v8.json など、リポジトリの外）。
- 単位・依存・見直しはコードの名と注釈の言葉から推した目安（印 ○）。単位の読めない長さ（SWING_MIN_H 0.2 単位など）には印が付かないので、印が無いことは見直さなくてよいことではない。「記録」の欄は `docs/params_notes.json`（HANDOVER などの記録から手で付けた出所）。
- 依存: 体 = cm・mm・m・単位の長さ・速さ・加速度（体と踊りの大きさで変わる）／重 = 重力に結んだ値／踊 = 曲・踊り・トレース・拍・版で測った値／模 = リンのモデル（White.pmx・骨・モーフ・材質・物理）で測った値／人 = 人の測りから／文 = 文献から。
- 見直し: retarget（体・重）、rig（模）、dance（踊りだけ。組み直しの後に物差しで測り直す）。
- 数: 全部 2518（定数 1992・引数 136・関数の既定 390。定数を既定にする引数 39 は定数の行に書き、数えない）、見直しの印 446（retarget 271・rig 70・踊りだけ 117）、記録の出所つき 84。

## v11 の組み直しで見直す順番（上流から）

| 順 | 段 | 道具 | 値 | retarget | rig | 踊り | 確かめの物差し（tools/mv_inspect.py） | ほかの確かめ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 模型の写し（rig の受け持ち） | pmx_rig.py・rig_skin.py・pmx_spine.py・pmx_eyes.py・pmx_skirt.py | 38 | 2 | 7 | 0 | skirt.floor_over122_frames、skirt.floor_max、pixels.pants_frames | rig_check.py・spine_check.py・skirt_probe.py |
| 2 | 踊りを体に写す（retarget の受け持ち）と手捩 | retarget.py・fix_twist.py | 67 | 25 | 2 | 1 | feet.under_floor_frames、feet.ik_miss_floor_frames、retarget.contacts_kept_share、retarget.arms_in_body_frames、retarget.toe_float_pct | motion_fk.py・retarget_check.py |
| 3 | 平滑化と手ぶれ除去（v4s） | smooth_motion.py | 18 | 1 | 0 | 0 | spikes.centre_per_min、spikes.wrist_R_per_min、spikes.wrist_L_per_min、spikes.head_per_min、arms.wrist_8hz_pct、arms.wrist_3_6hz_pct、upper.head_stop_ms | motion_jerk.py |
| 4 | 呼吸 | breath_layer.py | 60 | 6 | 0 | 3 | upper.head_stops_per_min、upper.upper_sudden_stops_per_min | - |
| 5 | 関節の拘束 | anatomy_layer.py | 70 | 6 | 2 | 5 | arms.a09_shoulder_elbow_L、arms.a09_shoulder_elbow_R | - |
| 6 | 運動（遅れと堅さ、--preset human --elbow-hinge on） | motor_layer.py | 103 | 15 | 3 | 3 | arms.a09_shoulder_elbow_L、arms.a09_shoulder_elbow_R、arms.a09_elbow_wrist_L、arms.a09_elbow_wrist_R、upper.head_sudden_stops_per_min、upper.head_stop_ms | - |
| 7 | 背骨 4 本へ配る | spine_layer.py | 9 | 1 | 0 | 0 | upper.upper_sudden_stops_per_min、upper.chest_follow | spine_check.py |
| 8 | 足（最初の足の層 feet0、--landing off。v11 から --skim on・--hover off が… | foot_layer.py | 78 | 28 | 5 | 3 | feet.under_floor_frames、feet.ik_miss_floor_frames | sink_check.py・leg_ik.py |
| 9 | 体重（順 C の balance） | balance_layer.py | 99 | 34 | 2 | 11 | gravity.centre_down_max、gravity.centre_down_gt98_pct、skirt.floor_over122_frames、skirt.floor_max、balance.com_lateral_cm、balance.moving_com_lateral_cm、balance.moving_mos_ml_cm、balance.still_com_lateral_cm、balance.touchdown_xcom_cm、gravity.landing_sink_cm、gravity.jump_apex_lowered、gravity.beat_dips_weak、spikes.centre_per_min | sink_check.py・leg_ik.py |
| 10 | 足（2 回目の足の層、--landing human。v11 から --skim on・--hover off が既定） | foot_layer.py（8 と同じ道具・同じ値） | 78 | 28 | 5 | 3 | feet.slide10_per_min、feet.slide3_per_min、feet.slide_path_cm_per_min、feet.slide_fast_share、feet.knee_gain_deg、feet.knee_straight_pct、feet.ik_new_miss_frames、gravity.hover_pct、gravity.hover_runs6_per_min、gravity.air_per_min | sink_check.py |
| 11 | 接地の計画（contact_layer） | contact_layer.py | 67 | 27 | 1 | 7 | gravity.hover_pct、gravity.hover_runs6_per_min、balance.single_share_pct、balance.zmp_inside_pct、feet.ik_new_miss_frames、gravity.jump_apex_lowered、spikes.centre_per_min | contact_check.py |
| 12 | 上体の慣性 | wb_layer.py・wb_dynamics.py | 34 | 7 | 3 | 0 | upper.head_follow、upper.chest_follow、upper.arms_follow、upper.head_follow_2_4hz、balance.zmp_inside_pct、balance.single_share_pct、balance.zmp_margin_single_cm、balance.zmp_tilt_deg_per_min | upper_body_check.py |
| 13 | 手と指、触れの層（v11arms） | hand_layer.py・touch_layer.py | 153 | 13 | 10 | 29 | arms.finger_speed_L、arms.finger_speed_R、arms.finger_wrist_ratio_L、arms.finger_wrist_ratio_R、arms.a09_wrist_finger_L、arms.a09_wrist_finger_R、arms.rests_per_min_R、retarget.contacts_kept_share、retarget.arms_in_body_frames、retarget.contacts_lost_runs、spikes.wrist_R_per_min、spikes.wrist_L_per_min、arms.wrist_8hz_pct | retarget_check.py |
| 14 | 視線 | eye_gaze.py | 105 | 4 | 2 | 4 | eyes.edge_pct、eyes.edge_longest_s、eyes.eccentric15_pct | - |
| 15 | 表情 | face_life.py | 147 | 1 | 6 | 5 | （物差しなし） | - |
| 16 | 口 | lip_sync.py・lip_timing.py | 84 | 0 | 1 | 1 | mouth.lag_median_ms、mouth.lag_open_ms、mouth.late_pct、mouth.late_open_pct、mouth.early_open_pct、mouth.shut_singing_pct | lip_check.py |
| 17 | 目の光と寄り | eye_optics.py | 88 | 13 | 3 | 0 | （物差しなし） | - |
| 18 | 描画と後処理 | mv_chunks.py・mv_world.py・stage_layer.py・mv_look.py・mv_text.py・make_stage.py・mme_shadow.py・pmm_gravity.py・mograph_layer.py | 441 | 16 | 15 | 37 | pixels.pants_frames、pixels.shadow_rough、pixels.shadow_total_rough | shadow_check.py・shadow_measure.py・selfshadow_check.py・look_analyze.py・typo_analyze.py・mograph_analyze.py |
| 19 | カメラ（加賀さんの指示で後回し） | make_camera.py | 67 | 3 | 2 | 0 | （物差しなし） | - |

各段は、その段より上流をすべて直してから測る（下流の層は上流の出力を読む）。ただしカメラ（19）と look（18）は視線（14）と目の光（17）が入力に読むので、変えたら 14〜17 を作り直す。物差しは `mv_inspect.py measure`（既定の --size hip の「股関節の高さでそろえた」値も見る）と `compare`。

## pmx_rig.py（1. 模型の写し（rig の受け持ち）、6）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HELPERS.wrist | ("{s}手首補助", "{s}手捩", "{s}手首", ("{s}手首",), ("{s}手捩", "{s}ひじ"… |  | 63 |  |  |  |  |  |  |  |  |  |
| HELPERS.shoulder | ("{s}腕補助", "{s}肩", "{s}腕", ("{s}腕W", "{s}腕"), ("{s}肩",) + T… |  | 64 |  |  |  |  |  |  |  |  |  |
| HELPERS.hip | ("{s}足補助", "腰キャンセル{s}", "{s}足D", ("{s}足D",), ("下半身", "腰キャンセ… |  | 65 |  |  |  |  |  |  |  |  |  |
| HELPER_FLAGS | 0x0002 ／ 0x0100 |  | 67 | rotatable, an append of the turn; hidden and not to be keyed (like ひじ補助) |  |  |  |  |  |  |  |  |
| BROW_UP | (0.0, 0.1992, -0.0419) |  | 69 | Sour's Rin's 上: the brow's raise, in the face's slope |  |  |  |  | ○ |  |  | rig |
| PANEL_BROW | 1 |  | 70 |  |  |  |  |  |  |  |  |  |

## rig_skin.py（1. 模型の写し（rig の受け持ち）、13）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F_IK | 0x0020 |  | 67 |  |  |  |  |  |  |  |  |  |
| F_LOCAL_APPEND | 0x0080 |  | 67 |  |  |  |  |  |  |  |  |  |
| F_TAIL_BONE | 0x0001 |  | 67 |  |  |  |  |  |  |  |  |  |
| F_AFTER_PHYSICS | 0x1000 |  | 68 |  |  |  |  |  |  |  |  |  |
| F_APPEND_ROTATE | 0x0100 |  | 68 |  |  |  |  |  |  |  |  |  |
| F_APPEND_TRANSLATE | 0x0200 |  | 68 |  |  |  |  |  |  |  |  |  |
| KIND_CODE.BDEF1 | 0 |  | 69 |  |  |  |  |  |  |  |  |  |
| KIND_CODE.BDEF2 | 1 |  | 69 |  |  |  |  |  |  |  |  |  |
| KIND_CODE.BDEF4 | 2 |  | 69 |  |  |  |  |  |  |  |  |  |
| KIND_CODE.QDEF | 4 |  | 69 |  |  |  |  |  |  |  |  |  |
| KIND_CODE.SDEF | 3 |  | 69 |  |  |  |  |  |  |  |  |  |
| IDENTITY | np.array([0.0, 0.0, 0.0, 1.0]) |  | 70 |  |  |  |  |  |  |  |  |  |
| XYZ | np.eye(3) |  | 71 |  |  |  |  |  |  |  |  |  |

## pmx_spine.py（1. 模型の写し（rig の受け持ち）、4）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| LUMBAR_Y | 12.95 | units | 37 |  | HANDOVER 2026-10-12〜13 第 4 段: 腰椎上部の骨の高さ（リンの体の割合で置いた絶対の高さ） |  |  |  |  |  |  | rig |
| THORACIC_Y | 14.85 | units | 38 |  | HANDOVER 2026-10-12〜13 第 4 段: 胸椎上部の骨の高さ（リンの体の割合で置いた絶対の高さ） |  |  |  |  |  |  | rig |
| UPPER_Y | 13.798 | units | 39 | Sour's Rin's 上半身2 (height_shares' default; build reads the model's own) | リンの上半身2 の高さ（build はモデルのものを読む） |  |  |  | ○ |  |  | rig |
| BLEND_HALF | 0.35 | units | 40 | model units (about 2.8 cm) either side of a joint | HANDOVER 2026-10-12〜13 第 4 段: 関節の両側 0.35 単位（約 2.8 cm）で重みを混ぜる | ○ |  |  |  |  |  | rig |

## pmx_eyes.py（1. 模型の写し（rig の受け持ち）、14）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HUMAN.pupil_to_centre | 4.67 |  | 73 | K: the entrance pupil to the cornea's centre of curvature (7.72 - 3.05) |  |  |  |  |  |  |  |  |
| HUMAN.iris_radius | 5.91 |  | 74 | half the visible iris (Aguirre 2019) |  |  |  |  |  |  | ○ |  |
| HUMAN.cornea_radius | 7.72 |  | 75 | the cornea's front surface (Navarro, via Barsingerhorn 2017) |  |  |  |  |  |  | ○ |  |
| HUMAN.pupil_across | 11.7 |  | 76 | d_p, the centre of rotation to the entrance pupil, turning sideways (Ohlendorf 2022) |  |  |  |  |  |  | ○ |  |
| HUMAN.pupil_up | 8.9 |  | 77 | the same turning up and down |  |  |  |  |  |  |  |  |
| FORWARD | (0.0, 0.0, -1.0) |  | 86 | the rest gaze: the model faces -Z |  |  |  |  | ○ |  |  | rig |
| APPEND_ROTATE | 0x0100 |  | 89 |  |  |  |  |  |  |  |  |  |
| NAME_BYTES | 15 |  | 90 | a VMD names a bone in 15 bytes of cp932 |  |  |  |  |  |  |  |  |
| MARGIN（引数 --margin） | 0.008 | units | 93 | model units it stays in front by at least |  | ○ |  |  |  |  |  | retarget |
| TRANSLATE | 0x0004 |  | 95 | the bone moves: tools/eye_optics.py keeps each light on the iris' surface |  |  |  |  |  |  |  |  |
| CLOSING_DROP | 0.08 |  | 96 | a morph that lowers an eye's upper light by this much on average closes its lids |  |  |  |  | ○ |  |  | rig |
| needed_lift(clear) | 0.06 |  | 262 |  |  |  |  |  |  |  |  |  |
| needed_lift(rings) | 3 |  | 262 |  |  |  |  |  |  |  |  |  |
| needed_lift(spokes) | 16 |  | 262 |  |  |  |  |  |  |  |  |  |

## pmx_skirt.py（1. 模型の写し（rig の受け持ち）、1）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FREE | 100.0 | units | 50 | a translation range never reached (model units) |  | ○ |  |  |  |  |  | retarget |

## retarget.py（2. 踊りを体に写す（retarget の受け持ち）と手捩、61）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FPS | 30.0 |  | 79 |  |  |  |  |  |  |  |  |  |
| UNIT_CM | 8.0 | cm | 80 | one unit of Sour's Rin is 8 cm (the analysis pack) |  | ○ |  |  | ○ |  |  | retarget・rig |
| IDENTITY | np.array([0.0, 0.0, 0.0, 1.0]) |  | 84 |  |  |  |  |  |  |  |  |  |
| fit(tol_deg) | 0.5 | deg | 344 |  |  |  |  |  |  |  |  |  |
| fit(tol_pos) | 0.01 |  | 344 |  |  |  |  |  |  |  |  |  |
| fit_rotations(tol_deg) | 0.5 | deg | 375 |  |  |  |  |  |  |  |  |  |
| fit_positions(tol) | 0.01 |  | 378 |  |  |  |  |  |  |  |  |  |
| place(depth) | 0 |  | 571 |  |  |  |  |  |  |  |  |  |
| _directions(n) | 98 |  | 694 |  |  |  |  |  |  |  |  |  |
| FLOOR_EPS | 0.06 | units | 800 | units (5 mm): a sole point this close to the floor touches it |  | ○ |  |  |  |  |  | retarget |
| STILL | 0.025 | units | 801 | units a frame (6 cm/s): a touching point slower than this stands |  | ○ |  |  |  |  |  | retarget |
| PLANT_MIN | 3 | frames | 802 | frames: standing this long is a plant |  |  |  |  |  |  |  |  |
| PITCH_FLAT_DEG | 4.0 | deg | 803 | a foot pitched less than this stands flat; toe down more: on the toe; toe up more: on the heel |  |  |  |  |  |  |  |  |
| MAX_PITCH_DEG | 75.0 | deg | 804 | the foot's pitch from flat at most (toe down) |  |  |  |  |  |  |  |  |
| EASE | 3 | frames | 805 | frames a correction takes to come in and to go out |  |  |  |  |  |  |  |  |
| TOUCH_FLOOR | 0.25 | units | 815 | units (2 cm) |  | ○ |  | ○ |  |  |  | retarget |
| TOUCH_RISE | 0.03 | units | 816 | units a frame (7 cm/s) |  | ○ |  |  |  |  |  | retarget |
| TOUCH_SPEED | 20.0 / UNIT_CM / FPS | units | 817 | units a frame (20 cm/s) |  | ○ |  |  |  |  |  | retarget |
| TURN_MIN | math.radians(60.0) / FPS | deg/s | 818 | radians a frame (60 degrees a second) |  |  |  |  |  |  |  |  |
| TURN_NEAR | 18.0 / UNIT_CM | units | 819 | units (18 cm): how far the turn's centre may lie from the sole's slowest point (the song's 127.9 s right foot turns 320-460 degrees a second about a point 15-17 cm off i… |  | ○ |  | ○ |  |  |  | retarget |
| LINE_T | np.linspace(-0.3, 1.0, 27) |  | 822 | the sole's line: shares of the way from the heel point to the toe point |  |  |  |  |  |  |  |  |
| TOUCH_MIN | 3 |  | 823 |  |  |  |  |  |  |  |  |  |
| AIR_H | 0.05 | units | 829 | units (4 mm) |  | ○ |  | ○ |  |  |  | retarget |
| HOLD_AIR | 6 | frames | 830 | frames |  |  |  |  |  |  |  |  |
| CLEAR_TO | 0.125 | units | 831 | units (1 cm): a carried shoe is kept as high over the floor as the source's, up to this (over main's contact_check's floor, 4 mm; under the review's 1.2 cm, within which… |  | ○ |  |  |  |  |  | retarget |
| TOUCH_PITCH_MAX | 20.0 | deg | 835 | degrees: the most a foot's pitch is changed from the source's to reach the floor, on the floor moving (the ankle comes down the rest, within FLAT_LIFT_MAX) or standing o… |  |  |  | ○ |  |  |  | dance |
| HEEL_BACK | 0.3 |  | 839 | without a shoe mesh, the heel lies this share of the ankle-to-toe line behind the ankle |  |  |  |  |  |  |  |  |
| sole_shell(cap) | 256 |  | 871 |  |  |  |  |  |  |  |  |  |
| runs(min_len) | 1 |  | 906 |  |  |  |  |  |  |  |  |  |
| PITCH_ON_FLOOR | 0.0125 | units | 998 | units (1 mm): a point this close to the floor is on it (solve_pitch takes it as found) |  | ○ |  |  |  |  |  | retarget |
| solve_pitch(step) | 0.5 |  | 1001 |  |  |  |  |  |  |  |  |  |
| FLAT_LIFT_MAX | 0.15 | units | 1045 | units (1.2 cm): a flat foot's ankle moves up or down at most this to put its sole on the floor |  | ○ |  |  |  |  |  | retarget |
| FEET_ROUNDS | 2 |  | 1046 |  |  |  |  |  |  |  |  |  |
| JUMP_NEAR | 0.25 | units | 1057 | units (2 cm) | v11feet 2026-10-17: 新設 2 cm（review_integ の pops.py の床の近さ） | ○ |  | ○ |  |  |  | retarget |
| JUMP_RATE | 2.5 / UNIT_CM | units | 1058 | units a frame (2.5 cm: 75 cm/s) | v11feet 2026-10-17: 新設 2.5 cm/コマ。床の近くで止めの分を 1 コマで返す跳び（128.0 秒の 13.7 cm）を、元の足より 2.5 cm/コマ以上速く動かないように前後へ配る | ○ |  |  |  |  |  | retarget |
| JUMP_SPREAD | 6 | frames | 1059 | frames each way at most | v11feet 2026-10-17: 新設 6 コマ（各側） |  |  |  |  |  |  |  |
| JUMP_TOUCH | 0.025 | units | 1060 | units (2 mm): a shoe's vertices this near its lowest touch (tools/sink_check.py's) | v11feet 2026-10-17: 新設 2 mm（tools/sink_check.py の触れる頂点、retarget_check の pops と同じ読み方）。底の線では 104.4 秒の着地の 9 cm を見落とした | ○ |  |  |  |  |  | retarget |
| _quant(qs) | (50, 90, 99, 100) |  | 1426 |  |  |  |  |  |  |  |  |  |
| TOUCH | 0.12 | units | 1435 | units (1 cm): a hand point this close to a part touches it |  | ○ |  |  |  |  |  | retarget |
| NEAR | 0.8 | units | 1436 | units (6.4 cm): the hand's place on a part is kept within this, fading out towards it |  | ○ |  |  |  |  |  | retarget |
| HAND_THICK | 0.15 | units | 1437 | units: half a hand's thickness (the two palms' points touch at twice this) |  | ○ |  |  |  |  |  | retarget |
| TOUCH_BAND | 0.08 | units | 1438 | units (6 mm): past TOUCH, a hand on a part is tested against it by this much more |  | ○ |  |  |  |  |  | retarget |
| CLEAR_ROUNDS | 4 |  | 1439 |  |  |  |  |  |  |  |  |  |
| CLEAR_MARGIN | 0.02 | units | 1440 | units: the arm is pushed this much past the surface |  | ○ |  |  |  |  |  | retarget |
| CLEAR_TOL | 0.005 | units | 1441 | units: an arm this little into a part is left as it is |  | ○ |  |  |  |  |  | retarget |
| ELBOW_SHARE | 0.25 |  | 1442 | the forearm's first share counts with the upper arm (cleared by turning the arm at the shoulder) |  |  |  |  |  |  |  |  |
| HOLD_FROM | 0.6 |  | 1443 | the relation's weight from which the clearance keeps the hand where it is (1 at a touch) |  |  |  |  |  |  |  |  |
| SHOULDER_SKIP | 0.5 |  | 1444 | the upper arm's half by the shoulder is not tested against the head (the shoulder is under it) |  |  |  |  |  |  |  |  |
| TOL_DEG | 0.3 | deg | 1445 | the keys meet the wanted turns this closely |  |  |  |  |  |  |  |  |
| HAND_CLOUD | 48 |  | 1712 | the hand's own vertices a clearance may test besides the line from the wrist to the middle finger's tip (penetration's hand, a capsule of the hand's radius): up to this … | v11revm 2026-10-18（_spike/out/stage6/v11revm/NOTES.md）: 新設 48 点（触れの層だけが使う）。手首と指に最も重みの載る頂点から休みの形で互いに遠い順。リンの手は手首→中指の先の線から… |  |  | ○ | ○ |  |  | rig |
| SWIVELS | 24 |  | 1841 | elbow positions tried round the shoulder-wrist line when a held hand's arm goes in |  |  |  |  |  |  |  |  |
| SWIVEL_COST | 0.02 | units | 1842 | units of depth one radian of swivel away from the dance's elbow is worth |  | ○ |  | ○ |  |  |  | retarget |
| SWIVEL_CLEARS | 0.03 | units | 1843 | units: a held hand's elbow position that leaves at most this keeps the hand where it is |  | ○ |  |  |  |  |  | retarget |
| of(depth) | 0 |  | 2026 |  |  |  |  |  |  |  |  |  |
| STANCE_LOW | 0.1 | units | 2141 | units: a foot IK goal this close to its rest height (and slow) stands (the stance's reach) |  | ○ |  |  |  |  |  | retarget |
| STANCE_SLOW | 0.05 | units | 2142 | units a frame |  | ○ |  |  |  |  |  | retarget |
| TOE_STILL | 0.03 | units | 2143 | units a frame: the toe goal this slow (and pitched) stands on the toe |  | ○ |  |  |  |  |  | retarget |
| TOE_PITCH | (6.0, 45.0) | deg | 2144 | degrees: the pitches the toe's floor relation is read over (above, the foot is on its ball) |  |  |  |  |  |  |  |  |
| lower_envelope(q) | 10.0 |  | 2169 |  |  |  |  |  |  |  |  |  |
| lower_envelope(width) | 6.0 |  | 2169 |  |  |  |  |  |  |  |  |  |
| --stance | "legs" |  | 2360 |  |  |  |  |  |  |  |  |  |

## fix_twist.py（2. 踊りを体に写す（retarget の受け持ち）と手捩、6）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| IDENTITY | (0.0, 0.0, 0.0, 1.0) |  | 41 |  |  |  |  |  |  |  |  |  |
| HALF | 180.0 |  | 42 |  |  |  |  |  |  |  |  |  |
| QUARTER | 90.0 |  | 42 |  |  |  |  |  |  |  |  |  |
| fix(share) | 0.5 |  | 139 |  |  |  |  |  |  |  |  |  |
| run(share) | 0.5 |  | 210 |  |  |  |  |  |  |  |  |  |
| --share | 0.5 |  | 229 | the part of the twist the forearm keeps, 0 to 1 (default 0.5) |  |  |  |  |  |  |  |  |

## smooth_motion.py（3. 平滑化と手ぶれ除去（v4s）、18）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| IDENTITY | (0.0, 0.0, 0.0, 1.0) |  | 146 |  |  |  |  |  |  |  |  |  |
| ZERO | (0.0, 0.0, 0.0) |  | 271 |  |  |  |  |  |  |  |  |  |
| STILL | 1e-9 |  | 272 | a rate below this is a hold |  |  |  |  |  |  |  |  |
| BULGE | 4.0 / 27.0 |  | 273 | max of the Hermite basis h10 (at u = 1/3) |  |  |  |  |  |  |  |  |
| LATERAL_BOUND | math.radians(3.0) |  | 274 | how far off its own arc a rotation segment may bulge |  |  |  |  |  |  |  |  |
| EASE_SPAN | 4 |  | 352 | --straight: the frames over which a segment comes to rest at a still key |  |  |  |  |  |  |  |  |
| FPS | 30.0 |  | 444 | MMD's frame rate |  |  |  |  |  |  |  |  |
| DENOISE_HZ | 7.5 | Hz | 445 | the cutoff of --denoise when none is given |  |  |  |  |  |  |  |  |
| DENOISE_CAP | (3.0, 0.05) | units | 446 | how far the denoise may move a frame: degrees, model units per position component | 既定 3 度/0.05。本番は 6 度/0.05（HANDOVER 2026-10-06: 右ひじ p99 −25.7 %、6 度/0.3 は足が床で 0.11 横滑りするので使わない） | ○ |  |  |  |  |  | retarget |
| DENSE_GAP | 2 |  | 447 | keys at most this many frames apart make a dense run |  |  |  |  |  |  |  |  |
| DENOISE_MARGIN | 2 | frames | 448 | the frames on either side of a dense key the correction may use |  |  |  |  |  |  |  |  |
| MIN_ZONE | 4 |  | 449 | a zone of fewer frames is left alone: with its mean and slope at 0 the only correction of 3 frames is c(1, -2, 1), a zigzag (review 9 M2) |  |  |  |  |  |  |  |  |
| BAKED_SHARE | 0.9 |  | 452 | a track with this share of its key gaps 1 frame long looks already baked |  |  |  |  |  |  |  |  |
| JERK | (-1.0, 3.0, -3.0, 1.0) |  | 453 | the third difference: the penalty is on the jerk |  |  |  |  |  |  |  |  |
| ROUNDS | 12 |  | 454 | rounds of holding the frames that leave their bounds |  |  |  |  |  |  |  |  |
| smooth(tension) | 0.5 |  | 753 |  |  |  |  |  |  |  |  |  |
| run(tension) | 0.5 |  | 838 |  |  |  |  |  |  |  |  |  |
| --tension | 0.5 |  | 877 | scale of the tangents, 0 to 1 (default 0.5 = Catmull-Rom) |  |  |  |  |  |  |  |  |

## breath_layer.py（4. 呼吸、60）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FPS | 30.0 |  | 118 |  |  |  |  |  |  |  |  |  |
| UNIT_MM | 80.0 | mm | 119 | one model unit is about 8 cm (Sour's Rin is 1.5 m tall at about 19 units) | 「リンは約 19 単位で 1.5 m」（8 cm/単位） | ○ |  |  | ○ |  |  | retarget |
| SIDES | (("左肩", "左腕", ("左中指３", "左手首"), 1.0), ("右肩", "右腕", ("右中指３", … |  | 124 | shoulder, arm, hand tips in order of preference, the sign of the turn about Z that lifts the arm joint |  |  |  |  |  |  |  |  |
| CHEST_BREATH | 1.2 | deg | 128 | degrees the chest opens (leans back) for a quiet breath (a06: 1 to 1.5) |  |  |  |  |  |  |  |  |
| SHOULDER_BREATH | 3.0 | deg | 129 | degrees the shoulders turn up for it (a06: 3 mm at the arm joint is 3.1) |  |  |  |  |  |  |  |  |
| NECK_COUNTER | 0.5 |  | 130 | share of the chest's breath the neck takes back |  |  |  |  |  |  |  |  |
| REST_PERIOD | (3.3, 5.0) | s | 131 | seconds of a quiet breath (12 to 18 a minute) |  |  |  |  |  |  |  |  |
| INHALE_SHARE | (0.36, 0.44) |  | 132 | share of a quiet breath spent breathing in |  |  |  |  |  |  |  |  |
| REST_DEPTH | (0.85, 1.15) |  | 133 | depth of a quiet breath (1 = CHEST_BREATH and SHOULDER_BREATH) |  |  |  |  |  |  |  |  |
| SHORT_BREATH | 2.5 | s | 134 | seconds: a breath squeezed into a shorter gap is shallower in proportion |  |  |  |  |  |  |  |  |
| MIN_BREATH | 1.2 | s | 135 | seconds: a shorter gap gets no breath |  |  |  |  |  |  |  |  |
| AFTER_PERIOD | 0.25 |  | 136 | the share a breath is shortened by at full exertion |  |  |  |  |  |  |  |  |
| AFTER_AMP | 0.3 |  | 137 | and the share it is deepened by (where the dance is quiet) |  |  |  | ○ |  |  |  | dance |
| EXERTION_TAU | 6.0 | s | 138 | seconds of the backward average of the motion that makes the exertion |  |  |  |  |  |  |  |  |
| LINE_INHALE | 0.6 | s | 139 | seconds of the inhale before a line (Salomoni 2016: 0.5 to 0.7) |  |  |  |  |  |  | ○ |  |
| LINE_LEAD | 0.0 | s | 140 | seconds from the cue's start to the top of that inhale |  |  |  |  |  |  |  |  |
| LINE_AMP | 1.4 |  | 141 | depth of a line inhale |  |  |  |  |  |  |  |  |
| LINE_EXHALE_MIN | 1.0 | s | 142 | seconds: a line without a later end breathes out over at least this |  |  |  |  |  |  |  |  |
| MIN_GAP | 0.25 | s | 143 | seconds from one peak to the next inhale's start, at least |  |  |  |  |  |  |  |  |
| MIN_INHALE | 0.2 | s | 144 | seconds: a shorter inhale is dropped |  |  |  |  |  |  |  |  |
| MOVE_SPEED | 5.0 | mm/s | 145 | mm/s of the head that is a move |  | ○ |  |  |  |  |  | retarget |
| MOVE_RUN | 10 | frames | 146 | frames the head must keep moving |  |  |  |  |  |  |  |  |
| ANTICIPATE_MIN | 1.5 | s | 147 | seconds into the song the first move must be for an anticipation |  |  |  | ○ |  |  |  | dance |
| ANTICIPATE_LEAD | 0.35 | s | 148 | seconds from the top of the anticipation's inhale to the move |  |  |  |  |  |  |  |  |
| ANTICIPATE_INHALE | 1.0 | s | 149 | seconds of that inhale |  |  |  |  |  |  |  |  |
| ANTICIPATE_AMP | 1.2 |  | 150 |  |  |  |  |  |  |  |  |  |
| ANTICIPATE_EXHALE | 0.8 | s | 151 | seconds it breathes out into the move |  |  |  |  |  |  |  |  |
| SINK | 0.6 | deg | 152 | degrees the upper body bends forward in the anticipation |  |  |  |  |  |  |  |  |
| SINK_FRAMES | (18, 4, 12) | frames | 153 | frames: the sink starts 18 before the move, is deepest 4 before, gone 12 after |  |  |  |  |  |  |  |  |
| SWAY_ROLL | (0.74, 0.86) | deg | 154 | degrees: semi-axis of the orbit to the sides |  |  |  |  |  |  |  |  |
| SWAY_YAW | (0.80, 1.00) | deg | 155 | degrees: semi-axis of the twist |  |  |  |  |  |  |  |  |
| SWAY_HZ | (0.25, 0.33) | Hz | 156 | rounds per second |  |  |  |  |  |  |  |  |
| SWAY_KNOT | 3.0 | s | 157 | seconds between the knots of the orbit's noise |  |  |  |  |  |  |  |  |
| SWAY_SPINE_SHARE | 0.5 |  | 158 | share of the sway in 上半身 (the rest in 上半身2) |  |  |  |  |  |  |  |  |
| HEAD_ROLL_COUNTER | 0.4 |  | 159 | share of the trunk's roll the neck takes back |  |  |  |  |  |  |  |  |
| NECK_NOD | 0.65 |  | 160 | the head nods on the neck by this share of the trunk's twist, in step with it |  |  |  |  |  |  |  |  |
| SWAY_FLOOR | 0.25 |  | 161 | the sway's scale in a big motion |  |  |  |  |  |  |  |  |
| BREATH_FLOOR | 0.45 |  | 162 | the breath's scale in a big motion |  |  |  |  |  |  |  |  |
| QUIET_TURN | (3.0, 15.0) | deg/s | 163 | deg/s of the chest: quiet below the first, moving above the second |  |  |  |  |  |  |  |  |
| QUIET_HEAD | (30.0, 150.0) | mm/s | 164 | mm/s of the head |  | ○ |  |  |  |  |  | retarget |
| QUIET_WINDOW | 9 | frames | 165 | frames |  |  |  |  |  |  |  |  |
| CONTACT_CM | (6.0, 14.0) | cm | 166 | cm from a hand's tip to the eyes: no shoulder breath below, all of it above |  | ○ |  |  |  |  |  | retarget |
| CONTACT_WINDOW | 6 | frames | 167 | frames |  |  |  |  |  |  |  |  |
| CONTACT_REPORT_CM | 15.0 | cm | 168 |  |  | ○ |  |  |  |  |  | retarget |
| FROZEN | (0.5, 0.5, 1.0) | deg/s | 169 | a20: cm/s of センター, cm/s of 上半身2, deg/s of 上半身2 |  |  |  |  |  |  |  |  |
| DANCE_PART | (300, 7599) | frames | 170 | a20's dance part (frames) |  |  |  | ○ |  |  |  | dance |
| FIX_ROUNDS | 4 |  | 171 |  |  |  |  |  |  |  |  |  |
| FIX_BOOST | 1.2 |  | 172 |  |  |  |  |  |  |  |  |  |
| FIX_SPREAD | 3 | frames | 173 | frames around a frozen frame that get the whole raise |  |  |  |  |  |  |  |  |
| FIX_RAMP | 15 | frames | 174 | frames over which the raise comes in and goes out (each way) |  |  |  |  |  |  |  |  |
| HOLD_HEAD | 1.0 | mm/s | 175 | mm/s: the input's head stands still below this (a01) |  | ○ |  |  |  |  |  | retarget |
| LONG_HOLD | 30 | frames | 176 | frames: a quiet stretch at least this long is a long hold (report) |  |  |  |  |  |  |  |  |
| _r(places) | 4 |  | 180 |  |  |  |  |  |  |  |  |  |
| speeds(scale) | 1.0 |  | 257 |  |  |  |  |  |  |  |  |  |
| breathe(seed) | 0 |  | 699 |  |  |  |  |  |  |  |  |  |
| breathe(strength) | 1.0 |  | 699 |  |  |  |  |  |  |  |  |  |
| run(seed) | 0 |  | 914 |  |  |  |  |  |  |  |  |  |
| run(strength) | 1.0 |  | 914 |  |  |  |  |  |  |  |  |  |
| --seed | 0 |  | 952 | the breaths' periods and depths and the sway (default 0) |  |  |  |  |  |  |  |  |
| --strength | 1.0 |  | 953 | scales every turn of the layer (default 1) |  |  |  |  |  |  |  |  |

## anatomy_layer.py（5. 関節の拘束、70）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UNIT_CM | 8.0 | cm | 104 | one model unit is 8 cm (the analysis pack's README) | 解析の資料の 8 cm/単位（adapt 10-17 の測りで 7.96〜8.15） | ○ |  |  |  |  |  | retarget |
| SIDES | (("左", 1.0), ("右", -1.0)) |  | 105 |  |  |  |  |  |  |  |  |  |
| X_ | np.array([1.0, 0.0, 0.0]) |  | 106 |  |  |  |  |  |  |  |  |  |
| U_ | np.array([0.0, 1.0, 0.0]) |  | 107 |  |  |  |  |  |  |  |  |  |
| F_ | np.array([0.0, 0.0, -1.0]) |  | 109 | the model faces -Z |  |  |  |  | ○ |  |  | rig |
| IDENTITY | np.array([0.0, 0.0, 0.0, 1.0]) |  | 115 |  |  |  |  |  |  |  |  |  |
| TRUNK_TO_UPPER.flex | 0.25 |  | 118 | moved from 上半身 onto 上半身2 (5.1 A2) |  |  |  |  |  |  |  |  |
| TRUNK_TO_UPPER.lat | 0.3 |  | 118 | moved from 上半身 onto 上半身2 (5.1 A2) |  |  |  |  |  |  |  |  |
| TRUNK_TO_UPPER.rot | 0.4 |  | 118 | moved from 上半身 onto 上半身2 (5.1 A2) |  |  |  |  |  |  |  |  |
| HEAD_TO_NECK.flex | 0.6 |  | 119 | moved from 頭 onto 首 (5.1 A3) |  |  |  |  |  |  |  |  |
| HEAD_TO_NECK.lat | 0.7 |  | 119 | moved from 頭 onto 首 (5.1 A3) |  |  |  |  |  |  |  |  |
| HEAD_TO_NECK.rot | 1.0 / 3.0 |  | 119 | moved from 頭 onto 首 (5.1 A3) |  |  |  |  |  |  |  |  |
| ARM_LIMITS.external_rotation | ((0.0, 60.0, 110.0), (90.0, 90.0, 131.0), (180.0, 90.0, 131… |  | 122 | (soft start = the Japanese reference range, cap = the research's proposal; where they were equal the cap is raised by 5 degrees to leave room for the saturation). Degree… |  |  |  |  |  |  |  |  |
| ARM_LIMITS.internal_rotation | ((0.0, 80.0, 85.0), (90.0, 70.0, 81.0), (180.0, 70.0, 81.0)) |  | 123 |  |  |  |  |  |  |  |  |  |
| ARM_LIMITS.pronation | (90.0, 95.0) |  | 124 |  |  |  |  |  |  |  |  |  |
| ARM_LIMITS.supination | (90.0, 95.0) |  | 124 |  |  |  |  |  |  |  |  |  |
| ARM_LIMITS.elbow_extension | (5.0, 18.0) |  | 125 |  |  |  |  |  |  |  |  |  |
| ARM_LIMITS.elbow_flexion | (145.0, 152.5) |  | 125 |  |  |  |  |  |  |  |  |  |
| ARM_LIMITS.wrist_extension | (70.0, 99.5) |  | 126 |  |  |  |  |  |  |  |  |  |
| ARM_LIMITS.wrist_flexion | (90.0, 115.0) |  | 126 |  |  |  |  |  |  |  |  |  |
| ARM_LIMITS.wrist_radial | (25.0, 37.0) |  | 127 |  |  |  |  |  |  |  |  |  |
| ARM_LIMITS.wrist_ulnar | (55.0, 60.0) |  | 127 |  |  |  |  |  |  |  |  |  |
| GIRDLE_LIMITS.depression | (5.0, 15.0) |  | 131 | The girdle: the Japanese reference is 20 (10 for depression) and the research has no measured cap; the saturation starts below the reference (10, 5) so that a stronger s… |  |  |  |  |  |  |  |  |
| GIRDLE_LIMITS.elevation | (10.0, 25.0) |  | 131 | The girdle: the Japanese reference is 20 (10 for depression) and the research has no measured cap; the saturation starts below the reference (10, 5) so that a stronger s… |  |  |  |  |  |  |  |  |
| GIRDLE_LIMITS.protraction | (10.0, 25.0) |  | 131 | The girdle: the Japanese reference is 20 (10 for depression) and the research has no measured cap; the saturation starts below the reference (10, 5) so that a stronger s… |  |  |  |  |  |  |  |  |
| GIRDLE_LIMITS.retraction | (10.0, 25.0) |  | 132 |  |  |  |  |  |  |  |  |  |
| RHYTHM.elevation | 0.05 |  | 138 | The rhythm added to the input's girdle above HT 25: elevation 0.05 deg/deg is Ludewig 2009's clavicle (+6 over the arc); the retraction is a fit of ours: Ludewig's mean … |  |  |  | ○ |  |  | ○ | dance |
| RHYTHM.retraction_abduction | 0.18 |  | 138 | The rhythm added to the input's girdle above HT 25: elevation 0.05 deg/deg is Ludewig 2009's clavicle (+6 over the arc); the retraction is a fit of ours: Ludewig's mean … |  |  |  | ○ |  |  | ○ | dance |
| RHYTHM.retraction_flexion | 0.06 |  | 138 | The rhythm added to the input's girdle above HT 25: elevation 0.05 deg/deg is Ludewig 2009's clavicle (+6 over the arc); the retraction is a fit of ours: Ludewig's mean … |  |  |  | ○ |  |  | ○ | dance |
| RHYTHM.start | 25.0 |  | 138 | The rhythm added to the input's girdle above HT 25: elevation 0.05 deg/deg is Ludewig 2009's clavicle (+6 over the arc); the retraction is a fit of ours: Ludewig's mean … |  |  |  | ○ |  |  | ○ | dance |
| PROTRACTED_DEG | 5.0 | deg | 139 |  |  |  |  |  |  |  |  |  |
| TENODESIS.dip | 0.16 |  | 140 | Su 2005, per degree of wrist extension |  |  |  |  |  |  | ○ |  |
| TENODESIS.mp | 0.30 |  | 140 | Su 2005, per degree of wrist extension |  |  |  |  |  |  | ○ |  |
| TENODESIS.pip | 0.43 |  | 140 | Su 2005, per degree of wrist extension |  |  |  |  |  |  | ○ |  |
| RELAX_DEG | 0.5 | deg | 141 |  |  |  |  |  |  |  |  |  |
| RELAX_FADE | 5 |  | 141 |  |  |  |  |  |  |  |  |  |
| RELAX_RUN | 10 |  | 141 |  |  |  |  |  |  |  |  |  |
| RELAX_MAX_DEG | 60.0 | deg | 142 | a relaxed hand: the fingers' mean bend (MP + PIP + DIP) at most this, none over 1.5x |  |  |  |  |  |  |  |  |
| SWIVEL_STEP | 5.0 | deg | 145 | degrees between the swivels tried |  |  |  |  |  |  |  |  |
| SIGMA_MOVE | 3.0 | deg | 146 | degrees of the elbow's offset (seen from the shoulder) that cost 1 |  |  |  |  |  |  |  |  |
| MOVE_CAP_DEG | 15.0 | deg | 147 | beyond (about 5 cm of elbow), the offset costs (excess / MOVE_HARD_DEG)^2: an excess that |  |  |  |  |  |  |  |  |
| MOVE_HARD_DEG | 0.25 | deg | 148 | would need the elbow moved further is left and listed |  |  |  |  |  |  |  |  |
| SIGMA_ROLL | 4.0 | deg | 149 | degrees per frame of the upper arm's roll beyond the split's own that cost 1 |  |  |  |  |  |  |  |  |
| SIGMA_OFFSET | 1.0 | deg | 150 | degrees per frame of change of the elbow's offset that cost 1 |  |  |  |  |  |  |  |  |
| HARD_DEG | 1.0 | deg | 151 | beyond a cap: (degrees / HARD_DEG)^2 |  |  |  |  |  |  |  |  |
| FLEX_PREFERENCE | 0.02 |  | 152 | a tie goes to the elbow bent to the front |  |  |  |  |  |  |  |  |
| BENT | (15.0, 35.0) |  | 153 | the elbow's bend over which the split's roll is trusted (a smoothstep) |  |  |  |  |  |  |  |  |
| PLANE_BLEND | (0.05, 0.1) | deg | 154 | degrees of bend: below, the roll is set by the swivel's plane (the hinge's own plane is undefined); above, the exact hinge (the wrist on its place) |  |  |  |  |  |  |  |  |
| REFINE_HALVINGS | 4 |  | 156 | the continuous search after the grid (see refine) |  |  |  |  |  |  |  |  |
| REFINE_POINTS | 9 |  | 156 | the continuous search after the grid (see refine) |  |  |  |  |  |  |  |  |
| REFINE_ROUNDS | 2 |  | 156 | the continuous search after the grid (see refine) |  |  |  |  |  |  |  |  |
| FOREARM_SHARE | 0.5 |  | 157 | --forearm-twist share: what 手捩 keeps, as tools/fix_twist.py (at most 45 degrees) |  |  |  |  |  |  |  |  |
| BACKOFF_PAD | 4 | frames | 158 | frames: a backed-off girdle is eased in and out |  |  |  |  |  |  |  |  |
| KEY_ELBOW_CM | 2.0 | cm | 159 | a trace key is listed where the elbow moved or the girdle turned more |  | ○ |  | ○ |  |  |  | retarget |
| KEY_GIRDLE_DEG | 8.0 | deg | 159 | a trace key is listed where the elbow moved or the girdle turned more |  |  |  | ○ |  |  |  | dance |
| BEND_TOL_DEG | 2.0 | deg | 160 | the elbow's bend may change this much where the shoulder moves; beyond, the hand moves |  |  |  |  |  |  |  |  |
| NECK_SHIFT_CM | 1.2 | cm | 161 | the head may move this much against the chest by the neck's share (then saturated) |  | ○ |  |  |  |  |  | retarget |
| TRUNK_SHIFT_CM | 1.2 | cm | 162 | the chest may move this much by the trunk's share (then saturated) |  | ○ |  |  |  |  |  | retarget |
| OFFSET_STEP_CAP | 6.0 | deg | 163 | degrees per frame of change of the elbow's offset (above a grid step), and of the upper |  |  |  |  |  |  |  |  |
| ROLL_STEP_CAP | 20.0 |  | 164 | arm's roll beyond the split's own, past which a step costs as a cap's excess: no new |  |  |  |  |  |  |  |  |
| STEP_HARD | 0.1 |  | 165 | one-frame jumps (the review of 2026-10-10, H2) |  |  |  |  |  |  |  |  |
| ACCEL_CAP | 1.5 | deg | 166 | degrees per frame^2 of the elbow's offset (1.5: about 0.7 cm): in the refine |  |  |  |  |  |  |  |  |
| SIGMA_ACCEL | 1.0 | deg | 166 | degrees per frame^2 of the elbow's offset (1.5: about 0.7 cm): in the refine |  |  |  |  |  |  |  |  |
| BRANCH_SWITCH_DEG | 1.0 | deg | 167 | a change of reading costs (bend / this)^2: only through a nearly straight arm |  |  |  |  |  |  |  |  |
| GIRDLE_HAND_SLACK_CM（引数 --hand-slack） | 4.0 | cm | 168 | how far a hand may slide along a straight arm so that the girdle can come back |  | ○ |  |  |  |  |  | retarget |
| RHYTHM_HAND_CM | 1.0 | cm | 169 | how far the rhythm may move a hand more than the trunk's split and the cap do (the bend kept) |  | ○ |  |  |  |  |  | retarget |
| _r(n) | 2 |  | 334 |  |  |  |  |  |  |  |  |  |
| left_beyond(limit) | 80 |  | 1271 |  |  |  |  |  |  |  |  |  |
| --forearm-twist | "share" |  | 1566 | share: fix_twist's rule on the new twist, 手捩 at most 45 degrees, 手首 the rest (default); keep: 手捩 keeps the input's key, 手首 takes the rest; handtw: all of it on 手捩 |  |  |  |  |  |  |  |  |
| --upper-twist-share | 1.0 |  | 1569 | the part of the upper arm's roll on 腕捩, the rest on 腕 (default 1; on Sour's Rin no vertex is weighted to 腕, so the skin sees the same twist whatever the share) |  |  |  |  | ○ |  |  | rig |

## motor_layer.py（6. 運動（遅れと堅さ、--preset human --elbow-hinge on）、103）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FPS | 30.0 |  | 178 |  |  |  |  |  |  |  |  |  |
| UNIT_M | 0.08 | m | 179 | one model unit is 8 cm (the analysis pack's README; Rin's 頭先 is then 1.50 m up) | 解析の資料の 8 cm/単位（リンの頭先 1.50 m） | ○ |  |  | ○ |  |  | retarget |
| UNIT_MM | 80.0 | mm | 180 |  |  | ○ |  |  |  |  |  | retarget |
| F1_HEIGHT_M | 1.575 | m | 197 | ---- the body (sources) ------------------------------------------------------------------------------ Holzbaur KRS, Delp SL, Gold GE, Murray WM (2007) Moment-generating… | Holzbaur の被験者 F1（1.575 m・49.9 kg）。リンの背は頭先 × 0.08 = 1.49 m で、体重は (h / 1.575)³ で縮める | ○ |  |  |  |  | ○ | retarget |
| F1_MASS_KG | 49.9 |  | 197 | ---- the body (sources) ------------------------------------------------------------------------------ Holzbaur KRS, Delp SL, Gold GE, Murray WM (2007) Moment-generating… |  |  |  |  |  |  | ○ |  |
| TORQUE_F1.upper | 31.6 |  | 198 | shoulder abduction (adduction is 43.0: the smaller one is taken) |  |  |  |  |  |  |  |  |
| TORQUE_F1.elbow | 23.5 |  | 199 | elbow flexion (extension 23.1) |  |  |  |  |  |  |  |  |
| TORQUE_F1.wrist | 10.3 |  | 200 | wrist flexion (extension 6.7) |  |  |  |  |  |  |  |  |
| TORQUE_F1.girdle | 31.6 |  | 201 | NO source for the shoulder girdle: the shoulder's abduction is assumed |  |  |  |  |  |  |  |  |
| DE_LEVA_F.head | (6.68, 48.41, (27.1 + 29.5) / 2.0) |  | 206 | VERT -> CERV (the alternative endpoints) |  |  |  |  |  |  |  |  |
| DE_LEVA_F.upper_trunk | (15.45, 50.50, (46.6 + 31.4) / 2.0) |  | 207 | CERV -> XYPH (the alternative endpoints) |  |  |  |  |  |  |  |  |
| DE_LEVA_F.middle_trunk | (14.65, 45.12, (43.3 + 35.4) / 2.0) |  | 208 | XYPH -> OMPH |  |  |  |  |  |  |  |  |
| DE_LEVA_F.upper_arm | (2.55, 57.54, (27.8 + 26.0) / 2.0) |  | 209 | SJC -> EJC |  |  |  |  |  |  |  |  |
| DE_LEVA_F.forearm | (1.38, 45.59, (26.1 + 25.7) / 2.0) |  | 210 | EJC -> WJC |  |  |  |  |  |  |  |  |
| DE_LEVA_F.hand | (0.56, 34.27, (24.4 + 20.8) / 2.0) |  | 211 | WJC -> DAC3 (the middle finger's tip; alternative) |  |  |  |  |  |  |  |  |
| HEAD_TIP_FALLBACK | 0.155 |  | 212 | without 頭先: the vertex this share of 頭's height above 頭 (Rin: 2.52 / 16.24 units) |  |  |  |  | ○ |  |  | rig |
| HAND_FALLBACK | 0.65 |  | 213 | without finger bones: the hand this share of the forearm long (de Leva 170.1 / 262.4) |  |  |  |  |  |  |  |  |
| SUBSTEPS（引数 --substeps） | 16 |  | 216 | per frame (480 Hz; the spike), at least |  |  |  |  |  |  |  |  |
| STEP_WN_DT | 0.25 |  | 217 | more substeps when the stiffest bone's wn * dt would pass this |  |  |  |  |  |  |  |  |
| SLOW_DEG_S | (200.0, 400.0) | deg/s | 218 | the upper arm's speed: slow below (delays doubled), fast above (RESEARCH 4.2: ~300) |  |  |  |  |  |  |  |  |
| SLOW_WINDOW | 15 | frames | 219 | frames each way for the fastest speed around a frame |  |  |  |  |  |  |  |  |
| FINGER_DELAY | 0.25 | frames | 220 | frames the fingers read after the wrist |  |  |  |  |  |  |  |  |
| FINGER_SNAP_DEG_S | (1000.0, 2000.0) | deg/s | 221 | the input's fingers (手首 -> 中指３) turning faster: on their own frame |  |  |  |  |  |  |  |  |
| FINGER_SNAP_PAD | 3 | frames | 222 | frames each way |  |  |  |  |  |  |  |  |
| HOLD_DEG_S | 5.0 | deg/s | 223 | a09: a joint is still under this |  |  |  |  |  |  |  |  |
| HOLD_MIN | 4 | frames | 224 | frames: a hold (the research, 2.0) |  |  |  |  |  |  |  |  |
| HOLD_SETTLE | 6 | frames | 225 | frames after a hold's start before it stiffens (1 degree within 5-7 frames, 4.2) |  |  |  |  |  |  |  |  |
| HOLD_EXIT | 2 | frames | 226 | frames before a hold's end it lets go again |  |  |  |  |  |  |  |  |
| HOLD_RAMP | 3 |  | 227 |  |  |  |  |  |  |  |  |  |
| HOLD_STIFF | 0.5 | s | 228 | s up by this share |  |  |  |  |  |  |  |  |
| KIME_BEAT | 2 | frames | 229 | frames from a beat for a beat hold |  |  |  | ○ |  |  |  | dance |
| KIME_LEAD | 3 | frames | 230 | frames before the beat hold it is stiff (RESEARCH 4.2: "決めの 3 フレーム前から") |  |  |  | ○ |  |  |  | dance |
| KIME_RAMP | 4 |  | 231 |  |  |  |  |  |  |  |  |  |
| KIME_STIFF | 0.5 |  | 232 | wn x 1.5 (RESEARCH 4.2) |  |  |  |  |  |  |  |  |
| KIME_FF | 0.2 |  | 233 | beta + 0.2 (RESEARCH 4.2) |  |  |  |  |  |  |  |  |
| CONTACT_FACE_MM | (70.0, 100.0) | mm | 234 | the tip to the eyes: all contact below, none above (the input's least is 58 mm) |  | ○ |  |  |  |  |  | retarget |
| CONTACT_BODY_MM | (60.0, 90.0) | mm | 235 | the tip to the line 上半身 - 首 (Rin's chest is about 9 cm deep each way) |  | ○ |  |  | ○ |  |  | retarget・rig |
| CONTACT_PAD | 4 | frames | 236 | frames (RESEARCH 4.2: "その前後 4 フレーム") |  |  |  |  |  |  |  |  |
| CONTACT_STIFF | 1.0 |  | 237 |  |  |  |  |  |  |  |  |  |
| JUMP_DEG | 60.0 | deg | 238 | a jump turns at least this in one frame, |  |  |  |  |  |  |  |  |
| JUMP_RATIO | 3.0 |  | 239 | this many times the median step of the JUMP_WINDOW frames each way, |  |  |  |  |  |  |  |  |
| JUMP_WINDOW | 4 |  | 240 |  |  |  |  |  |  |  |  |  |
| JUMP_BIG_DEG | 90.0 | deg | 241 | and either this much or JUMP_NEXT_RATIO times either step next to it (the fingers |  |  |  |  |  |  |  |  |
| JUMP_NEXT_RATIO | 2.5 | deg/s | 242 | change shape over 2 frames at up to 1,700 deg/s: that is no jump) |  |  |  |  |  |  |  |  |
| FALLBACK_RAMP | 4 | frames | 243 | frames in and out of a stretch given back to the input |  |  |  |  |  |  |  |  |
| JUMP_HOLD | (1, 2) | frames | 244 | frames before and after a jump's interval that are wholly the input's |  |  |  |  |  |  |  |  |
| UNSOLVED_DEG | 10.0 | deg | 245 |  |  |  |  |  |  |  |  |  |
| UNSOLVED_RUN | 2 | frames | 246 | frames |  |  |  |  |  |  |  |  |
| UNSOLVED_HARD_DEG | 45.0 | deg | 247 |  |  |  |  |  |  |  |  |  |
| DEVIATION_CM | 8.0 | cm | 248 | a wrist further than this from the input's, late allowed (the layer's p95: 4 cm) |  | ○ |  |  |  |  |  | retarget |
| DEVIATION_SAME_CM | 12.0 | cm | 249 | or further than this on the same frame (the review: 10.9 cm at 6,393, late allowed 2) |  | ○ |  |  |  |  |  | retarget |
| EDGE_DEV_CM | 3.0 | cm | 250 | a stretch given back widens while the layer's wrist is further than this (same frame) |  | ○ |  |  |  |  |  | retarget |
| EDGE_EXTEND | 12 | frames | 251 | frames each way at most |  |  |  |  |  |  |  |  |
| SEAM_STEP_CM | 3.0 | cm | 252 | an edge whose wrist steps more than the input's by this (cm/frame) gets a longer ramp |  | ○ |  |  |  |  |  | retarget |
| SEAM_RAMP_MAX | 16 | frames | 253 | frames (the layer's own excess away from the edges: p99 2.6, p99.9 4.9-5.5) |  |  |  |  |  |  |  |  |
| SEAM_ROUNDS | 6 |  | 254 |  |  |  |  |  |  |  |  |  |
| FLOOR_MM | 8.0 | mm | 255 | the hand may come this much closer than the input had it, within FLOOR_KNEE_MM, |  | ○ |  |  |  |  |  | retarget |
| FLOOR_KNEE_MM | 100.0 | mm | 256 |  |  | ○ |  |  |  |  |  | retarget |
| FLOOR_SLOPE | 0.25 |  | 257 | and further out this share of the distance beyond the knee more |  |  |  |  |  |  |  |  |
| FLOOR_RANGE_MM | 200.0 | mm | 258 | (the face; the body FLOOR_BODY_RANGE_MM): no floor further out |  | ○ |  |  |  |  |  | retarget |
| FLOOR_BODY_RANGE_MM | 150.0 | mm | 259 |  |  | ○ |  |  |  |  |  | retarget |
| FLOOR_PAD | 2 |  | 260 |  |  |  |  |  |  |  |  |  |
| FLOOR_ROUNDS | 5 |  | 261 |  |  |  |  |  |  |  |  |  |
| LEAD_LIMIT | 2.0 |  | 262 |  |  |  |  |  |  |  |  |  |
| ELBOW_SKIN_CM | 2.5 | cm | 263 | --elbow-hinge: the skin's distance from the arm's axis at the elbow (r in the cost; Rin: 2.4 - 2.7 cm) |  | ○ |  |  | ○ |  |  | retarget・rig |
| HINGE_GRID_DEG | (90.0, 0.5, 0.5, 0.01) | deg | 264 | the roll searched: +-90 by 0.5 degrees, then +-0.5 about the best by 0.01 |  |  |  |  |  |  |  |  |
| FOREARM_SHARE | 0.5 |  | 265 | --elbow-hinge: what 手捩 keeps of the forearm's twist (tools/anatomy_layer.py's default) |  |  |  |  |  |  |  |  |
| LINE_MM | 0.1 | mm | 266 | --elbow-hinge: 腕捩 this near the line 腕 - ひじ takes 腕's roll |  | ○ |  |  |  |  |  | retarget |
| SONG | (600, 7600) |  | 267 | the analysts' frames for a02 (on the MV's 7,743 frames; a shorter motion: all) |  |  |  |  |  |  |  |  |
| ACTIVE | (167, 7661) |  | 268 | a04's dancing part and the trace's keys (the same) |  |  |  | ○ |  |  |  | dance |
| PRESETS.strong.girdle.ff | 0.9 |  | 279 |  |  |  |  |  |  |  |  |  |
| PRESETS.strong.girdle.fn | 4.0 |  | 279 |  |  |  |  |  |  |  |  |  |
| PRESETS.strong.girdle.zeta | 0.85 |  | 279 |  |  |  |  |  |  |  |  |  |
| PRESETS.strong.upper.ff | 0.85 |  | 280 |  |  |  |  |  |  |  |  |  |
| PRESETS.strong.upper.fn | 3.5 |  | 280 |  |  |  |  |  |  |  |  |  |
| PRESETS.strong.upper.zeta | 0.85 |  | 280 |  |  |  |  |  |  |  |  |  |
| PRESETS.strong.elbow.ff | 0.75 |  | 281 |  |  |  |  |  |  |  |  |  |
| PRESETS.strong.elbow.fn | 3.5 |  | 281 |  |  |  |  |  |  |  |  |  |
| PRESETS.strong.elbow.zeta | 0.8 |  | 281 |  |  |  |  |  |  |  |  |  |
| PRESETS.strong.wrist.ff | 0.5 |  | 282 |  |  |  |  |  |  |  |  |  |
| PRESETS.strong.wrist.fn | 5.0 |  | 282 |  |  |  |  |  |  |  |  |  |
| PRESETS.strong.wrist.zeta | 0.75 |  | 282 |  |  |  |  |  |  |  |  |  |
| PRESETS.human.girdle.delay | (0.0, 0.0) |  | 283 |  |  |  |  |  |  |  |  |  |
| PRESETS.human.upper.delay | (0.0, 0.0) |  | 283 |  |  |  |  |  |  |  |  |  |
| PRESETS.human.elbow.delay | (0.0, 0.0) |  | 284 |  |  |  |  |  |  |  |  |  |
| PRESETS.human.wrist.delay | (0.0, 0.0) |  | 284 |  |  |  |  |  |  |  |  |  |
| PRESET_PARAMS.human.finger_delay | 0.0 |  | 285 | a preset's parameters outside the classes |  |  |  |  |  |  |  |  |
| IDENT | np.array([0.0, 0.0, 0.0, 1.0]) |  | 381 |  |  |  |  |  |  |  |  |  |
| _r(places) | 3 |  | 428 |  |  |  |  |  |  |  |  |  |
| place(depth) | 0 |  | 480 |  |  |  |  |  |  |  |  |  |
| lag_of(maxlag) | 6 |  | 1080 |  |  |  |  |  |  |  |  |  |
| spread(places) | 4 |  | 1280 |  |  |  |  |  |  |  |  |  |
| xcorr_lags(maxlag) | 6 |  | 1638 |  |  |  |  |  |  |  |  |  |
| xcorr_lags(step) | 15 |  | 1638 |  |  |  |  |  |  |  |  |  |
| xcorr_lags(win) | 60 |  | 1638 |  |  |  |  |  |  |  |  |  |
| rests(minlen) | 3 |  | 1661 |  |  |  |  |  |  |  |  |  |
| rests(thr) | 5.0 |  | 1661 |  |  |  |  |  |  |  |  |  |
| BINS | [0.0, 0.25, 0.5, 0.75, 0.9] |  | 1686 |  |  |  |  |  |  |  |  |  |
| band(hi) | 6.0 |  | 1711 |  |  |  |  |  |  |  |  |  |
| band(lo) | 3.0 |  | 1711 |  |  |  |  |  |  |  |  |  |
| valley_offsets(maxoff) | 6 |  | 1875 |  |  |  |  |  |  |  |  |  |
| --preset | "default" |  | 2200 | default; strong (softer upper arm and elbow, less fed forward); or human (no delays between the arm's joints and the fingers on the wrist's time, as people's motion capt… |  |  |  |  |  | ○ |  |  |
| --delay-scale | 1.0 |  | 2204 | scales every delay (default 1) |  |  |  |  |  |  |  |  |

## spine_layer.py（7. 背骨 4 本へ配る、9）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| LUMBAR_TOTAL | (96.0, 30.0, 15.3) | deg | 65 | degrees per joint, one side: (flexion+extension, lateral bend, axial turn) |  |  |  |  |  |  |  |  |
| THORACIC_TOTAL | (48.0, 30.0, 47.0) |  | 66 |  |  |  |  |  |  |  |  |  |
| THORACIC_UPPER | (0.5, 6.9 / (6.9 + 10.9), 9.5 / (9.5 + 11.9)) |  | 67 | the upper half's part of the thoracic total |  |  |  |  |  |  |  |  |
| JOINTS | {LO: (4, 0, 0), S.LUMBAR: (1, 2, 0), UP: (0, 4, 0), S.THORA… |  | 69 | the joints each bone stands for: (lumbar joints, lower thoracic joints, upper thoracic joints) of 5, 6 and 6 |  |  |  |  |  |  |  |  |
| GN_STEPS | 12 |  | 106 |  |  |  |  |  |  |  |  |  |
| BISECT_STEPS | 20 |  | 107 |  |  |  |  |  |  |  |  |  |
| PLACE_CAP_CM（引数 --place-cap-cm） | 3.0 | cm | 108 | the full song (v5a): 87 frames bent the other way at 3.0, 584 at 1.5, 1,367 at 0 |  | ○ |  | ○ |  |  |  | retarget |
| DAMP | 1e-6 |  | 109 |  |  |  |  |  |  |  |  |  |
| frame_runs(gap) | 5 |  | 142 |  |  |  |  |  |  |  |  |  |

## foot_layer.py（8. 足（最初の足の層 feet0、--landing off。v11 から --skim on・--hover off が既定）、78）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UNIT_CM | 8.0 | cm | 68 |  | 解析の資料の 8 cm/単位（adapt 10-17 の測りで 7.96〜8.15） | ○ |  |  |  |  |  | retarget |
| FPS | 30.0 |  | 69 |  |  |  |  |  |  |  |  |  |
| SOLE_BAND | 0.03 | units | 72 | units above the lowest vertex that still count as the sole's bottom layer |  | ○ |  |  |  |  |  | retarget |
| SHELL_BAND | 0.35 | units | 73 | units above it that the shoe's lower shell takes: the toe cap's front edge and the heel's back, which go lowest when the foot is pitched (Rin's cap is 0.6 cm under the s… |  | ○ |  |  | ○ |  |  | retarget・rig |
| TIP_WEIGHT | 0.8 |  | 76 | the toe cap: the shoe's lower shell weighted this much or more on 足先EX |  |  |  |  |  |  |  |  |
| BALL_WEIGHT | (0.1, 0.55) |  | 77 | the ball: the sole's bottom weighted between these on 足先EX (under the MTP's line) |  |  |  |  |  |  |  |  |
| CONTACT_ENTER | 0.03 | units | 78 | units above the trace's floor: a flat sole this low is on the floor |  | ○ |  | ○ |  |  |  | retarget |
| CONTACT_EXIT | 0.06 |  | 79 | ... and leaves it above this |  |  |  |  |  |  |  |  |
| HEEL_UP_DEG | 4.0 | deg | 80 | a foot on the floor pitched toes-down more than this stands on its forefoot |  |  |  |  |  |  |  |  |
| HEEL_PITCH_DEG | 20.0 | deg | 88 | The pitch of the foot inside Sour's Rin's loafers, asin(h / L) (the stage-6 research, 4: h the heel's sole above the forefoot's, L the heel's contact to the metatarsal h… |  |  |  |  | ○ |  | ○ | rig |
| _r(n) | 3 |  | 103 |  |  |  |  |  |  |  |  |  |
| measure_feet(floor_y) | 0.0 |  | 297 |  |  |  |  |  |  |  |  |  |
| feet_of(floor_y) | 0.0 |  | 303 |  |  |  |  |  |  |  |  |  |
| TOE_SLIDE | (30.0, 80.0) | cm/s | 348 | cm/s: a pointed foot moving faster than the first is less and less taken to touch the floor with the trace model's toe, faster than the second not at all (a toe on the f… |  | ○ |  | ○ |  |  |  | retarget |
| trace_height(extra) | 0.0 |  | 369 |  |  |  |  |  |  |  |  |  |
| PEN_TOL | 0.005 | units | 402 | units: deeper than this below the floor is a penetration (0.4 mm) |  | ○ |  |  |  |  |  | retarget |
| PLANE_DEPTH | 0.02 |  | 403 | the floor's dark plane lies this far below its lines (tools/make_stage.py) |  |  |  |  |  |  |  |  |
| TOES_FLAT_DEG | 8.0 | deg | 404 | a toe box within this of level lies on the floor (on a raised heel: the toes bent) |  |  |  |  |  |  |  |  |
| REFERENCE.dorsiflexion | (20.0, 36.0) |  | 418 |  |  |  |  |  |  |  |  |  |
| REFERENCE.eversion | (20.0, 25.0) |  | 418 |  |  |  |  |  |  |  |  |  |
| REFERENCE.inversion | (30.0, 36.0) |  | 418 |  |  |  |  |  |  |  |  |  |
| REFERENCE.plantarflexion | (50.0, 75.0) |  | 418 |  |  |  |  |  |  |  |  |  |
| REFERENCE.mtp_extension | (50.0, 70.0) |  | 419 |  |  |  |  |  |  |  |  |  |
| LOADED_DORSI_CAP | 40.0 |  | 420 |  |  |  |  |  |  |  |  |  |
| LOAD_FULL | 0.03 | units | 587 | units above the trace's floor (the flat sole): the foot bears weight below this |  | ○ |  | ○ |  |  |  | retarget |
| LOAD_NONE | 0.30 | cm | 588 | ... and none above (2.4 cm); between, a smoothstep: the roll is laid flat this way |  | ○ |  |  |  |  |  | retarget |
| ON_FLOOR | (0.03, 0.10) | units | 589 | the band (units above the trace's floor) over which the sole is put onto the floor and the toes take a raised heel: below, on the floor; above, the floor shift alone |  | ○ |  | ○ |  |  |  | retarget |
| EASE | 4 | frames | 591 | frames over which the flattening and the toes come and go |  |  |  |  |  |  |  |  |
| LOAD_D0 | 1.0 | units | 592 | units added to a foot's distance from the pelvis in the load share (8 cm) |  | ○ |  |  |  |  |  | retarget |
| LOAD_SHARE | (0.15, 0.45) |  | 593 | a foot bearing less of the weight than the first keeps its roll and its toes; more than the second: laid flat, the toes bent under a raised heel |  |  |  |  |  |  |  |  |
| ROLL_DORSI | (45.0, 60.0) |  | 595 | ／dorsiflexion／ over which the roll against the shank fades out of the corrections |  |  |  |  |  |  |  |  |
| AXIS_DORSI | (70.0, 80.0) |  | 596 | ／dorsiflexion／ (as the bones stand) over which the dorsiflexion's correction fades out: the foot points along the shank within 20 to 10 degrees, and the plane of the two… |  |  |  |  |  |  |  |  |
| SHANK_SWING | 25.0 | deg | 599 | degrees a frame: a shank turning faster takes no range correction of the foot |  |  |  |  |  |  |  |  |
| FOOT_STILL | 15.0 | deg | 600 | degrees a frame: a roll that jumps more while the foot turns less is a jump of the shank (the reference), not of the foot |  |  |  |  |  |  |  |  |
| ROLL_JUMP | 40.0 | deg | 600 | degrees a frame: a roll that jumps more while the foot turns less is a jump of the shank (the reference), not of the foot |  |  |  |  |  |  |  |  |
| FLAT_PITCH | (30.0, 60.0) | deg | 602 | degrees of pitch from the floor: a sole steeper than the first is laid flat less and less, steeper than the second (a foot pointed down at the floor) keeps its roll |  |  |  |  |  |  |  |  |
| ROUNDS | 3 |  | 604 | rounds of solving the legs again to put the sole on the floor |  |  |  |  |  |  |  |  |
| SUB | 8 |  | 605 | MMD draws 240 fps from the 30 fps keys and interpolates them in between: the frames between two keys are checked at 1/SUB |  |  |  |  |  |  |  |  |
| SUB_NEAR | 0.25 | units | 607 | units: an interval is checked where either end's planned lowest point is this near the floor |  | ○ |  |  |  |  |  | retarget |
| SUB_ROUNDS | 3 |  | 609 | rounds of raising both frames of an interval whose shoe dips below the floor |  |  |  |  |  |  |  |  |
| BRIDGE | 2 | frames | 610 | frames: a standing foot lifted for this long or less (the trace's jitter) stays down, |  |  |  | ○ |  |  |  | dance |
| BRIDGE_LIFT | 0.1875 | units | 611 | ... when its shoe stays this low (units, 1.5 cm): a real quick step goes higher |  | ○ |  |  |  |  |  | retarget |
| X_AXIS | np.array([1.0, 0.0, 0.0]) |  | 612 |  |  |  |  |  |  |  |  |  |
| TOE_FLEX_CAP | 20.0 | deg | 616 | degrees the toes bend down against the foot at most (足先EX toward flexion). Sour's Rin's shoe bends with 足先EX over its front half (the weights ramp from 0.06 at the vamp … |  |  |  |  | ○ |  |  | rig |
| TOE_LOAD_TAU | 1.0 | frames | 623 | frames: the weight comes onto the ball through two first-order lags of this (critically damped: from naught, half in 1.7 frames = 56 ms, 90 % in 3.9 = 130 ms). In a run … |  |  |  |  |  |  | ○ |  |
| TOE_RELEASE_TAU | 2.0 | frames | 628 | frames: after the toe-off the toe box returns to the shoe's own shape (first order): a 30 degree bend comes back at 350 deg/s at first, about the fastest an MTP turns at… |  |  |  |  |  |  | ○ |  |
| TOE_REACH | 0.3125 | units | 632 | units (2.5 cm), when asked (--toe-reach-cm; off by default): a still pointed foot whose shoe hovers lower than this over the floor reaches it with its toes (the trace's … | HANDOVER 2026-10-15 toes: 振付の元のモデルは足首からつま先が 3.2〜3.6 cm 長く、リンでは爪先が 1.3〜1.6 cm 浮く（トレースの模型 DIVA風ミク_105改。retarget で変わる） | ○ |  | ○ |  |  |  | retarget |
| TOE_REACH_SPEED | (10.0, 20.0) | cm/s | 637 | cm/s: a foot moving faster than the first reaches less and less, faster than the second not at all (a resting toe stays; a step's swing skims past) |  | ○ |  |  |  |  |  | retarget |
| TOE_REACH_RISE | (1.0, 3.0) | cm/s | 639 | cm/s up: a foot rising off the floor (after a toe-off) does not reach back for it |  | ○ |  |  |  |  |  | retarget |
| TOE_REACH_PITCH | (5.0, 10.0) | deg | 640 | degrees toes-down: a level foot over the floor does not reach, a pointed one does |  |  |  |  |  |  |  |  |
| TOE_REACH_TAU | 2.0 | frames | 641 | frames: the reach comes and goes this smoothly (a first order run both ways) |  |  |  |  |  |  |  |  |
| HOVER_MAX | 0.5 | units | 699 | units over the trace's floor (4 cm, a05 s11's band): the lower shoe this low counts as hovering | a05 s11 の帯（4 cm）。floaty（10-17） | ○ | ○ | ○ | ○ | ○ |  | retarget・rig |
| HOVER_FLIGHT_ACC | 61.25 | units/s^2 | 700 | units/s^2 down (half of gravity): a run whose pelvis falls faster is a flight | 重力の半分（122.5 / 2、8 cm/単位）。floaty の fq.py の宙の決めと同じ | ○ | ○ |  |  |  |  | retarget |
| HOVER_MIN_RUN | 4 | frames | 701 | frames: a shorter hover is left as it is |  |  |  |  |  |  |  |  |
| HOVER_FOOT_SPEED | 2.5 | units/s | 702 | units/s (20 cm/s): a run whose lower shoe moves up or down faster than this (the median over the run) is a foot on its way to or from the floor - a step's touch or lift,… |  | ○ |  | ○ |  |  |  | retarget |
| HOVER_TRANSIT | 0.15 | units | 705 | units (1.2 cm): a run whose lower shoe only rises (or only falls, within 1 mm a frame) by more than this is a foot passing through the band at a lift-off or a touch, not… |  | ○ |  | ○ |  |  |  | retarget |
| HOVER_EASE | 6 | frames | 708 | frames: the sink comes and goes over this many frames each way (a raised cosine) |  |  |  |  |  |  |  |  |
| HOVER_SMOOTH | 3 | frames | 709 | frames: the half width of the Hann window that smooths the sink inside a run |  |  |  |  |  |  |  |  |
| HOVER_ACC_BOUND | 122.0 | units/s^2 | 710 | units/s^2: the pelvis's downward acceleration (下半身's and センター's: pelvis_fall) the sink may not take a frame past (a frame already past it in the input keeps its own): th… | HANDOVER 2026-10-17 floaty の査読の直し: 床のコマで腰の下向きの加速度が 122 を越えない（実装は 130 で 41 コマ越えていた） | ○ | ○ | ○ |  |  | ○ | retarget |
| HOVER_ACC_TOL | 0.5 | units/s^2 | 720 | units/s^2: past a bound by more than this (as the balance layer's report counts) |  | ○ | ○ |  |  |  |  | retarget |
| HOVER_TOUCH | 0.025 | units | 721 | units (2 mm): the shoe's vertices this close to its lowest are the part that would touch |  | ○ |  |  |  |  |  | retarget |
| HOVER_GLIDE（引数 --hover-glide） | TOE_SLIDE[0] | cm/s | 722 | cm/s (30): a frame whose lower shoe's lowest part moves along the floor faster than this is a step's swing skimming the floor, not a foot held over it: the speed under w… | HANDOVER 2026-10-17 floaty: 協調役の決め「--hover-glide は既定 30 のまま」（1000 にすると浮き 4.12 % だが 10 cm 以上の滑りが 27.9 回/分） | ○ |  | ○ |  | ○ |  | retarget |
| LANDING_WINDOW | 6 | frames | 901 | frames (0.2 s) after a touchdown over which the heel comes down with the pelvis |  |  | ○ | ○ |  | ○ | ○ | retarget |
| LANDING_GAP | 4 | frames | 902 | frames off the floor before a touchdown (the human baseline's a05) |  |  |  |  |  | ○ |  |  |
| REACH_KNEE_DEG | 5.5 | deg | 908 | The human baseline found no frame of a planted human leg straighter than 5 degrees (a05's knee: the hip joint's distance to the ankle, the law of cosines); the MV's are … |  |  |  | ○ | ○ | ○ |  | rig |
| SKIM_SPEED | (5.0, 15.0) | cm | 912 | A foot that the dance moves over the floor faster than the first speed (cm/s) is less and less, faster than the second not at all, put onto the floor where the dance has… |  | ○ |  | ○ |  |  |  | retarget |
| HEEL_DROP_DEG | 5.0 | deg | 915 | The most the landing's heel comes down in a frame (degrees): the cap (some 25 degrees) over 5 frames, about the humans' 0.1 s median from the touch to the heel down and … |  |  |  |  |  |  |  |  |
| SKIM_LIFT | (0.0, 0.005) | units | 916 | units over the trace's floor (the flat sole): a foot moving faster than SKIM_SPEED higher than 0.4 mm over it is not put onto it. (CONTACT_EXIT's 4.8 to 5.2 mm before v1… | v11feet 2026-10-17（_spike/out/stage6/v11feet/NOTES.md）: 4.8〜5.2 mm → 0〜0.4 mm。retarget が元の高さで運ぶ足を足の層が床へ下ろして滑らせていた（足の層 1… | ○ |  | ○ |  |  |  | retarget |
| SKIM_LIFT_BEFORE | (CONTACT_EXIT, CONTACT_EXIT + 0.005) |  | 923 | (--skim off: the band before v11feet) | v11feet 2026-10-17: --skim off で前の作り（landing human だけ、CONTACT_EXIT の 4.8〜5.2 mm） |  |  |  |  |  |  |  |
| least_turn(rounds) | 30 |  | 939 |  |  |  |  |  |  |  |  |  |
| damped_up(substeps) | 8 |  | 1172 |  |  |  |  |  |  |  |  |  |
| toes_touching(rounds) | 30 |  | 1222 |  |  |  |  |  |  |  |  |  |
| measure_report(toe_extra) | 0.0 |  | 1755 |  |  |  |  |  |  |  |  |  |
| --trace-toe-cm | 0.0 | cm | 1783 | how much further the trace's model's foot reached from the ankle to the toe (cm): its pointed toe touched the floor where this model's stops short; the report's trace_to… |  | ○ |  | ○ |  |  |  | retarget |
| --toes | "anatomical" |  | 1787 | the toes (足先EX): anatomical (the floor bends them, a foot on its ball stays on it until it leaves, they return over TOE_RELEASE_TAU after it, nothing bent in the air) or… |  |  |  |  |  |  |  |  |
| --toe-reach-cm | 0.0 | cm | 1791 | a still pointed foot whose shoe hovers less than this over the floor reaches it with its toes, bent down up to TOE_FLEX_CAP (anatomical; 0, the default, for none; 2.5 is… |  | ○ |  |  |  |  |  | retarget |
| --skim | "on" |  | 1798 | on (the default, with any --landing): a foot the dance moves faster than SKIM_SPEED over the floor (its flat sole higher than SKIM_LIFT) is not pressed onto it; off: as … | v11feet 2026-10-17: 新設、既定 on（--landing off の 1 回目にも）。--landing off --skim off で c012c32 とバイト同じ |  |  | ○ |  | ○ |  | dance |
| --hover | "off" |  | 1802 | sink: where no foot is on the floor but the lower shoe hovers under HOVER_MAX over it and the pelvis does not fall as in a flight, the whole figure (centre and leg IKs) … | v11feet 2026-10-17: 既定 sink（--landing human）→ off。retarget の後は 2 回目の足の層の下げが 1 か所 23 コマ・最大 1.3 cm だけで、off でも鎖の最後の数が同じ（靴の… |  |  | ○ |  |  |  | dance |

## balance_layer.py（9. 体重（順 C の balance）、99）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FPS | 30.0 |  | 132 |  |  |  |  |  |  |  |  |  |
| DT | 1.0 / FPS |  | 133 |  |  |  |  |  |  |  |  |  |
| UNIT_M | 0.08 | m | 134 | one model unit is 8 cm (the analysis pack) |  | ○ |  |  |  |  |  | retarget |
| CM | 8.0 | cm | 135 | cm per unit |  | ○ |  |  |  |  |  | retarget |
| G | 9.81 |  | 136 |  |  |  | ○ |  |  |  |  | retarget |
| SUPPORT_H | 0.2 | units | 141 | units (1.6 cm, a05's FLY): a foot this low carries weight |  | ○ |  |  |  |  |  | retarget |
| CONTACT_EPS | 0.05 | units | 142 | units (4 mm, a05): a foot on the floor (the a05 measure, the landings) |  | ○ |  |  |  |  |  | retarget |
| CLEAR_CM | 5.0 | cm | 143 | the other foot this high: the full pull (a05's single support: 5 cm) |  | ○ |  |  |  |  |  | retarget |
| R_BAL_CM（引数 --r-bal） | 0.6 | cm | 144 | the band about the standing sole's line: people standing on one foot keep the centre of pressure -0.32 +- 0.55 cm from the foot's long axis (Haba & Iwatsuki 2023, Table … |  | ○ |  |  |  | ○ | ○ | retarget |
| LEAD_S（引数 --lead） | 0.15 | s | 148 | the pull ramps up this long before the foot lifts |  |  |  |  |  |  |  |  |
| LAG_S（引数 --lag） | 0.05 | s | 149 | and down this long after it lands |  |  |  |  |  |  |  |  |
| TRANSFER_V | 0.2 | m/s | 150 | m/s: a run whose COM moves this fast towards where the other foot lands, its XcoM past half the way there, is a step onto that foot and is not pulled (the review's crite… |  | ○ |  |  |  |  |  | retarget |
| STILL_V_CM_S | 5.0 | cm/s | 152 | cm/s: single support whose pelvis moves slower than this on the floor for STILL_MIN_S is |  | ○ |  |  |  |  |  | retarget |
| STILL_MIN_S | 0.3 | s | 153 | still, and pulled over the foot; elsewhere it moves (the human baseline's COM: v / w0 < 1.5 cm, a third of the foot's half width, so the XcoM stands within 1.5 cm of the… |  |  |  | ○ |  | ○ |  | dance |
| STILL_WEIGHT | 1.0 |  | 163 | the pull's weight there, times the run's peak (10 and 30 kept the body still a little longer at the stillness's end but started the weight shift over a second early and … |  |  |  |  |  |  |  |  |
| STILL_TAIL_S | 0.1 | s | 166 | the pull held this long after a still stretch (the foot still on the floor): the way back then starts at its end, not inside it (0.2 s left a 17 cm shift 0.5 cm short 1 … |  |  |  |  |  |  |  |  |
| STILL_LEAD_S | 0.6 | s | 170 | a still stretch that starts inside its run is pulled from this long before it: carrying the body 9 cm at ACC_MAX (up, then down) takes 2 sqrt(0.09 / 1) = 0.6 s |  |  |  |  |  |  |  |  |
| SUPPORT_R_CM | 4.0 | cm | 172 | a05's support of a foot: the capsule of this radius about the line from the heel point (ankle - 0.3 (toe - ankle)) to the toe; its centre half way |  | ○ |  |  |  |  |  | retarget |
| MOS_ML_MIN_CM（引数 --mos-ml-min） | -4.2 | cm | 174 | moving single support: the XcoM's sideways margin (SUPPORT_R_CM less the XcoM's sideways offset from the support's centre, towards the lifted foot along 下半身's side axis)… | HANDOVER 2026-10-16 balance-v2: 動きながらの片足立ちは XcoM の余裕で守る（人 −4.2 [−6.1, −3.6]、human_baseline の stance_summary） | ○ |  | ○ |  | ○ |  | retarget |
| STANCE_WEIGHT | 30.0 |  | 180 | the pull on the XcoM to that bound where the dance is past it (as CATCH_WEIGHT) |  |  |  | ○ |  |  |  | dance |
| ACC_MAX（引数 --acc-max） | 1.0 | m/s^2 | 182 | m/s^2 of added COM acceleration (about 9 cm of centre-of-pressure move) |  | ○ | ○ |  |  |  |  | retarget |
| TAU_S | 0.1 | s | 183 | the minimum-jerk smoothness's time scale |  |  |  |  |  |  |  |  |
| LAM_IN | 0.02 |  | 184 | the pull back to the dance where the pull is (relative to a full pull) |  |  |  | ○ |  |  |  | dance |
| LAM_OUT | 0.5 |  | 185 | and elsewhere: keeps a brief step's lean short (it does not start a second early) |  |  |  |  |  |  |  |  |
| DROP_MAX_CM（引数 --drop-max） | 2.0 | cm | 186 | the hips may go down this far for the legs to reach |  | ○ |  |  |  |  |  | retarget |
| DROP_ACC_MAX | 0.5 | m/s^2 | 187 | m/s^2: the drop's own acceleration (a slow give of the knees) |  | ○ | ○ |  |  |  |  | retarget |
| DROP_INSIDE_CM | 0.01 | cm | 188 | the drop for the legs' reach aims this much inside REACH_TOL_CM |  | ○ |  |  |  |  |  | retarget |
| REACH_TOL_CM | 1.5 | cm | 189 | a leg keeps this much slack, or as much as it had: MMD's IK (saba's solve, the feet layer's tools/leg_ik.py) leaves a foot on the floor more than 4 mm short of its IK ta… | HANDOVER 2026-10-14 balance の査読: 足ＩＫ 40 回の MMD の IK は余り 1 cm 未満で 70〜100 %、1.5〜4 cm で 2〜3 % 届かない。v11bal 2026-10-17: 足ＩＫ … | ○ |  | ○ | ○ |  |  | retarget・rig |
| REACH_FULL_LOOPS | 120 |  | 194 | a model whose leg IKs run this many loops and more keeps REACH_TOL_FULL_CM instead | v11bal 2026-10-17: 余り 0〜0.25 cm で届かないのは 40 回 89 %・60 回 83 %・80 回 28 %・120 回以上 0 % |  |  |  |  |  |  |  |
| REACH_TOL_FULL_CM | 0.5 | cm | 195 | (reach_tol_cm): the v11 chain's floor frames with 0-0.25 / 0.25-0.5 / 0.5-0.75 / 0.75-1 / 1-1.5 cm of slack, MMD's IK more than 4 mm short on 89 / 81 / 76 / 67 / 17 % of… | v11bal 2026-10-17: 足ＩＫ 120 回以上の模型（rig の写し 400 回）は余り 0〜1.5 cm の床のコマで MMD の IK が 4 mm より届かないコマ 0 → 余り 0.5 cm（1.5 cm のままでは… | ○ |  | ○ |  |  |  | retarget |
| ADMM_ITERS | 2000 |  | 199 | at most; it stops when the residuals are under the tolerances (v7: about 1,650) |  |  |  | ○ |  |  |  | dance |
| ADMM_TOL_ACC | 0.02 | m/s^2 | 200 | m/s^2 |  | ○ | ○ |  |  |  |  | retarget |
| ADMM_TOL_REACH | 0.05 | cm | 201 | cm |  | ○ |  |  |  |  |  | retarget |
| SET_MARGIN | 0.001 | m | 202 | m: the bounds are solved this much tighter, so the converged curve is inside the true ones |  | ○ |  |  |  |  |  | retarget |
| REACH_NO_WORSE_M | 0.0005 | m | 203 | m: "no worse than the dance" bounds allow this much, so the dance itself (no shift) is |  | ○ |  | ○ |  |  |  | retarget |
| RANGE_NO_WORSE_M | 0.002 | m | 204 | inside them, not on their edge (on the edge, the smallest miss of the solve could only be |  | ○ |  |  |  |  |  | retarget |
| RANGE_LINEAR_DEG | 0.5 | deg | 205 | degrees: the thigh's range is solved this much inside (its linear bound missed by up to 0.3 degrees where the shift turns the thigh 8 degrees, 195 s of the MV) |  |  |  |  |  |  |  |  |
| RANGE_NO_WORSE_DEG | 0.2 | deg | 207 | undone by no shift at all). A leg already past its reach: 0.5 mm (under the 1 mm of a new IK miss); a knee past 159 degrees: 2 mm along the hip-to-ankle line; a hip alre… |  |  |  | ○ |  |  |  | dance |
| FIX_HALF | 9 | frames | 211 | frames: the half-width of the smooth cover that brings an unconverged curve inside |  |  |  |  |  |  |  |  |
| SOLE_HALF_W_CM | 4.65 | cm | 213 | half the sole's width (young Japanese women's foot width 93.2 mm, AIST 1997-98) |  | ○ |  |  |  | ○ | ○ | retarget |
| CATCH_MARGIN_CM | 1.0 | cm | 214 | at a landing the margin of stability (the landing foot's outer edge along the step minus the XcoM) is kept at least this: a step onto a foot placed beyond the XcoM (Hof … |  | ○ |  |  |  |  | ○ | retarget |
| CATCH_WEIGHT | 30.0 |  | 218 | the pull on the XcoM at a landing the dance does not catch (against LAM_OUT 0.5 per frame) |  |  |  | ○ |  |  |  | dance |
| CATCH_FREE_S | 0.2 | s | 219 | the "never away from the nearest pull" half-plane is off this long after such a landing |  |  |  |  |  |  |  |  |
| CATCH_HOLD_MAX_CM | 8.0 | cm | 220 | a landing the dance misses by more than this (its margin under CATCH_MARGIN_CM less this) is a body running past the foot: it is not held back (nor bounded), the dance's… | v11bal 2026-10-17: v11 の鎖で受け止めを 9.8・10.0・27.1 cm 外す着地を引き戻すと体を 10〜22 cm ずらし解き方が収まらない（195・200 秒の ZMP の外れ）→ 8 cm を越えて外す着地は… | ○ | ○ | ○ |  |  |  | retarget |
| XI_RHO | 1.0 |  | 228 | the catch block's ADMM penalty relative to the per-frame sets' (convergence only) |  |  |  |  |  |  |  |  |
| IK_ROUNDS | 6 |  | 229 | with MMD's IK at hand: the rounds of holding back where it would newly fall short |  |  |  |  |  |  |  |  |
| IK_MISS | 0.05 | units | 230 | units (4 mm, a05's contact): an ankle this far from its foot IK's target misses it |  | ○ |  |  |  |  |  | retarget |
| IK_WORSE | 0.0125 | units | 231 | units (1 mm): and this much farther than in the dance: a new miss (the review's) |  | ○ |  | ○ |  |  |  | retarget |
| IK_HALF | 2 | frames | 232 | frames on each side of a new miss whose shift and dips are halved in a round |  |  |  |  |  |  |  |  |
| KEPT_MIN | 0.02 |  | 233 | a foot carried 98 % and more: its leg sets no bound on the shift |  |  |  |  |  |  |  |  |
| FREE_M | 1.0e3 | m | 234 | m: the radius (or slab side) of a bound that does not bound |  | ○ |  |  |  |  |  | retarget |
| CARRY_HALF | 6 | frames | 235 | frames: the half-width of the carry's smoothing (it changes over about 0.4 s) |  |  |  |  |  |  |  |  |
| G_MMD | 98.0 | units/s^2 | 237 | units/s^2: MMD's gravity as saba, three.js, MMDAgent-EX and babylon-mmd all have it (9.8 x 10; MMD's own default is not documented; the skirt research, question 4) | 再実装（saba・three.js・MMDAgent-EX・babylon-mmd）の 9.8 × 10。MMD 9.32 で測ると窓の値 1 あたり 9.6 単位/s²（窓 9.8 → 94。README の pmm_gravity の… | ○ | ○ |  |  |  |  | rig |
| DOWN_ACC_MAX（引数 --down-acc-max） | 122.0 | units/s^2 | 239 | units/s^2: the pelvis's downward acceleration, the dance's and the layer's together, at most this: the real g at 8 cm a unit (122.5). A body the floor holds up cannot fa… | HANDOVER 2026-10-16 balance-v2 の取り込み: 上限 122（1 単位 8 cm の重力 122.5。天井 70 のスカートで 99.4・213.4・253.6 秒の下着 0）。78 は拍の窪み 38 か所を浅… | ○ | ○ | ○ |  | ○ |  | retarget |
| SPIKE_T | 0.15 | m/s | 252 | m/s: a step of センター's path whose speed is above (or below) both neighbours' by more than this is a 1-frame spike, a jolt or a hitch (a08: s2_spectrum.spikes, T_SPIKE of … |  | ○ |  |  |  |  |  | retarget |
| SPIKE_PER_MIN（引数 --spike-per-min） | 7.2 |  | 254 | left at most, a minute, the largest taken first: human dancers have 7.2 [2.9, 10.9] (the human baseline, FineDance K-pop / choreography / jazz, 62 sequences); the traced… |  |  |  | ○ |  | ○ |  | dance |
| SPIKE_KINK_SHARE | 0.95 |  | 256 | around a spike taken the path's kinks at most this share of SPIKE_T (the speed changes no more than the velocity does: ／s(k) - s(k-1)／ <= ／v(k) - v(k-1)／) |  |  |  |  |  |  |  |  |
| DESPIKE_XZ_CM | 0.5 | cm | 258 | a despiked frame moves at most this far on the floor (the legs' reach is solved before it) |  | ○ |  |  |  |  |  | retarget |
| DESPIKE_DOWN_CM | 1.5 | cm | 259 | and at most this far down |  | ○ |  |  |  |  |  | retarget |
| DESPIKE_UP_CM | 0.75 | cm | 260 | and up (and never past the legs' reach). On the MV (on what the vertical fix leaves, 161 spikes): 1 / 0.5 / 0.3 cm leave 47 (10.9 a minute), 1.5 / 0.75 / 0.5 leave 38 (8… |  | ○ |  |  |  |  |  | retarget |
| DESPIKE_SOFT | 100.0 |  | 263 | the kink bound's weight (against 1 for the change): where the box cannot meet it, smaller |  |  |  |  |  |  |  |  |
| DESPIKE_HALF | 10 | frames | 264 | frames each side of a bounded kink that may move with it |  |  |  |  |  |  |  |  |
| DESPIKE_ROUNDS | 8 |  | 265 |  |  |  |  |  |  |  |  |  |
| DESPIKE_ITERS | 1500 |  | 266 |  |  |  |  |  |  |  |  |  |
| DESPIKE_PASSES（引数 --despike-passes） | 3 |  | 267 | (1: the layer before 2026-10-16; --despike-passes) | HANDOVER 2026-10-17 balance-v3: 突起のならしは最大 3 回（11.2 → 8.5 回/分） |  |  |  |  |  |  |  |
| DESPIKE_AIR | 1.0 |  | 268 | the box in the air (no leg reaches a floor there): order C of the MV kept 11.2 spikes a minute with the floor's box once the air kept the dance's fall (10.7 with 122 the… |  |  |  | ○ |  |  |  | dance |
| DIP_DEG（引数 --dip-deg） | 15.0 | deg | 271 | the knee's extra bend on a landing that takes the weight, from the heel (walking: 1-3 -> |  |  |  |  |  |  |  |  |
| DIP_PEAK_S | 0.13 | s | 272 | 17 degrees at 0.129 s after contact; Winter 2009 Table A.1, a woman of 156 cm) |  |  |  |  |  |  | ○ |  |
| DIP_DEG_FLAT | 12.0 |  | 273 | the foot flat (level walking 6 -> 18 degrees at 14 % of the cycle; De Pieri et al. 2022) |  |  |  |  |  |  |  |  |
| DIP_DEG_FORE | 9.0 |  | 274 | from the forefoot: the knee is already bent and the ankle takes more (toe walking 22 -> 30 degrees, the ankle 11 degrees up, De Pieri et al. 2022; the weight acceptance … |  |  |  |  |  |  |  |  |
| PITCH_KIND_DEG | 4.0 | deg | 277 | the toe-IK-to-ankle-IK line pitched this much from its rest: forefoot / heel first (the feet layer's HEEL_UP_DEG) |  |  |  |  |  |  |  |  |
| DIP_END_S | 0.4 | s | 279 |  |  |  |  |  |  |  |  |  |
| DIP_MAX_CM | 2.0 | cm | 280 | (2 cm in 0.13 s: the hips accelerate at most about 6 m/s^2) |  | ○ |  |  |  |  |  | retarget |
| DIP_WINDOW_S | 0.3 | s | 281 | the other foot lifts within this after the landing: the landing takes the weight |  |  |  |  |  |  |  |  |
| GAP | 4 |  | 282 | a05's swing: at least 4 frames off the floor... |  |  |  |  |  |  |  |  |
| SWING_MIN_H | 0.2 |  | 283 | ...in which the foot rose at least 1.6 cm |  |  |  |  |  |  |  |  |
| HIP_ADDUCTION_DEG | (20.0, 22.0) | deg | 285 | ---- the reference ranges (stage 3 research, the Japanese reference ROM 1995 / 2022 and the upper proposal) ----- |  |  |  |  |  |  | ○ |  |
| HIP_ABDUCTION_DEG | 45.0 | deg | 286 |  |  |  |  |  |  |  |  |  |
| KNEE_FLEXION_DEG | (130.0, 159.0) | deg | 287 |  |  |  |  |  |  |  |  |  |
| KNEE_GIVE_DEG | 12.0 | deg | 288 | the reach's drop bends a leg on the floor by at most this much more |  |  |  |  |  |  |  |  |
| KNEE_MIN_DEG | 5.0 | deg | 289 | a leg on the floor keeps its knee bent at least this much (the two-bone knee from the hip to the foot IK's target, a05's measure): human dancers never stand on a straigh… |  |  |  | ○ |  | ○ |  | dance |
| LIFT_FOLD_DEG | 5.0 | deg | 294 | a lifted leg's knee folds at most this much past the dance's (195 s of the MV: the heel kicked up behind from 3 to 60 cm in 0.2 s, faster than the carry comes in; 150 ->… |  |  |  | ○ |  |  |  | dance |
| SEGMENTS.head | (6.68, 48.41) |  | 300 | de Leva P (1996) J Biomech 29:1223-1230, Table 4, females: mass %, CM % from the first end (read in the original: _spike/out/stage2/motor/work/deleva1996_table4_text.txt… |  |  |  |  |  |  |  |  |
| SEGMENTS.middle_trunk | (14.65, 45.12) |  | 300 | de Leva P (1996) J Biomech 29:1223-1230, Table 4, females: mass %, CM % from the first end (read in the original: _spike/out/stage2/motor/work/deleva1996_table4_text.txt… |  |  |  |  |  |  |  |  |
| SEGMENTS.upper_trunk | (15.45, 50.50) |  | 300 | de Leva P (1996) J Biomech 29:1223-1230, Table 4, females: mass %, CM % from the first end (read in the original: _spike/out/stage2/motor/work/deleva1996_table4_text.txt… |  |  |  |  |  |  |  |  |
| SEGMENTS.forearm | (1.38, 45.59) |  | 301 |  |  |  |  |  |  |  |  |  |
| SEGMENTS.hand | (0.56, 34.27) |  | 301 |  |  |  |  |  |  |  |  |  |
| SEGMENTS.lower_trunk | (12.47, 49.20) |  | 301 |  |  |  |  |  |  |  |  |  |
| SEGMENTS.upper_arm | (2.55, 57.54) |  | 301 |  |  |  |  |  |  |  |  |  |
| SEGMENTS.foot | (1.29, 40.14) |  | 302 |  |  |  |  |  |  |  |  |  |
| SEGMENTS.shank | (4.81, 43.52) |  | 302 |  |  |  |  |  |  |  |  |  |
| SEGMENTS.thigh | (14.78, 36.12) |  | 302 |  |  |  |  |  |  |  |  |  |
| HEEL_BACK | 0.3 |  | 303 | the heel this share of the ankle-to-toe line behind the ankle (a05) |  |  |  |  |  |  |  |  |
| q_stats(qs) | (0.5, 0.9, 0.99) |  | 555 |  |  |  |  |  |  |  |  |  |
| D2_STENCIL | (1.0, -2.0, 1.0) |  | 626 |  |  |  |  |  |  |  |  |  |
| D3_STENCIL | (-1.0, 3.0, -3.0, 1.0) |  | 627 |  |  |  |  |  |  |  |  |  |
| project(rounds) | 30 |  | 865 |  |  |  |  |  |  |  |  |  |
| AIR_RAMP | 3 | frames | 1478 | frames: the drop goes from all to none over this many frames in from each end of the air |  |  |  |  |  |  |  |  |
| AIR_MIN | 4 | frames | 1479 | frames: the air is neither foot supporting for this many frames running or more (a jump, as the song's tests read it). A shorter stretch is a shuffle with a foot 1.6-3 c… |  |  |  | ○ |  |  |  | dance |

## contact_layer.py（11. 接地の計画（contact_layer）、67）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UNIT_CM | 8.0 | cm | 122 |  |  | ○ |  |  |  |  |  | retarget |
| FPS | 30.0 |  | 123 |  |  |  |  |  |  |  |  |  |
| G | 122.5 | units/s^2 | 124 | units/s^2: gravity (9.8 m/s^2) at 8 cm a unit |  | ○ | ○ |  |  |  |  | retarget |
| ON_FLOOR | 0.05 | units | 128 | units (4 mm, a05's contact): a shoe this low stands on the floor |  | ○ |  |  |  |  |  | retarget |
| HOLD_MAX | 0.5 | units | 129 | units (4 cm, a05 s11's band): a still shoe lower than this is held over the floor ... |  | ○ |  |  |  |  |  | retarget |
| HOLD_SPEED | 30.0 | cm/s | 130 | cm/s: ... its touching part moving along the floor slower than this (the foot layer's TOE_SLIDE and HOVER_GLIDE: a toe on the floor stays or slides slowly, a swing skims… |  | ○ |  |  |  |  |  | retarget |
| HOLD_RISE | 20.0 | cm/s | 132 | cm/s: ... its lowest point rising or falling slower than this, the smaller of the steps into and out of the frame (the foot layer's HOVER_FOOT_SPEED: faster is a touch o… |  | ○ |  |  |  |  |  | retarget |
| HOLD_MIN | 4 | frames | 134 | frames: a shorter hold is a foot passing by |  |  |  |  |  |  |  |  |
| FLIGHT_FIT | 0.8 * G | units/s^2 | 135 | units/s^2: no foot on the floor and the pelvis's parabola over the run and a frame each side falling faster than this is a flight even over a foot held still (people: 6 … |  | ○ | ○ |  |  | ○ |  | retarget |
| FLIGHT_BAND | (FLIGHT_FIT, 1.0 * G) | units/s^2 | 138 | units/s^2 down: a flight's centre of mass falls at the dance's own rate (its parabola over the flight) kept within this: slower comes to FLIGHT_FIT, faster (no body fall… | v11feet 2026-10-17（_spike/out/stage6/v11feet/NOTES.md）: 新設（FLIGHT_FIT 0.8 G 〜 G）。宙の重心は踊りの落ち方（宙の区間の放物線）をこの中で保つ（遅いものは 0.8… | ○ | ○ | ○ |  | ○ |  | retarget |
| FALL_BOUND | 122.0 | units/s^2 | 148 | units/s^2: the pelvis's downward acceleration where a foot holds the body up (the balance layer's DOWN_ACC_MAX, for the skirt); faster on a frame of a run with no foot d… |  | ○ | ○ |  |  |  |  | retarget |
| FALL_TOL | 0.5 | units/s^2 | 150 | units/s^2: past a bound by more than this (as the balance layer's report counts) |  | ○ | ○ |  |  |  |  | retarget |
| BRIDGE | 2 | frames | 151 | frames: a standing foot lifted this long or less stays down ... |  |  |  |  |  |  |  |  |
| BRIDGE_LIFT | 0.1875 | units | 152 | units (1.5 cm): ... where its shoe stays this low (the foot layer's BRIDGE_LIFT) |  | ○ |  |  |  |  |  | retarget |
| EASE | 4 | frames | 153 | frames: a foot's lowering comes and goes over this many frames each way (the foot layer's) |  |  |  |  |  |  |  |  |
| TOUCH | 0.025 | units | 154 | units (2 mm): the shoe's vertices this near its lowest touch (the foot layer's HOVER_TOUCH) |  | ○ |  |  |  |  |  | retarget |
| SWING_CLEAR | ON_FLOOR + 0.0125 | units | 155 | units (5 mm): a foot not standing whose touching part moves along the floor faster than PLANT_SPEED is not brought lower than this (nor below its own height in the dance… | v11feet 2026-10-17: 新設 5 mm（ON_FLOOR + 1 mm）。立ちの回りへの下げの馴らし・宙の体の変化に連れる下げで、30 cm/s より速い振りの足を床へ下ろしていた（曲の 22 + 15 cm/分） | ○ |  | ○ |  |  |  | retarget |
| GLIDE_MAX | 0.25 | units | 161 | units (2 cm): in a run of AIR_MIN frames and more with no foot standing whose pelvis does not fall as in a flight (its parabola over the run and a frame each side slower… | v11feet 2026-10-17: 新設 2 cm（retarget の TOUCH_FLOOR）。立つ足の無い 4 コマ以上で腰が宙のように落ちない所を低い方の足で支える。1.6 cm（AIR_CLEAR）では宙 4.63 回/分・… | ○ |  | ○ |  | ○ |  | retarget |
| NEED_CM | 10.0 | cm | 171 | cm: the centre of mass's floor point this far outside the other foot's sole: this foot bears weight (the MV's free resting feet have it -5 to +0.5 cm, the feet of its wi… |  | ○ |  |  |  | ○ |  | retarget |
| SOLE_TOUCH | 0.15 | units | 174 | units (1.2 cm): the vertices of a shoe this near the floor make its sole on it |  | ○ |  |  |  |  |  | retarget |
| KNEE_GIVE | 10.0 | deg | 175 | degrees: a held foot's knee stays within this of the leg's without the hold; further the foot slides as the dance has it (the knee change tools/sink_check.py and tools/c… |  |  |  | ○ |  |  |  | dance |
| DROP_MAX | 1.0 | units | 180 | units (8 cm): the most the pelvis goes down to let a standing leg reach the floor |  | ○ |  |  |  |  |  | retarget |
| REACH_MIN | 9 | frames | 181 | frames (0.3 s): a weight-bearing foot standing out of reach this long gets the pelvis lowered |  |  |  |  |  |  |  |  |
| DROP_WINDOW | 24 | frames | 182 | frames each side of a lowering over which it comes and goes (smoothly, within the bound) |  |  |  |  |  |  |  |  |
| DROP_QP_ROUNDS | 400 |  | 183 |  |  |  |  |  |  |  |  |  |
| JUDGE_MISS | 0.75 | units | 184 | units (6 cm): a foot MMD leaves this far or less from its goal is judged at the goal (a leg lagging or just out of reach: 159.7-163.9 and 197-198.7 s are 5.1 cm); furthe… |  | ○ |  |  |  |  |  | retarget |
| PLANT_SPEED | 30.0 | cm/s | 187 | cm/s: a standing foot's touching part moving slower than this is held in place (the trace's drift and jitter: v10's standing feet move faster than 27 cm/s on 10 % of the… |  | ○ |  | ○ |  | ○ |  | retarget |
| PLANT_POP | 2 |  | 190 | steps: a standing foot's moves faster than PLANT_SPEED in a run of this many or fewer, with a slower step of the same stand on each side, are a jump, not a slide, and ar… | v11feet 2026-10-17: 新設 2 歩。立つ足の 1〜2 歩の跳び（前後は遅い）は踊りの滑りでなく止める |  |  | ○ |  |  |  | dance |
| PLANT_SPIKE | (2.0, 5.0) | cm | 194 | (times, cm): and a standing foot's step longer than the first times the longer of its two neighbours and than the second is a jump inside a slide: it is brought to the n… | v11feet 2026-10-17: 新設（2 倍、5 cm）。滑りの中の 1 歩の跳び（曲の 242.1 秒、前後 1.7・1.9 cm の間の 11.35 cm）を前後の速さへ | ○ |  | ○ |  |  |  | retarget |
| PLANT_GIVE_BACK | 1.0 |  | 197 | times a step: what a jump inside a slide had taken off (PLANT_SPIKE) is given back over the slide's fast steps after it (before it, on the frames before the stand's put … | v11revm 2026-10-18（_spike/out/stage6/v11revm/NOTES.md）: 新設 1.0（1 歩につきその歩みの長さまで）。PLANT_SPIKE が滑りの中の跳びで止めた分を同じ立ちの滑りの速い歩みへ… |  |  | ○ |  |  |  | dance |
| AIR_MIN | 4 | frames | 203 | frames with no foot standing: a flight (the balance layer's AIR_MIN) |  |  |  |  |  |  |  |  |
| WINDOW | 8 | frames | 204 | frames each side of a flight over which the pelvis may change |  |  |  |  |  |  |  |  |
| SMOOTH | 30.0 |  | 205 | the weight of the change's third differences against the change itself |  |  |  |  |  |  |  |  |
| AIR_CLEAR | 0.2 + 0.0125 | units | 206 | units (1.6 cm and 1 mm): a shoe lower than 1.6 cm stands, as the skirt's bound counts it (the balance layer's support, tools/sink_check.py's SUPPORT_CM) |  | ○ |  |  |  |  |  | retarget |
| CARRY_RAMP | 2 | frames | 208 | frames: a foot leaving the floor goes with the body's change by half on its first frame off it and fully from the second (the same before a landing) |  |  |  |  |  |  |  |  |
| LIMB_SMOOTH | (1, 4, 6, 4, 1) |  | 210 | the weights the limbs' part of the centre of mass (its height over the pelvis) is smoothed with for the flight's parabola (binomial: none of a one-frame jump's 15 Hz pas… |  |  |  |  |  |  |  |  |
| PAD | 2 | frames | 212 | frames pinned to no change each side of a window of the pelvis's solves |  |  |  |  |  |  |  |  |
| SUB_NEAR | 0.25 | units | 213 | units: the intervals checked between the frames (either end this near the floor) |  | ○ |  |  |  |  |  | retarget |
| SUB_ROUNDS | 3 |  | 214 |  |  |  |  |  |  |  |  |  |
| IK_MISS | 0.0125 | units | 215 | units (1 mm): MMD's ankle this far from its goal has not reached it |  | ○ |  |  |  |  |  | retarget |
| LAND_TOL | 0.0125 | units | 216 | units (1 mm): a weight-bearing foot whose shoe MMD leaves higher than this gets more drop |  | ○ |  |  |  |  |  | retarget |
| PUSH_ROUNDS | 4 |  | 217 | rounds of pushing the goal of a weight-bearing foot MMD leaves over the floor ... |  |  |  |  |  |  |  |  |
| PUSH_STEP | 0.15 | units | 218 | units: ... by at most this a round (the foot layer's push) |  | ○ |  |  |  |  |  | retarget |
| DROP_ROUNDS | 4 |  | 219 | rounds of checking the lowered pelvis on MMD's IK (a nearly straight leg stops short) |  |  |  |  |  |  |  |  |
| FLIGHT_ROUNDS | 4 |  | 220 | rounds of solving the flight again on the centre of mass the changed dance moves ... |  |  |  | ○ |  |  |  | dance |
| FLIGHT_RESID | 1.0 | units/s^2 | 221 | units/s^2: ... until it falls within this of its flight's fall (FLIGHT_BAND) on the frames with air on both sides |  | ○ | ○ |  |  |  |  | retarget |
| STRICT_SMOOTH | 3.0 |  | 223 | the weight of the third differences of a lowering within STRICT_NEAR frames of a turn it |  |  |  |  |  |  |  |  |
| STRICT_NEAR | 8 |  | 224 | brings within the bound (strict frames) with no need there: the least lowering, not a wide one (the song's 40.13 s: 2.88 cm with SMOOTH, 1.55 with this, 1.29 the least; … |  |  |  | ○ |  |  |  | dance |
| KNEE_NEAR | 0.05 |  | 237 | of the reach: the band at its end (Rin's knee bent 31 degrees and less) where a frame or two straighter than the frames round them are bent like them |  |  |  | ○ | ○ |  | ○ | rig |
| KNEE_POP_DEG | 6.0 | deg | 239 | degrees: there a frame's bend comes within this of the line through its neighbours, and no neighbour's further than this the other way (rig_check counts a jump at 10. On… |  |  |  | ○ |  |  |  | dance |
| KNEE_JUMP_DEG | 10.0 | deg | 243 | degrees: rig_check ik's jump, a frame further than this off the line through its neighbours. Only such a frame and the frames KNEE_JUMP_NEAR round it are bent (the revie… |  |  |  | ○ |  |  |  | dance |
| KNEE_JUMP_NEAR | 1 | frames | 249 | frames |  |  |  |  |  |  |  |  |
| KNEE_ROUNDS | 40 |  | 250 | rounds of evening out (a pop of two frames halves its gap a round) |  |  |  |  |  |  |  |  |
| KNEE_PITCH_MAX | 30.0 | deg | 251 | degrees: the most a standing foot turns onto its toes or its heel for its knee |  |  |  |  |  |  |  |  |
| KNEE_PITCH_STEP | 0.25 | deg | 252 | degrees: the turns tried |  |  |  |  |  |  |  |  |
| KNEE_EDGE | 3 | frames | 253 | frames at either end of a standing run: a turn there is held on to the end of the run (the heel does not come down again before the foot lifts, nor rise again after it l… |  |  |  |  |  |  |  |  |
| KNEE_TOE_TOL | 1e-4 | units | 256 | units: a goal MMD's ankle is nearer than this to is reached (its toe IK's goal moves with it) |  | ○ |  |  |  |  |  | retarget |
| KNEE_PLAN_ROUNDS | 8 |  | 257 | rounds of the targets on the distances the changes so far leave (a turn held on to a run's end bends that frame more, and the frame before may then need more) |  |  |  |  |  |  |  |  |
| runs(n) | 1 |  | 261 |  |  |  |  |  |  |  |  |  |
| _r(n) | 3 |  | 268 |  |  |  |  |  |  |  |  |  |
| knee_bend(least_deg) | 0.0 | deg | 544 |  |  |  |  |  |  |  |  |  |
| knee_targets(least_deg) | 0.0 | deg | 595 |  |  |  |  |  |  |  |  |  |
| solve_qp(batch) | 1 |  | 631 |  |  |  |  |  |  |  |  |  |
| solve_qp(rounds) | 60 |  | 631 |  |  |  |  |  |  |  |  |  |
| knee_turn(least) | 0.0 |  | 982 |  |  |  |  |  |  |  |  |  |
| knee_turn(sign) | 0.0 |  | 982 |  |  |  |  |  |  |  |  |  |
| knee_jump_frames(deg) | 10.0 |  | 1623 |  |  |  |  |  |  |  |  |  |

## wb_layer.py（12. 上体の慣性、5）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FPS | 30.0 |  | 76 |  |  |  |  |  |  |  |  |  |
| GAIN（引数 --gain） | 0.9 |  | 77 | the head's pivot moves back by this share of the pelvis's quick part (see the doc) | HANDOVER 2026-10-17 wbbalance: 骨盤の左右・前後の 1.5 Hz より速い分の 0.9 倍だけ頭を戻す（頭が骨盤に付く傾き 0.89 → 0.31、人 0.29） |  |  |  |  |  |  |  |
| CUTOFF_HZ（引数 --cutoff） | 1.5 | Hz | 78 | the pelvis's slower part, which the upper body follows (people: 0.89 at 0.5 Hz, 0.47 at 1.5) | HANDOVER 2026-10-17 wbbalance（1.5 Hz） |  |  |  |  | ○ |  |  |
| MAX_BEND_DEG（引数 --max-bend） | 10.0 | deg | 79 | the whole bend of the spine at most (the sum over its joints) | HANDOVER 2026-10-17 wbbalance（曲げの合計 10 度まで） |  |  |  |  |  |  |  |
| UPRIGHT_SHARE | (0.3, 0.6) |  | 80 | the levers' height over their length: no tilt under the first, the whole over the second |  |  |  |  |  |  |  |  |

## wb_dynamics.py（12. 上体の慣性、29）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FPS | 30.0 |  | 57 |  |  |  |  |  |  |  |  |  |
| UNIT_M | 0.08 | m | 58 | metres a model unit (the analysis pack) | 解析の資料の 8 cm/単位 | ○ |  |  |  |  |  | retarget |
| G | 9.81 |  | 59 |  |  |  | ○ |  |  |  |  | retarget |
| HAND_TIP_SHARE | 0.88 |  | 67 | Rin: 手首 -> 中指３ 12.0 cm of about 13.6 to the tip; SMPL-X: 16.4 cm of about 18.7 |  |  |  |  | ○ |  |  | rig |
| HEEL_BACK | 0.3 |  | 82 | the foot segment's heel this share of the ankle -> toe line behind the ankle (a05) |  |  |  |  |  |  |  |  |
| ZMP_MIN_G | 0.2 |  | 84 | the ZMP is read where the floor pushes up at least this share of g |  |  | ○ |  |  |  |  | retarget |
| CUTOFF_HZ（引数 --cutoff） | 6.0 | Hz | 85 | the low-pass on the segments' COMs (Winter 2009's 6 Hz for markers before differentiating) |  |  |  |  |  |  | ○ |  |
| RUN_DEPTH_M | 0.005 | m | 86 | a stretch outside the base of support: the ZMP 5 mm and more outside ... |  | ○ |  |  |  |  |  | retarget |
| EDGE_FRAMES | 3 | frames | 87 | (frames at each end left out of the statistics: the filter's and the differences' ends) |  |  |  |  |  |  |  |  |
| KNEE_FLOOR_M | 0.08 | m | 88 | a knee joint this near the floor kneels on it (the joint's centre over the kneecap's skin) |  | ○ |  |  |  |  |  | retarget |
| HAND_FLOOR_M | 0.04 | m | 89 | a hand's wrist or middle finger joint this near the floor is put down on it |  | ○ |  |  |  |  |  | retarget |
| OTHER_R_M | 0.03 | m | 90 | the disc of floor under a knee or a hand |  | ○ |  |  |  |  |  | retarget |
| AIR_MIN_FRAMES | 5 | frames | 91 | an air stretch this long and longer is measured (its parabola and its angular momentum's line) |  |  |  |  |  |  |  |  |
| RIN_TOE_U | 0.1217 |  | 103 |  |  |  |  |  |  |  |  |  |
| RIN_FEET.ankle_rest_y | 1.7452 |  | 105 |  |  |  |  |  |  |  |  |  |
| RIN_FEET.contact | 0.15 |  | 105 |  |  |  |  |  |  |  |  |  |
| RIN_FEET.floor_y | 0.111 |  | 105 |  |  |  |  |  |  |  |  |  |
| RIN_FEET.foot_length_m | 0.1672 | m | 105 |  | リンの靴の頂点から（16.7 cm）。人の体（SMPL-X の中立）の足は約 26 cm（足首→母指球 12.7 cm / 0.49）で 0.64 倍、脚は 0.91 倍（adapt 10-17、左右の平均は review_adapt） | ○ |  |  |  |  |  | rig |
| RIN_FEET.toe_rest_y | 0.1 |  | 105 |  |  |  |  |  |  |  |  |  |
| RIN_FEET.stature_m | (18.7663 - 0.111) * UNIT_M | m | 106 |  | リンの頭先の骨 18.7663 − 床 0.111（8 cm/単位で 1.49 m）。髪の上までなら 19.086 単位（adapt 10-17） | ○ |  |  |  |  |  | rig |
| human_feet(contact) | 0.15 |  | 109 |  |  |  |  |  |  |  |  |  |
| HEAD_TIP_FALLBACK | 0.155 |  | 284 | without 頭先: the vertex this share of 頭's height above 頭 (tools/motor_layer.py) |  |  |  |  |  |  |  |  |
| dynamics(floor_y) | 0.0 |  | 346 |  |  |  |  |  |  |  |  |  |
| _q(qs) | (0.05, 0.25, 0.5, 0.75, 0.95) |  | 574 |  |  |  |  |  |  |  |  |  |
| BANDS.0.5-1Hz | (0.5, 1.0) |  | 716 |  |  |  |  |  |  |  |  |  |
| BANDS.1-2Hz | (1.0, 2.0) |  | 716 |  |  |  |  |  |  |  |  |  |
| BANDS.2-4Hz | (2.0, 4.0) |  | 716 |  |  |  |  |  |  |  |  |  |
| BANDS.4-8Hz | (4.0, 8.0) |  | 716 |  |  |  |  |  |  |  |  |  |
| WELCH_N | 60 | frames | 717 | frames (2 s Hann windows, half overlap) |  |  |  |  |  |  |  |  |

## hand_layer.py（13. 手と指、触れの層（v11arms）、150）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SIDES | (("左", 1.0), ("右", -1.0)) |  | 201 |  |  |  |  |  |  |  |  |  |
| PULP_MIN_VERTICES | 20 |  | 206 | the thumb's pulp side is read from the mesh when this many vertices hang on 親指２ |  |  |  |  |  |  |  |  |
| PULP_WEIGHT | 0.6 |  | 207 | (a vertex hangs on a bone when its weight there is at least this) |  |  |  |  |  |  |  |  |
| GRAVITY | np.array([0.0, -9.80665, 0.0]) | m/s^2 | 363 | m/s^2 in the model's axes (Y up) |  | ○ | ○ |  | ○ |  |  | retarget・rig |
| passive_response(substeps) | 8 |  | 366 |  |  |  |  |  |  |  |  |  |
| follow_response(substeps) | 8 |  | 392 |  |  |  |  |  |  |  |  |  |
| FPS | 30.0 |  | 463 |  |  |  |  |  |  |  |  |  |
| UNIT_M | 0.08 | m | 464 | one model unit is 8 cm (the analysis pack's README) | 解析の資料の 8 cm/単位 | ○ |  |  |  |  |  | retarget |
| HINGE.side | (3.0, 8.0) | deg | 470 | the hinge joints (PIP, DIP, the thumb's IP and MP) bend in one plane: their sideways bend and their twist, read from the rest pose, eased from the start toward the cap (… |  |  |  |  | ○ |  | ○ | rig |
| HINGE.twist | (5.0, 12.0) | deg | 470 | the hinge joints (PIP, DIP, the thumb's IP and MP) bend in one plane: their sideways bend and their twist, read from the rest pose, eased from the start toward the cap (… |  |  |  |  | ○ |  | ○ | rig |
| HINGE_THUMB_MP.side | (12.0, 20.0) |  | 471 |  |  |  |  |  |  |  |  |  |
| HINGE_THUMB_MP.twist | (5.0, 12.0) |  | 471 |  |  |  |  |  |  |  |  |  |
| COUPLING.from | 20.0 |  | 477 | DIP / PIP of the long fingers where the PIP bends more than COUPLING["from"] degrees: kept between low and high. The low ends are the slopes of DIP on PIP in the lightes… |  |  |  |  |  |  | ○ |  |
| COUPLING.full | 40.0 |  | 477 | DIP / PIP of the long fingers where the PIP bends more than COUPLING["from"] degrees: kept between low and high. The low ends are the slopes of DIP on PIP in the lightes… |  |  |  |  |  |  | ○ |  |
| COUPLING.high | 1.0 |  | 477 | DIP / PIP of the long fingers where the PIP bends more than COUPLING["from"] degrees: kept between low and high. The low ends are the slopes of DIP on PIP in the lightes… |  |  |  |  |  |  | ○ |  |
| COUPLING.low.中指 | 0.36 |  | 477 | DIP / PIP of the long fingers where the PIP bends more than COUPLING["from"] degrees: kept between low and high. The low ends are the slopes of DIP on PIP in the lightes… |  |  |  |  |  |  | ○ |  |
| COUPLING.low.人指 | 0.32 |  | 477 | DIP / PIP of the long fingers where the PIP bends more than COUPLING["from"] degrees: kept between low and high. The low ends are the slopes of DIP on PIP in the lightes… |  |  |  |  |  |  | ○ |  |
| COUPLING.low.小指 | 0.25 |  | 477 | DIP / PIP of the long fingers where the PIP bends more than COUPLING["from"] degrees: kept between low and high. The low ends are the slopes of DIP on PIP in the lightes… |  |  |  |  |  |  | ○ |  |
| COUPLING.low.薬指 | 0.16 |  | 477 | DIP / PIP of the long fingers where the PIP bends more than COUPLING["from"] degrees: kept between low and high. The low ends are the slopes of DIP on PIP in the lightes… |  |  |  |  |  |  | ○ |  |
| COUPLING_SOFT | 4.0 | deg | 478 | degrees inside the band where the wall starts |  |  |  |  |  |  |  |  |
| ENSLAVE | 0.05 |  | 481 | each long finger's MP is pulled toward each neighbour's MP by this share of their difference (the adjacent fingers' passive coupling) |  |  |  |  |  |  |  |  |
| ROM.mp.flex | ((25.0, 40.0), (90.0, 100.0)) |  | 487 |  |  |  |  |  |  |  |  |  |
| ROM.mp.twist | ((15.0, 25.0), (15.0, 25.0)) |  | 487 |  |  |  |  |  |  |  |  |  |
| ROM.pip.flex | ((15.0, 30.0), (100.0, 110.0)) |  | 488 |  |  |  |  |  |  |  |  |  |
| ROM.dip.flex | ((10.0, 20.0), (80.0, 90.0)) |  | 489 |  |  |  |  |  |  |  |  |  |
| ROM.cmc.flex | ((10.0, 20.0), (60.0, 65.0)) |  | 490 |  |  |  |  |  |  |  |  |  |
| ROM.cmc.side | ((15.0, 25.0), (90.0, 95.0)) |  | 490 |  |  |  |  |  |  |  |  |  |
| ROM.cmc.twist | ((25.0, 35.0), (25.0, 35.0)) |  | 490 |  |  |  |  |  |  |  |  |  |
| ROM.tmp.flex | ((10.0, 25.0), (60.0, 65.0)) |  | 491 |  |  |  |  |  |  |  |  |  |
| ROM.ip.flex | ((15.0, 30.0), (80.0, 90.0)) |  | 492 |  |  |  |  |  |  |  |  |  |
| MP_SIDE.中指 | ((25.0, 35.0), (25.0, 35.0)) |  | 499 | the MCP's sideways range, finger by finger (Latz 2019, table 1, the wrist neutral: the mean for the start, the mean + 2 SD for the cap): (ulnar, radial). The little fing… |  |  |  |  | ○ |  | ○ | rig |
| MP_SIDE.人指 | ((20.7, 44.1), (31.2, 50.8)) |  | 499 | the MCP's sideways range, finger by finger (Latz 2019, table 1, the wrist neutral: the mean for the start, the mean + 2 SD for the cap): (ulnar, radial). The little fing… |  |  |  |  | ○ |  | ○ | rig |
| MP_SIDE.小指 | ((48.5, 82.5), (14.8, 40.4)) |  | 500 |  |  |  |  |  |  |  |  |  |
| MP_SIDE.薬指 | ((28.0, 49.4), (8.1, 19.7)) |  | 500 |  |  |  |  |  |  |  |  |  |
| SPEED_MAX_DEG_S（引数 --speed-max） | 1900.0 | deg/s | 501 | a finger's MP + PIP + DIP together, degrees per second |  |  |  |  |  |  |  |  |
| ORDER.close.dip | 0.10 | frames | 506 | the order of a finger's joints within a change of its shape, as shares of the change's length (frames, at most ORDER_MAX): closing, the MCP's speed peaks 11.4 % after th… |  |  |  |  |  |  | ○ |  |
| ORDER.close.mp | 0.114 | frames | 506 | the order of a finger's joints within a change of its shape, as shares of the change's length (frames, at most ORDER_MAX): closing, the MCP's speed peaks 11.4 % after th… |  |  |  |  |  |  | ○ |  |
| ORDER.close.pip | 0.0 | frames | 506 | the order of a finger's joints within a change of its shape, as shares of the change's length (frames, at most ORDER_MAX): closing, the MCP's speed peaks 11.4 % after th… |  |  |  |  |  |  | ○ |  |
| ORDER.open.dip | 0.074 | frames | 506 | the order of a finger's joints within a change of its shape, as shares of the change's length (frames, at most ORDER_MAX): closing, the MCP's speed peaks 11.4 % after th… |  |  |  |  |  |  | ○ |  |
| ORDER.open.mp | 0.0 | frames | 506 | the order of a finger's joints within a change of its shape, as shares of the change's length (frames, at most ORDER_MAX): closing, the MCP's speed peaks 11.4 % after th… |  |  |  |  |  |  | ○ |  |
| ORDER.open.pip | 0.074 | frames | 506 | the order of a finger's joints within a change of its shape, as shares of the change's length (frames, at most ORDER_MAX): closing, the MCP's speed peaks 11.4 % after th… |  |  |  |  |  |  | ○ |  |
| ORDER_MAX（引数 --order-max） | 1.5 |  | 507 |  |  |  |  |  |  |  |  |  |
| ORDER_SPEED | 60.0 | deg | 508 | degrees per second of a finger's MP + PIP + DIP: it is changing its shape |  |  |  |  |  |  |  |  |
| PACE.c | 1.10 |  | 521 | the pace of a change of shape (pace): the dancers of FineDance (K-pop and street, the middle finger's MP + PIP + DIP, about 25,000 changes; _spike/out/stage6/finger_moti… |  |  |  | ○ |  | ○ |  | dance |
| PACE.iterations | 4 |  | 521 | the pace of a change of shape (pace): the dancers of FineDance (K-pop and street, the middle finger's MP + PIP + DIP, about 25,000 changes; _spike/out/stage6/finger_moti… |  |  |  | ○ |  | ○ |  | dance |
| PACE.min | 20.0 |  | 521 | the pace of a change of shape (pace): the dancers of FineDance (K-pop and street, the middle finger's MP + PIP + DIP, about 25,000 changes; _spike/out/stage6/finger_moti… |  |  |  | ○ |  | ○ |  | dance |
| PACE.p | 0.35 |  | 521 | the pace of a change of shape (pace): the dancers of FineDance (K-pop and street, the middle finger's MP + PIP + DIP, about 25,000 changes; _spike/out/stage6/finger_moti… |  |  |  | ○ |  | ○ |  | dance |
| PACE.step | 0.2 |  | 521 | the pace of a change of shape (pace): the dancers of FineDance (K-pop and street, the middle finger's MP + PIP + DIP, about 25,000 changes; _spike/out/stage6/finger_moti… |  |  |  | ○ |  | ○ |  | dance |
| PACE_H | math.sqrt(3.0) / 2.563 |  | 525 | a centred box average of half-width h adds h^2 / 3 to the variance of a change's speed profile, and a bell-shaped profile's 10 - 90 % time is about 2.563 of its standard… |  |  |  |  |  |  |  |  |
| TRANSIT.c | 30.79 |  | 532 | the transit (_spike/out/stage6/fingers_v3/, v3_human.py, v3_human2.py, v3_human3.py: FineDance's K-pop and street dances, 74,000 movements of the arm: the knuckle's spee… |  |  |  | ○ |  | ○ |  | dance |
| TRANSIT.cap | 25.0 |  | 532 | the transit (_spike/out/stage6/fingers_v3/, v3_human.py, v3_human2.py, v3_human3.py: FineDance's K-pop and street dances, 74,000 movements of the arm: the knuckle's spee… |  |  |  | ○ |  | ○ |  | dance |
| TRANSIT.open | 15.0 |  | 532 | the transit (_spike/out/stage6/fingers_v3/, v3_human.py, v3_human2.py, v3_human3.py: FineDance's K-pop and street dances, 74,000 movements of the arm: the knuckle's spee… |  |  |  | ○ |  | ○ |  | dance |
| TRANSIT.p | 0.564 |  | 532 | the transit (_spike/out/stage6/fingers_v3/, v3_human.py, v3_human2.py, v3_human3.py: FineDance's K-pop and street dances, 74,000 movements of the arm: the knuckle's spee… |  |  |  | ○ |  | ○ |  | dance |
| TRANSIT.peak | 0.3 |  | 532 | the transit (_spike/out/stage6/fingers_v3/, v3_human.py, v3_human2.py, v3_human3.py: FineDance's K-pop and street dances, 74,000 movements of the arm: the knuckle's spee… |  |  |  | ○ |  | ○ |  | dance |
| TRANSIT.shut | 170.0 |  | 532 | the transit (_spike/out/stage6/fingers_v3/, v3_human.py, v3_human2.py, v3_human3.py: FineDance's K-pop and street dances, 74,000 movements of the arm: the knuckle's spee… |  |  |  | ○ |  | ○ |  | dance |
| TRANSIT.smooth | 2 |  | 532 | the transit (_spike/out/stage6/fingers_v3/, v3_human.py, v3_human2.py, v3_human3.py: FineDance's K-pop and street dances, 74,000 movements of the arm: the knuckle's spee… |  |  |  | ○ |  | ○ |  | dance |
| TRANSIT.span | (6, 60) |  | 532 | the transit (_spike/out/stage6/fingers_v3/, v3_human.py, v3_human2.py, v3_human3.py: FineDance's K-pop and street dances, 74,000 movements of the arm: the knuckle's spee… |  |  |  | ○ |  | ○ |  | dance |
| TRANSIT.change | 10.0 |  | 533 |  |  |  |  |  |  |  |  |  |
| TRANSIT.flip | 0.55 |  | 533 |  |  |  |  |  |  |  |  |  |
| TRANSIT.half | 3 |  | 533 |  |  |  |  |  |  |  |  |  |
| TRANSIT.pad | 2 |  | 533 |  |  |  |  |  |  |  |  |  |
| TRANSIT.spread | (30.0, 60.0) |  | 533 |  |  |  |  |  |  |  |  |  |
| TRANSIT_SYNERGY.中指 | (0.410, 0.316, 0.179) |  | 541 | "flip": between open and shut the way turns from the last movement's with this chance, drawn per movement (the dancers turn it 53 - 56 % of the time and nothing of the a… |  |  |  | ○ |  | ○ |  | dance |
| TRANSIT_SYNERGY.人指 | (0.327, 0.317, 0.150) |  | 541 | "flip": between open and shut the way turns from the last movement's with this chance, drawn per movement (the dancers turn it 53 - 56 % of the time and nothing of the a… |  |  |  | ○ |  | ○ |  | dance |
| TRANSIT_SYNERGY.薬指 | (0.400, 0.355, 0.134) |  | 541 | "flip": between open and shut the way turns from the last movement's with this chance, drawn per movement (the dancers turn it 53 - 56 % of the time and nothing of the a… |  |  |  | ○ |  | ○ |  | dance |
| TRANSIT_SYNERGY.小指 | (0.296, 0.232, 0.149) |  | 542 |  |  |  |  |  |  |  |  |  |
| OPEN | (30.0, 70.0, 90.0) |  | 550 | the relaxed hand: an open hand (the four fingers' mean MP + PIP + DIP under OPEN[0], none over OPEN[2]) is relaxed (fully at OPEN[0], not at all from OPEN[1]); it leans … |  |  |  | ○ |  |  | ○ | dance |
| RELAXED_HAND.中指 | (33.2, 40.7, 14.2) |  | 551 |  |  |  |  |  |  |  |  |  |
| RELAXED_HAND.人指 | (27.1, 38.7, 13.8) |  | 551 |  |  |  |  |  |  |  |  |  |
| RELAXED_HAND.小指 | (26.2, 43.1, 16.1) |  | 551 |  |  |  |  |  |  |  |  |  |
| RELAXED_HAND.薬指 | (29.3, 44.8, 14.3) |  | 551 |  |  |  |  |  |  |  |  |  |
| RELAXED_WRIST | 17.5 |  | 552 |  |  |  |  |  |  |  |  |  |
| TENODESIS.dip | 0.16 |  | 553 |  |  |  |  |  |  |  |  |  |
| TENODESIS.mp | 0.30 |  | 553 |  |  |  |  |  |  |  |  |  |
| TENODESIS.pip | 0.43 |  | 553 |  |  |  |  |  |  |  |  |  |
| TENODESIS_WRIST | 60.0 | deg | 554 | degrees each way of the wrist that Su 2005 measured |  |  |  |  |  |  | ○ |  |
| RELAX_GAIN（引数 --relax-gain） | 0.25 |  | 555 |  |  |  |  |  |  |  |  |  |
| SEGMENT_MASS.中指 | (20.0, 9.6, 6.5) |  | 557 | the passive lag: one body per finger turning at its MP (the thumb at its MP) against a spring and a damper |  |  |  |  |  |  |  |  |
| SEGMENT_MASS.人指 | (19.1, 8.1, 6.0) |  | 557 | the passive lag: one body per finger turning at its MP (the thumb at its MP) against a spring and a damper |  |  |  |  |  |  |  |  |
| SEGMENT_MASS.小指 | (10.8, 5.3, 4.3) |  | 557 | the passive lag: one body per finger turning at its MP (the thumb at its MP) against a spring and a damper |  |  |  |  |  |  |  |  |
| SEGMENT_MASS.薬指 | (17.0, 8.9, 5.5) |  | 557 | the passive lag: one body per finger turning at its MP (the thumb at its MP) against a spring and a damper |  |  |  |  |  |  |  |  |
| SEGMENT_MASS.親指 | (12.0, 6.0) |  | 558 |  |  |  |  |  |  |  |  |  |
| REF_LENGTH_M.中指 | 0.109 | m | 559 |  |  | ○ |  |  |  |  |  | retarget |
| REF_LENGTH_M.人指 | 0.099 | m | 559 |  |  | ○ |  |  |  |  |  | retarget |
| REF_LENGTH_M.小指 | 0.082 | m | 559 |  |  | ○ |  |  |  |  |  | retarget |
| REF_LENGTH_M.薬指 | 0.102 | m | 559 |  |  | ○ |  |  |  |  |  | retarget |
| REF_LENGTH_M.親指 | 0.06 | m | 559 |  |  | ○ |  |  |  |  |  | retarget |
| REF_INERTIA.中指 | 1.26e-4 |  | 560 |  |  |  |  |  |  |  |  |  |
| REF_INERTIA.人指 | 9.5e-5 |  | 560 |  |  |  |  |  |  |  |  |  |
| REF_INERTIA.小指 | 4.6e-5 |  | 560 |  |  |  |  |  |  |  |  |  |
| REF_INERTIA.薬指 | 9.9e-5 |  | 560 |  |  |  |  |  |  |  |  |  |
| REF_INERTIA.親指 | 4.0e-5 |  | 560 |  |  |  |  |  |  |  |  |  |
| STIFFNESS.held | 1.0 |  | 564 | N m/rad at the MP of a grown finger: a held shape (a finger stroking a surface, Kry & Pai 2006: about 1.0; a held finger is 2 to 5 times the relaxed one, Milner & Frankl… |  |  |  |  |  |  | ○ |  |
| STIFFNESS.open | 0.21 |  | 564 | N m/rad at the MP of a grown finger: a held shape (a finger stroking a surface, Kry & Pai 2006: about 1.0; a held finger is 2 to 5 times the relaxed one, Milner & Frankl… |  |  |  |  |  |  | ○ |  |
| ZETA.held | 0.85 |  | 568 | the damping ratio of a held shape: co-contracted, it trails and catches up without swinging back (a pressed fingertip 0.83 - 1.15, Kry & Pai 2006, Hajian & Howe 1997; th… |  |  |  | ○ |  |  | ○ | dance |
| ZETA.open | 0.85 |  | 568 | the damping ratio of a held shape: co-contracted, it trails and catches up without swinging back (a pressed fingertip 0.83 - 1.15, Kry & Pai 2006, Hajian & Howe 1997; th… |  |  |  | ○ |  |  | ○ | dance |
| ZETA_OPEN.中指 | 0.614 |  | 572 | the open hand's damping ratio, finger by finger: relaxed fingers released from a bend (Tsakonas et al. 2024, 23 people, the MP's flexion, the means of each finger's fits… |  |  |  |  |  | ○ |  |  |
| ZETA_OPEN.人指 | 0.562 |  | 572 | the open hand's damping ratio, finger by finger: relaxed fingers released from a bend (Tsakonas et al. 2024, 23 people, the MP's flexion, the means of each finger's fits… |  |  |  |  |  | ○ |  |  |
| ZETA_OPEN.小指 | 0.689 |  | 572 | the open hand's damping ratio, finger by finger: relaxed fingers released from a bend (Tsakonas et al. 2024, 23 people, the MP's flexion, the means of each finger's fits… |  |  |  |  |  | ○ |  |  |
| ZETA_OPEN.薬指 | 0.591 |  | 572 | the open hand's damping ratio, finger by finger: relaxed fingers released from a bend (Tsakonas et al. 2024, 23 people, the MP's flexion, the means of each finger's fits… |  |  |  |  |  | ○ |  |  |
| PASSIVE_SHARE.dip | 0.2 |  | 573 |  |  |  |  |  |  |  |  |  |
| PASSIVE_SHARE.ip | 0.5 |  | 573 |  |  |  |  |  |  |  |  |  |
| PASSIVE_SHARE.mp | 1.0 |  | 573 |  |  |  |  |  |  |  |  |  |
| PASSIVE_SHARE.pip | 0.35 |  | 573 |  |  |  |  |  |  |  |  |  |
| PASSIVE_SHARE.tmp | 1.0 |  | 573 |  |  |  |  |  |  |  |  |  |
| PASSIVE_CAP | (4.0, 10.0) | deg | 574 | degrees: the lag is eased from the start toward the cap |  |  |  |  |  |  |  |  |
| PASSIVE_LEAD（引数 --passive-lead） | 0.0 |  | 579 | review_fingers_v3: off by default (see REVIEW) |  |  |  | ○ | ○ |  | ○ | rig |
| ACC_SMOOTH | 1 | frames | 580 | frames each way of the triangle that smooths the accelerations |  |  |  |  |  |  |  |  |
| WRIST_ELLIPSE.centre | (-8.2, -1.8) | deg | 584 | the active circumduction of the wrist as an ellipse (Gracia-Ibanez 2020, dominant hand): x radial (+) / ulnar deviation, y palmar flexion (+) / extension, degrees: the c… |  |  |  |  |  |  | ○ |  |
| WRIST_ELLIPSE.half_axes | (35.0, 73.2) | deg | 584 | the active circumduction of the wrist as an ellipse (Gracia-Ibanez 2020, dominant hand): x radial (+) / ulnar deviation, y palmar flexion (+) / extension, degrees: the c… |  |  |  |  |  |  | ○ |  |
| WRIST_ELLIPSE.tilt_deg | 13.2 | deg | 584 | the active circumduction of the wrist as an ellipse (Gracia-Ibanez 2020, dominant hand): x radial (+) / ulnar deviation, y palmar flexion (+) / extension, degrees: the c… |  |  |  |  |  |  | ○ |  |
| FIST_WRIST.flexion | 0.73 * 77.6 |  | 587 | a fist takes away palmar flexion and ulnar deviation (Gehrmann 2008: 0.73 and 0.89 of the free hand's); the free hand's active palmar flexion and ulnar deviation (Gracia… |  |  |  |  |  |  | ○ |  |
| FIST_WRIST.ulnar | 0.89 * 33.4 |  | 587 | a fist takes away palmar flexion and ulnar deviation (Gehrmann 2008: 0.73 and 0.89 of the free hand's); the free hand's active palmar flexion and ulnar deviation (Gracia… |  |  |  |  |  |  | ○ |  |
| CONTACT_MM.chest | (60.0, 90.0) | mm | 592 | where the hand touches the face, the body or the other arm and hand, the relaxed curl and the passive lag are left out (what the fingers touch holds them; Varghese 2020 … |  | ○ |  |  |  |  | ○ | retarget |
| CONTACT_MM.face | (70.0, 100.0) | mm | 592 | where the hand touches the face, the body or the other arm and hand, the relaxed curl and the passive lag are left out (what the fingers touch holds them; Varghese 2020 … | 手の層（hands-anatomy、10-14）: 指先が目からこの距離（mm）の内で触れる。リンの顔の大きさで決めた値。v11arms（10-17）: 顔の前はこのまま（目から）。手の層が指先を部位へ 5 mm 以上入れたコマ（I7、頭… | ○ |  |  |  |  | ○ | retarget・rig |
| CONTACT_MM.other | (35.0, 60.0) | mm | 592 | where the hand touches the face, the body or the other arm and hand, the relaxed curl and the passive lag are left out (what the fingers touch holds them; Varghese 2020 … |  | ○ |  |  |  |  | ○ | retarget |
| CONTACT_MM.waist | (80.0, 110.0) | mm | 592 | where the hand touches the face, the body or the other arm and hand, the relaxed curl and the passive lag are left out (what the fingers touch holds them; Varghese 2020 … |  | ○ |  |  |  |  | ○ | retarget |
| CONTACT_PAD | 4 |  | 593 |  |  |  |  |  |  |  |  |  |
| CONTACT_SURFACE_MM | (10.0, 25.0) | mm | 605 | and where a fingertip or the palm's middle lies within the first distance (mm) of one of Rin's hard parts, fully, none past the second: the parts' own surfaces (tools/re… | v11arms（10-17）: 手の層が指先・手のひらの中を部位へ 5 mm 以上入れたコマ（I7、54 コマ、頭 43）の入力は面から −11〜+16 mm（中央値 5）。帯 10〜25 mm でその全部を捕まえ、20〜40 mm より… | ○ |  | ○ | ○ | ○ |  | retarget・rig |
| FOLLOW_SCALE（引数 --follow-scale） | 0.5 |  | 619 | the follow (--follow; off by default): each finger reaches the shape its muscles take it to through the passive body's spring and damper (its omega and zeta between the … |  |  |  | ○ | ○ | ○ | ○ | rig |
| HOLD_DEG_S | 5.0 | deg/s | 627 | a beat hold (--beats; motor_layer's): the joints of the shoulder, the elbow and the wrist all under HOLD_DEG_S for HOLD_MIN frames or more, the hold starting within KIME… |  |  |  | ○ |  |  | ○ | dance |
| HOLD_MIN | 4 |  | 627 | a beat hold (--beats; motor_layer's): the joints of the shoulder, the elbow and the wrist all under HOLD_DEG_S for HOLD_MIN frames or more, the hold starting within KIME… |  |  |  | ○ |  |  | ○ | dance |
| HOLD_EXIT | 2 |  | 628 |  |  |  |  |  |  |  |  |  |
| HOLD_RAMP | 3 |  | 628 |  |  |  |  |  |  |  |  |  |
| KIME_BEAT | 2 |  | 628 |  |  |  |  |  |  |  |  |  |
| KIME_LEAD | 3 |  | 628 |  |  |  |  |  |  |  |  |  |
| KIME_RAMP | 4 |  | 628 |  |  |  |  |  |  |  |  |  |
| KIME_STIFFNESS | 4.0 |  | 629 |  |  |  |  |  |  |  |  |  |
| _r(n) | 2 |  | 674 |  |  |  |  |  |  |  |  |  |
| REACH.band | 5.0 |  | 817 | the hinges and the coupling undo a shape the trace made at the wrong joint (the thumbs of a heart bent sideways at their MP, a pinch made at the index's PIP, a fist hook… |  |  |  | ○ |  |  |  | dance |
| REACH.damping | 1e-6 |  | 817 | the hinges and the coupling undo a shape the trace made at the wrong joint (the thumbs of a heart bent sideways at their MP, a pinch made at the index's PIP, a fist hook… |  |  |  | ○ |  |  |  | dance |
| REACH.h | 0.01 |  | 817 | the hinges and the coupling undo a shape the trace made at the wrong joint (the thumbs of a heart bent sideways at their MP, a pinch made at the index's PIP, a fist hook… |  |  |  | ○ |  |  |  | dance |
| REACH.iterations | 16 |  | 817 | the hinges and the coupling undo a shape the trace made at the wrong joint (the thumbs of a heart bent sideways at their MP, a pinch made at the index's PIP, a fist hook… |  |  |  | ○ |  |  |  | dance |
| REACH.reg | 0.05 |  | 817 | the hinges and the coupling undo a shape the trace made at the wrong joint (the thumbs of a heart bent sideways at their MP, a pinch made at the index's PIP, a fist hook… |  |  |  | ○ |  |  |  | dance |
| REACH.rom | 1.0 |  | 817 | the hinges and the coupling undo a shape the trace made at the wrong joint (the thumbs of a heart bent sideways at their MP, a pinch made at the index's PIP, a fist hook… |  |  |  | ○ |  |  |  | dance |
| REACH.step_max | 15.0 |  | 817 | the hinges and the coupling undo a shape the trace made at the wrong joint (the thumbs of a heart bent sideways at their MP, a pinch made at the index's PIP, a fist hook… |  |  |  | ○ |  |  |  | dance |
| MM_PER_UNIT | UNIT_M * 1000.0 |  | 818 |  |  |  |  |  |  |  |  |  |
| order(scale) | 1.0 |  | 1018 |  |  |  |  |  |  |  |  |  |
| transit(scale) | 1.0 |  | 1253 |  |  |  |  |  |  |  |  |  |
| transit(seed) | 0 |  | 1253 |  |  |  |  |  |  |  |  |  |
| a09_lags(maxlag) | 6 |  | 1584 |  |  |  |  |  |  |  |  |  |
| a09_lags(step) | 15 |  | 1584 |  |  |  |  |  |  |  |  |  |
| a09_lags(win) | 60 |  | 1584 |  |  |  |  |  |  |  |  |  |
| shape_changes(min_change) | 20.0 |  | 1954 |  |  |  |  |  |  |  |  |  |
| shape_changes(still) | 1.0 |  | 1954 |  |  |  |  |  |  |  |  |  |
| onset(share) | 0.1 |  | 1965 |  |  |  |  |  |  |  |  |  |
| HELD_REACH | 4 | frames | 1977 | frames each way the input's joint must be still for a frame to count as a held shape |  |  |  |  |  |  |  |  |
| --order-scale | 1.0 |  | 2096 | the joints' lags within a change of shape times this (default 1; 0 moves them together) |  |  |  |  |  |  |  |  |
| --order-mode | "centre" |  | 2112 | the joints' stagger laid round the change's middle (centre, default) or only delaying (delay, v8) |  |  |  | ○ |  |  |  | dance |
| --transit-scale | 1.0 |  | 2123 | the transit's excursions (the fingers moving out and back with each movement of the arm) times this (default 1, FineDance's dancers; 0 leaves them out as --no-transit do… |  |  |  |  |  | ○ |  |  |

## touch_layer.py（13. 手と指、触れの層（v11arms）、3）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SMOOTH_FRAMES（引数 --smooth-frames） | 1.0 | frames | 88 | the change made to the arm, as the moves of the wrist and the elbow in the world, is smoothed over the frames by a Gaussian of this many frames (its standard deviation; … | v11arms（10-17）: 触れの層の直しを時間でならす（元の手が触れるコマはそのまま）。σ 0 / 1.0 / 1.5 / 2.5 コマ: 右手首の 8 Hz 超 0.97 / 0.71 / 0.72 / -（前の段 0.60、人 … |  |  | ○ | ○ | ○ |  | rig |
| RAMP_CM（引数 --ramp-cm） | 2.0 | cm | 101 | cm a frame: where the source's hand touches a part only for a frame or two (a hand brushing a thigh in a swing) the change that puts it back can be large (the later laye… | v11arms（10-17）: 一瞬だけの触れ（20.2 秒、元の右手が振りの途中で右ももを 1 コマかすめる）を戻す直しが 1 コマで 9.0 cm 跳んでいた（右手首の 1 コマの落ちと跳ね 3.08・2.78 m/s）。入れ抜きの上… | ○ |  | ○ |  | ○ |  | retarget |
| smoothed(ramp) | 0.0 |  | 156 |  |  |  |  |  |  |  |  |  |

## eye_gaze.py（14. 視線、105）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FPS | 30.0 |  | 221 |  |  |  |  |  |  |  |  |  |
| MAX_YAW | 18.0 | deg | 222 | degrees the eyes turn sideways (default of --max-yaw) |  |  |  |  |  |  |  |  |
| MAX_DOWN | 10.0 | deg | 223 | degrees they turn up and down (--max-up, --max-down; review 8, R1: at +10 the upper lid of Sour's Rin covers 17 % more of the iris) |  |  |  |  | ○ |  |  | rig |
| MAX_UP | 6.0 | deg | 223 | degrees they turn up and down (--max-up, --max-down; review 8, R1: at +10 the upper lid of Sour's Rin covers 17 % more of the iris) |  |  |  |  | ○ |  |  | rig |
| LIMIT_MAX | 45.0 | deg | 225 | degrees: the most a limit may be |  |  |  |  |  |  |  |  |
| SOFT_FROM | 0.6 |  | 226 | share of a limit up to which the eyes follow exactly; beyond, tanh towards it |  |  |  |  |  |  |  |  |
| EDGE | 0.9 |  | 227 | share of a limit from which the analysis counts the eyes as at the edge |  |  |  |  |  |  |  |  |
| FREE_SHARE | (2.0 / 3.0, 2.0 / 3.0, 0.7) |  | 228 | the free zone, shares of the yaw, up and down limits (12, 4, 7) |  |  |  |  |  |  |  |  |
| CONTACT_SHARE | (0.889, 0.883, 0.89) |  | 229 | the contact zone (16, 5.3, 8.9: inside the EDGE lines) |  |  |  |  |  |  |  |  |
| CONTACT_ERROR | 4.0 | deg | 230 | degrees off the camera at most for a frame to be within reach (a13 counts 4; 3.5 gave 8 contacts and none at the first chorus, 4.0 gives 13: review eye) |  |  |  |  |  |  |  |  |
| CONTACT_GAP | 2 | frames | 232 | frames out of reach that do not break a run (a13 joins gaps of 2) |  |  |  |  |  |  |  |  |
| CONTACT_MIN | 48 | frames | 233 | frames: a run this long is always a contact (1.6 s) |  |  |  |  |  |  |  |  |
| CONTACT_MID | 30 | frames | 234 | frames: a run this long is a contact near an anchor of the song |  |  |  | ○ |  |  |  | dance |
| CONTACT_SPARE | 2 |  | 235 | the shorter contacts are this many fewer than the long ones |  |  |  |  |  |  |  |  |
| CONTACT_MAX | 150 | frames | 236 | frames: a contact lasts at most this (5 s) |  |  |  |  |  |  |  |  |
| ANCHOR_NEAR | 30 | frames | 237 | frames from a run within which an anchor counts (1 s) |  |  |  |  |  |  |  |  |
| CUT_CLEAR | 6 | frames | 238 | frames before and after a cut without a contact |  |  |  |  |  |  |  |  |
| END_CLEAR | 2 | frames | 238 | frames before and after a cut without a contact |  |  |  |  |  |  |  |  |
| LOOK_AHEAD | 2 | frames | 239 | frames ahead from which a fixation is checked against the face's way |  |  |  |  |  |  |  |  |
| GAP | 8.0 | deg | 240 | degrees off the face's way the eyes may stay before a recentre |  |  |  |  |  |  |  |  |
| SUSTAIN | 6 | frames | 241 | frames past LOOK_AHEAD the gap must last (a nod with the beat comes back) |  |  |  | ○ |  |  |  | dance |
| MIN_FIXATION（引数 --min-fixation） | 10 | frames | 242 | frames from the landing of a saccade to the earliest recentre or glance (333 ms) |  |  |  |  |  |  |  |  |
| FIXATION_SPREAD | 5 | frames | 243 | frames: each fixation's earliest is MIN_FIXATION plus 0 to this (the seed) |  |  |  |  |  |  |  |  |
| GLANCE | (45, 120) | frames | 244 | frames of one fixation before a glance (both included) |  |  |  |  |  |  |  |  |
| VOR_GAIN | (1.0, 1.0) |  | 245 | share of the counter-rotation the eyes make sideways and up and down |  |  |  |  |  |  |  |  |
| GATE_TURN | 20.0 | deg | 246 | degrees a fast turn goes its way for a lead before it and quick phases in it |  |  |  |  |  |  |  |  |
| QUICK_AFTER | 5 | frames | 247 | frames after a landing before a quick phase or a saccade off the wall, plus |  |  |  |  |  |  |  |  |
| QUICK_SPREAD | 3 |  | 248 | 0 to this drawn for each fixation (its own stream of the seed) |  |  |  |  |  |  |  |  |
| QUICK_SUSTAIN | 6 | frames | 249 | frames a press against the wall must last, from the frame on, for one |  |  |  |  |  |  |  |  |
| QUICK_AHEAD | 3 | frames | 250 | frames: a quick phase goes toward where the head will be this many frames on (at 150 to 600 deg/s, 15 to 60 degrees ahead: never behind her in a spin) |  |  |  |  |  |  |  |  |
| FACE_AHEAD | 12 |  | 252 | the face's way: the head's forward averaged over the frame and the next 12 |  |  |  |  |  |  |  |  |
| WALL | 0.85 |  | 253 | share of each limit a fixation is pressed softly against beyond the free zone |  |  |  |  |  |  |  |  |
| WALL_SEEN | 0.84 |  | 254 | share of each limit from which the measures count the eyes as at the wall |  |  |  |  |  |  |  |  |
| ECCENTRIC_FROM | 13.9 | deg | 255 | degrees off the middle, yaw and pitch together, from which a fixation, a saccade's goal or a lead is pressed along tanh toward ECCENTRIC_WALL (just beyond the free zone'… | v11face 2026-10-17: 自由な範囲の一番遠い角（横 12・下 7 は正面から 13.87 度）のすぐ外。ここから ECCENTRIC_WALL へ tanh で押す（自由な範囲の中は前のまま） |  |  |  |  |  |  |  |
| ECCENTRIC_WALL | 14.5 | deg | 258 | degrees off the middle that no angle the plan holds goes beyond (people keep the eyes within 15 degrees of it 99 % of the time, a13; 15 less the drift's 0.42) | v11face 2026-10-17: 人は目を正面から 15 度以内に置く（目の動きの 99 %、a13・mv_inspect eyes.eccentric15_pct の決まり 1 % 以下）。15 から目の揺れ（drift）の最大 … |  |  |  |  | ○ |  |  |
| MAX_STEP | 8.0 | deg | 261 | degrees the eyes turn in the head a frame at most outside saccades |  |  |  |  |  |  |  |  |
| FLIP_STEP | 4.0 | deg | 262 | degrees the kept-off gaze may move beyond the gaze's own move before it is a saccade (the keep-off flipping to the other side of the camera) |  |  |  |  |  |  |  |  |
| LONG_SACCADE | 35.0 | deg | 264 | degrees: saccades of 2 frames below the first, 3 up to the second, then 4 |  |  |  |  |  |  |  |  |
| SHORT_SACCADE | 15.0 | deg | 264 | degrees: saccades of 2 frames below the first, 3 up to the second, then 4 |  |  |  |  |  |  |  |  |
| GLANCE_OFF | ((-4.0, 4.0), (-3.0, 1.5)) | deg | 265 | degrees off the face's way of a glance or a look away: yaw, pitch |  |  |  |  |  |  |  |  |
| AVOID | 6.0 | deg | 266 | degrees off the camera the face target keeps |  |  |  |  |  |  |  |  |
| KEEP_OFF | 5.0 | deg | 267 | degrees off the camera the gaze keeps outside the contacts |  |  |  |  |  |  |  |  |
| TURN_SPEED | 150.0 | deg/s | 268 | deg/s of the head's yaw that make a fast turn |  |  |  |  |  |  |  |  |
| LEAD | (2, 4) | frames | 269 | frames before a fast turn's onset on which the eyes land (both included) |  |  |  |  |  |  |  |  |
| LEAD_SHARE | 13.0 / 18.0 |  | 270 | a lead lands at most this share of the yaw limit off the middle |  |  |  |  |  |  |  |  |
| LEAD_STEP | 6.0 | deg | 271 | degrees beyond where the eyes are that a lead goes at least |  |  |  |  |  |  |  |  |
| QUIET | 8 | frames | 272 | frames before a lead in which no other saccade starts |  |  |  |  |  |  |  |  |
| GUARD | 3 | frames | 273 | frames after a fast turn's onset without a recentre |  |  |  |  |  |  |  |  |
| MIN_SACCADE | 0.5 | deg | 274 | degrees: a smaller move is no saccade, only the fixation moves |  |  |  |  |  |  |  |  |
| CUT_JUMP | 1.0 | units | 275 | model units the camera moves in one frame on a cut |  | ○ |  |  |  |  |  | retarget |
| CUT_TURN | 5.0 | deg | 276 | degrees the camera's line of sight turns in one frame on a cut |  |  |  |  |  |  |  |  |
| DRIFT_STEP | 0.03 | deg | 277 | degrees per frame and axis, at most, of the fixation drift |  |  |  |  |  |  |  |  |
| DRIFT_LIMIT | 0.3 | deg | 278 | degrees: the drift stays within this on each axis |  |  |  |  |  |  |  |  |
| MICRO_INTERVAL | (15, 45) | frames | 279 | frames between microsaccades |  |  |  |  |  |  |  |  |
| MICRO_SIZE | 0.15 | deg | 280 | degrees: a microsaccade lands within this of the center |  |  |  |  |  |  |  |  |
| FORWARD_TOLERANCE | 20.0 | deg | 281 | degrees off -Z within which 両目 -> 両目先 is taken as the rest gaze |  |  |  |  |  |  |  |  |
| WALL_GAP | 3.0 | deg | 282 | degrees the face's way lies back toward the middle of a fixation pressed beyond the free zone, on that axis, for a quick phase or a saccade off the wall |  |  |  |  |  |  |  |  |
| UNIT_M | 0.08 | m | 288 | metres in a unit of the model (Sour's Rin; tools/eye_optics.py unit_mm 80) | eye_optics の unit_mm 80（8 cm/単位） | ○ |  |  | ○ |  |  | retarget |
| HAND_FAR | 0.60 | m | 289 | metres from the eyes: nearer, the hand covers or touches the face; further, beyond an arm's reach |  | ○ |  |  |  |  |  | retarget |
| HAND_NEAR | 0.18 | m | 289 | metres from the eyes: nearer, the hand covers or touches the face; further, beyond an arm's reach |  | ○ |  |  |  |  |  | retarget |
| HAND_REACH | 4.0 |  | 292 | before her face: the face turned to it, the eyes resting near the middle |  |  |  |  |  |  |  |  |
| HAND_CAMERA | 10.0 | deg | 293 | degrees: a hand nearer the camera's line is held out to the viewer, not looked at |  |  |  |  |  |  |  |  |
| HAND_FAST | 300.0 | deg/s | 294 | deg/s: a hand moving faster, seen from the eyes in the world, is not followed |  |  |  |  |  |  |  |  |
| HAND_SLOW | 100.0 | deg/s | 295 | deg/s: a look at a hand needs it this slow on one frame of it at least |  |  |  |  |  |  |  |  |
| HAND_MIN | 9 | frames | 296 | frames a look at a hand lasts at least (0.3 s: a person's look at a gesture lasts 0.46 s on average, Gullberg & Holmqvist 2006; shorter, the eyes only pass) |  |  |  |  |  | ○ | ○ |  |
| HAND_PALM | 45.0 | deg | 298 | degrees: a palm turned this near the camera is shown to the viewer, not looked at |  |  |  |  |  |  |  |  |
| HAND_JOIN | 2 | frames | 299 | frames between two runs of the hand that make one |  |  |  |  |  |  |  |  |
| HAND_AHEAD | 1 | frames | 300 | frames: the eyes follow the hand where it will be (a self-moved target is led) |  |  |  |  |  |  |  |  |
| PURSUIT_SPEED | 100.0 | deg/s | 301 | deg/s: the gaze follows a hand at most this fast in the world |  |  |  |  |  |  |  |  |
| CATCH_UP | 3.0 | deg | 302 | degrees the eyes may trail the hand before a saccade catches up |  |  |  |  |  |  |  |  |
| CATCH_UP_AFTER | 4 | frames | 303 | frames after a landing before a saccade catches up with the hand |  |  |  |  |  |  |  |  |
| DEBUG_STEP | 30 |  | 304 |  |  |  |  |  |  |  |  |  |
| REVERSAL | 3.0 | deg | 307 | degrees: a saccade above this followed, within REVERSAL_WITHIN frames of its |  |  |  |  |  |  |  |  |
| REVERSAL_WITHIN | 10 |  | 308 | landing, by one above this the opposite way is a reversal (restless eyes) |  |  |  |  |  |  |  |  |
| STEADY_GAZE | 10.0 | deg/s | 312 | the world gaze (review gaze-smooth 1.3 to 1.6), on the steps outside saccades: with the head at STEADY_HEAD deg/s (what it would carry a resting eye) the gaze is steady … |  |  |  |  |  |  |  |  |
| STEADY_HEAD | (15.0, 120.0) | deg/s | 312 | the world gaze (review gaze-smooth 1.3 to 1.6), on the steps outside saccades: with the head at STEADY_HEAD deg/s (what it would carry a resting eye) the gaze is steady … |  |  |  |  |  |  |  |  |
| STEADY_BANDS | ((15.0, 60.0), (60.0, 120.0)) | deg/s | 313 | the head's deg/s by which the remeasure of stage 6 splits W2 |  |  |  |  |  |  |  |  |
| STILL_FLOW | 0.1 |  | 314 |  |  |  |  |  |  |  |  |  |
| STILL_HEAD | 20.0 |  | 314 |  |  |  |  |  |  |  |  |  |
| CONTACT_SEEN | 4.0 | deg | 316 | degrees: the analysis counts the gaze within this of the camera as eye contact |  |  |  |  |  |  |  |  |
| CONTACT_JOIN | 2 | frames | 317 | frames: gaps it joins |  |  |  |  |  |  |  |  |
| LARGE_CHANGE | 20.0 |  | 318 | a large gaze change: more than 20 degrees in the world within 15 frames |  |  |  |  |  |  |  |  |
| LARGE_WINDOW | 15 |  | 318 | a large gaze change: more than 20 degrees in the world within 15 frames |  |  |  |  |  |  |  |  |
| LEAD_MIN_FRAMES | 3 | frames | 319 | a20: yaw rate, frames, degrees of the eyes ahead |  |  |  |  |  |  |  |  |
| LEAD_SEEN | 3.0 | frames | 319 | a20: yaw rate, frames, degrees of the eyes ahead |  |  |  |  |  |  |  |  |
| LEAD_TURN | 200.0 | frames | 319 | a20: yaw rate, frames, degrees of the eyes ahead |  |  |  |  |  |  |  |  |
| LEAD_MARGINS | (330, 172) |  | 320 | a20 left out turns in the first 330 and the last 172 frames of the song |  |  |  | ○ |  |  |  | dance |
| PROBE | ((0, 29, (0.0, 0.0, 0.0)), (30, 59, (0.0, 15.0, 0.0)), (60,… |  | 322 | (first frame, last frame, window angles of 両目): the probe |  |  |  |  |  |  |  |  |
| _r(places) | 4 |  | 326 |  |  |  |  |  |  |  |  |  |
| _vec(places) | 4 |  | 330 |  |  |  |  |  |  |  |  |  |
| sights(first) | 0 |  | 429 |  |  |  |  |  |  |  |  |  |
| hand_points(first) | 0 |  | 454 |  |  |  |  |  |  |  |  |  |
| hand_palms(first) | 0 |  | 469 |  |  |  |  |  |  |  |  |  |
| hand_aims(first) | 0 |  | 499 |  |  |  |  |  |  |  |  |  |
| REACH_STEPS | 24 |  | 529 | bisection steps for the point of a finger where the eyes' reach ends |  |  |  |  |  |  |  |  |
| REACH_SAMPLES | 16 |  | 530 | points a segment of the finger is walked in, from the tip back |  |  |  |  |  |  |  |  |
| hand_fingers(first) | 0 |  | 533 |  |  |  |  |  |  |  |  |  |
| plan(seed) | 0 |  | 1017 |  |  |  |  |  |  |  |  |  |
| world_measures(rest) | (0.0, 0.0) |  | 1478 |  |  |  |  |  |  |  |  |  |
| gaze(seed) | 0 |  | 1662 |  |  |  |  |  |  |  |  |  |
| write_json(indent) | 1 |  | 1790 |  |  |  |  |  |  |  |  |  |
| run(seed) | 0 |  | 1833 |  |  |  |  |  |  |  |  |  |
| --seed | 0 |  | 1902 | the drift, the microsaccades, the glances, the leads (default 0) |  |  |  |  |  |  |  |  |
| --aim | "finger" |  | 1908 | where the eyes aim on a hand: the point of the aimed finger nearest its tip that they reach (finger, default) or the tip itself, in reach or not (tip: the gaze of 2026-1… |  |  |  |  |  |  |  |  |
| --hand-still | "wrist" |  | 1912 | where whether a hand moves or rests is judged: the wrist (default) or the hand's look point (look: before fingers-v3, with --aim tip the gaze of main c012c32 byte for by… |  |  |  | ○ |  |  |  | dance |

## face_life.py（15. 表情、147）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FPS | 30.0 |  | 120 |  |  |  |  |  |  |  |  |  |
| CORNERS_UP | ("口角上げ", "笑い", 0.6) |  | 124 | (morph, the morph it follows, share of its weight) |  |  |  |  | ○ |  |  | rig |
| CORNERS_DOWN | ("口角下げ", "真面目", 0.2) |  | 125 |  |  |  |  |  |  |  |  |  |
| ACTIVE | 0.05 |  | 126 | weight above which an expression counts as shown (a11) |  |  |  |  |  |  |  |  |
| SNAP | 9 | frames | 127 | frames: a change this quick or quicker is stretched |  |  |  |  |  |  |  |  |
| ONSET_FRAMES | (12, 16) | frames | 128 | frames of a rise from nothing (both ends included) |  |  |  |  |  |  |  |  |
| OFFSET_FRAMES | (14, 18) | frames | 129 | of a fall to nothing |  |  |  |  |  |  |  |  |
| CHANGE_FRAMES | (10, 14) | frames | 130 | of any other change |  |  |  |  |  |  |  |  |
| TOGETHER | 4 | frames | 131 | frames: changes of different morphs this close are one change of the face |  |  |  |  | ○ |  |  | rig |
| DELAY.brow | (0, 0) | frames | 132 | frames each part starts after the brows |  |  |  |  |  |  |  |  |
| DELAY.eye | (3, 4) | frames | 132 | frames each part starts after the brows |  |  |  |  |  |  |  |  |
| DELAY.mouth | (1, 2) | frames | 132 | frames each part starts after the brows |  |  |  |  |  |  |  |  |
| ALIGN | 9 | frames | 133 | frames a change may move toward the fastest turn of the head |  |  |  |  |  |  |  |  |
| ALIGN_RATIO | 1.5 |  | 134 |  |  |  |  |  |  |  |  |  |
| ALIGN_LEAD | 2 | frames | 135 | frames the face starts changing before the head turns fastest |  |  |  |  |  |  |  |  |
| WAVE.brow | 0.15 |  | 136 | how far the envelope lowers a held weight |  |  |  |  |  |  |  |  |
| WAVE.eye | 0.12 |  | 136 | how far the envelope lowers a held weight |  |  |  |  |  |  |  |  |
| WAVE.mouth | 0.25 |  | 136 | how far the envelope lowers a held weight |  |  |  |  |  |  |  |  |
| HUMAN_WAVE.brow | 0.15 |  | 137 | human style: a held smile eases off by up to a fifth. A decided value, set by Hyde et al. 2013 (toon characters' whole motion scaled to 80-120 % was not told apart): the… |  |  |  |  |  | ○ |  |  |
| HUMAN_WAVE.eye | 0.2 |  | 137 | human style: a held smile eases off by up to a fifth. A decided value, set by Hyde et al. 2013 (toon characters' whole motion scaled to 80-120 % was not told apart): the… |  |  |  |  |  | ○ |  |  |
| HUMAN_WAVE.mouth | 0.25 |  | 137 | human style: a held smile eases off by up to a fifth. A decided value, set by Hyde et al. 2013 (toon characters' whole motion scaled to 80-120 % was not told apart): the… |  |  |  |  |  | ○ |  |  |
| ENVELOPE_STEP | (35, 70) | frames | 141 | frames between the keys of the envelope |  |  |  |  |  |  |  |  |
| ENVELOPE_MIN_STEP | 0.15 |  | 142 | the envelope changes by at least this from one key to the next |  |  |  |  |  |  |  |  |
| SLOW | 20 | frames | 143 | frames: a change between two keys this far apart is a drift, and is waved too |  |  |  |  |  |  |  |  |
| CLOSED | 0.8 |  | 146 | closure (まばたき + 笑い) at which the eye counts as shut (a10) |  |  |  |  |  |  |  |  |
| STEEP | 0.05 |  | 147 | per-frame change of the closure that counts as the lid moving (a10) |  |  |  |  |  |  |  |  |
| SHORT_CLOSURE | 4 |  | 148 | closed frames: up to this a closure is a blink, longer ones are kept (a10) |  |  |  |  |  |  |  |  |
| CLOSING_FRAMES | (2, 3) | frames | 149 |  |  |  |  |  |  |  |  |  |
| HOLD_FRAMES | (0, 1) | frames | 150 |  |  |  |  |  |  |  |  |  |
| OPENING_FRAMES | (5, 6) | frames | 151 |  |  |  |  |  |  |  |  |  |
| CLOSING | {2: (0.5,), 3: (0.3, 0.75)} |  | 152 | the lid between open (0) and shut (1) |  |  |  |  |  |  |  |  |
| OPENING | {5: (0.62, 0.36, 0.18, 0.07), 6: (0.7, 0.45, 0.27, 0.14, 0.… |  | 153 |  |  |  |  |  |  |  |  |  |
| P_GAZE | 0.75 |  | 154 |  |  |  |  |  |  |  |  |  |
| P_PHRASE | 0.55 |  | 154 |  |  |  |  |  |  |  |  |  |
| P_SACCADE | 0.7 |  | 154 |  |  |  |  |  |  |  |  |  |
| GAZE_SHIFT | 33.0 | deg | 155 | degrees in frames (a10, Evinger et al. 1994) |  |  |  |  |  |  |  |  |
| GAZE_SHIFT_FRAMES | 9 | frames | 155 | degrees in frames (a10, Evinger et al. 1994) |  |  |  |  |  |  |  |  |
| BIG_SACCADE | 20.0 |  | 156 |  |  |  |  |  |  |  |  |  |
| SACCADE_SPEED | 1.5 | deg | 157 | degrees per frame of the eyes in the head and in the world on a saccade frame |  |  |  |  |  |  |  |  |
| SACCADE_LONGEST | 5 | frames | 158 | frames: a faster stretch than this is no saccade |  |  |  |  |  |  |  |  |
| PHRASE_PAUSE | 15 | frames | 159 | frames between two vowel onsets that end a phrase for the blinks (a10) |  |  |  |  |  |  |  |  |
| PHRASE_BLINK | (5, 9) | frames | 160 | frames after the last vowel of a phrase the blink starts |  |  |  |  |  |  |  |  |
| MIN_BETWEEN | 15 | frames | 161 | frames between the starts of two blinks |  |  |  |  |  |  |  |  |
| RATE | 25.0 |  | 162 | blinks a minute at most (the KAZUSA motion: 25.6; people talking: 26, 10.5-32.5) |  |  |  | ○ |  | ○ |  | dance |
| BLINK_WINDOW | 300 |  | 163 | at most WINDOW_MAX blinks in any BLINK_WINDOW frames (10 s) |  |  |  |  |  |  |  |  |
| WINDOW_MAX | 7 |  | 163 | at most WINDOW_MAX blinks in any BLINK_WINDOW frames (10 s) |  |  |  |  |  |  |  |  |
| WINDOW_MARGIN | 4 | frames | 164 | frames added to the window when the blinks are chosen |  |  |  |  |  |  |  |  |
| GAZE_SHARE | 0.7 |  | 165 | the share of the blinks that may go to the gaze shifts (the largest first) |  |  |  |  |  |  |  |  |
| FILL_MEDIAN | 3.4 | s | 166 | seconds, log-normal |  |  |  |  |  |  |  |  |
| FILL_SIGMA | 0.5 | s | 166 | seconds, log-normal |  |  |  |  |  |  |  |  |
| LONG_PAUSE | (6.0, 10.0) |  | 167 |  |  |  |  |  |  |  |  |  |
| LONG_PAUSE_CHANCE | 0.12 |  | 167 |  |  |  |  |  |  |  |  |  |
| KEEP_CLEAR | 15 | frames | 168 | frames around the long closures and after the eyes open without new blinks |  |  |  |  |  |  |  |  |
| BASE_SWITCH | 8 | frames | 169 | frames over which the lid level changes where an old blink hid the change |  |  |  |  |  |  |  |  |
| CREEP_LONGEST | 9 | frames | 170 | frames: the lid never closes slowly for longer (a10 counts 10 and more as a creep) |  |  |  |  |  |  |  |  |
| LID_DOWN | 0.01 |  | 171 | まばたき per degree the eyes look down / up |  |  |  |  |  |  |  |  |
| LID_UP | 0.005 |  | 171 | まばたき per degree the eyes look down / up |  |  |  |  |  |  |  |  |
| HUMAN_CLOSING_FRAMES | (2, 3) | frames | 186 | A spontaneous blink closes in 2 to 3 frames and opens in 4 to 7, 7 to 12 frames in all as the end of the opening is taken (Wu et al. 2014: 7.8 frames; Trutoiu et al. 201… |  |  |  | ○ |  |  |  | dance |
| HUMAN_HOLD_CHANCE | 0.25 |  | 187 |  |  |  |  |  |  |  |  |  |
| HUMAN_OPENING_FRAMES | (5, 6) | frames | 188 |  |  |  |  |  |  |  |  |  |
| LONG_CLOSING | 2 | frames | 189 | frames a long blink closes in |  |  |  |  |  |  |  |  |
| LONG_HOLD | (2, 3) | frames | 190 | frames it stays shut beyond the first (10 to 11 frames in all) |  |  |  |  |  |  |  |  |
| LONG_OPENING | 6 |  | 191 |  |  |  |  |  |  |  |  |  |
| LONG_GAP | 240 | frames | 192 | frames (8 s) at least between the starts of two long blinks |  |  |  |  |  |  |  |  |
| P_LONG.phrase_end | 0.5 |  | 194 |  |  |  |  |  |  |  |  |  |
| P_LONG.rest | 0.25 |  | 194 |  |  |  |  |  |  |  |  |  |
| CLOSURE_CAP | 0.7 |  | 195 | human style: between the blinks まばたき + 笑い at most this (or the author's): the lid that follows the eyes down must not shut a smiling eye. A decided value, under a10's "s… |  |  |  |  |  | ○ |  |  |
| FLASH_QUIET | (8, 3) | frames | 197 | frames before and after a flash's kime no blink starts (blinks hold off at a moment that holds the attention: Shultz et al. 2011) |  |  |  |  |  |  |  |  |
| SMILE_END_BLINK | 21 | frames | 199 | frames before a smile has fallen (its last moving frame) a blink is placed: in natural smiles of light conversation blinks came 21 frames on average before the offset, t… |  |  |  |  |  |  | ○ |  |
| P_SMILE_END | 0.6 |  | 202 |  |  |  |  |  |  |  |  |  |
| LID_NEUTRAL | 0.10 |  | 203 | the lid's level a person's face rests at (Sour's Rin: the upper lid 0.75 iris radii above the iris' centre seen from the front with the eyes level; stage 6 face-v2 q2) |  |  |  | ○ | ○ | ○ |  | rig |
| LID_SHOWN | (0.85, 0.95, 1.0) |  | 205 | the share of the author's lowering below LID_NEUTRAL that shows: while a phrase is sung (the loudest), at rest, and in the relaxing after a phrase. A decided value, chos… | HANDOVER 2026-10-14 face-v2: KAZUSA 様の真顔の瞼を見せる割合 歌う間 0.85・休み 0.95・句の後 1.0（査読の 0.4〜0.55 は丸い目に見えた） |  |  | ○ |  | ○ |  | dance |
| LID_QUIET | 0.25 |  | 212 | the quietest phrase shows this much more of it than the loudest (ranked by the voice), never more than all of it |  |  |  |  |  |  |  |  |
| LID_DEEP | 0.5 |  | 214 | from here to CLOSED the author's lid (a long closure, the wake-up) is blended back in |  |  |  |  |  |  |  |  |
| LID_STEP | 6 | frames | 215 | frames a change of the shown share takes |  |  |  |  |  |  |  |  |
| LID_RELAX_AFTER | 6 | frames | 216 | frames after a phrase's last vowel the lid starts to relax |  |  |  |  |  |  |  |  |
| LID_RELAX_HOLD | 24 | frames | 217 | frames the relaxed lid holds before it goes back to rest |  |  |  |  |  |  |  |  |
| LID_RELAX_BACK | 12 | frames | 218 | frames it takes to go back (the lid opening: slow is no creep) |  |  |  |  |  |  |  |  |
| LID_SHORT_GAP | 20 | frames | 219 | frames: phrases this close keep the lid as in a phrase between them |  |  |  |  |  |  |  |  |
| LID_FOLLOW | (0.029, 0.021) |  | 220 | まばたき per degree the eyes look down / up. A person's upper lid follows the eye up and down by about the same angle (Becker and Fuchs 1988), the cover over the iris growin… | HANDOVER 2026-10-14 face-v2: 瞼が毎コマ目の縦の向きに付く（下 0.029/度・上 0.021/度） |  |  | ○ | ○ | ○ | ○ | rig |
| BLINK_KEY_TOLERANCE | 0.001 |  | 227 | human style: まばたき's keys are those straight lines need to stay this near every frame (bake_within; eye_optics' keys.morph). Following the eyes the lid bends on most fram… |  |  |  |  | ○ | ○ |  | rig |
| GAIN | (0.6, 1.0) |  | 233 |  |  |  |  |  |  |  |  |  |
| SMALL_FLOOR | 0.8 |  | 234 |  |  |  |  |  |  |  |  |  |
| FINAL_FLOOR | 0.9 |  | 235 | the last vowel of a phrase (a held note) is at least this |  |  |  |  |  |  |  |  |
| SUNG | 0.99 |  | 236 | an onset key at least this high is a sung vowel and gets a gain |  |  |  |  |  |  |  |  |
| PHRASE_GAP | 24 | frames | 237 | frames between onsets that end a phrase for the mouth (tools/lip_timing.py) |  |  |  |  |  |  |  |  |
| CROSSFADE | 3 |  | 238 |  |  |  |  |  |  |  |  |  |
| HOLD_RELAX | 0.08 | frames | 239 | a held vowel eases off by this much, frames |  |  |  |  |  |  |  |  |
| HOLD_TAU | 12.0 | frames | 239 | a held vowel eases off by this much, frames |  |  |  |  |  |  |  |  |
| CLOSE_FRAMES | 3 | frames | 240 |  |  |  |  |  |  |  |  |  |
| OPEN_FRAMES | (2, 3) | frames | 241 |  |  |  |  |  |  |  |  |  |
| BREATH | (0.03, 0.08, 0.20) |  | 242 |  |  |  |  |  |  |  |  |  |
| BREATH_PERIOD | (1.6, 2.6) |  | 243 |  |  |  |  |  |  |  |  |  |
| JOIN_BREATH | 0.25 |  | 244 | under lip_timing's MIN_WEIGHT, so a breath is no onset |  |  |  |  |  |  |  |  |
| JOIN_GAP | (10, 90) | frames | 245 | frames between two onsets where a breath may go |  |  |  |  |  |  |  |  |
| JOIN_INTO | 3 | frames | 246 | frames from the breath to the next vowel's onset |  |  |  |  |  |  |  |  |
| BREATH_CAP | 0.29 |  | 247 | a breath never takes あ to lip_timing's MIN_WEIGHT (0.3): it makes no onset |  |  |  |  |  |  |  |  |
| JOIN_PAUSE_BINS | 10 |  | 248 |  |  |  |  |  |  |  |  |  |
| JOIN_PAUSE_DB | 6.0 |  | 248 |  |  |  |  |  |  |  |  |  |
| VOICE_BAND | (300.0, 3500.0) |  | 249 |  |  |  |  |  |  |  |  |  |
| HOP | 160 |  | 250 |  |  |  |  |  |  |  |  |  |
| SAMPLE_RATE | 16000 |  | 250 |  |  |  |  |  |  |  |  |  |
| WINDOW | 1024 |  | 250 |  |  |  |  |  |  |  |  |  |
| AUDIO_T0 | WINDOW / 2.0 / SAMPLE_RATE | s | 251 | seconds: the centre of the first window |  |  |  |  |  |  |  |  |
| SHOWN | 0.1875 | frames | 252 | frames: the MV shows frame f at f + 0.1875 (tools/mv_look.py, a12) |  |  |  |  |  |  |  |  |
| LEAD | 15 | frames | 254 | frames the eyes are open before the body moves |  |  |  |  |  |  |  |  |
| WAKE_AFTER | 45 |  | 255 |  |  |  |  |  |  |  |  |  |
| WAKE_BEFORE | 15 |  | 255 |  |  |  |  |  |  |  |  |  |
| WAKE_OPEN | 10 |  | 255 |  |  |  |  |  |  |  |  |  |
| BODY_MOVES | (3.0, 0.1) | deg | 256 | degrees / model units the head has moved from frame 0 when the body starts (more than breathing at rest moves it) |  |  |  |  |  |  |  |  |
| MEASURE_SEED | 1234 |  | 260 | the circular shifts of the chance levels |  |  |  |  |  |  |  |  |
| SHIFTS | 2000 |  | 261 |  |  |  |  |  |  |  |  |  |
| _r(places) | 3 |  | 285 |  |  |  |  |  |  |  |  |  |
| bake(places) | 6 |  | 318 |  |  |  |  |  |  |  |  |  |
| bake_within(places) | 6 |  | 329 |  |  |  |  |  |  |  |  |  |
| bake_within(start) | 0 |  | 329 |  |  |  |  |  |  |  |  |  |
| FORWARD | np.array([0.0, 0.0, -1.0]) |  | 394 |  |  |  |  |  |  |  |  |  |
| KIME_PEAK | 75 |  | 469 | percentile of a part's speed (from the body's start) the peak before a stop reaches |  |  |  |  |  |  |  |  |
| KIME_MIN_SPEED | 8.0 | units/s | 470 | model units a second the peak reaches at least (0.64 m/s at 8 cm a unit) | 決めの頂きの速さ 8 単位/秒（8 cm/単位で 0.64 m/s） | ○ |  |  |  |  |  | retarget |
| KIME_LOOK | 8 | frames | 471 | frames before the stop the peak is looked for in |  |  |  |  |  |  |  |  |
| KIME_DROP | 0.25 |  | 472 | the speed falls below this share of the peak (tools/motor_layer.py's stops_and_hits) |  |  |  |  |  |  |  |  |
| KIME_HOLD | 6 | frames | 473 | frames the part then stays under it: the pose is held |  |  |  |  |  |  |  |  |
| KIME_MERGE | 4 | frames | 474 | frames: stops of several parts this close are one accent |  |  |  |  |  |  |  |  |
| KIME_ARRIVE | 1 | frames | 475 | frames before a kime a change of the face arrives (human style). A decided value: never after the kime. The face and the body are both picture: the tolerance of sound ag… |  |  |  |  |  | ○ |  |  |
| HUMAN_ONSET_FRAMES | (14, 18) | frames | 478 | human style: a rise from nothing (onsets of 4 and 7 frames looked faker than 16, |  |  |  |  |  | ○ |  |  |
| HUMAN_OFFSET_FRAMES | (15, 20) | frames | 479 | Krumhuber and Kappas 2005; spontaneous smiles rise in 17 to 18 frames and fall in 17 |  |  |  |  |  |  | ○ |  |
| HUMAN_CHANGE_FRAMES | (13, 17) | frames | 480 | to 19, Schmidt et al. 2006), a fall to nothing, any other change |  |  |  |  |  |  |  |  |
| kimes(start) | 0 |  | 492 |  |  |  |  |  |  |  |  |  |
| intensity(seconds) | 2.0 |  | 535 |  |  |  |  |  |  |  |  |  |
| plan(seed) | 0 |  | 594 |  |  |  |  |  |  |  |  |  |
| align_shift(length) | 13.0 |  | 957 |  |  |  |  |  |  |  |  |  |
| PULSE_LONGEST | 3 | frames | 1288 | frames a blink's shut keys span at most (KAZUSA: 1; the long closures: 4 and more) |  |  |  | ○ |  |  |  | dance |
| PULSE_HEIGHT | 0.15 |  | 1289 | how far a blink's peak stands above the keys on either side |  |  |  |  |  |  |  |  |
| LID_HIDE | 3 | frames | 1313 | frames: a blink this near a change of the shown share takes it into its shut frames |  |  |  |  |  |  |  |  |
| FLASH_RATE | 5.0 |  | 1314 | human style: eyes opened for a moment at a kime, at most this many in any minute. The flash is a decided value: Sour's Rin's brows lie under her fringe, so the lid carri… |  |  |  |  | ○ | ○ |  | rig |
| FLASH_GAP | 60 | frames | 1318 | frames between two of them at least |  |  |  |  |  |  |  |  |
| FLASH_STRENGTH | 60 |  | 1319 | percentile of the kimes' speed a kime reaches to get one |  |  |  |  |  |  |  |  |
| FLASH_SHAPE | (5, 3, 8) | frames | 1320 | frames opening (ending a frame before the kime), held, closing again (decided values) |  |  |  |  |  |  |  |  |
| FLASH_SUNG | 9 | frames | 1321 | frames around a lyric line or a phrase that count as singing |  |  |  |  |  |  |  |  |
| smile_falls(gone) | 0.1 |  | 1324 |  |  |  |  |  |  |  |  |  |
| smile_falls(steep) | 0.005 |  | 1324 |  |  |  |  |  |  |  |  |  |
| smile_falls(top) | 0.25 |  | 1324 |  |  |  |  |  |  |  |  |  |
| choose_flashes(start) | 0 |  | 1342 |  |  |  |  |  |  |  |  |  |
| HALF | 0.2 |  | 1848 | まばたき from which the eye counts as half closed between the blinks (a10's base) |  |  |  |  |  |  |  |  |
| run(seed) | 0 |  | 2117 |  |  |  |  |  |  |  |  |  |
| --seed | 0 |  | 2152 | the random draws (default 0) |  |  |  |  |  |  |  |  |
| --style | "human" |  | 2156 | human (default): blinks of a person's length and lids tied to the voice, the gaze and the body; v7: the face of the MV v7 again, byte for byte |  |  |  | ○ |  | ○ |  | dance |

## lip_sync.py（16. 口、73）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FPS | 30.0 |  | 103 |  |  |  |  |  |  |  |  |  |
| SHOWN | 0.1875 | frames | 104 | frames: the MV shows frame f at f + 0.1875 (tools/mv_look.py) |  |  |  |  |  |  |  |  |
| SR | 16000 |  | 105 |  |  |  |  |  |  |  |  |  |
| HOP | 160 | ms | 106 | 10 ms |  |  |  |  |  |  |  |  |
| WIN | 400 | ms | 107 | 25 ms |  |  |  |  |  |  |  |  |
| NFFT | 512 |  | 108 |  |  |  |  |  |  |  |  |  |
| AC_FFT | 1024 |  | 109 |  |  |  |  |  |  |  |  |  |
| N_MELS | 40 |  | 110 |  |  |  |  |  |  |  |  |  |
| MEL_RANGE | (80.0, 7600.0) |  | 111 |  |  |  |  |  |  |  |  |  |
| N_MFCC | 12 |  | 112 |  |  |  |  |  |  |  |  |  |
| BAND | (250.0, 4000.0) |  | 113 |  |  |  |  |  |  |  |  |  |
| F0_RANGE | (150.0, 1300.0) |  | 114 |  |  |  |  |  |  |  |  |  |
| SHAPES.a.あ | 1.0 |  | 118 |  |  |  |  |  |  |  |  |  |
| SHAPES.e.え | 1.0 |  | 118 |  |  |  |  |  |  |  |  |  |
| SHAPES.i.あ | 0.3 |  | 118 |  | v11face 2026-10-17（tools/mouth_shape.py の測り）: MV の絵で あ の開きは 4.7〜8.1 画素、い＋あ 0.3 の隙間は 1.1〜1.8 画素（い＋あ 0.1 は 0.4〜0.5 画素で閉じて… |  |  |  |  |  |  | rig |
| SHAPES.i.い | 1.0 |  | 118 |  |  |  |  |  |  |  |  |  |
| SHAPES.o.お | 1.0 |  | 118 |  |  |  |  |  |  |  |  |  |
| SHAPES.u.う | 1.0 |  | 118 |  |  |  |  |  |  |  |  |  |
| CONSONANTS.f | (0.25, "u") |  | 122 | consonant class -> (share of its vowel's opening kept, a shape of its own or None). The shares are chosen, not measured: the lips shut for m b p, nearly for v f (the low… |  |  |  |  |  |  |  |  |
| CONSONANTS.m | (0.0, None) |  | 122 | consonant class -> (share of its vowel's opening kept, a shape of its own or None). The shares are chosen, not measured: the lips shut for m b p, nearly for v f (the low… |  |  |  |  |  |  |  |  |
| CONSONANTS.n | (0.35, None) |  | 122 | consonant class -> (share of its vowel's opening kept, a shape of its own or None). The shares are chosen, not measured: the lips shut for m b p, nearly for v f (the low… |  |  |  |  |  |  |  |  |
| CONSONANTS.s | (0.35, None) |  | 122 | consonant class -> (share of its vowel's opening kept, a shape of its own or None). The shares are chosen, not measured: the lips shut for m b p, nearly for v f (the low… |  |  |  |  |  |  |  |  |
| CONSONANTS.v | (0.12, None) |  | 122 | consonant class -> (share of its vowel's opening kept, a shape of its own or None). The shares are chosen, not measured: the lips shut for m b p, nearly for v f (the low… |  |  |  |  |  |  |  |  |
| CONSONANTS.h | (0.6, None) |  | 123 |  |  |  |  |  |  |  |  |  |
| CONSONANTS.k | (0.5, None) |  | 123 |  |  |  |  |  |  |  |  |  |
| CONSONANTS.r | (0.55, None) |  | 123 |  |  |  |  |  |  |  |  |  |
| CONSONANTS.w | (0.45, "u") |  | 123 |  |  |  |  |  |  |  |  |  |
| CONSONANTS.y | (0.5, "i") |  | 123 |  |  |  |  |  |  |  |  |  |
| N_OPEN | 0.15 |  | 124 | ん, not before the lips shut: nearly closed |  |  |  |  |  |  |  |  |
| BREAK_SHARE | 0.6 |  | 125 | a break before a vowel alone keeps this share of its opening where the voice sounds (chosen as for h: the jaw stays, nothing closes it) | v11face 2026-10-17: 母音だけの音節の前の切れの間、声が鳴る所で口に残す母音の形の割合（h の 0.6 と同じに決めた） |  |  |  |  |  |  |  |
| CONSONANT_LONGEST | 0.10 | s | 127 | s: a consonant shapes the mouth over this much before its vowel at most |  |  |  |  |  |  |  |  |
| GAIN | (0.5, -24.0, -6.0) |  | 128 | the gain at the soft level, the soft level and the loud level (dB, e) |  |  |  |  |  |  |  |  |
| GAIN_SMOOTH | 0.05 | s | 129 | s |  |  |  |  |  |  |  |  |
| INHALE | 0.22 |  | 130 | あ of the breath before a phrase |  |  |  |  |  |  |  |  |
| INHALE_REST | 0.45 | s | 131 | s of silence before a phrase that let her breathe in |  |  |  |  |  |  |  |  |
| INHALE_SPAN | (0.40, 0.12) | s | 132 | s before the phrase's first sound: the breath starts and is gone |  |  |  |  |  |  |  |  |
| COARTICULATION | 30.0 | ms | 133 | ms: the sigma of the Gaussian that smooths the shapes (10 to 90 % in 77 ms) |  |  |  |  |  |  |  |  |
| CLOSURE_MOVE | 0.16 | s | 134 | s: the lips shut over this much centred on a closure's start and open over this much centred on its end (the sound of the vowel starts as they part); a closure shorter t… |  |  |  |  |  |  | ○ |  |
| CLOSURE_HOLD | 0.04 | s | 138 | s: the lips stay shut at least this long (a frame of the MV at least) |  |  |  |  |  |  |  |  |
| CLOSURE_RAMP | 0.10 | s | 139 | s: shutting and parting take at least this long each |  |  |  |  |  |  |  |  |
| RELEASE | 0.12 | s | 140 | s: after the last vowel of a phrase the singing ends here |  |  |  |  |  |  |  |  |
| REST_OPEN | 0.15 |  | 141 | outside the singing, where the voice is silent, the mouth opens at most this |  |  |  |  |  |  |  |  |
| HOLD_DB | -20.0 |  | 142 | outside the lines, FACE's last vowel is held while the voice stays above this (e: the voice clearly sings, tools/lip_check.py's LOUD_DB) | v11face 2026-10-17: 行の外で手打ちの口が閉じても声がこれより大きい間は最後の母音を保つ（lip_check の LOUD_DB と同じ。233.2 秒の長い声の終わり） |  |  |  |  |  |  |  |
| LEAD_MS（引数 --lead-ms） | 50.0 | ms | 144 |  | HANDOVER 2026-10-17 lipsync: 口は声より 50 ms 先（lip_check で半分開く時刻 +54 ms、ITU-R BT.1359-1 の窓の中） |  |  |  |  |  |  |  |
| KEY_TOLERANCE | 0.025 |  | 145 |  |  |  |  |  |  |  |  |  |
| SIL_DB | -30.0 |  | 146 | e below this: quiet |  |  |  |  |  |  |  |  |
| FILLER | -2.5 |  | 147 | log a row: the silence between lines may hold a sound that is no lyric (an ad lib, a breath, a vocal chop, the echo of the line before) at this cost; a vowel of the line… |  |  |  |  |  |  |  |  |
| BLOCK_GAP | 2.0 | s | 150 | s between lines that are aligned apart |  |  |  |  |  |  |  |  |
| LINE_SLACK | (1.0, 1.5) | s | 151 | s a line may begin before its given start, end after its given end |  |  |  |  |  |  |  |  |
| MARGIN | (1.2, 1.6) | s | 152 | s of the voice taken before and after a block |  |  |  |  |  |  |  |  |
| ITERATIONS | 6 |  | 153 |  |  |  |  |  |  |  |  |  |
| STAY.BR | 0.6 |  | 154 |  |  |  |  |  |  |  |  |  |
| STAY.C | 0.6 |  | 154 |  |  |  |  |  |  |  |  |  |
| STAY.N | 0.85 |  | 154 |  |  |  |  |  |  |  |  |  |
| STAY.Q | 0.85 |  | 154 |  |  |  |  |  |  |  |  |  |
| STAY.SIL | 0.95 |  | 154 |  |  |  |  |  |  |  |  |  |
| STAY.SP | 0.9 |  | 154 |  |  |  |  |  |  |  |  |  |
| STAY.V | 0.9 |  | 154 |  |  |  |  |  |  |  |  |  |
| SP_PENALTY | (4.0, 1.5) |  | 155 | log: a short pause inside a word, between words |  |  |  |  |  |  |  |  |
| SPECTRAL_WEIGHT | 0.5 |  | 156 |  |  |  |  |  |  |  |  |  |
| GUIDE | (2.0, -1.0) |  | 157 | log a row added to a vowel where the guide's mouth shows that vowel, another vowel |  |  |  |  |  |  |  |  |
| GUIDE_OPEN | 0.3 |  | 158 | the guide's mouth shows a vowel where its mixes add up to more than this |  |  |  |  |  |  |  |  |
| GUIDE_LAG | 0.07 | s | 159 | s: the guide's mouth leads the voice by this much (KAZUSA's keys, analysis a12) |  |  |  | ○ |  |  |  | dance |
| POSTERIOR_FLOOR | -6.0 |  | 160 |  |  |  |  |  |  |  |  |  |
| NEG | -1e9 |  | 162 |  |  |  |  |  |  |  |  |  |
| SHORTEST.BR | 2 |  | 345 |  |  |  |  |  |  |  |  |  |
| SHORTEST.C | 2 |  | 345 |  |  |  |  |  |  |  |  |  |
| SHORTEST.N | 4 |  | 345 |  |  |  |  |  |  |  |  |  |
| SHORTEST.Q | 3 |  | 345 |  |  |  |  |  |  |  |  |  |
| SHORTEST.SIL | 1 |  | 345 |  |  |  |  |  |  |  |  |  |
| SHORTEST.SP | 3 |  | 345 |  |  |  |  |  |  |  |  |  |
| SHORTEST.V | 5 |  | 345 |  |  |  |  |  |  |  |  |  |
| face_rows_of(lag) | 0.0 |  | 761 |  |  |  |  |  |  |  |  |  |

## lip_timing.py（16. 口、11）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FPS | 30.0 |  | 45 |  |  |  |  |  |  |  |  |  |
| MIN_WEIGHT | 0.3 |  | 47 |  |  |  |  |  |  |  |  |  |
| GAP（引数 --gap） | 24 |  | 48 |  |  |  |  |  |  |  |  |  |
| SPAN_PER_VOWEL | 30 | frames | 49 | frames: a match is at most this long per vowel of its line |  |  |  |  |  |  |  |  |
| EDIT | 1.0 |  | 50 | align: a vowel without an onset, an onset of another vowel, an extra onset in a line |  |  |  |  |  |  |  |  |
| BETWEEN | 0.05 |  | 51 | align: an onset between two lines (an ad lib, a breath, the intro) |  |  |  |  |  |  |  |  |
| PAUSE | 45 |  | 52 | align: frames between two onsets that make a pause (1.5 s) ... |  |  |  |  |  |  |  |  |
| PAUSE_COST | 3.0 |  | 53 | ... which a line costs this much more to run on over |  |  |  |  |  |  |  |  |
| find(errors) | 0 |  | 141 |  |  |  |  |  |  |  |  |  |
| run(errors) | 0 |  | 260 |  |  |  |  |  |  |  |  |  |
| --errors | 0 |  | 310 | with --search: vowels of a line that may be missing, extra or different (default 0) |  |  |  |  |  |  |  |  |

## eye_optics.py（17. 目の光と寄り、88）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FPS | 30.0 |  | 195 |  |  |  |  |  |  |  |  |  |
| SHOWN | 0.1875 | frames | 196 | frames: the MV shows frame f at f + 0.1875 (tools/mv_look.py; tools/face_life.py) |  |  |  |  |  |  |  |  |
| FORWARD | (0.0, 0.0, -1.0) |  | 197 |  |  |  |  |  |  |  |  |  |
| UP | (0.0, 1.0, 0.0) |  | 198 |  |  |  |  |  |  |  |  |  |
| CUT_JUMP | 1.0 | units | 200 | a camera cut: it moves more than this (units) or turns more (degrees) in a frame |  | ○ |  |  |  |  |  | retarget |
| CUT_TURN | 5.0 | units | 200 | a camera cut: it moves more than this (units) or turns more (degrees) in a frame |  | ○ |  |  |  |  |  | retarget |
| TAIL | 5.0 |  | 201 | time constants after which a first-order vergence move ends (0.7 % was left) |  |  |  |  |  |  |  |  |
| X90 | -math.log(1.0 - 0.9 * (1.0 - math.exp(-TAIL))) |  | 202 | 2.2437: where such a move (ended at TAIL) is 90 % done |  |  |  |  |  |  |  |  |
| MAX_SPAN | 120 | frames | 203 | frames between two keys at most |  |  |  |  |  |  |  |  |
| OPEN_LID | 0.45 |  | 204 | an eye whose closing morphs are at this or less is open (the report's open-eye measures) |  |  |  |  | ○ |  |  | rig |
| PARAMS.light.cornea_radius_mm | 7.72 | mm | 208 | R (Navarro, via Barsingerhorn 2017) |  | ○ |  |  |  |  | ○ | retarget |
| PARAMS.light.pupil_to_centre_mm | 4.67 | mm | 209 | K: entrance pupil to the cornea's centre of curvature (RESEARCH 1.1) |  | ○ |  |  |  |  |  | retarget |
| PARAMS.light.iris_radius_mm | 5.91 | mm | 210 | the visible iris (Aguirre 2019) |  | ○ |  |  |  |  | ○ | retarget |
| PARAMS.light.direction | [-0.5, -1.0, 0.5] |  | 211 | MMD's light, as its window shows it (where the light goes) |  |  |  |  |  |  |  |  |
| PARAMS.light.hide | [90.0, 100.0] | deg | 212 | degrees between the light and the camera: HL消 0 .. 1 (RESEARCH 1.6) |  |  |  |  |  |  |  |  |
| PARAMS.light.cap | 1.0 |  | 213 | iris radii the light moves off its drawn place at most (soft) |  |  |  |  |  |  |  |  |
| PARAMS.light.side | [72.0, 84.0] | deg | 214 | degrees an iris is seen off its forward: its light gives way to its drawn place |  |  |  |  |  |  |  |  |
| PARAMS.light.ride_cap | 0.3 | units | 216 | model units a light's bone moves at most |  | ○ |  |  |  |  |  | retarget |
| PARAMS.light.damping | 0.15 |  | 217 | light_turn's damping, a share of the bone's depth |  |  |  |  |  |  |  |  |
| PARAMS.light.key_cap | 45.0 | deg | 218 | degrees a light bone's key turns at most (soft from 60 % of it) |  |  |  |  |  |  |  |  |
| PARAMS.light.reach | 0.9 |  | 219 | iris radii from the iris' centre a light's centre goes at most (soft) |  |  |  |  |  |  |  |  |
| PARAMS.light.lid_margin | 0.05 |  | 222 | iris radii a light keeps off where the lids cover its iris |  |  |  |  |  |  |  |  |
| PARAMS.light.lid_slide | 0.15 |  | 223 | iris radii a light slides off them at most (further, it stays under) |  |  |  |  |  |  |  |  |
| PARAMS.light.guard_margin | 0.01 | units | 225 | model units about a light's centre the guard also looks |  | ○ |  |  |  |  |  | retarget |
| PARAMS.light.hug_height | 0.002 | units | 226 | model units in front of its iris a light under them is brought down to |  | ○ |  |  |  |  |  | retarget |
| PARAMS.light.hide_depth | 0.2 | units | 227 | model units behind its iris a light is put when that is not enough (into the eyeball: beside the iris the eye white lies up to 0.2 behind its rim) |  | ○ |  |  |  |  |  | retarget |
| PARAMS.vergence.unit_mm | 80.0 | mm | 235 | one model unit |  | ○ |  |  |  |  |  | retarget |
| PARAMS.vergence.gain | 1.0 |  | 236 | the geometric angle (RESEARCH 0.1 and 3.2, the coordinator's probe) |  |  |  |  |  |  |  |  |
| PARAMS.vergence.angle_near_m | 0.15 | m | 237 | the angle is at most that of a point this near (12.3 degrees an eye on Sour's Rin, 11.6 with a person's 61.5 mm) |  | ○ |  |  | ○ | ○ |  | retarget・rig |
| PARAMS.vergence.gap_frames | 6 | frames | 239 | looks at a hand this many frames apart or fewer are one look |  |  |  |  |  |  |  |  |
| PARAMS.vergence.camera_deg | 4.0 | deg | 240 | tools/eye_gaze.py counts a gaze this near the camera as eye contact |  |  |  |  |  |  |  |  |
| PARAMS.vergence.camera_frames | 3 | frames | 241 |  |  |  |  |  |  |  |  |  |
| PARAMS.vergence.lead | 0.07 | s | 242 | seconds the eyes start before a look the report names no saccade onto (Erkelens 1989: they lead a target the hand moves by about 90 ms) |  |  |  |  |  |  | ○ |  |
| PARAMS.vergence.max_speed | 60.0 | deg/s | 244 | degrees a second an eye (natural gaze shifts reach 50 to 200 with both eyes together, Erkelens 1989) |  |  |  |  |  |  | ○ |  |
| PARAMS.vergence.d90.versions | [0.0, 10.0, 20.0, 40.0] |  | 251 |  |  |  |  |  |  |  |  |  |
| PARAMS.vergence.d90.sizes | [5.0, 10.0, 15.0, 20.0] |  | 252 |  |  |  |  |  |  |  |  |  |
| PARAMS.vergence.d90.convergence | [[227.0, 328.0, 372.0, 418.0], [180.0, 310.0, 310.0, 360.0]… |  | 253 |  |  |  |  |  |  |  |  |  |
| PARAMS.vergence.d90.divergence | [[280.0, 370.0, 395.0, 435.0], [170.0, 220.0, 340.0, 360.0]… |  | 255 |  |  |  |  |  |  |  |  |  |
| PARAMS.pupil.iris_mm | 11.82 | mm | 260 | the visible iris' diameter, to give the pupil in mm |  | ○ |  |  |  |  |  | retarget |
| PARAMS.pupil.reflex.constrict | 0.3 |  | 261 |  |  |  |  |  |  |  |  |  |
| PARAMS.pupil.reflex.hold | 0.75 |  | 261 |  |  |  |  |  |  |  |  |  |
| PARAMS.pupil.reflex.latency | 0.25 |  | 261 |  |  |  |  |  |  |  |  |  |
| PARAMS.pupil.reflex.peak | 0.12 |  | 261 |  |  |  |  |  |  |  |  |  |
| PARAMS.pupil.reflex.redilate | 2.4 |  | 261 |  |  |  |  |  |  |  |  |  |
| PARAMS.pupil.arousal.amplitude | 0.015 |  | 262 |  |  |  |  |  |  |  |  |  |
| PARAMS.pupil.arousal.fall | 3.0 |  | 262 |  |  |  |  |  |  |  |  |  |
| PARAMS.pupil.arousal.high | 90.0 |  | 262 |  |  |  |  |  |  |  |  |  |
| PARAMS.pupil.arousal.low | 10.0 |  | 262 |  |  |  |  |  |  |  |  |  |
| PARAMS.pupil.arousal.rise | 1.0 |  | 262 |  |  |  |  |  |  |  |  |  |
| PARAMS.pupil.chorus.amplitude | 0.015 |  | 263 |  |  |  |  |  |  |  |  |  |
| PARAMS.pupil.chorus.n | 10.1 |  | 263 |  |  |  |  |  |  |  |  |  |
| PARAMS.pupil.chorus.peak | 0.93 |  | 263 |  |  |  |  |  |  |  |  |  |
| PARAMS.pupil.near.per_dioptre | 0.01 |  | 264 |  |  |  |  |  |  |  |  |  |
| PARAMS.pupil.unrest.amplitude | 0.01 |  | 265 |  |  |  |  |  |  |  |  |  |
| PARAMS.pupil.unrest.high_hz | 0.7 | Hz | 265 |  |  |  |  |  |  |  |  |  |
| PARAMS.pupil.unrest.low_hz | 0.1 | Hz | 265 |  |  |  |  |  |  |  |  |  |
| PARAMS.pupil.unrest.waves | 6 |  | 265 |  |  |  |  |  |  |  |  |  |
| PARAMS.pupil.range | [-0.35, 0.5] |  | 266 |  |  |  |  |  |  |  |  |  |
| PARAMS.keys.bone_deg | 0.05 | deg | 269 | a bone's keys: straight lines between them miss no frame by more |  |  |  |  |  |  |  |  |
| PARAMS.keys.morph | 0.001 |  | 270 | a morph's keys: the same in weight |  |  |  |  | ○ |  |  | rig |
| PARAMS.keys.position | 0.0005 | units | 271 | a light bone's keys: the same in place (model units) |  | ○ |  |  |  |  |  | retarget |
| PARAMS.keys.limit | 20000 |  | 272 | MMD's registered points for a model: loading stops past them |  |  |  |  |  |  |  |  |
| PARAMS.keys.reserve | 1000 |  | 273 | refused this near the limit (a later touch to the face would cross it) |  |  |  |  |  |  |  |  |
| light_turn(damping) | 0.15 |  | 638 |  |  |  |  |  |  |  |  |  |
| light_turn(steps) | 4 |  | 638 |  |  |  |  |  |  |  |  |  |
| SOFT_FROM | 0.6 |  | 682 | share of a cap up to which soft_cap passes values unchanged |  |  |  |  |  |  |  |  |
| SEEN_COS | 0.1 |  | 720 | a disc seen more than about 84 degrees off its normal (or from behind) is not seen |  |  |  |  |  |  |  |  |
| pupil_track(seed) | 0 |  | 789 |  |  |  |  |  |  |  |  |  |
| iris_heights(cells) | 32 |  | 872 |  |  |  |  |  |  |  |  |  |
| ride_on_iris(steps) | 4 |  | 907 |  |  |  |  |  |  |  |  |  |
| iris_hit(halvings) | 14 |  | 936 |  |  |  |  |  |  |  |  |  |
| iris_hit(step) | 0.01 |  | 936 |  |  |  |  |  |  |  |  |  |
| lid_mesh(across) | 3.0 |  | 995 |  |  |  |  |  |  |  |  |  |
| lid_mesh(back) | 0.4 |  | 995 |  |  |  |  |  |  |  |  |  |
| lid_mesh(front) | 0.6 |  | 995 |  |  |  |  |  |  |  |  |  |
| slide_off_lids(steps) | 8 |  | 1106 |  |  |  |  |  |  |  |  |  |
| _r(places) | 4 |  | 1256 |  |  |  |  |  |  |  |  |  |
| _bone_keys(reach) | 0.0005 |  | 1335 |  |  |  |  |  |  |  |  |  |
| _bone_keys(tolerance) | 0.05 |  | 1335 |  |  |  |  |  |  |  |  |  |
| _morph_keys(tolerance) | 0.001 |  | 1373 |  |  |  |  |  |  |  |  |  |
| optics(seed) | 0 |  | 1432 |  |  |  |  |  |  |  |  |  |
| loudness(high) | 90.0 |  | 1948 |  |  |  |  |  |  |  |  |  |
| loudness(low) | 10.0 |  | 1948 |  |  |  |  |  |  |  |  |  |
| loudness(rate) | 8000 |  | 1948 |  |  |  |  |  |  |  |  |  |
| loudness(smooth) | 0.5 |  | 1948 |  |  |  |  |  |  |  |  |  |
| loudness(window) | 0.2 |  | 1948 |  |  |  |  |  |  |  |  |  |
| run(seed) | 0 |  | 2001 |  |  |  |  |  |  |  |  |  |
| --seed | 0 |  | 2093 | the pupil's unrest (default 0) |  |  |  |  |  |  |  |  |

## mv_chunks.py（18. 描画と後処理、30）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FPS（引数 --out-fps） | 30 | frames | 84 | the frames of the song (MMD's): the cuts, the lead, the spans and the seconds count in them |  |  |  |  |  |  |  |  |
| OUT_FPS | (30, 60) |  | 85 | the joined video: 30 to publish (the motion's terms), 60 to watch |  |  |  |  |  |  |  |  |
| MMD_FPS | (30, 60, 120, 240, 480, 960) |  | 86 |  |  |  |  |  |  |  |  |  |
| MIN_FRAMES | 3 | frames | 87 |  |  |  |  |  |  |  |  |  |
| DISK_MARGIN | 2 * 1024 ** 3 |  | 96 |  |  |  |  |  |  |  |  |  |
| MAX_BYTES_PER_PIXEL | 1e6 |  | 100 | no AVI comes near; it keeps the arithmetic finite |  |  |  |  |  |  |  |  |
| MAX_WORKERS | 8 |  | 101 | each worker runs an MMD and an encoder (GeForce cards take up to 8 NVENC sessions) |  |  |  |  |  |  |  |  |
| PHYSICS_HZ | 60 | Hz | 102 | MMD steps its physics 60 times a second whatever --fps (tools/mv_look.py PHYSICS_HZ) |  |  |  |  |  |  |  |  |
| STAGE_JOBS | 4 |  | 104 | the processes that draw a stage in the world ("world": true) unless stage_jobs says |  |  |  |  |  |  |  |  |
| KEEP_FREE_GB | 30 |  | 107 | the free space kept on the disk of "out" (render12, 2026-10-21): 30 GB with a stage of a model (the rule of the render machine, _spike/out/stage6/COMMON.md: MMD starts o… |  |  |  |  |  |  |  |  |
| GB | 1024 ** 3 |  | 108 |  |  |  |  |  |  |  |  |  |
| PICTURE_BPP | 2.0 |  | 111 | MMD's picture of the stage, unpacked (RGBA PNG): 1.38 (stagecity), 1.69 (render12) |  |  |  |  |  |  |  |  |
| LAYER_BPP | 2.0 |  | 112 | a frame of the stage of a model and its spill (tools/stage_layer.py, PNG): 1.42, about 1.8 |  |  |  |  |  |  |  |  |
| WORLD_BPP | 0.5 |  | 113 | a frame of the stage in the world (tools/mv_world.py, PNG): 0.41 |  |  |  |  |  |  |  |  |
| MP4_BPP | 0.1 |  | 114 | a frame of the folded video (libx264 crf 16): 0.04 over v7's whole song |  |  |  | ○ |  |  |  | dance |
| MMD_POLL_S | 30 | s | 117 | "mmd_limit" (render12): before every MMD the driver waits while this many MikuMikuDance run on the machine (the shared render machine's rule, COMMON.md: 3), looking ever… |  |  |  |  |  |  |  |  |
| MMD_WAIT_MIN | 60 |  | 118 |  |  |  |  |  |  |  |  |  |
| avi_bytes(bytes_per_pixel) | 4 |  | 205 |  |  |  |  |  |  |  |  |  |
| chunk_disk(workers) | 1 |  | 210 |  |  |  |  |  |  |  |  |  |
| disk_summary(workers) | 1 |  | 230 |  |  |  |  |  |  |  |  |  |
| _look_check(shutter) | 0.5 |  | 555 |  |  |  |  |  |  |  |  |  |
| _look_check(subframes) | 1 |  | 555 |  |  |  |  |  |  |  |  |  |
| _chunk_call(workers) | 1 |  | 934 |  |  |  |  |  |  |  |  |  |
| write(workers) | 1 |  | 1309 |  |  |  |  |  |  |  |  |  |
| --lead | 120 | frames | 1376 | frames rendered before each cut for the physics (default 120) | HANDOVER 2026-10-06: 物理の助走 120 フレーム（区間の境目はカメラのカット） |  |  |  |  |  |  |  |
| --fps | 240 |  | 1377 | the rate MMD renders at: 30, 60, 120, 240, 480 or 960 (default 240) | HANDOVER 2026-10-06 ぼかしの決め: 240 fps で描き 8 枚中 4 枚の平均で 30 fps に畳む（本番の計画は 480 fps・16 枚中 8 枚） |  |  |  |  |  |  | dance |
| --shutter | 0.5 |  | 1381 | share of each frame of the video blurred (default 0.5) |  |  |  |  |  |  |  |  |
| --tag | "final" |  | 1384 | names the files of this run (default final) |  |  |  |  |  |  |  |  |
| --workers | 1 |  | 1385 | "chunks rendered and folded at the same time, 1 to %d (default 1: one after the other)" % MAX_WORKERS |  |  |  |  |  |  |  |  |
| --encoder | "x264" |  | 1387 | x264 (libx264 crf 16, the default; the video to publish) or nvenc (h264_nvenc; the files get _nvenc) |  |  |  |  |  |  |  |  |

## mv_world.py（18. 描画と後処理、54）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SONG_FPS | 30 |  | 67 | MMD's frames of the song (mv_look's SONG_FPS) |  |  |  |  |  |  |  |  |
| LIGHT_SCALE | 2 |  | 68 | the backdrop and the light are drawn at half size: they are all blur (mv_look's LIGHT_SCALE) |  |  |  |  |  |  |  |  |
| REFERENCE_HEIGHT | 720.0 |  | 69 | lengths of the look are pixels of a 720 line picture (mv_look) |  |  |  |  |  |  |  |  |
| REFERENCE.distance | 38.0 |  | 71 | the camera the picture-fixed look was made for: 38 in front of the stage centre, 13 up, level (make_camera's shots) |  |  |  |  |  |  |  |  |
| REFERENCE.fov | 30.0 |  | 71 | the camera the picture-fixed look was made for: 38 in front of the stage centre, 13 up, level (make_camera's shots) |  |  |  |  |  |  |  |  |
| REFERENCE.look_at | (0.0, 13.0, 0.0) |  | 71 | the camera the picture-fixed look was made for: 38 in front of the stage centre, 13 up, level (make_camera's shots) |  |  |  |  |  |  |  |  |
| BEAM_ORIGIN | (0.5, -0.35) |  | 73 | where the old fan of beams had its origin: above the middle of the picture by 35 % of its height (mv_look._beams) |  |  |  |  |  |  |  |  |
| FLOOR_COLOURS.accent | (198.9, 126.5, 41.6) |  | 80 | (the settings of the stage, look["stage"], and their defaults are mv_look's DEFAULT_LOOK["stage"]) the floor of tools/make_stage.py as v7 showed it. Its materials are em… |  |  |  | ○ | ○ |  |  | rig |
| FLOOR_COLOURS.line | (93.9, 110.9, 138.3) |  | 80 | (the settings of the stage, look["stage"], and their defaults are mv_look's DEFAULT_LOOK["stage"]) the floor of tools/make_stage.py as v7 showed it. Its materials are em… |  |  |  | ○ | ○ |  |  | rig |
| FLOOR_COLOURS.plane | (6.0, 9.0, 17.9) |  | 80 | (the settings of the stage, look["stage"], and their defaults are mv_look's DEFAULT_LOOK["stage"]) the floor of tools/make_stage.py as v7 showed it. Its materials are em… |  |  |  | ○ | ○ |  |  | rig |
| FLOOR_SEE_THROUGH | 0.08 |  | 81 | the old floor let 8 % of the stage behind it through (its alpha 0.92): kept |  |  |  |  |  |  |  |  |
| LINE_SEE_THROUGH.accent | 0.20 |  | 84 | and its lines let the plane under them through by 1 - their alpha (0.55 and 0.80): a plane lit brighter than v7's (stage.floor_plane, look2) shows through them by as muc… |  |  |  | ○ |  |  |  | dance |
| LINE_SEE_THROUGH.line | 0.45 |  | 84 | and its lines let the plane under them through by 1 - their alpha (0.55 and 0.80): a plane lit brighter than v7's (stage.floor_plane, look2) shows through them by as muc… |  |  |  | ○ |  |  |  | dance |
| NEAR | 0.1 | units | 85 | nothing nearer the camera than this is drawn (MMD units) |  | ○ |  |  |  |  |  | retarget |
| rays(scale) | 1 |  | 120 |  |  |  |  |  |  |  |  |  |
| truss_point(size) | (1280, 720) |  | 252 |  |  |  |  |  |  |  |  |  |
| MMD_LIGHT | (-0.5, -1.0, 0.5) |  | 429 | where MMD's light shines to at its default (`light get` on a new project, 2026-10-17): the light MMD shades her with |  |  |  |  |  |  |  |  |
| KEY_SHARE | 0.6 |  | 430 | of the light on the floor's plane and pool, the share of the key light (the rest is all round): the default of stage.shadow_key (the core of a shadow keeps 0.40); her bo… |  |  |  |  |  |  |  |  |
| SHADOW_CELL | 0.08 | units | 433 | MMD units: the soft shadow is worked out on a grid of the floor this fine, fixed in the world | softshadow（10-17）: 床の上の影の格子 0.08 単位 | ○ |  |  |  |  |  | retarget |
| SHADOW_GRID_MAX | 1200 |  | 434 | cells to a side at most (a grid that would be larger is coarser) |  |  |  |  |  |  |  |  |
| CUTOFF | 8.0 |  | 435 | standard deviations of the light's spread past which a capsule keeps none of it off |  |  |  |  |  |  |  |  |
| COARSE_STEPS | 6 |  | 436 | a capsule's shade is worked out on a grid at least this many cells to the distance it changes |  |  |  |  |  |  |  |  |
| COARSE_LEVELS | 4 |  | 437 | over (its least blur on the floor; for the light from all round its axis's height), up to 2^4 times SHADOW_CELL coarser |  |  |  |  |  |  |  |  |
| soft_shadow_grid(floor_y) | 0.0 |  | 620 |  |  |  |  |  |  |  |  |  |
| _floor_top(step) | 8 |  | 748 |  |  |  |  |  |  |  |  |  |
| FIGURE_WINDOW | 90 | frames | 890 | frames: the pool follows the centre averaged like make_camera's look-at point |  |  |  |  |  |  |  |  |
| FIGURE_REST_PERCENTILE | 2.0 |  | 891 |  |  |  |  |  |  |  |  |  |
| REFERENCE_HEAD | 16.24313735961914 |  | 911 | the rest height of 頭 on Sour's Rin, whose mesh BODY_PARTS were measured on | リンの頭の骨の休みの高さ 16.243。体のカプセル（BODY_PARTS、リンの頂点から測った）をほかのモデルではこの比で縮める |  |  |  | ○ |  |  | rig |
| BODY_PARTS | ( ("上半身", (0.0, 0.0, 0.0), "上半身2", (0.0, 0.0, 0.0), 1.0), (… |  | 919 | the head and the hair the ribbon the hips the skirt: its upper part and its hem |  |  |  |  | ○ |  |  | rig |
| LEG_PARTS | (("hip", "knee", 0.78), ("knee", "ankle", 0.68)) |  | 945 | the legs, as MMD's IK puts them (tools/leg_ik.py): (from, to, radius) of the solved points; then the foot, turned with 足首: the instep from the ankle to above the ball of… |  |  |  |  |  |  |  |  |
| INSTEP | 0.5 |  | 946 |  |  |  |  |  |  |  |  |  |
| SOLE | 0.42 |  | 947 |  |  |  |  |  |  |  |  |  |
| LEG_BLOCK | 256 | frames | 948 | frames the legs are solved for at a time (leg_ik is vectorised over frames) |  |  |  |  |  |  |  |  |
| DOF_MOST | 3.0 |  | 1127 | a stage nearer the camera than the focus blurs at most this many times stage.dof |  |  |  |  |  |  |  |  |
| DOF_LEVELS | 2.0 ** 0.5 |  | 1128 | defocus blurs the picture at levels of blur this far apart (and 0.5 px the first) |  |  |  |  |  |  |  |  |
| floor_depth(height) | 0.0 |  | 1159 |  |  |  |  |  |  |  |  |  |
| LAMP_LIFT | 0.15 | units | 1220 | MMD units: the edge lamps stand this far above the floor |  | ○ |  |  |  |  |  | retarget |
| LAMP_LEAST | 0.75 | px | 1221 | pixels: a lamp's core is never narrower (smaller, it would fall between the pixels) |  |  |  |  |  |  |  |  |
| LAMP_COLOURS.cool | (150.0, 180.0, 255.0) |  | 1222 | the specks' colours |  |  |  |  |  |  |  |  |
| LAMP_COLOURS.warm | (255.0, 214.0, 150.0) |  | 1222 | the specks' colours |  |  |  |  |  |  |  |  |
| lamp_places(size) | (1280, 720) |  | 1225 |  |  |  |  |  |  |  |  |  |
| FRESNEL_R0 | 0.04 |  | 1299 | a polished floor's share of the light it mirrors, looked at straight down (Schlick's) |  |  |  |  |  |  |  |  |
| mirrored(height) | 0.0 |  | 1302 |  |  |  |  |  |  |  |  |  |
| moments(shutter) | 1.0 |  | 1341 |  |  |  |  |  |  |  |  |  |
| moments(subframes) | 1 |  | 1341 |  |  |  |  |  |  |  |  |  |
| SHARP_ENOUGH | 1.0 | px | 1349 | px: a floor that moves less while the shutter is open is drawn once, at its middle |  |  |  |  |  |  |  |  |
| floor_moves(height) | 0.0 |  | 1352 |  |  |  |  |  |  |  |  |  |
| floor_moments(height) | 0.0 |  | 1363 |  |  |  |  |  |  |  |  |  |
| stage_image(shutter) | 1.0 |  | 1374 |  |  |  |  |  |  |  |  |  |
| stage_image(subframes) | 1 |  | 1374 |  |  |  |  |  |  |  |  |  |
| write_stage(jobs) | 1 |  | 1435 |  |  |  |  |  |  |  |  |  |
| write_stage(shutter) | 1.0 |  | 1435 |  |  |  |  |  |  |  |  |  |
| write_stage(subframes) | 1 |  | 1435 |  |  |  |  |  |  |  |  |  |
| --size | "1280x720" |  | 1521 |  |  |  |  |  |  |  |  |  |

## stage_layer.py（18. 描画と後処理、34）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NEAR | 0.1 | units | 31 | nothing nearer the camera than this is drawn (MMD units; mv_world.NEAR) |  | ○ |  |  |  |  |  | retarget |
| BOTH_SIDES | 0x01 |  | 32 | a PMX material's flag: drawn on both sides (MMD culls the back of every other face) |  |  |  |  | ○ |  |  | rig |
| MIN_ALPHA | 0.5 |  | 33 | faces of a material with less alpha are seen through (MMD does not draw alpha 0) |  |  |  |  | ○ |  |  | rig |
| EDGE | 1e-9 |  | 34 | a pixel centre this close outside a face's edge still counts as inside |  |  |  |  |  |  |  |  |
| _zbuffer_plain(block) | 16 |  | 207 |  |  |  |  |  |  |  |  |  |
| batch_lines(fps) | 30 |  | 354 |  |  |  |  |  |  |  |  |  |
| LEVEL_LEAST | 64 |  | 492 | a level floor round her with at least this many pixels takes mv_world's grid |  |  |  |  |  |  |  |  |
| REFERENCE_HEIGHT | 720.0 |  | 548 | lengths in pixels of the look are pixels of a 720 line picture (mv_look) |  |  |  |  |  |  |  |  |
| floor_levels(least) | 0.01 |  | 621 |  |  |  |  |  |  |  |  |  |
| MIRROR_LEAST | 24.0 |  | 632 | of 255: the parts of the stage brighter than this are mirrored (at night the rest adds little) |  |  |  |  |  |  |  |  |
| FILL | 1.5 | px | 688 | pixels: the gaps a mirror's points leave are filled over at least this blur |  |  |  |  |  |  |  |  |
| COVERED | 0.05 |  | 689 | a neighbourhood where the known pixels' Gaussian weight is under this is faded out |  |  |  |  |  |  |  |  |
| FLICKER_SLOW | (0.25, 0.8) | Hz | 781 | Hz: the swell of a sign's flicker, drawn per material from this range ... |  |  |  |  | ○ |  |  | rig |
| FLICKER_FAST | (6.0, 13.0) |  | 782 | ... and the buzz inside it |  |  |  |  |  |  |  |  |
| SONG_FPS | 30 |  | 872 | MMD's frames of the song (mv_world.SONG_FPS) |  |  |  |  |  |  |  |  |
| __init__(shutter) | 1.0 |  | 885 |  |  |  |  |  |  |  |  |  |
| __init__(subframes) | 1 |  | 885 |  |  |  |  |  |  |  |  |  |
| CHECK_STEP | 0.25 | units | 1085 | MMD units: a capsule is checked as balls this far apart along its axis |  | ○ |  |  |  |  |  | retarget |
| FLOOR_TOLERANCE | 0.06 | units | 1086 | MMD units (about 5 mm): a ball of her body this far into a face reaches into it |  | ○ |  |  |  |  |  | retarget |
| UNDER | 0.1 / 8.0 | units | 1087 | MMD units (0.1 cm, tools/sink_check.py's UNDER_CM): a shoe lower than the floor by more is in it |  | ○ |  |  |  |  |  | retarget |
| FLOOR_LOOK | 3.0 |  | 1088 | the floor under a sole is looked for from this far above it ... |  |  |  |  |  |  |  |  |
| FLOOR_DOWN | 60.0 |  | 1089 | ... down to this far below it (a foot high in a kick still has its floor under it) |  |  |  |  |  |  |  |  |
| SOLE_BAND | 0.4 | units | 1090 | MMD units: a shoe's vertices this near its lowest are its sole (where it stands) |  | ○ |  |  |  |  |  | retarget |
| SOLE_POINTS | 24 |  | 1091 | at most this many of them are looked under |  |  |  |  |  |  |  |  |
| VIEW_REACH | 150.0 |  | 1092 | a camera's sight is checked this far: the inside of a thing it stands in lies nearer |  |  |  |  |  |  |  |  |
| check_placement(body_margin) | 4.0 |  | 1095 |  |  |  |  |  |  |  |  |  |
| check_placement(size) | (1280, 720) |  | 1095 |  |  |  |  |  |  |  |  |  |
| --size | "1280x720" |  | 1277 |  |  |  |  |  |  |  |  |  |
| --size | "1280x720" |  | 1294 |  |  |  |  |  |  |  |  |  |
| --fps | 30 |  | 1295 |  |  |  |  |  |  |  |  |  |
| --subframes | 1 |  | 1296 |  |  |  |  |  |  |  |  |  |
| --shutter | 1.0 |  | 1297 |  |  |  |  |  |  |  |  |  |
| --from | 0 |  | 1309 | the first frame of the song (default 0) |  |  |  | ○ |  |  |  | dance |
| --size | "1280x720" |  | 1311 |  |  |  |  |  |  |  |  |  |

## mv_look.py（18. 描画と後処理、140）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DEFAULT_LOOK.plate.base | [10, 12, 20] |  | 133 | colours are r, g, b of 255; horizon is the height of the haze band (0 top, 1 bottom) |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.plate.haze | [34, 44, 78] |  | 133 | colours are r, g, b of 255; horizon is the height of the haze band (0 top, 1 bottom) |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.plate.horizon | 0.68 |  | 133 | colours are r, g, b of 255; horizon is the height of the haze band (0 top, 1 bottom) |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.plate.pool | [70, 86, 140] |  | 133 | colours are r, g, b of 255; horizon is the height of the haze band (0 top, 1 bottom) |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.plate.vignette | 0.45 |  | 133 | colours are r, g, b of 255; horizon is the height of the haze band (0 top, 1 bottom) |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.beams.count | 6 |  | 136 | count beams over `spread` degrees, each swaying `sway` degrees; every `warm_every`-th one is warm. The light is a loop of `loop_seconds`; the beams sway cycles[0] and cy… |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.beams.cycles | [1, 2] |  | 136 | count beams over `spread` degrees, each swaying `sway` degrees; every `warm_every`-th one is warm. The light is a loop of `loop_seconds`; the beams sway cycles[0] and cy… |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.beams.loop_seconds | 12 |  | 136 | count beams over `spread` degrees, each swaying `sway` degrees; every `warm_every`-th one is warm. The light is a loop of `loop_seconds`; the beams sway cycles[0] and cy… |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.beams.opacity | 0.55 |  | 136 | count beams over `spread` degrees, each swaying `sway` degrees; every `warm_every`-th one is warm. The light is a loop of `loop_seconds`; the beams sway cycles[0] and cy… |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.beams.spread | 76.0 |  | 136 | count beams over `spread` degrees, each swaying `sway` degrees; every `warm_every`-th one is warm. The light is a loop of `loop_seconds`; the beams sway cycles[0] and cy… |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.beams.sway | 3.0 |  | 136 | count beams over `spread` degrees, each swaying `sway` degrees; every `warm_every`-th one is warm. The light is a loop of `loop_seconds`; the beams sway cycles[0] and cy… |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.beams.cool | [90, 110, 190] |  | 137 |  |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.beams.warm | [200, 150, 80] |  | 137 |  |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.beams.warm_every | 5 |  | 137 |  |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.bokeh.count | 26 |  | 139 | the specks drift round cycles[0] times per loop and twinkle cycles[1] times |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.bokeh.cycles | [1, 2] |  | 139 | the specks drift round cycles[0] times per loop and twinkle cycles[1] times |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.bokeh.opacity | 0.8 |  | 139 | the specks drift round cycles[0] times per loop and twinkle cycles[1] times |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.bokeh.seed | 7 |  | 139 | the specks drift round cycles[0] times per loop and twinkle cycles[1] times |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.bokeh.warm_share | 0.35 |  | 139 | the specks drift round cycles[0] times per loop and twinkle cycles[1] times |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.glow.radius | 14 |  | 142 | tuned on the first real excerpt (hinata, 2026-10-05): 150 / 16 / 0.6 washed the white dress out and turned the skin pink; this keeps the folds of the dress and still giv… |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.glow.strength | 0.45 |  | 142 | tuned on the first real excerpt (hinata, 2026-10-05): 150 / 16 / 0.6 washed the white dress out and turned the skin pink; this keeps the folds of the dress and still giv… |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.glow.threshold | 175 |  | 142 | tuned on the first real excerpt (hinata, 2026-10-05): 150 / 16 / 0.6 washed the white dress out and turned the skin pink; this keeps the folds of the dress and still giv… | 2026-10-05 の最初の抜粋で決めた（150 / 16 / 0.6 は白い服を飛ばし肌が桃色に）。リン White の服に合わせた値 |  |  |  |  |  |  | rig |
| DEFAULT_LOOK.flare.colour | [255, 244, 224] |  | 144 | the flare lasts `frames` frames of the song (SONG_FPS: 0.4 s, at 30 fps and at 60) |  |  |  | ○ |  |  |  | dance |
| DEFAULT_LOOK.flare.frames | 12 |  | 144 | the flare lasts `frames` frames of the song (SONG_FPS: 0.4 s, at 30 fps and at 60) |  |  |  | ○ |  |  |  | dance |
| DEFAULT_LOOK.flare.strength | 0.85 |  | 144 | the flare lasts `frames` frames of the song (SONG_FPS: 0.4 s, at 30 fps and at 60) |  |  |  | ○ |  |  |  | dance |
| DEFAULT_LOOK.camera.aberration | 3 |  | 147 | what the camera does at a flare: it punches in by `punch` of the picture and comes back within `punch_frames` frames of the song, and red and blue part by `aberration` p… |  |  |  | ○ |  |  |  | dance |
| DEFAULT_LOOK.camera.punch | 0.04 |  | 147 | what the camera does at a flare: it punches in by `punch` of the picture and comes back within `punch_frames` frames of the song, and red and blue part by `aberration` p… |  |  |  | ○ |  |  |  | dance |
| DEFAULT_LOOK.camera.punch_frames | 10 | frames | 147 | what the camera does at a flare: it punches in by `punch` of the picture and comes back within `punch_frames` frames of the song, and red and blue part by `aberration` p… |  |  |  | ○ |  |  |  | dance |
| DEFAULT_LOOK.lens.grain | 3 |  | 150 | the lens: the corners a little darker (vignette, 0 none to 1 strong) and a fine grain that changes with every frame (0 none, up to about 10); both lie under the text in … |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.lens.vignette | 0.3 |  | 150 | the lens: the corners a little darker (vignette, 0 none to 1 strong) and a fine grain that changes with every frame (0 none, up to about 10); both lie under the text in … |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.rim.colour | [200, 220, 255] |  | 155 | a light from behind her (a rim light, look2 2026-10-18): it lights the band inside her edges that face where it comes from in the picture (`from`, x right and y down: [0… |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.rim.from | [0.0, -1.0] |  | 155 | a light from behind her (a rim light, look2 2026-10-18): it lights the band inside her edges that face where it comes from in the picture (`from`, x right and y down: [0… |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.rim.soft | 2.0 |  | 155 | a light from behind her (a rim light, look2 2026-10-18): it lights the band inside her edges that face where it comes from in the picture (`from`, x right and y down: [0… |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.rim.strength | 0.0 |  | 155 | a light from behind her (a rim light, look2 2026-10-18): it lights the band inside her edges that face where it comes from in the picture (`from`, x right and y down: [0… |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.rim.width | 5.0 |  | 155 | a light from behind her (a rim light, look2 2026-10-18): it lights the band inside her edges that face where it comes from in the picture (`from`, x right and y down: [0… |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.stage.world | 0 |  | 159 | 1: the stage lies in the world and follows the camera (render needs --camera) |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.stage.radius | 120.0 | units | 160 | the cyc: a cylinder round the stage centre, MMD units (0: infinitely far) |  | ○ |  |  |  |  |  | retarget |
| DEFAULT_LOOK.stage.truss | 60.0 |  | 161 | the beams hang from a truss this far behind the stage centre |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.stage.specks | 160.0 |  | 162 | the specks lie on the cyc over this many degrees round the stage centre |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.stage.floor | 1 |  | 163 | 1: draw the floor (MMD renders the dancer without the floor accessory); 0: MMD draws it |  |  |  | ○ |  |  |  | dance |
| DEFAULT_LOOK.stage.floor_accent_every | 4 |  | 164 | make_stage.py's floor |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.stage.floor_half | 60.0 |  | 164 | make_stage.py's floor |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.stage.floor_line | 0.06 |  | 164 | make_stage.py's floor |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.stage.floor_step | 5.0 |  | 164 | make_stage.py's floor |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.stage.floor_y | 0.0 |  | 165 | its height (make_stage --height): 0.111 is where the model's soles stand (2026-10-14) |  |  |  |  | ○ |  |  | rig |
| DEFAULT_LOOK.stage.pool | 0.0 |  | 166 | a pool of light on the floor round the dancer, 0 none to 1 (needs her motion) |  |  |  | ○ |  |  |  | dance |
| DEFAULT_LOOK.stage.pool_radius | 14.0 | units | 167 | its size (a standard deviation, MMD units) |  | ○ |  |  |  |  |  | retarget |
| DEFAULT_LOOK.stage.pool_colour | [34, 32, 30] |  | 168 | what it adds to the floor at its middle at 1 |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.stage.shadow | 0.0 |  | 169 | the shadows of her feet and body on the floor, 0 none to 1 (needs her motion) |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.stage.shadow_soft | 1 |  | 170 | 1: the soft shadow of her whole body from a light (mv_world.soft_shadow_grid); 0: the shadows of v8 and v9 (round her soles and her pelvis, straight down) | HANDOVER 2026-10-17 softshadow: やわらかい床の影を既定に（0 で v9 とバイト単位で同じ） |  |  | ○ |  |  |  | dance |
| DEFAULT_LOOK.stage.shadow_blur | 5.0 | deg | 172 | the soft shadow: the spread of the light, degrees (a standard deviation): the edge of a shadow blurs by about 2.6 x this (in radians) x the distance along the light from… | HANDOVER 2026-10-17 softshadow: 光の広がり 5 度 |  |  |  |  |  |  |  |
| DEFAULT_LOOK.stage.shadow_light | [-0.5, -1.0, 0.5] |  | 175 | where the light shines to (MMD's light direction; its default) |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.stage.shadow_contact | 0.9 |  | 176 | how dark the light from all round leaves the floor under her, 0 to 1 |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.stage.shadow_key | 0.6 |  | 177 | the soft shadow: the key light's share of the floor's light (mv_world.KEY_SHARE): the core of a shadow keeps 1 - this (the rest comes from all round) |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.stage.shadow_share | 1 |  | 179 | the soft shadow: 1 the key light's shadow cuts its share of the plane's and the pool's light and the darkening from all round the rest, the lines keep their own (mv_worl… |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.stage.floor_plane | [6.0, 9.0, 17.9] |  | 184 | the colour of the floor's plane between its lines (v7's: mv_world's FLOOR_COLOURS); its lines keep their own light |  |  |  | ○ |  |  |  | dance |
| DEFAULT_LOOK.stage.reflect | 0.0 |  | 186 | the floor mirrors the cyc, the beams, the specks and the lamps above it by Fresnel's share (more where it is seen at a grazing angle) times this, 0 none to 1 (polished).… |  |  |  | ○ |  |  |  | dance |
| DEFAULT_LOOK.stage.reflect_blur | 8.0 |  | 189 | how blurred the reflection is (a rough floor), pixels of a 720 line picture |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.stage.dof | 0.0 |  | 192 | the blur (a standard deviation, pixels of a 720 line picture) of what lies infinitely far; half of it at twice the focus's distance, none at the focus; 0 no blur |  |  |  | ○ |  |  |  | dance |
| DEFAULT_LOOK.stage.dof_focus | 0.0 | units | 194 | the distance in focus along the line of sight (MMD units); 0: the camera's own distance to its look-at point (where the MV's cameras put the dancer) |  | ○ |  | ○ |  |  |  | retarget |
| DEFAULT_LOOK.lamps.cyc | 0 |  | 200 | how many lamps on the cyc, over stage.specks degrees and the height the reference camera sees of it (as the specks); 0 none |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.lamps.edge_step | 0.0 |  | 202 | a lamp every this many MMD units along the edges of the floor; 0 none |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.lamps.size | 1.2 |  | 203 | the radius of a lamp's core (a standard deviation), pixels of a 720 line picture |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.lamps.power | 3.0 |  | 204 | its light at the middle, times white |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.lamps.warm_share | 0.35 |  | 205 | the share of warm lamps (the specks' colours: warm 255, 214, 150, cool 150, 180, 255) |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.lamps.twinkle | 0.5 |  | 206 | how far a lamp's light dips as it twinkles, 0 (steady) to 1 |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.lamps.cycles | 3 |  | 207 | whole twinkles per light loop (beams.loop_seconds: the loop closes) |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.lamps.seed | 11 |  | 208 |  |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.lamps.glow | 0.0 |  | 209 | the lamps' glow round each: its middle is this share of the lamp's colour; 0 none |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.lamps.glow_radius | 8.0 |  | 210 | its radius (a standard deviation), pixels of a 720 line picture |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.layer.on | 0 |  | 216 | 1: the stage is a model (render needs --stage-set and --stage-pictures) |  |  |  | ○ | ○ |  |  | rig |
| DEFAULT_LOOK.layer.night | 1.0 |  | 217 | the share of MMD's light the model keeps where it gives no light of its own |  |  |  |  | ○ |  |  | rig |
| DEFAULT_LOOK.layer.tint | [1.0, 1.0, 1.0] |  | 218 | ... in this colour (r, g, b factors; a night: a little blue) |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.layer.emissive | 1.0 |  | 219 | the light of the set's emissive materials (signs, lit windows): MMD's colour times this |  |  |  |  | ○ |  |  | rig |
| DEFAULT_LOOK.layer.lamp | 0.0 |  | 220 | the set's lamps light what is near them (MMD's colour times their light); 0 none |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.layer.lamp_colour | [255.0, 214.0, 170.0] |  | 221 |  |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.layer.lamp_reach | 40.0 | units | 222 | MMD units: a lamp's light falls to a half at this distance |  | ○ |  |  |  |  |  | retarget |
| DEFAULT_LOOK.layer.lamp_spot | 2.0 |  | 223 | it throws its light down: (cos of the angle from straight down)^this; 0 all round |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.layer.reflect | 0.0 |  | 224 | the level floors mirror the stage (its lit parts) by Fresnel's share times this; 0 none |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.layer.reflect_blur | 6.0 |  | 225 | how rough the mirror is, pixels of a 720 line picture |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.layer.sky_top | [4.0, 7.0, 20.0] |  | 226 | where MMD drew nothing: the night sky, 0.5 radians above the horizon |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.layer.sky_horizon | [18.0, 22.0, 42.0] |  | 227 | ... and at (and below) the horizon |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.layer.haze | 0.0 |  | 228 | haze by depth: 1 - exp(-haze x depth) of haze_colour; 0 none |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.layer.haze_colour | [14.0, 16.0, 34.0] |  | 229 |  |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.layer.glow | 0.0 |  | 230 | a glow round what is brighter than glow_threshold (of 255), after the blur; 0 none |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.layer.glow_threshold | 204.0 |  | 231 |  |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.layer.glow_radius | 10.0 | px | 232 | pixels of a 720 line picture |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.layer.emissive_glow | 0.0 |  | 233 | a glow round the emissive materials (as AutoLuminous makes them glow); 0 none |  |  |  |  | ○ |  |  | rig |
| DEFAULT_LOOK.layer.emissive_glow_radius | 14.0 |  | 234 |  |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.layer.person | 1.0 |  | 235 | the light on her: her colour (as MMD drew her) times this ... |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.layer.person_tint | [1.0, 1.0, 1.0] |  | 236 | ... in this colour (r, g, b factors) |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.layer.spill | 0.0 |  | 237 | the street's light on her: her colour times (1 + this x the light round her); 0 none |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.layer.spill_wrap | 0.0 |  | 238 | and round her outline (a light wrap): the light round her added in a band inside it |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.layer.spill_radius | 40.0 |  | 239 | how far round her the light is gathered from, pixels of a 720 line picture |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.layer.spill_wrap_width | 6.0 |  | 240 | the band's width, pixels of a 720 line picture |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.light.person.on | 0 |  | 242 | the light on her: MMD draws it through MME (tools/mme_shadow.py prepare --look takes it: key, fill, face, rim, sections; written, the rest comes from its NIGHT_DEFAULTS)… |  |  |  | ○ |  |  |  | dance |
| DEFAULT_LOOK.light.grade.highs | [0.0, 0.0, 0.0] |  | 248 | it: key, fill, face, rim, sections; written, the rest comes from its NIGHT_DEFAULTS); here only checked, the dancer comes lit the grade of the picture under the front te… |  |  |  | ○ |  |  |  | dance |
| DEFAULT_LOOK.light.grade.mids | [0.0, 0.0, 0.0] |  | 248 | it: key, fill, face, rim, sections; written, the rest comes from its NIGHT_DEFAULTS); here only checked, the dancer comes lit the grade of the picture under the front te… |  |  |  | ○ |  |  |  | dance |
| DEFAULT_LOOK.light.grade.saturation | 1.0 |  | 248 | it: key, fill, face, rim, sections; written, the rest comes from its NIGHT_DEFAULTS); here only checked, the dancer comes lit the grade of the picture under the front te… |  |  |  | ○ |  |  |  | dance |
| DEFAULT_LOOK.light.grade.shadows | [0.0, 0.0, 0.0] |  | 248 | the grade of the picture under the front text: a curve a channel (r, g, b shifts of -0.2 to 0.2 of the coded values 0.25, 0.5 and 0.75: the shadows, the middle tones, th… |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.light.flicker | 0.0 |  | 249 | the stage of a model: its lit signs flicker by this share of their light; 0 none |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.light.flicker_seed | 7 |  | 250 |  |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.light.core | 0.0 |  | 251 | ... and their light past white spills into their other channels by this share (an overexposed core goes white: the cores of neon and lamps); 0 none |  |  |  |  |  |  |  |  |
| DEFAULT_LOOK.mograph.on | 0 |  | 256 | the motion graphics (mograph, 2026-10-21; tools/mograph_layer.py, which says how and holds the section's defaults): punches, shakes, flashes, fades, dissolves and glitch… |  |  |  | ○ |  |  |  | dance |
| REFERENCE_HEIGHT | 720.0 |  | 258 |  |  |  |  |  |  |  |  |  |
| LIGHT_SCALE | 2 |  | 259 | the light is drawn at half size: it is all blur |  |  |  |  |  |  |  |  |
| SONG_FPS | 30 | frames | 260 | the frames the look counts in (flare.frames, camera.punch_frames): MMD's, of the song |  |  |  |  |  |  |  |  |
| GRADE_AT | (0.25, 0.5, 0.75) |  | 345 | the coded values (0..1) whose shift each range of the grade gives |  |  |  |  |  |  |  |  |
| GRADE_MOST | 0.2 |  | 346 | a shift is -this to this |  |  |  |  |  |  |  |  |
| FLARE_HEIGHT | 0.42 |  | 631 | of the picture, from the top: about the dancer's chest in a full shot | 「全身のショットで胸のあたり」。adapt 10-17 の測り: 正面固定のカメラでリンの胸（上半身2）は絵の上から 0.43（中央値）、カメラ D で 0.48 |  |  | ○ |  |  |  | dance |
| ffmpeg_command(flare_frames) | 0 | frames | 751 |  |  |  |  |  |  |  |  |  |
| ffmpeg_command(offset) | 0.0 |  | 752 |  |  |  |  |  |  |  |  |  |
| ffmpeg_command(shutter) | 1.0 |  | 752 |  |  |  |  |  |  |  |  |  |
| ffmpeg_command(subframes) | 1 |  | 752 |  |  |  |  |  |  |  |  |  |
| PHYSICS_HZ | 60 | Hz | 1089 | MMD steps its physics this many times a second, whatever the rate of the AVI |  |  |  |  |  |  |  |  |
| SCAN_WIDTH | 320 |  | 1090 | the dancer is read at this width (area-scaled) to find the steps |  |  |  | ○ |  |  |  | dance |
| MOVED | 8 |  | 1091 | of 255 in a channel: a pixel that changed by more has moved |  |  |  |  |  |  |  |  |
| PHASE_WINDOW | 4 | frames | 1092 | frames of the song read together for the residue of the steps |  |  |  | ○ |  |  |  | dance |
| LONE_LEAST | 20 |  | 1093 | lone pixels (at SCAN_WIDTH) a window needs to tell its residue |  |  |  |  |  |  |  |  |
| CLEAR | 2.0 |  | 1094 | and as many times those of the next residue |  |  |  |  |  |  |  |  |
| dancer_input(offset) | 0.0 |  | 1135 |  |  |  |  |  |  |  |  |  |
| measure_physics(offset) | 0.0 |  | 1222 |  |  |  |  |  |  |  |  |  |
| _whole_sequence(first) | 0 |  | 1429 |  |  |  |  |  |  |  |  |  |
| FLOOR_ALPHA | (226, 252) |  | 1485 | the floor accessory of tools/make_stage.py in MMD's picture: its plane at alpha 235, its lines 246 and 251. A dancer's file with more of a picture than FLOOR_SHARE at th… |  |  |  | ○ |  |  |  | dance |
| FLOOR_SHARE | 0.05 |  | 1486 |  |  |  |  |  |  |  |  |  |
| FLOOR_SAMPLES | 8 |  | 1487 |  |  |  |  |  |  |  |  |  |
| world_inputs(jobs) | 1 |  | 1490 |  |  |  |  |  |  |  |  |  |
| world_inputs(shutter) | 0.5 |  | 1490 |  |  |  |  |  |  |  |  |  |
| world_inputs(subframes) | 1 |  | 1490 |  |  |  |  |  |  |  |  |  |
| --jobs | 1 |  | 1752 | a stage in the world: the processes that draw its frames (default 1; the pictures are the same) |  |  |  |  |  |  |  |  |
| --encoder | "x264" |  | 1767 | x264 (libx264 crf 16, the default) or nvenc (h264_nvenc on an NVIDIA GPU) |  |  |  |  |  |  |  |  |
| --offset | 0.0 | s | 1769 | the song time at the dancer's first frame, in seconds (a chunk rendered from a later frame) |  |  |  | ○ |  |  |  | dance |
| --subframes | 1 |  | 1771 | the dancer was rendered at this many times the output rate: fold them into one frame (motion blur) |  |  |  | ○ |  |  |  | dance |
| --shutter | 0.5 |  | 1773 | with --subframes: the share of a frame the shutter is open (default 0.5, the film standard) |  |  |  |  |  |  |  |  |
| --shutter | 0.5 |  | 1787 | as for render (default 0.5) |  |  |  |  |  |  |  |  |
| --offset | 0.0 |  | 1788 | as for render |  |  |  |  |  |  |  |  |
| --encoder | "x264" |  | 1798 | nvenc: also check that h264_nvenc works here |  |  |  |  |  |  |  |  |
| --encoder | "x264" |  | 1807 | nvenc: also check that h264_nvenc works here |  |  |  |  |  |  |  |  |
| --subframes | 1 |  | 1809 | a stage in the world: the renders fold this many dancer frames into one (the floor's motion blur) |  |  |  | ○ |  |  |  | dance |
| --shutter | 0.5 |  | 1811 | a stage in the world: the renders' --shutter |  |  |  |  |  |  |  |  |

## mv_text.py（18. 描画と後処理、51）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CJK_START | 0x2E80 |  | 117 | from here up (CJK, kana, fullwidth forms) a code point is Japanese |  |  |  |  |  |  |  |  |
| FPS | 30 |  | 122 | ---- the cue file --------------------------------------------------------------------------- |  |  |  |  |  |  |  |  |
| SIZE | (1280, 720) |  | 123 |  |  |  |  |  |  |  |  |  |
| ENTER | 0.6 | s | 124 | seconds a cue takes to come and to go, unless it says otherwise |  |  |  |  |  |  |  |  |
| EXIT | 0.4 | s | 124 | seconds a cue takes to come and to go, unless it says otherwise |  |  |  |  |  |  |  |  |
| RISE | (24.0, -12.0) | px | 127 | px: where "rise" starts below its place, where it leaves above it |  |  |  |  |  |  |  |  |
| TRACKING_IN | (0.6, 0.1) |  | 128 | em: how far "tracking-in" starts spread, and spreads again leaving |  |  |  |  |  |  |  |  |
| WIPE_EDGE | 24.0 | px | 129 | px: the soft edge of "wipe" |  |  |  |  |  |  |  |  |
| FLASH | (1.0, 0.0, 1.0, 0.35, 1.0) |  | 130 | the alpha of the first frames of "flash"; full after them |  |  |  |  |  |  |  |  |
| FLASH_FPS | 30 |  | 131 | those frames are frames of the song (MMD's): 60 fps holds each for two |  |  |  | ○ |  |  |  | dance |
| PALETTES.dark.accent | (240, 160, 48) |  | 142 | white text and an amber accent for a black stage (glow and light effects need the black); the secondary colour is 70 % of the text colour |  |  |  |  |  |  |  |  |
| PALETTES.dark.ink | (22, 22, 30) |  | 142 | white text and an amber accent for a black stage (glow and light effects need the black); the secondary colour is 70 % of the text colour |  |  |  |  |  |  |  |  |
| PALETTES.dark.secondary | (172, 172, 174) |  | 142 | white text and an amber accent for a black stage (glow and light effects need the black); the secondary colour is 70 % of the text colour |  |  |  |  |  |  |  |  |
| PALETTES.dark.text | (245, 245, 248) |  | 142 | white text and an amber accent for a black stage (glow and light effects need the black); the secondary colour is 70 % of the text colour |  |  |  |  |  |  |  |  |
| PALETTES.dark.shadow | (0, 0, 0) |  | 143 |  |  |  |  |  |  |  |  |  |
| PALETTES.dark.stage | (0, 0, 0) |  | 143 |  |  |  |  |  |  |  |  |  |
| PALETTES.light.accent | (240, 160, 48) |  | 146 | ink on the white stage MMD draws by default; white text would vanish there. The soft shadow is a white halo here: black under ink would smear the text instead of parting… |  |  |  |  |  |  |  |  |
| PALETTES.light.ink | (22, 22, 30) |  | 146 | ink on the white stage MMD draws by default; white text would vanish there. The soft shadow is a white halo here: black under ink would smear the text instead of parting… |  |  |  |  |  |  |  |  |
| PALETTES.light.secondary | (120, 120, 130) |  | 146 | ink on the white stage MMD draws by default; white text would vanish there. The soft shadow is a white halo here: black under ink would smear the text instead of parting… |  |  |  |  |  |  |  |  |
| PALETTES.light.text | (22, 22, 30) |  | 146 | ink on the white stage MMD draws by default; white text would vanish there. The soft shadow is a white halo here: black under ink would smear the text instead of parting… |  |  |  |  |  |  |  |  |
| PALETTES.light.shadow | (255, 255, 255) |  | 147 |  |  |  |  |  |  |  |  |  |
| PALETTES.light.stage | (255, 255, 255) |  | 147 |  |  |  |  |  |  |  |  |  |
| REFERENCE_HEIGHT | 720 |  | 161 | ---- the layout ----------------------------------------------------------------------------- All px below are those of a frame REFERENCE_HEIGHT high and scale with the … |  |  |  |  |  |  |  |  |
| MARGIN | (64, 48) | px | 162 | px kept free at the left and right, at the top and bottom |  |  |  |  |  |  |  |  |
| LINE_GAP | 0.35 |  | 163 | em of the larger neighbour, from the bottom of a line to the next top |  |  |  |  |  |  |  |  |
| LOWER | 5.0 / 6.0 |  | 164 | "lower": the block is centred on the middle of the lower third |  |  |  |  |  |  |  |  |
| X_CENTRES.center | 0.5 |  | 165 |  |  |  |  |  |  |  |  |  |
| X_CENTRES.left-third | 0.25 |  | 165 |  |  |  |  |  |  |  |  |  |
| X_CENTRES.right-third | 0.75 |  | 165 |  |  |  |  |  |  |  |  |  |
| UNDERLINE.gap | 0.2 |  | 167 | of the text width; px; em under the last line |  |  |  |  |  |  |  |  |
| UNDERLINE.height | 2.0 |  | 167 | of the text width; px; em under the last line |  |  |  |  |  |  |  |  |
| UNDERLINE.width | 0.6 |  | 167 | of the text width; px; em under the last line |  |  |  |  |  |  |  |  |
| INK_COPY | 3.0 | px | 168 | px: how far left of the text its ink copy sits |  |  |  |  |  |  |  |  |
| SHADOW.alpha | 170 |  | 169 | of 255; px: the blur radius and how far down it lies |  |  |  |  |  |  |  |  |
| SHADOW.blur | 6.0 |  | 169 | of 255; px: the blur radius and how far down it lies |  |  |  |  |  |  |  |  |
| SHADOW.offset | 2.0 |  | 169 | of 255; px: the blur radius and how far down it lies |  |  |  |  |  |  |  |  |
| BLUR_REACH | 3.0 |  | 170 | Pillow's GaussianBlur(r) reaches about 2.6 r past its source (measured) |  |  |  |  |  |  |  |  |
| CANVAS_PAD | 8 | px | 171 | px (not scaled) around everything a cue draws |  |  |  |  |  |  |  |  |
| COMMAND_LIMIT | 32000 |  | 176 | characters of one command line (Windows takes 32767) |  |  |  |  |  |  |  |  |
| STYLES.logo | Style("logo", 150, 150, 900, 0.02, "text", ("latin",)) |  | 201 |  |  |  |  |  |  |  |  |  |
| STYLES.title_jp | Style("jp", 44, 44, 900, 0.0, "text", ("jp",)) |  | 202 |  |  |  |  |  |  |  |  |  |
| STYLES.sub | Style("latin", 30, 30, 700, 0.25, "accent", ("latin",), upp… |  | 203 |  |  |  |  |  |  |  |  |  |
| STYLES.credit | Style("latin", 22, 24, 400, 0.12, "secondary", ("latin", "j… |  | 204 |  |  |  |  |  |  |  |  |  |
| STYLES.lyric | Style("jp", 46, 46, 700, 0.0, "text", ("jp",), underline=Tr… |  | 205 |  |  |  |  |  |  |  |  |  |
| STYLES.hook | Style("accent", 180, 180, 900, 0.0, "accent", ("latin",), i… |  | 206 |  |  |  |  |  |  |  |  |  |
| STYLES.caption | Style("jp", 28, 28, 400, 0.0, "text", ("jp",)) |  | 207 |  |  |  |  |  |  |  |  |  |
| seconds(least) | 0.0 |  | 404 |  |  |  |  |  |  |  |  |  |
| line_width(extra) | 0.0 |  | 624 |  |  |  |  |  |  |  |  |  |
| line_x(extra) | 0.0 |  | 627 |  |  |  |  |  |  |  |  |  |
| text(dx) | 0 |  | 880 |  |  |  |  |  |  |  |  |  |
| text(dy) | 0 |  | 880 |  |  |  |  |  |  |  |  |  |

## make_stage.py（18. 描画と後処理、13）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FILE_UNITS_PER_MMD_UNIT | 0.1 |  | 32 |  |  |  |  |  |  |  |  |  |
| PLANE_DEPTH | -0.02 |  | 33 |  |  |  |  |  |  |  |  |  |
| MATERIALS | ( ((0.0, 0.0, 0.0, 0.92), 5.0, (0.0, 0.0, 0.0), (0.03, 0.04… |  | 35 | 0 the plane: blue-black 1 a line: cool white 2 an accent line: amber |  |  |  |  |  |  |  |  |
| floor(accent_every) | 4 |  | 56 |  |  |  |  |  |  |  |  |  |
| floor(half) | 60.0 |  | 56 |  |  |  |  |  |  |  |  |  |
| floor(height) | 0.0 |  | 56 |  |  |  |  |  |  |  |  |  |
| floor(line) | 0.06 |  | 56 |  |  |  |  |  |  |  |  |  |
| floor(step) | 5.0 |  | 56 |  |  |  |  |  |  |  |  |  |
| --half | 60.0 |  | 119 | half the side of the floor, in MMD units (default 60) |  |  |  |  |  |  |  |  |
| --step | 5.0 |  | 120 | between two lines (default 5, MMD's own grid) |  |  |  |  |  |  |  |  |
| --line | 0.06 |  | 121 | half the width of a line (default 0.06) |  |  |  |  |  |  |  |  |
| --accent-every | 4 |  | 122 | every N-th line is amber and wider; 0 for none (default 4) |  |  |  |  |  |  |  |  |
| --height | 0.0 |  | 123 | the height of the floor (its lines), in MMD units (default 0; 0.111 is where the model's soles stand) |  |  |  |  | ○ |  |  | rig |

## mme_shadow.py（18. 描画と後処理、30）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| KERNEL_SIGMAS | 2.5 |  | 93 | the points lie within this many standard deviations of the Gaussian |  |  |  |  |  |  |  |  |
| CUT_STD | math.sqrt((1.0 - (1.0 + 0.5 * KERNEL_SIGMAS ** 2) * math.ex… |  | 96 | the standard deviation of a Gaussian of 1 cut at KERNEL_SIGMAS (along an axis): the points are widened by its inverse, so that their spread is the light's (cut, an edge … |  |  |  |  |  |  |  |  |
| GOLDEN | math.pi * (3.0 - math.sqrt(5.0)) |  | 98 |  |  |  |  |  |  |  |  |  |
| DEFAULTS.blur | 5.0 |  | 102 | key_share 0.35: the shade keeps 0.65 of the light, option D (Kaga-san's choice of 2026-10-17 among A: the shade 0.40, B: MMD's toon, C: the shade and the floor 0.65, D: … |  |  |  |  |  |  |  |  |
| DEFAULTS.key_share | 0.35 |  | 102 | key_share 0.35: the shade keeps 0.65 of the light, option D (Kaga-san's choice of 2026-10-17 among A: the shade 0.40, B: MMD's toon, C: the shade and the floor 0.65, D: … | HANDOVER 2026-10-17 softshadow-mme（0.6 = mv_world.KEY_SHARE）。加賀さんは陰の濃さ D（体 0.65・床 0.40）を選んだ（10-17、枝 softshadow-mme2 で既定… |  |  |  |  |  |  |  |
| DEFAULTS.min_blur | 0.05 |  | 102 | key_share 0.35: the shade keeps 0.65 of the light, option D (Kaga-san's choice of 2026-10-17 among A: the shade 0.40, B: MMD's toon, C: the shade and the floor 0.65, D: … |  |  |  |  |  |  |  |  |
| DEFAULTS.search_taps | 64 |  | 102 | key_share 0.35: the shade keeps 0.65 of the light, option D (Kaga-san's choice of 2026-10-17 among A: the shade 0.40, B: MMD's toon, C: the shade and the floor 0.65, D: … |  |  |  |  |  |  |  |  |
| DEFAULTS.taps | 64 |  | 102 | key_share 0.35: the shade keeps 0.65 of the light, option D (Kaga-san's choice of 2026-10-17 among A: the shade 0.40, B: MMD's toon, C: the shade and the floor 0.65, D: … |  |  |  |  |  |  |  |  |
| HARMONIC | 0 |  | 110 | the casters' gaps found by the search are averaged plainly (0) or harmonically (1: the nearest caster rules). Review of softshadow-mme2, against the reference of a 5 deg… |  |  |  | ○ |  |  |  | dance |
| FACING_MIN | 0.25 |  | 111 | the receiver's normal is held at least this far towards the light (75.5 degrees from it) when the plane round the pixel is worked out: a face along the light has no dept… |  |  |  |  |  |  |  |  |
| DEBUGS | {False: 0, None: 0, True: 1, "shadow": 1, "lit": 2, "toon":… |  | 113 |  |  |  |  |  |  |  |  |  |
| SEARCH_INNER | 0.03 |  | 114 | the innermost point of the search, a share of its radius (0.054 units: a caster's cone near the pixel is small, 0.38 units at 1.5 for 5 degrees) |  |  |  |  |  |  |  |  |
| SEARCH | 1.8 | units | 116 | MMD units round the point the casters are looked for (2.5 standard deviations of a 5 degree light at 8 units: the hips above the knees) |  | ○ |  |  |  |  |  | retarget |
| LIGHT_DEFAULT | 154.0 / 256.0 |  | 119 | MMD's light colour by default, as MME gives it (the light's AMBIENT is the colour of MMD's light panel over 256: on hinata a light of 200, 100, 50 drew 199, 100, 50 of 2… |  |  |  |  |  | ○ |  |  |
| NIGHT_MOST | 4.0 |  | 122 | a colour of the night is r, g, b of 0 to this (over 1: brighter than MMD's white) |  |  |  |  |  |  |  |  |
| NIGHT_DEFAULTS.on | 0 |  | 123 |  |  |  |  |  |  |  |  |  |
| NIGHT_DEFAULTS.direction | [-0.5, -1.0, 0.5] |  | 124 | MMD's light, where it shines to (y below 0): the key's direction and the self shadow's (light_vmd writes it into the camera's motion) |  |  |  |  |  |  |  |  |
| NIGHT_DEFAULTS.key | [1.0, 1.0, 1.0] |  | 126 | the key light: her colour times this where MMD's light reaches her |  |  |  |  |  |  |  |  |
| NIGHT_DEFAULTS.fill | [0.35, 0.35, 0.35] |  | 127 | the fill: her colour times this in the shade (in the toon's hue) |  |  |  |  |  |  |  |  |
| NIGHT_DEFAULTS.face | 0.75 |  | 128 | the face and the eyes (MMD shades them not): from the fill (0) to the key (1) |  |  |  |  |  |  |  |  |
| NIGHT_DEFAULTS.rim | [0.0, 0.0, 0.0] |  | 129 | the rim light: this colour times Fresnel's (1 - n.v)^rim_power; 0 none |  |  |  |  |  |  |  |  |
| NIGHT_DEFAULTS.rim_power | 3.0 |  | 130 |  |  |  |  |  |  |  |  |  |
| NIGHT_DEFAULTS.rim_from | [0.0, -1.0] |  | 131 | where the rim light comes from in the picture (x right, y down; look.rim) |  |  |  |  |  |  |  |  |
| NIGHT_DEFAULTS.rim_sided | 1.0 |  | 132 | 0: all round her outline; 1: only on the side it comes from |  |  |  |  |  |  |  |  |
| NIGHT_DEFAULTS.rim_albedo | 0.3 |  | 133 | 0: the rim's own colour; 1: times her colour |  |  |  |  |  |  |  |  |
| NIGHT_DEFAULTS.edge | 1.0 |  | 134 | the outline: 1 MMD's own (the edge colour, unlit); under 1 its colour times this and the light between the fill and the key |  |  |  |  |  |  |  |  |
| NIGHT_DEFAULTS.fade | 0.5 | s | 137 | seconds over which a section's colours come in (round its start) |  |  |  |  |  |  |  |  |
| _share(high) | 1.0 |  | 181 |  |  |  |  |  |  |  |  |  |
| _share(low) | 0.0 |  | 181 |  |  |  |  |  |  |  |  |  |
| MMD_LIGHT | (-0.5, -1.0, 0.5) |  | 875 | MMD's light after `new`: a camera's motion without light keys leaves it so |  |  |  |  |  |  |  |  |

## pmm_gravity.py（18. 描画と後処理、8）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CURRENT.acceleration | 0 |  | 26 | offsets from pmm.loads(positions=...): the current setting, and each key's fields after its links | pmm の中の位置（重力の今の値の加速度）。値の決めではない。窓の値と単位: MMD 9.32 で窓の値 1 あたり 9.6 単位/s²（README） |  |  |  |  |  |  |  |
| CURRENT.direction | 8 |  | 26 | offsets from pmm.loads(positions=...): the current setting, and each key's fields after its links |  |  |  |  |  |  |  |  |
| CURRENT.noise | 4 |  | 26 | offsets from pmm.loads(positions=...): the current setting, and each key's fields after its links |  |  |  |  |  |  |  |  |
| CURRENT.noise_enabled | 20 |  | 26 | offsets from pmm.loads(positions=...): the current setting, and each key's fields after its links |  |  |  |  |  |  |  |  |
| KEY.acceleration | 5 |  | 27 |  |  |  |  |  |  |  |  |  |
| KEY.direction | 9 |  | 27 |  |  |  |  |  |  |  |  |  |
| KEY.noise | 1 |  | 27 |  |  |  |  |  |  |  |  |  |
| KEY.noise_enabled | 0 |  | 27 |  |  |  |  |  |  |  |  |  |

## mograph_layer.py（18. 描画と後処理、81）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SONG_FPS | 30 | frames | 65 | the frames the section counts in: MMD's, of the song (mv_look.SONG_FPS) |  |  |  |  |  |  |  |  |
| REFERENCE_HEIGHT | 720.0 |  | 66 | lengths are pixels of a 720 line picture (mv_look) |  |  |  |  |  |  |  |  |
| DEFAULTS.on | 0 |  | 69 |  |  |  |  |  |  |  |  |  |
| DEFAULTS.punch.amount | 0.10 |  | 70 |  |  |  |  |  |  |  |  |  |
| DEFAULTS.punch.centre | [0.5, 0.45] |  | 70 |  |  |  |  |  |  |  |  |  |
| DEFAULTS.punch.fall | 10 |  | 70 |  |  |  |  |  |  |  |  |  |
| DEFAULTS.punch.rise | 2 |  | 70 |  |  |  |  |  |  |  |  |  |
| DEFAULTS.shake.amount | 5.0 |  | 71 |  |  |  |  |  |  |  |  |  |
| DEFAULTS.shake.frames | 10 |  | 71 |  |  |  |  |  |  |  |  |  |
| DEFAULTS.shake.hz | 9.0 |  | 71 |  |  |  |  |  |  |  |  |  |
| DEFAULTS.flash.colour | [255, 255, 255] | frames | 74 | (9 frames: 4 of them over 0.10 of Y' on the city at night, as tools/mograph_analyze.py reads a flash; the references' last 0.119 s, 3.6 frames. 7 gave 2 on window A of t… |  |  |  |  |  |  |  |  |
| DEFAULTS.flash.frames | 9 | frames | 74 | (9 frames: 4 of them over 0.10 of Y' on the city at night, as tools/mograph_analyze.py reads a flash; the references' last 0.119 s, 3.6 frames. 7 gave 2 on window A of t… |  |  |  |  |  |  |  |  |
| DEFAULTS.flash.light | 0.0 | frames | 74 | (9 frames: 4 of them over 0.10 of Y' on the city at night, as tools/mograph_analyze.py reads a flash; the references' last 0.119 s, 3.6 frames. 7 gave 2 on window A of t… |  |  |  |  |  |  |  |  |
| DEFAULTS.flash.strength | 0.27 | frames | 74 | (9 frames: 4 of them over 0.10 of Y' on the city at night, as tools/mograph_analyze.py reads a flash; the references' last 0.119 s, 3.6 frames. 7 gave 2 on window A of t… |  |  |  |  |  |  |  |  |
| DEFAULTS.fade.back | 15 |  | 75 |  |  |  |  |  |  |  |  |  |
| DEFAULTS.fade.colour | [0, 0, 0] |  | 75 |  |  |  |  |  |  |  |  |  |
| DEFAULTS.fade.hold | 2 |  | 75 |  |  |  |  |  |  |  |  |  |
| DEFAULTS.fade.out | 12 |  | 75 |  |  |  |  |  |  |  |  |  |
| DEFAULTS.dissolve.frames | 12 |  | 76 |  |  |  |  |  |  |  |  |  |
| DEFAULTS.glitch.bands | 3 |  | 79 | (split 14: red and blue 28 px apart, which tools/mograph_analyze.py reads at its 128 x 72 as the references' glitches; split 6 on v7 read as none, 2026-10-21) |  |  |  | ○ |  |  |  | dance |
| DEFAULTS.glitch.frames | 2 |  | 79 | (split 14: red and blue 28 px apart, which tools/mograph_analyze.py reads at its 128 x 72 as the references' glitches; split 6 on v7 read as none, 2026-10-21) |  |  |  | ○ |  |  |  | dance |
| DEFAULTS.glitch.seed | 5 |  | 79 | (split 14: red and blue 28 px apart, which tools/mograph_analyze.py reads at its 128 x 72 as the references' glitches; split 6 on v7 read as none, 2026-10-21) |  |  |  | ○ |  |  |  | dance |
| DEFAULTS.glitch.shift | 40.0 |  | 79 | (split 14: red and blue 28 px apart, which tools/mograph_analyze.py reads at its 128 x 72 as the references' glitches; split 6 on v7 read as none, 2026-10-21) |  |  |  | ○ |  |  |  | dance |
| DEFAULTS.glitch.split | 14.0 |  | 79 | (split 14: red and blue 28 px apart, which tools/mograph_analyze.py reads at its 128 x 72 as the references' glitches; split 6 on v7 read as none, 2026-10-21) |  |  |  | ○ |  |  |  | dance |
| DEFAULTS.particles.brightness | 1.0 |  | 84 | (the specks in the air round her, near the focus, sharp; the lights far behind her, low over the street, blurred into bokeh by stage.dof. One box for both, 2026-10-21's … |  |  |  |  |  |  |  |  |
| DEFAULTS.particles.drift | [0.25, 0.06, 0.0] |  | 84 | (the specks in the air round her, near the focus, sharp; the lights far behind her, low over the street, blurred into bokeh by stage.dof. One box for both, 2026-10-21's … |  |  |  |  |  |  |  |  |
| DEFAULTS.particles.lights | 0 |  | 84 | (the specks in the air round her, near the focus, sharp; the lights far behind her, low over the street, blurred into bokeh by stage.dof. One box for both, 2026-10-21's … |  |  |  |  |  |  |  |  |
| DEFAULTS.particles.seed | 9 |  | 84 | (the specks in the air round her, near the focus, sharp; the lights far behind her, low over the street, blurred into bokeh by stage.dof. One box for both, 2026-10-21's … |  |  |  |  |  |  |  |  |
| DEFAULTS.particles.size | 1.0 |  | 84 | (the specks in the air round her, near the focus, sharp; the lights far behind her, low over the street, blurred into bokeh by stage.dof. One box for both, 2026-10-21's … |  |  |  |  |  |  |  |  |
| DEFAULTS.particles.specks | 0 |  | 84 | (the specks in the air round her, near the focus, sharp; the lights far behind her, low over the street, blurred into bokeh by stage.dof. One box for both, 2026-10-21's … |  |  |  |  |  |  |  |  |
| DEFAULTS.particles.box | [-34.0, 0.5, -16.0, 34.0, 30.0, 14.0] |  | 85 |  |  |  |  |  |  |  |  |  |
| DEFAULTS.particles.light_box | [-70.0, 0.5, 40.0, 70.0, 22.0, 150.0] |  | 85 |  |  |  |  |  |  |  |  |  |
| DEFAULTS.particles.clear | 9.0 |  | 86 |  |  |  |  |  |  |  |  |  |
| DEFAULTS.particles.front | 0.35 |  | 86 |  |  |  |  |  |  |  |  |  |
| LIMITS.flash.strength | (0.0, 1.0) |  | 90 |  |  |  |  |  |  |  |  |  |
| LIMITS.punch.amount | (0.0, 0.5) |  | 90 |  |  |  |  |  |  |  |  |  |
| LIMITS.shake.amount | (0.0, 40.0) |  | 90 |  |  |  |  |  |  |  |  |  |
| LIMITS.shake.hz | (0.1, 14.9) |  | 90 |  |  |  |  |  |  |  |  |  |
| LIMITS.flash.light | (0.0, 4.0) |  | 91 |  |  |  |  |  |  |  |  |  |
| LIMITS.glitch.shift | (0.0, 200.0) |  | 92 |  |  |  |  |  |  |  |  |  |
| LIMITS.glitch.split | (0.0, 40.0) |  | 92 |  |  |  |  |  |  |  |  |  |
| LIMITS.particles.brightness | (0.0, 4.0) |  | 92 |  |  |  |  |  |  |  |  |  |
| LIMITS.particles.clear | (0.0, 100.0) |  | 93 |  |  |  |  |  |  |  |  |  |
| LIMITS.particles.front | (0.0, 1.0) |  | 93 |  |  |  |  |  |  |  |  |  |
| LIMITS.particles.size | (0.05, 10.0) |  | 93 |  |  |  |  |  |  |  |  |  |
| WHOLE.fade.hold | -1 |  | 94 |  |  |  |  |  |  |  |  |  |
| WHOLE.fade.out | 0 |  | 94 |  |  |  |  |  |  |  |  |  |
| WHOLE.flash.frames | 1 |  | 94 |  |  |  |  |  |  |  |  |  |
| WHOLE.punch.fall | 1 |  | 94 |  |  |  |  |  |  |  |  |  |
| WHOLE.punch.rise | 1 |  | 94 |  |  |  |  |  |  |  |  |  |
| WHOLE.shake.frames | 1 |  | 94 |  |  |  |  |  |  |  |  |  |
| WHOLE.dissolve.frames | 1 |  | 95 |  |  |  |  |  |  |  |  |  |
| WHOLE.fade.back | 0 |  | 95 |  |  |  |  |  |  |  |  |  |
| WHOLE.glitch.bands | 0 |  | 95 |  |  |  |  |  |  |  |  |  |
| WHOLE.glitch.frames | 1 |  | 95 |  |  |  |  |  |  |  |  |  |
| WHOLE.glitch.seed | 0 |  | 95 |  |  |  |  |  |  |  |  |  |
| WHOLE.particles.lights | 0 |  | 96 |  |  |  |  |  |  |  |  |  |
| WHOLE.particles.seed | 0 |  | 96 |  |  |  |  |  |  |  |  |  |
| WHOLE.particles.specks | 0 |  | 96 |  |  |  |  |  |  |  |  |  |
| MARGIN | 1.15 |  | 97 | a shake's zoom covers this many times its reach (bilinear sampling needs a pixel more) |  |  |  |  |  |  |  |  |
| FRONT_GAP | 2.0 | units | 98 | MMD units: a particle this much nearer the camera than the dancer's place is in front |  | ○ |  | ○ |  |  |  | retarget |
| NEAR_FADE | (3.0, 8.0) | units | 99 | MMD units from the eye: none nearer than the first, all of it past the second |  | ○ |  |  |  |  |  | retarget |
| EDGE_FADE | 3.0 | units | 100 | MMD units: particles fade within this of the box's faces (they wrap round there) |  | ○ |  |  |  |  |  | retarget |
| SPRITE_LEAST | 0.6 | px | 101 | px: the least spread (a standard deviation) of a particle on the picture |  |  |  |  |  |  |  |  |
| BUSY_RAMP | 1.0 | s | 102 | s: a busy span's level comes and goes over this |  |  |  |  |  |  |  |  |
| DEFAULT_SHAKE_RATIO | (0.6, 1.37) |  | 103 | the vertical jolt: this share of the horizontal one, ringing this many times as fast |  |  |  |  |  |  |  |  |
| ARGV_MOST | 30000 |  | 104 | characters: a longer ffmpeg command goes past Windows' command line (32767) |  |  |  |  |  |  |  |  |
| CUT_LEAD | 0.077 | s | 105 | s: a change of picture at a section's start comes this much before its first beat, as the references' cuts do (five of nine, [0.034, 0.108]: typorev) |  |  |  | ○ |  |  |  | dance |
| PLAN_PARTICLES.lights | 24 |  | 108 | references' cuts do (five of nine, [0.034, 0.108]: typorev) the plan's particles: restrained, by eye (their count is no target: typorev), and a little busier over the in… |  |  |  |  |  |  |  |  |
| PLAN_PARTICLES.specks | 100 |  | 108 | the plan's particles: restrained, by eye (their count is no target: typorev), and a little busier over the interludes |  |  |  |  |  |  |  |  |
| FLASH_LIGHT | 1.1 |  | 116 | the plan's flashes are of light, not a veil: the references' 51 flashes (typorev's events of the nine videos) leave the dark of the picture where it was (its darkest 5 %… |  |  |  |  |  |  |  |  |
| PLAN_BUSY | 1.3 |  | 117 |  |  |  |  |  |  |  |  |  |
| SPECK_COLOURS | ((255.0, 240.0, 214.0), (255.0, 255.0, 255.0), (214.0, 228.… |  | 611 |  |  |  |  |  |  |  |  |  |
| LIGHT_COLOURS | ((255.0, 196.0, 120.0), (255.0, 160.0, 186.0), (150.0, 214.… |  | 612 |  |  |  |  |  |  |  |  |  |
| particle_frame(shutter) | 1.0 |  | 753 |  |  |  |  |  |  |  |  |  |
| particle_frame(subframes) | 1 |  | 753 |  |  |  |  |  |  |  |  |  |
| plan(level) | 1.0 |  | 853 |  |  |  |  |  |  |  |  |  |
| apply_argv(offset) | 0.0 |  | 967 |  |  |  |  |  |  |  |  |  |
| --level | 1.0 |  | 1023 | the punches', shakes' and flashes' strength times this |  |  |  |  |  |  |  |  |
| --size | "1280x720" |  | 1029 |  |  |  |  |  |  |  |  |  |
| --offset | 0.0 |  | 1036 |  |  |  |  |  |  |  |  |  |

## make_camera.py（19. カメラ（加賀さんの指示で後回し）、67）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FPS | 30 |  | 90 |  |  |  |  |  |  |  |  |  |
| WINDOW | 30 | frames | 91 | frames: the strength of a frame is the motion of the second around it |  |  |  |  |  |  |  |  |
| TREND_WINDOW | 90 | frames | 92 | frames: sections are found on a 3 second moving average of the strength |  |  |  |  |  |  |  |  |
| HIGH_PERCENTILE | 65 |  | 93 |  |  |  |  |  |  |  |  |  |
| LOW_PERCENTILE | 35 |  | 93 |  |  |  |  |  |  |  |  |  |
| MAX_SHOT（引数 --max-shot） | 480 | frames | 94 | frames: 6 to 16 seconds |  |  |  |  |  |  |  |  |
| MIN_SHOT（引数 --min-shot） | 180 | frames | 94 | frames: 6 to 16 seconds |  |  |  |  |  |  |  |  |
| LEVEL_SHARE | 0.6 |  | 95 | of a shot's frames in high (low) sections to call it a peak (valley) |  |  |  |  |  |  |  |  |
| SHOT_VALUES.push_in.distance | (38.0, 32.0) |  | 103 |  |  |  |  |  |  |  |  |  |
| SHOT_VALUES.push_in.height | 13.0 |  | 103 |  | リンに合わせた注視点の高さ（頭の上 19.5、リボン 20.8 の注釈。adapt 10-17 の測りで髪の上 19.197・リボン 20.55）。カメラの仕事は加賀さんの指示で後回し |  |  |  |  |  |  | rig |
| SHOT_VALUES.push_in.x | 0.0 |  | 103 |  |  |  |  |  |  |  |  |  |
| SHOT_VALUES.push_in.y | (0.0, 0.0) |  | 103 |  |  |  |  |  |  |  |  |  |
| SHOT_VALUES.pull_out.distance | (32.0, 42.0) |  | 104 |  |  |  |  |  |  |  |  |  |
| SHOT_VALUES.pull_out.height | 13.0 |  | 104 |  |  |  |  |  |  |  |  |  |
| SHOT_VALUES.pull_out.x | 0.0 |  | 104 |  |  |  |  |  |  |  |  |  |
| SHOT_VALUES.pull_out.y | (0.0, 0.0) |  | 104 |  |  |  |  |  |  |  |  |  |
| SHOT_VALUES.orbit.distance | (34.0, 34.0) |  | 105 |  |  |  |  |  |  |  |  |  |
| SHOT_VALUES.orbit.height | 12.0 |  | 105 |  | リンに合わせた注視点の高さ（カメラの仕事は後回し） |  |  |  |  |  |  | rig |
| SHOT_VALUES.orbit.x | 0.0 |  | 105 |  |  |  |  |  |  |  |  |  |
| SHOT_VALUES.orbit.y | (-15.0, 15.0) |  | 105 |  |  |  |  |  |  |  |  |  |
| SHOT_VALUES.above.distance | (38.0, 36.0) |  | 106 |  |  |  |  |  |  |  |  |  |
| SHOT_VALUES.above.height | 12.0 |  | 106 |  |  |  |  |  |  |  |  |  |
| SHOT_VALUES.above.x | 10.0 |  | 106 |  |  |  |  |  |  |  |  |  |
| SHOT_VALUES.above.y | (0.0, 0.0) |  | 106 |  |  |  |  |  |  |  |  |  |
| PEAK_DISTANCE_ADD | 6.0 |  | 108 |  |  |  |  |  |  |  |  |  |
| PEAK_ORBIT_SWING | 22.0 |  | 109 |  |  |  |  |  |  |  |  |  |
| TYPE_WEIGHTS.valley.above | 1 |  | 111 |  |  |  |  |  |  |  |  |  |
| TYPE_WEIGHTS.valley.orbit | 1 |  | 111 |  |  |  |  |  |  |  |  |  |
| TYPE_WEIGHTS.valley.pull_out | 1 |  | 111 |  |  |  |  |  |  |  |  |  |
| TYPE_WEIGHTS.valley.push_in | 3 |  | 111 |  |  |  |  |  |  |  |  |  |
| TYPE_WEIGHTS.peak.above | 1 |  | 112 |  |  |  |  |  |  |  |  |  |
| TYPE_WEIGHTS.peak.orbit | 2 |  | 112 |  |  |  |  |  |  |  |  |  |
| TYPE_WEIGHTS.peak.pull_out | 2 |  | 112 |  |  |  |  |  |  |  |  |  |
| TYPE_WEIGHTS.peak.push_in | 1 |  | 112 |  |  |  |  |  |  |  |  |  |
| TYPE_WEIGHTS.mid.above | 1 |  | 113 |  |  |  |  |  |  |  |  |  |
| TYPE_WEIGHTS.mid.orbit | 1 |  | 113 |  |  |  |  |  |  |  |  |  |
| TYPE_WEIGHTS.mid.pull_out | 1 |  | 113 |  |  |  |  |  |  |  |  |  |
| TYPE_WEIGHTS.mid.push_in | 1 |  | 113 |  |  |  |  |  |  |  |  |  |
| CLEAR_CUT.angle | 10.0 |  | 117 | a cut must change the picture clearly, or it reads as a dropped frame: at least one of these between the end of a shot and the start of the next |  |  |  |  |  |  |  |  |
| CLEAR_CUT.distance | 8.0 |  | 117 | a cut must change the picture clearly, or it reads as a dropped frame: at least one of these between the end of a shot and the start of the next |  |  |  |  |  |  |  |  |
| CLEAR_CUT.height | 3.0 |  | 117 | a cut must change the picture clearly, or it reads as a dropped frame: at least one of these between the end of a shot and the start of the next |  |  |  |  |  |  |  |  |
| DISTANCE_RANGE | (24.0, 48.0) |  | 118 |  |  |  |  |  |  |  |  |  |
| HEIGHT_RANGE | (7.0, 14.0) |  | 119 |  |  |  |  |  |  |  |  |  |
| ANGLE_X_RANGE | (-10.0, 10.0) |  | 120 |  |  |  |  |  |  |  |  |  |
| ANGLE_Y_RANGE | (-25.0, 25.0) |  | 121 |  |  |  |  |  |  |  |  |  |
| FOV | 30 |  | 122 |  |  |  |  |  |  |  |  |  |
| S_CURVE | (64, 0, 64, 127) |  | 123 | ease in and out over a whole shot, on distance, angles and fov |  |  |  |  |  |  |  |  |
| CUT_CURVE | (127, 0, 127, 0) |  | 124 | on the first key of a shot: the step, so nothing is drawn between two shots |  |  |  |  |  |  |  |  |
| LOOK_AT_STEP | 90 | frames | 125 | frames: at most this far between two keys of a shot (the look-at point follows) |  |  |  |  |  |  |  |  |
| LOOK_AT_WINDOW | 90 | frames | 126 | frames: the look-at point is the center averaged over this window |  |  |  |  |  |  |  |  |
| HANDHELD.angle | 0.3 | units | 130 | --handheld: a person holding the camera sways it a little. Amplitudes at strength 1 (window units: degrees, model units); the sway of each channel is a sum of slow sines… |  | ○ |  |  |  | ○ |  | retarget |
| HANDHELD.distance | 0.1 | units | 130 | --handheld: a person holding the camera sways it a little. Amplitudes at strength 1 (window units: degrees, model units); the sway of each channel is a sum of slow sines… |  | ○ |  |  |  | ○ |  | retarget |
| HANDHELD.look_at | 0.03 | units | 130 | --handheld: a person holding the camera sways it a little. Amplitudes at strength 1 (window units: degrees, model units); the sway of each channel is a sum of slow sines… |  | ○ |  |  |  | ○ |  | retarget |
| SWAY_HZ | (0.13, 0.31, 0.57) | Hz | 131 |  |  |  |  |  |  |  |  |  |
| SWAY_WEIGHTS | (0.5, 0.3, 0.2) |  | 132 |  |  |  |  |  |  |  |  |  |
| ROTATION_WEIGHTS | ( ("指", 0.5), ("目", 0.2), ("捩", 1.0), ("ＩＫ", 1.0), ("IK", 1… |  | 138 | (part of the bone name, weight): the first match wins; see the module docstring for the reasoning |  |  |  |  |  |  |  |  |
| DEFAULT_ROTATION_WEIGHT | 1.0 |  | 143 |  |  |  |  |  |  |  |  |  |
| POSITION_WEIGHTS | (("センター", 1.0), ("グルーブ", 1.0), ("全ての親", 1.0), ("ＩＫ", 0.5), … |  | 144 |  |  |  |  |  |  |  |  |  |
| DEFAULT_POSITION_WEIGHT | 0.5 |  | 145 |  |  |  |  |  |  |  |  |  |
| plan_shots(seed) | 0 |  | 524 |  |  |  |  |  |  |  |  |  |
| sway(seed) | 0 |  | 649 |  |  |  |  |  |  |  |  |  |
| camera_motion(handheld) | 0.0 |  | 696 |  |  |  |  |  |  |  |  |  |
| camera_motion(seed) | 0 |  | 696 |  |  |  |  |  |  |  |  |  |
| run(seed) | 0 |  | 766 |  |  |  |  |  |  |  |  |  |
| run(handheld) | 0.0 |  | 767 |  |  |  |  |  |  |  |  |  |
| --seed | 0 |  | 800 | the draw of the shot kinds (default 0) |  |  |  |  |  |  |  |  |
| --handheld | 0.0 |  | 804 | a slow handheld sway: 0 none (default), 1 about 0.3 degrees, keys on every frame |  |  |  |  |  |  |  |  |

## 確かめの道具と部品（物差しの決め）

### rig_check.py（確かめ・部品、37）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UNIT_CM | 8.0 | cm | 97 | Sour's Rin: one unit is 8 cm |  | ○ |  |  | ○ |  |  | retarget・rig |
| MOVE_DEG | 0.01 | deg | 100 | a key turned less than this from rest does not move |  |  |  |  |  |  |  |  |
| MOVE_UNITS | 1e-4 |  | 101 | nor one slid less than this |  |  |  |  |  |  |  |  |
| MORPH_W | 1e-4 |  | 102 | a morph key below this weight does nothing |  |  |  |  | ○ |  |  | rig |
| KNEE_JUMP_DEG | 10.0 | deg | 103 |  |  |  |  |  |  |  |  |  |
| ANKLE_JUMP_DEG | 10.0 | deg | 104 | the ankle's bend and the foot's pitch jump as the knee's: a frame this far off the line through its neighbours (degrees) |  |  |  |  |  |  |  |  |
| DEPTH | 0.02 | units | 106 | units (1.6 mm): a vertex this far inside another part is pushed into it |  | ○ |  |  |  |  |  | retarget |
| GAP | 15 | frames | 107 | frames between two picked frames of one yardstick |  |  |  |  |  |  |  |  |
| section_profile(bins) | 20 |  | 125 |  |  |  |  |  |  |  |  |  |
| section_profile(hi) | 1.0 |  | 125 |  |  |  |  |  |  |  |  |  |
| section_profile(lo) | 0.0 |  | 125 |  |  |  |  |  |  |  |  |  |
| section_profile(min_radius) | 0.02 |  | 125 |  |  |  |  |  |  |  |  |  |
| signed_distance(chunk) | 2048 |  | 209 |  |  |  |  |  |  |  |  |  |
| signed_distance(k) | 8 |  | 209 |  |  |  |  |  |  |  |  |  |
| pick_frames(per) | 5 |  | 263 |  |  |  |  |  |  |  |  |  |
| dance_angles(first) | 0 |  | 508 |  |  |  |  |  |  |  |  |  |
| gap(samples) | 21 |  | 624 |  |  |  |  |  |  |  |  |  |
| physics_report(gravities) | (94.0, 122.5) |  | 652 |  |  |  | ○ |  |  |  |  | retarget |
| pmx_diff(limit) | 2000 |  | 806 |  |  |  |  |  |  |  |  |  |
| skin_delta(limit) | 400 |  | 996 |  |  |  |  |  |  |  |  |  |
| skin_delta(tol) | 1e-4 |  | 996 |  |  |  |  |  |  |  |  |  |
| LIMBS.upper_arm | ("腕", "ひじ", ("腕W", "腕", "腕補助", "腕捩", "腕捩1", "腕捩2", "腕捩3"), … |  | 1051 |  |  |  |  |  |  |  |  |  |
| LIMBS.forearm | ("ひじ", "手首", ("ひじ", "ひじ補助", "ひじ補助+", "手捩", "手捩1", "手捩2", "手… |  | 1052 |  |  |  |  |  |  |  |  |  |
| LIMBS.thigh | ("足", "ひざ", ("足D", "足", "足補助"), (0.15, 0.9)) |  | 1053 |  |  |  |  |  |  |  |  |  |
| LIMBS.shin | ("ひざ", "足首", ("ひざD", "ひざ"), (0.1, 0.9)) |  | 1054 |  |  |  |  |  |  |  |  |  |
| JOINTS.shoulder | ("腕", 0.75, ("肩", "腕W", "腕", "腕補助", "腕捩", "腕捩1", "腕捩2", "腕捩… |  | 1057 |  |  |  |  |  |  |  |  |  |
| JOINTS.elbow | ("ひじ", 0.6, ("腕捩", "腕捩1", "腕捩2", "腕捩3", "腕W", "ひじ", "ひじ補助",… |  | 1058 |  |  |  |  |  |  |  |  |  |
| JOINTS.wrist | ("手首", 0.45, ("手捩", "手捩1", "手捩2", "手捩3", "手首", "手首補助")) |  | 1059 |  |  |  |  |  |  |  |  |  |
| JOINTS.hip | ("足", 1.1, ("足D", "足", "足補助")) |  | 1060 |  |  |  |  |  |  |  |  |  |
| JOINTS.knee | ("ひざ", 0.8, ("足D", "ひざD", "足", "ひざ")) |  | 1061 |  |  |  |  |  |  |  |  |  |
| JOINTS.ankle | ("足首", 0.6, ("ひざD", "足首D", "足先EX", "ひざ", "足首")) |  | 1062 |  |  |  |  |  |  |  |  |  |
| vertices(at_least) | 0.9 |  | 1092 |  |  |  |  |  |  |  |  |  |
| vertices(physics_max) | 0.05 |  | 1092 |  |  |  |  |  |  |  |  |  |
| --pick | 4 |  | 1324 |  |  |  |  |  |  |  |  |  |
| --figures | 0 |  | 1326 |  |  |  |  |  |  |  |  |  |
| --gravity | [94.0, 122.5] |  | 1330 |  |  |  | ○ |  |  |  |  | retarget |
| --pick | 4 |  | 1341 |  |  |  |  |  |  |  |  |  |

### spine_check.py（確かめ・部品、1）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| --frames | 4 | frames | 156 |  |  |  |  |  |  |  |  |  |

### skirt_probe.py（確かめ・部品、20）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SIZE（引数 --size） | 0.07 | units | 57 | a marker's half width (model units; 0.56 cm) |  | ○ |  |  |  |  |  | retarget |
| LEVELS | (30, 75, 120, 165, 210, 255) |  | 58 |  |  |  |  |  |  |  |  |  |
| MIN_SUM | 150 |  | 59 | no colour darker than this (sum of the channels) |  |  |  |  |  |  |  |  |
| TOL | 12 |  | 60 | a pixel's channels within TOL of a level count as that level |  |  |  |  |  |  |  |  |
| CAMERA.distance | 700.0 |  | 61 |  |  |  |  |  |  |  |  |  |
| CAMERA.fov | 1.0 |  | 61 |  |  |  |  |  |  |  |  |  |
| CAMERA.pitch | 0.0 |  | 61 |  |  |  |  |  |  |  |  |  |
| CAMERA.size | [1920, 1080] |  | 61 |  |  |  |  |  |  |  |  |  |
| CAMERA.yaw | 90.0 |  | 61 |  |  |  |  |  |  |  |  |  |
| HEIGHT_OVER_HIPS | -1.2 |  | 62 | --around: the camera looks at 下半身 + this (the skirt's middle) |  |  |  |  |  |  |  |  |
| write_camera(last_frame) | 7742 |  | 207 |  |  |  |  |  |  |  |  |  |
| track(first) | 0 |  | 281 |  |  |  |  |  |  |  |  |  |
| track(fps) | 60 |  | 281 |  |  |  |  |  |  |  |  |  |
| occluded(share) | 0.4 |  | 312 |  |  |  |  |  |  |  |  |  |
| MAX_GAP（引数 --max-gap） | 0.1 |  | 354 |  |  |  |  |  |  |  |  |  |
| LENGTH_TOL | 0.15 |  | 355 | a body's two ends must lie its rest length apart within this share (the joints do not stretch) |  |  |  |  |  |  |  |  |
| CAPSULES | (("左", "leg", "左足D", "左ひざD", 0.987), ("右", "leg", "右足D", "右… |  | 356 |  |  |  |  |  |  |  |  |  |
| --last-frame | 7742 |  | 592 |  |  |  |  |  |  |  |  |  |
| --first | 0.0 |  | 598 | the song frame of the AVI's first picture |  |  |  | ○ |  |  |  | dance |
| --fps | 60.0 |  | 599 |  |  |  |  |  |  |  |  |  |

### motion_fk.py（確かめ・部品、0）

（数を持つ定数・引数の既定なし）

### retarget_check.py（確かめ・部品、26）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UNIT_CM | 8.0 | cm | 82 |  |  | ○ |  |  |  |  |  | retarget |
| TOUCH | 0.15 | units | 83 | units (1.2 cm): a source hand point this close to a part touches it |  | ○ |  |  |  |  |  | retarget |
| KEEP | 0.125 | units | 84 | units (1 cm): the target's point within this of the source's distance keeps the touch |  | ○ |  |  |  |  |  | retarget |
| LOST | 0.25 | units | 85 | units (2 cm): more than this off (or inside) loses it |  | ○ |  |  |  |  |  | retarget |
| PLANT_EPS | 0.05 | units | 86 | units (4 mm, a05's contact): a goal this close to its rest height is on the floor |  | ○ |  |  |  |  |  | retarget |
| STILL | 0.025 | units | 87 | units a frame |  | ○ |  |  |  |  |  | retarget |
| PLANT_MIN | 3 |  | 88 |  |  |  |  |  |  |  |  |  |
| TOE_PITCH | 4.0 |  | 89 |  |  |  |  |  |  |  |  |  |
| FPS | 30.0 |  | 90 |  |  |  |  |  |  |  |  |  |
| FLOOR_CM | 0.4 | cm | 91 | cm (a05's 4 mm): a shoe whose lowest point is this close to the floor is on it |  | ○ |  |  |  |  |  | retarget |
| POP_NEAR_CM | 2.0 | cm | 97 | a one-frame jump along the floor the source does not make (review_integ 2026-10-17, its scripts/pops.py: the retarget gave a turning foot's hold back in one frame, the s… | v11feet 2026-10-17: review_integ の pops.py と同じ 2 cm | ○ |  | ○ |  |  |  | retarget |
| POP_CM | 8.0 | cm | 98 |  | v11feet 2026-10-17: review_integ の pops.py と同じ 8 cm | ○ |  |  |  |  |  | retarget |
| POP_SHARE | 0.5 |  | 99 |  | v11feet 2026-10-17: review_integ の pops.py と同じ（元の動きがその半分未満なら元に無い跳び） |  |  |  |  |  |  |  |
| RESTING_MIN | 4 | frames | 100 | frames: a touch this long ... |  |  |  |  |  |  |  |  |
| RESTING_SPEED | 35.0 | cm/s | 101 | cm/s: ... whose hand point moves slower than this in the part's frame (median) rests on it |  | ○ |  |  |  |  |  | retarget |
| LAG_WINDOW | 60 | frames | 102 | frames (2 s): the timing's windows, LAG_HOP apart, lags within LAG_MAX |  |  |  |  |  |  |  |  |
| LAG_HOP | 30 |  | 103 |  |  |  |  |  |  |  |  |  |
| LAG_MAX | 5 |  | 104 |  |  |  |  |  |  |  |  |  |
| STEP_MIN_CM | 10.0 | cm | 105 | cm: the source's steps between plants this long and longer are compared |  | ○ |  |  |  |  |  | retarget |
| JUMP_CM | 2.5 | cm | 106 | cm (mv_inspect's 宙): both feet this high over their rest heights ... |  | ○ |  |  |  |  |  | retarget |
| JUMP_MIN | 4 | frames | 107 | frames: ... this long is a jump |  |  |  |  |  |  |  |  |
| SKIP_SHOULDER | 0.5 |  | 109 |  |  |  |  |  |  |  |  |  |
| runs(min_len) | 1 |  | 133 |  |  |  |  |  |  |  |  |  |
| quant(qs) | (50, 90, 99, 100) |  | 139 |  |  |  |  |  |  |  |  |  |
| _cube_directions(n) | 4 |  | 171 |  |  |  |  |  |  |  |  |  |
| LINE_TS | np.array([-0.3, 0.0, 1 / 6, 2 / 6, 3 / 6, 4 / 6, 5 / 6, 1.0… |  | 379 |  |  |  |  |  |  |  |  |  |

### motion_jerk.py（確かめ・部品、0）

（数を持つ定数・引数の既定なし）

### sink_check.py（確かめ・部品、16）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FPS | 30.0 |  | 59 |  |  |  |  |  |  |  |  |  |
| UNIT_CM | 8.0 | cm | 60 | one unit of Sour's Rin is 8 cm |  | ○ |  |  | ○ |  |  | retarget・rig |
| BOUND（引数 --bound） | 122.0 | units/s^2 | 62 | units/s^2: the pelvis's downward acceleration where a foot holds the body up (the balance layer's DOWN_ACC_MAX: the real g at 8 cm a unit, 122.5) | 体重の層の DOWN_ACC_MAX 122（HANDOVER 2026-10-16） | ○ | ○ |  |  |  |  | retarget |
| BOUND_TOL | 0.5 |  | 64 | past the bound by more than this (as the balance layer's report counts) |  |  |  |  |  |  |  |  |
| AIR_MIN | 4 | frames | 65 | frames: neither shoe supporting this long is the air (the balance layer's AIR_MIN) |  |  |  |  |  |  |  |  |
| SUPPORT_CM | 1.6 | cm | 66 | a shoe this low supports (the balance layer's SUPPORT_H, a05's FLY) |  | ○ |  |  |  |  |  | retarget |
| CONTACT_CM | 0.5 | cm | 67 | a shoe this low is on the floor (for the slides) |  | ○ |  |  |  |  |  | retarget |
| UNDER_CM | 0.1 | cm | 68 | a shoe lower than the floor by more than this is under it |  | ○ |  |  |  |  |  | retarget |
| TOUCH_CM | 0.2 | cm | 69 | the shoe's vertices this close to its lowest are the ones touching |  | ○ |  |  |  |  |  | retarget |
| NOTHING_CM | 0.4 | cm | 70 | a05 s11: neither shoe within this ... |  | ○ |  |  |  |  |  | retarget |
| HOVER_CM | 4.0 | cm | 71 | ... and the lower one under this: nothing holds the body |  | ○ |  |  |  |  |  | retarget |
| FOOT_SHARE | 0.5 |  | 72 | a vertex this much on the foot's bones belongs to the shoe |  |  |  |  |  |  |  |  |
| CHUNK | 256 | frames | 73 | frames skinned at a time |  |  |  |  |  |  |  |  |
| _r(n) | 2 |  | 233 |  |  |  |  |  |  |  |  |  |
| compare(first) | 0 |  | 267 |  |  |  |  |  |  |  |  |  |
| --first | 0 |  | 356 |  |  |  |  |  |  |  |  |  |

### leg_ik.py（確かめ・部品、2）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EPS_DEG | 1.0e-3 | deg | 42 | saba: a CCD step smaller than this (degrees) is skipped |  |  |  |  |  |  |  |  |
| GAIN | 1.0e-7 | units | 43 | units: a loop that brings the target closer by less ends the solve. saba (and MMD) stop at the first loop that does not bring it closer; MMD's float32 cannot tell a gain… |  | ○ |  |  |  |  |  | retarget |

### contact_check.py（確かめ・部品、20）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FPS | 30.0 |  | 61 |  |  |  |  |  |  |  |  |  |
| UNIT_CM | 8.0 | cm | 62 |  |  | ○ |  |  |  |  |  | retarget |
| G | 122.5 | units/s^2 | 63 | units/s^2 at 8 cm a unit |  | ○ | ○ |  |  |  |  | retarget |
| CONTACT_CM | 0.4 | cm | 66 | a05's contact (4 mm) |  | ○ |  |  |  |  |  | retarget |
| SUPPORT_CM | 1.2 | cm | 67 | the human baseline's planted foot and tools/wb_dynamics.py's contact |  | ○ |  |  |  | ○ |  | retarget |
| SUPPORT_FALL_CM | 1.6 | cm | 68 | the balance layer's support (the frames whose pelvis is bound) |  | ○ |  |  |  |  |  | retarget |
| HOVER_CM | 4.0 | cm | 69 | a05 s11's band |  | ○ |  |  |  |  |  | retarget |
| HELD_LOW_CM | 0.4 | cm | 70 |  |  | ○ |  |  |  |  |  | retarget |
| HELD_STEP_CM | 0.05 | cm | 71 | a05 s11 (1): still |  | ○ |  |  |  |  |  | retarget |
| HELD_MIN | 9 | frames | 72 | frames (0.3 s) |  |  |  |  |  |  |  |  |
| TOUCH_CM | 0.2 | cm | 73 | the shoe's vertices this near its lowest touch (sink_check's) |  | ○ |  |  |  |  |  | retarget |
| AIR_MIN | 4 |  | 74 |  |  |  |  |  |  |  |  |  |
| BOUND | 122.0 |  | 75 |  |  |  |  |  |  |  |  |  |
| BOUND_TOL | 0.5 |  | 76 |  |  |  |  |  |  |  |  |  |
| FAST_STAND | 30.0 | cm/s | 77 | cm/s |  | ○ |  |  |  |  |  | retarget |
| runs(n) | 1 |  | 80 |  |  |  |  |  |  |  |  |  |
| _r(n) | 3 |  | 84 |  |  |  |  |  |  |  |  |  |
| _q(qs) | (50, 90) |  | 88 |  |  |  |  |  |  |  |  |  |
| check(first) | 0 |  | 315 |  |  |  |  |  |  |  |  |  |
| --first | 0 |  | 346 |  |  |  |  |  |  |  |  |  |

### upper_body_check.py（確かめ・部品、17）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FPS | 30.0 |  | 69 |  |  |  |  |  |  |  |  |  |
| UNIT_M | 0.08 | m | 70 | metres a model unit (the analysis pack) |  | ○ |  |  |  |  |  | retarget |
| STOP_VFAST | 0.6 | m/s | 74 | m/s: a08's head (s1_events.VFAST["頭"]) |  | ○ |  |  |  |  |  | retarget |
| STOP_WIN | 8 |  | 75 | steps before the minimum (a08 WIN) |  |  |  |  |  |  |  |  |
| STOP_DEEP | 0.4 |  | 76 | the minimum at most this share of the peak (a08 DEEP) |  |  |  |  |  |  |  |  |
| BAND | (1.5, 6.0) | Hz | 77 | Hz: the quick part for the lag |  |  |  |  |  |  |  |  |
| MAX_LAG | 10 | frames | 78 | frames |  |  |  |  |  |  |  |  |
| HOP | 15 | frames | 79 | frames: the local follow's windows |  |  |  |  |  |  |  |  |
| WIN | 60 | frames | 79 | frames: the local follow's windows |  |  |  |  |  |  |  |  |
| FACE_NEAR_CM | 10.0 | cm | 80 |  |  | ○ |  |  |  |  |  | retarget |
| WAIST_NEAR_CM | 11.0 | cm | 81 | a fingertip this near the line from the hips' middle to 下半身 (tools/hand_layer.py's waist) |  | ○ |  |  |  |  |  | retarget |
| BEAT_BINS | 8 |  | 82 |  |  |  |  |  |  |  |  |  |
| BEAT_TOL | 2 | frames | 83 | frames |  |  |  |  |  |  |  |  |
| dance_range(thr_mm_s) | 50.0 | mm/s | 132 |  |  | ○ |  |  |  |  |  | retarget |
| dance_range(trim) | 15 |  | 132 |  |  |  |  |  |  |  |  |  |
| band_share(nw) | 64 |  | 232 |  |  |  |  |  |  |  |  |  |
| local_follow(cutoff_hz) | 6.0 | Hz | 314 |  |  |  |  |  |  |  |  |  |

### lip_check.py（確かめ・部品、46）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FPS | 30.0 |  | 85 |  |  |  |  |  |  |  |  |  |
| SHOWN | 0.1875 | frames | 86 | frames: the MV shows frame f at f + 0.1875 (tools/mv_look.py) |  |  |  |  |  |  |  |  |
| SR | 16000 |  | 87 |  |  |  |  |  |  |  |  |  |
| HOP | 160 | ms | 88 | 10 ms |  |  |  |  |  |  |  |  |
| WIN | 512 | ms | 90 | 32 ms |  |  |  |  |  |  |  |  |
| BAND | (300.0, 3500.0) |  | 91 |  |  |  |  |  |  |  |  |  |
| SOUND_DB | -30.0 |  | 92 | the voice sounds above this (dB re the 99th percentile) |  |  |  |  |  |  |  |  |
| PEAK_SPACING | 0.05 | s | 93 | s: a flux peak is the largest within this on each side |  |  |  |  |  |  |  |  |
| FLUX_FLOOR | 1.0 |  | 94 | a flux peak is above this times the median flux where the voice sounds |  |  |  |  |  |  |  |  |
| RISE_DB | 6.0 |  | 95 |  |  |  |  |  |  |  |  |  |
| PRE | 0.04 | s | 96 | s before a flux peak where the level is lowest ... |  |  |  |  |  |  |  |  |
| POST | 0.03 | s | 97 | s ... and after it where it is highest |  |  |  |  |  |  |  |  |
| FULL | (0.25, 6.0) |  | 98 | the level after an onset is within 6 dB of the loudest of the 0.25 s after it (not the hum of m or the hiss of s before the vowel) |  |  |  |  |  |  |  |  |
| AREA（引数 --area） | (1.0, 0.02, 0.28, 0.63, 0.68) |  | 101 | the open area of あ い う え お on Sour's Rin (stage 6 lipsync, shape_area.json) |  |  |  |  | ○ |  |  | rig |
| MOVE | 0.15 |  | 102 | a rise of the opening is at least this |  |  |  |  |  |  |  |  |
| MATCH | 0.20 | s | 103 | s: an onset and a rise further apart are not paired |  |  |  |  |  |  |  |  |
| LATE | 0.045 | s | 104 | s: the mouth this much after the sound is noticed (ITU-R BT.1359-1) |  |  |  |  |  |  |  |  |
| EARLY | 0.125 | s | 105 | s: the mouth this much before the sound is noticed |  |  |  |  |  |  |  |  |
| TRIGGER | 0.40 | s | 106 | s each side of the onsets for the triggered average |  |  |  |  |  |  |  |  |
| XCORR_LAG | 0.30 | s | 107 | s |  |  |  |  |  |  |  |  |
| NEAR_SINGING | 0.5 | s | 108 | s: the cross-correlation is taken within this of a row where the voice sounds |  |  |  |  |  |  |  |  |
| CHANCE_SHIFT | 0.10 | s | 109 | s: the aligned starts moved this much both ways give the chance agreement |  |  |  |  |  |  |  |  |
| INSIDE | (0.08, 0.05) | s | 110 | s: a voice onset this far after an aligned vowel's start and before its end is inside it |  |  |  |  |  |  |  |  |
| ONSET_VOWEL | (0.03, 0.13) | s | 111 | s after an onset over which its vowel is heard (OPEN, as for the aligned vowels) |  |  |  |  |  |  |  |  |
| LOUD_DB | -20.0 |  | 112 | the voice clearly sings above this ... |  |  |  |  |  |  |  |  |
| QUIET_DB | -40.0 |  | 113 | ... and is silent below this |  |  |  |  |  |  |  |  |
| SHUT | 0.1 |  | 114 | the mouth looks shut below this opening ... |  |  |  |  |  |  |  |  |
| OPEN | 0.35 |  | 115 | ... and open above this |  |  |  |  |  |  |  |  |
| SILENCE_RUN | 0.15 | s | 116 | s: a silence counts from this long |  |  |  |  |  |  |  |  |
| OPEN_BANDS | ((300.0, 700.0), (700.0, 1500.0)) |  | 117 | OPEN = the level of the second over the first |  |  |  |  |  |  |  |  |
| FRONT_BANDS | ((700.0, 1500.0), (1800.0, 3500.0)) |  | 118 | FRONT = the level of the second over the first |  |  |  |  |  |  |  |  |
| SHIFT_GAIN | 0.2 |  | 120 | a line fits better shifted by one mora when the share agreeing grows by this |  |  |  |  |  |  |  |  |
| SHIFT_MIN | 6 |  | 121 | vowels a line needs for the shift test |  |  |  |  |  |  |  |  |
| _runs(shortest) | 1 |  | 349 |  |  |  |  |  |  |  |  |  |
| jumps(over) | 0.4 |  | 388 |  |  |  |  |  |  |  |  |  |
| _draw_span(lab) | 22 |  | 615 |  |  |  |  |  |  |  |  |  |
| _draw_span(mh) | 90 |  | 615 |  |  |  |  |  |  |  |  |  |
| _draw_span(sh) | 200 |  | 615 |  |  |  |  |  |  |  |  |  |
| draw_sheet(cols) | 2 |  | 672 |  |  |  |  |  |  |  |  |  |
| draw_sheet(rows_per_page) | 4 |  | 672 |  |  |  |  |  |  |  |  |  |
| draw_sheet(span) | 0.4 |  | 672 |  |  |  |  |  |  |  |  |  |
| draw_view(px_per_second) | 500 |  | 699 |  |  |  |  |  |  |  |  |  |
| run(sample) | 40 |  | 710 |  |  |  |  |  |  |  |  |  |
| run(seed) | 1 |  | 710 |  |  |  |  |  |  |  |  |  |
| --sample | 40 |  | 792 | syllables on the sheet (default %(default)s) |  |  |  |  |  |  |  |  |
| --seed | 1 |  | 793 | the draw of the sheet (default %(default)s) |  |  |  |  |  |  |  |  |

### shadow_check.py（確かめ・部品、29）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| LUMA | np.array([0.2126, 0.7152, 0.0722]) |  | 42 | BT.709, on the 8-bit values as they are |  |  |  |  |  |  |  |  |
| RAY_LENGTH | 1.0e4 | units | 43 | MMD units: a ray is a segment this long (the stage is some 100 across) |  | ○ |  |  |  |  |  | retarget |
| CHUNK | 1 << 18 |  | 44 | rays tested at a time |  |  |  |  |  |  |  |  |
| gaussian_directions(side) | 64 |  | 92 |  |  |  |  |  |  |  |  |  |
| light_through(side) | 64 |  | 113 |  |  |  |  |  |  |  |  |  |
| floor_points(floor_y) | 0.0 |  | 141 |  |  |  |  |  |  |  |  |  |
| ratio_map(min_plain) | 4.0 |  | 162 |  |  |  |  |  |  |  |  |  |
| edge_width(hi) | 0.9 |  | 169 |  |  |  |  |  |  |  |  |  |
| edge_width(lo) | 0.1 |  | 169 |  |  |  |  |  |  |  |  |  |
| ground_shadow(alpha_min) | 0.04 |  | 202 |  |  |  |  |  |  |  |  |  |
| ground_shadow(grow) | 0 |  | 202 |  |  |  |  |  |  |  |  |  |
| ground_shadow(her_alpha) | 0.02 |  | 202 |  |  |  |  |  |  |  |  |  |
| roughness(axis) | 0 |  | 224 |  |  |  |  |  |  |  |  |  |
| _r(n) | 4 |  | 243 |  |  |  |  |  |  |  |  |  |
| --blur | 5.0 |  | 371 |  |  |  |  |  |  |  |  |  |
| --light | [-0.5, -1.0, 0.5] |  | 372 |  |  |  |  |  |  |  |  |  |
| --floor-y | 0.0 |  | 373 |  |  |  |  |  |  |  |  |  |
| --side | 48 |  | 374 | directions: side x side |  |  |  |  |  |  |  |  |
| --step | 0.16 | units | 375 | floor points this far apart at least (MMD units) |  | ○ |  |  |  |  |  | retarget |
| --max-points | 6000 |  | 376 |  |  |  |  |  |  |  |  |  |
| --floor-y | 0.0 |  | 383 |  |  |  |  |  |  |  |  |  |
| --min-plain | 4.0 |  | 384 |  |  |  |  |  |  |  |  |  |
| --alpha-min | 0.04 |  | 388 |  |  |  |  |  |  |  |  |  |
| --her-alpha | 0.02 |  | 389 |  |  |  |  |  |  |  |  |  |
| --grow | 2 |  | 390 |  |  |  |  |  |  |  |  |  |
| --level | 0.5 |  | 391 |  |  |  |  |  |  |  |  |  |
| --min-plain | 4.0 |  | 392 |  |  |  |  |  |  |  |  |  |
| --reach | 0.95 | px | 399 | pixels whose ratio falls below this at some frame |  |  |  |  |  |  |  |  |
| --min-plain | 4.0 |  | 400 |  |  |  |  |  |  |  |  |  |

### shadow_measure.py（確かめ・部品、3）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HALF | (0.4, 0.6) |  | 35 |  |  |  |  |  |  |  |  |  |
| FULL | 0.05 |  | 36 |  |  |  |  |  |  |  |  |  |
| LUMA | np.array([0.2126, 0.7152, 0.0722]) |  | 116 |  |  |  |  |  |  |  |  |  |

### selfshadow_check.py（確かめ・部品、54）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| LIGHT | (-0.5, -1.0, 0.5) |  | 66 | MMD's default light: where it shines to |  |  |  |  |  |  |  |  |
| LUMA | np.array([0.2126, 0.7152, 0.0722]) |  | 67 |  |  |  |  |  |  |  |  |  |
| FAN_ANGLES | (0.0, 20.0, 40.0, 50.0, 60.0, 65.0, 70.0, 75.0) |  | 68 |  |  |  |  |  |  |  |  |  |
| PLATE_HALF | 1.4 |  | 69 |  |  |  |  |  |  |  |  |  |
| PLATE_STEP | 3.5 |  | 70 |  |  |  |  |  |  |  |  |  |
| PLATE_HEIGHT | 3.0 |  | 71 |  |  |  |  |  |  |  |  |  |
| RAMP_FROM | -8.0 |  | 72 | the wall's foot along the row (u), from where it touches the floor to its top |  |  |  |  |  |  |  |  |
| RAMP_TO | 6.0 |  | 72 | the wall's foot along the row (u), from where it touches the floor to its top |  |  |  |  |  |  |  |  |
| FLOOR_U | (-12.0, 10.0) |  | 73 |  |  |  |  |  |  |  |  |  |
| FLOOR_W | (-3.0, 12.0) |  | 73 |  |  |  |  |  |  |  |  |  |
| FACING | math.degrees(math.atan2(math.hypot(LIGHT[0], LIGHT[2]), -LI… |  | 102 | the tilt that turns the floor to the light |  |  |  |  |  |  |  |  |
| floor_point(tilt) | 0.0 |  | 114 |  |  |  |  |  |  |  |  |  |
| ramp_model(tilt) | 0.0 |  | 184 |  |  |  |  |  |  |  |  |  |
| _camera_for(down) | 50.0 |  | 205 |  |  |  |  |  |  |  |  |  |
| _camera_for(fov) | 30.0 |  | 205 |  |  |  |  |  |  |  |  |  |
| _camera_for(yaw) | -135.0 |  | 205 |  |  |  |  |  |  |  |  |  |
| probe(height) | 10.0 |  | 229 |  |  |  |  |  |  |  |  |  |
| probe(size) | (1920, 1080) |  | 229 |  |  |  |  |  |  |  |  |  |
| contact(blur) | 5.0 |  | 320 |  |  |  |  |  |  |  |  |  |
| contact(min_blur) | 0.05 |  | 320 |  |  |  |  |  |  |  |  |  |
| contact(step) | 0.5 |  | 320 |  |  |  |  |  |  |  |  |  |
| fan(margin) | 0.25 |  | 421 |  |  |  |  |  |  |  |  |  |
| acne(far) | 60 |  | 508 |  |  |  |  |  |  |  |  |  |
| acne_of(far) | 60 |  | 512 |  |  |  |  |  |  |  |  |  |
| shade_ratio(min_lit) | 20.0 |  | 560 |  |  |  |  |  |  |  |  |  |
| seen_of(shutter) | 0.5 |  | 610 |  |  |  |  |  |  |  |  |  |
| seen_of(sub) | 16 |  | 610 |  |  |  |  |  |  |  |  |  |
| seen(shutter) | 0.5 |  | 633 |  |  |  |  |  |  |  |  |  |
| seen(sub) | 16 |  | 633 |  |  |  |  |  |  |  |  |  |
| GOLDEN | math.pi * (3.0 - math.sqrt(5.0)) |  | 640 |  |  |  |  |  |  |  |  |  |
| light_jitter(blur) | 5.0 |  | 643 |  |  |  |  |  |  |  |  |  |
| _ripples(least) | 0.04 |  | 715 |  |  |  |  |  |  |  |  |  |
| against(gap) | 0.25 |  | 745 |  |  |  |  |  |  |  |  |  |
| against(tile) | 24 |  | 745 |  |  |  |  |  |  |  |  |  |
| against(top) | 8 |  | 745 |  |  |  |  |  |  |  |  |  |
| toggles_of(jump) | 0.25 |  | 858 |  |  |  |  |  |  |  |  |  |
| toggles_of(shutter) | 0.5 |  | 858 |  |  |  |  |  |  |  |  |  |
| toggles_of(sub) | 16 |  | 858 |  |  |  |  |  |  |  |  |  |
| toggles_of(tile) | 24 |  | 858 |  |  |  |  |  |  |  |  |  |
| toggles_of(top) | 8 |  | 858 |  |  |  |  |  |  |  |  |  |
| --height | 10.0 |  | 892 |  |  |  |  |  |  |  |  |  |
| --size | "1920x1080" |  | 893 |  |  |  |  |  |  |  |  |  |
| --part | "ramp" |  | 897 | the ramp on the level floor, or the one whose floor faces the light (ramp_tilt) |  |  |  |  |  |  |  |  |
| --blur | 5.0 |  | 899 |  |  |  |  |  |  |  |  |  |
| --min-blur | 0.05 |  | 900 |  |  |  |  |  |  |  |  |  |
| --far | 60 |  | 907 |  |  |  |  |  |  |  |  |  |
| --sub | 16 |  | 912 |  |  |  |  |  |  |  |  |  |
| --shutter | 0.5 |  | 913 |  |  |  |  |  |  |  |  |  |
| --blur | 5.0 |  | 917 |  |  |  |  |  |  |  |  |  |
| --tile | 24 |  | 926 |  |  |  |  |  |  |  |  |  |
| --top | 8 |  | 927 |  |  |  |  |  |  |  |  |  |
| --jump | 0.25 |  | 930 |  |  |  |  |  |  |  |  |  |
| --sub | 16 |  | 931 |  |  |  |  |  |  |  |  |  |
| --shutter | 0.5 |  | 932 |  |  |  |  |  |  |  |  |  |

### look_analyze.py（確かめ・部品、163）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| REFERENCE_HEIGHT | 720.0 |  | 57 | every length is in pixels of a picture this tall (the height of our MV) |  |  |  |  |  |  |  |  |
| CLIP_WHITE | 253.0 / 255.0 |  | 139 | a channel this high is clipped white |  |  |  |  |  |  |  |  |
| CLIP_BLACK | 2.0 / 255.0 |  | 140 | all channels this low are crushed black |  |  |  |  |  |  |  |  |
| LOCAL_SIGMA | 10.0 |  | 141 | the fine contrast: L* against itself blurred by this (720 line pixels) |  |  |  |  |  |  |  |  |
| tone(unit) | 1.0 |  | 144 |  |  |  |  |  |  |  |  |  |
| SPLIT_BANDS.high | (65.0, 95.0) |  | 167 | the bands of L* for split toning, and the direction of orange in a*b* (teal is its opposite) |  |  |  |  |  |  |  |  |
| SPLIT_BANDS.mid | (35.0, 65.0) |  | 167 | the bands of L* for split toning, and the direction of orange in a*b* (teal is its opposite) |  |  |  |  |  |  |  |  |
| SPLIT_BANDS.shadow | (8.0, 35.0) |  | 167 | the bands of L* for split toning, and the direction of orange in a*b* (teal is its opposite) |  |  |  |  |  |  |  |  |
| ORANGE | (math.cos(math.radians(55.0)), math.sin(math.radians(55.0))) |  | 168 |  |  |  |  |  |  |  |  |  |
| WHITE_CHROMA | 30.0 |  | 207 | a near-white pixel: this bright and at most this coloured, and not clipped |  |  |  |  |  |  |  |  |
| WHITE_L | 80.0 |  | 207 | a near-white pixel: this bright and at most this coloured, and not clipped |  |  |  |  |  |  |  |  |
| BAR_LEVEL | 0.06 |  | 235 | a bar's rows (or columns) stay under this Y' (15 of 255) in every frame |  |  |  |  |  |  |  |  |
| FLASH_RISE | 0.10 |  | 292 | Y' above the running median (of FLASH_WINDOW s each side) by this much is a flash |  |  |  |  |  |  |  |  |
| FLASH_WINDOW | 0.5 |  | 293 |  |  |  |  |  |  |  |  |  |
| FLASH_LONGEST | 0.6 | s | 294 | s: longer is a change of light, not a flash |  |  |  |  |  |  |  |  |
| FLASH_BACK | 0.5 |  | 295 | after it the level comes back within this share of its rise (a step does not) |  |  |  |  |  |  |  |  |
| CUT_LEAST | 0.06 |  | 336 | mean ／difference／ of the thumbnails (Y') a cut changes at least, and |  |  |  |  |  |  |  |  |
| CUT_OVER | 5.0 |  | 337 | this many times the frame-to-frame change around it |  |  |  |  |  |  |  |  |
| BLOOM_SOURCE | 0.9 |  | 401 | Y': the light sources whose glow is read |  |  |  |  |  |  |  |  |
| BLOOM_REACH | 96.0 |  | 402 | 720 line pixels: the glow is read this far out from them, and |  |  |  |  |  |  |  |  |
| BLOOM_BACK | (96.0, 160.0) |  | 403 | the level it falls to (the background) between these distances |  |  |  |  |  |  |  |  |
| BLOOM_AT | 4.0 |  | 404 | bloom.strength: the share of the sources' light found this far out (720 px) |  |  |  |  |  |  |  |  |
| BLOOM_NEAR | (2.0, 8.0) |  | 405 | the glow's colour is read between these distances |  |  |  |  |  |  |  |  |
| bloom(unit) | 1.0 |  | 419 |  |  |  |  |  |  |  |  |  |
| STREAK_RING | (6.0, 40.0) |  | 503 | 720 line pixels round a small highlight where its rays are read, |  |  |  |  |  |  |  |  |
| STREAK_BACK | (40.0, 60.0) |  | 504 | against the level of this ring |  |  |  |  |  |  |  |  |
| STREAK_BINS | 36 |  | 505 |  |  |  |  |  |  |  |  |  |
| STREAK_HARMONICS | (2, 4, 6, 8) |  | 506 |  |  |  |  |  |  |  |  |  |
| streaks(unit) | 1.0 |  | 509 |  |  |  |  |  |  |  |  |  |
| BEAM_LINES | 180 | frames | 593 | the frame is read this many lines tall (averaging whole pixels) |  |  |  |  |  |  |  |  |
| BEAM_BG | 18.0 | px | 594 | px at BEAM_LINES: the light round a part is the frame blurred by this |  |  |  |  |  |  |  |  |
| BEAM_LEAST | 0.01 |  | 595 | linear luminance: a part rises at least this above the light round it, |  |  |  |  |  |  |  |  |
| BEAM_SHARE | 0.2 |  | 596 | and at least this share of the frame's highest rise (its 99.9th percentile) |  |  |  |  |  |  |  |  |
| BEAM_ELONG | 3.0 |  | 597 | a beam: this many times longer than wide (second moments), |  |  |  |  |  |  |  |  |
| BEAM_LENGTH | 0.25 |  | 598 | at least this long (share of the frame's height), |  |  |  |  |  |  |  |  |
| BEAM_WIDTH | 0.02 |  | 599 | and at least this wide at half its rise (a painted line or a bar is thinner) |  |  |  |  |  |  |  |  |
| SPOT_ELONG | 3.0 |  | 600 | a spot: rounder than this (a pool on the floor seen at a slant is 2 to 3 times wider |  |  |  |  |  |  |  |  |
| SPOT_AREA | 0.003 |  | 602 | covering at least this share of the frame, |  |  |  |  |  |  |  |  |
| SPOT_WIDTH | 0.04 |  | 603 | and at least this wide at half its rise |  |  |  |  |  |  |  |  |
| SOFT_PLATEAU | 0.45 |  | 604 | beams and spots are soft: under this share of a part rises to 3/4 of its highest (a |  |  |  |  |  |  |  |  |
| COLOUR_BINS | 36 |  | 607 | hue bins of the bright, coloured pixels (10 degrees) |  |  |  |  |  |  |  |  |
| COLOUR_LEAST | 0.10 |  | 608 | a colour of the light holds at least this share of their chroma |  |  |  |  |  |  |  |  |
| STROBE_GAP | 0.35 | s | 609 | s between the starts of flashes of one strobe at most, and |  |  |  |  |  |  |  |  |
| STROBE_LEAST | 3 |  | 610 | this many flashes at least |  |  |  |  |  |  |  |  |
| FLICKER_WINDOW | 0.25 | s | 611 | s: the flicker is the mean Y' less its mean over this |  |  |  |  |  |  |  |  |
| PALETTE_LEAST | 0.05 |  | 612 | a colour of the key light holds at least this share of the coloured frames |  |  |  |  |  |  |  |  |
| CHANGE_HUE | 40.0 | deg | 613 | degrees between shots' key light: a change of colour |  |  |  |  |  |  |  |  |
| KEY_COLOURED | 15.0 |  | 614 | C*: the key light is coloured above this |  |  |  |  |  |  |  |  |
| beams(unit) | 1.0 |  | 617 |  |  |  |  |  |  |  |  |  |
| flat_mask(grow) | 2 |  | 802 |  |  |  |  |  |  |  |  |  |
| flat_mask(sigma) | 2.0 |  | 802 |  |  |  |  |  |  |  |  |  |
| grain(unit) | 1.0 |  | 826 |  |  |  |  |  |  |  |  |  |
| GLITCH_SHIFT | 6 | px | 878 | pixels: a torn row is moved at least this much against the row above |  |  |  |  |  |  |  |  |
| GLITCH_SEARCH | 32 |  | 879 |  |  |  |  |  |  |  |  |  |
| EDGE_POINTS | 4000 |  | 906 | edges read per frame at most (a random choice, the same for the same frame) |  |  |  |  |  |  |  |  |
| EDGE_LEAST | 0.03 |  | 907 | an edge's gradient (Y' per pixel, Sobel) at least this |  |  |  |  |  |  |  |  |
| SOBEL_VAR | 0.5 |  | 908 | px^2: the Sobel gradient and the pixel grid widen a step by this (measured on synthetic steps blurred by 0 to 8 px: est^2 - true^2 = 0.51 to 0.70) |  |  |  |  |  |  |  |  |
| REBLUR | (1.0, 3.0, 8.0) | px | 910 | px: the re-blurs; an edge is read with the narrowest whose reading stays under |  |  |  |  |  |  |  |  |
| SWITCH | (2.5, 6.0, float("inf")) |  | 911 | its switch (a narrow re-blur hardly lowers a soft edge's gradient) |  |  |  |  |  |  |  |  |
| edges(seed) | 0 |  | 920 |  |  |  |  |  |  |  |  |  |
| edges(unit) | 1.0 |  | 920 |  |  |  |  |  |  |  |  |  |
| SOFT_EDGE | 3.0 |  | 966 | 720 line pixels: an edge blurred more than this is soft (out of focus) |  |  |  |  |  |  |  |  |
| DOF_BLOCK | 40.0 |  | 982 | 720 line pixels: depth of field is read in blocks this wide, |  |  |  |  |  |  |  |  |
| DOF_CONTRAST | 0.10 |  | 983 | those whose Y' spreads at least this (5 to 95 %: they hold detail), |  |  |  |  |  |  |  |  |
| DOF_TOP | 0.02 |  | 984 | each by the blur of its steepest 2 % of pixels |  |  |  |  |  |  |  |  |
| DOF_PRE | 0.0 |  | 987 | image px: blur the frame by this first (and take it out after); 0 none |  |  |  |  |  |  |  |  |
| DOF_LINES | 180 |  | 988 | depth of field is read on the frame made this small (averaging whole pixels): the noise and the coding blocks of a compressed video, which read sharp, average out, while… |  |  |  |  |  |  |  |  |
| _blur_blocks(unit) | 1.0 |  | 1013 |  |  |  |  |  |  |  |  |  |
| dof_blocks(unit) | 1.0 |  | 1048 |  |  |  |  |  |  |  |  |  |
| SHORT | (8.0, 16.0) |  | 1077 | 720 line pixels: the near sides of an edge (sharpening, width) and |  |  |  |  |  |  |  |  |
| LONG | (28.0, 40.0) |  | 1078 | the far sides (diffusion), where a step's flat sides are read |  |  |  |  |  |  |  |  |
| STEP_LEAST | 0.12 |  | 1079 | Y': a step read for its profile rises at least this, |  |  |  |  |  |  |  |  |
| FLAT_MOST | 0.04 |  | 1080 | and each side's spread stays under this |  |  |  |  |  |  |  |  |
| INNER | 4.0 |  | 1081 | diffusion: the share of the step not reached within this of the edge (720 px) |  |  |  |  |  |  |  |  |
| DIFFUSION_TOP | 0.65 |  | 1082 | Y': diffusion is read on steps whose bright side is at most this (a glow of the |  |  |  |  |  |  |  |  |
| BRIGHT_EDGE | 0.85 |  | 1083 | bright parts does not reach them); the glow's own skirt on steps from this up |  |  |  |  |  |  |  |  |
| CORE_MOST | 3.0 |  | 1084 | diffusion is read on edges whose core is at most this blurred (720 px) |  |  |  |  |  |  |  |  |
| PROFILE_POINTS | 1500 |  | 1085 |  |  |  |  |  |  |  |  |  |
| edge_profiles(seed) | 0 |  | 1136 |  |  |  |  |  |  |  |  |  |
| edge_profiles(unit) | 1.0 |  | 1136 |  |  |  |  |  |  |  |  |  |
| MOVING_LEAST | 3.0 |  | 1216 | 720 line pixels a frame: an edge moving across itself at least this is read for |  |  |  |  |  |  |  |  |
| STILL_MOST | 0.5 |  | 1217 | motion blur, against edges moving less than this; a pixel moving at least |  |  |  |  |  |  |  |  |
| MOVING_PIXEL | 1.0 |  | 1218 | this counts as moving |  |  |  |  |  |  |  |  |
| MOTION_LEAST | 0.008 |  | 1219 | Y' per pixel: the weakest moving edge read for motion blur (a 0.3 step blurred over 30 px still shows) |  |  |  |  |  |  |  |  |
| motion(seed) | 0 |  | 1279 |  |  |  |  |  |  |  |  |  |
| motion(unit) | 1.0 |  | 1279 |  |  |  |  |  |  |  |  |  |
| CA_SCALES | np.linspace(-0.012, 0.012, 25) |  | 1330 | the radial scales of red and blue against green searched |  |  |  |  |  |  |  |  |
| aberration(unit) | 1.0 |  | 1333 |  |  |  |  |  |  |  |  |  |
| LINE_LEAST | 0.2 |  | 1373 | distortion: segments at least this long (of the picture's height), and at least |  |  |  |  |  |  |  |  |
| LINE_OFF_CENTRE | 0.2 |  | 1374 | this far from the centre (of the half diagonal), are read for their bend |  |  |  |  |  |  |  |  |
| K1_SEARCH | np.linspace(-0.4, 0.4, 161) |  | 1377 |  |  |  |  |  |  |  |  |  |
| distortion(unit) | 1.0 |  | 1411 |  |  |  |  |  |  |  |  |  |
| measure_frame(seed) | 0 |  | 1605 |  |  |  |  |  |  |  |  |  |
| measure_frame(unit) | 1.0 |  | 1605 |  |  |  |  |  |  |  |  |  |
| PERSON_INNER | 3.0 |  | 1663 | 720 line px: the person is read this far inside its outline (the edge mixes with |  |  |  |  |  | ○ |  |  |
| STAGE_GAP | 12.0 |  | 1664 | the stage), the stage this far outside it (the person's glow, the mask's error) |  |  |  |  |  | ○ |  |  |
| REGION_LEAST | 0.005 |  | 1665 | a region under this share of the frame is not read |  |  |  |  |  |  |  |  |
| RIM_EDGE | (3.0, 6.0) |  | 1666 | 720 line px inside the outline: the edge's light, past an outline of 1 to 2 px, |  |  |  |  |  |  |  |  |
| RIM_CORE | (12.0, 20.0) |  | 1667 | against the light further in along the same normal |  |  |  |  |  |  |  |  |
| HALO_EDGE | (1.0, 4.0) |  | 1668 | 720 line px inside the outline: the person's own light at its edge, the source of |  |  |  |  |  | ○ |  |  |
| HALO_NEAR | (3.0, 8.0) |  | 1669 | the glow it throws on the stage just outside, |  |  |  |  |  |  |  |  |
| HALO_FAR | (24.0, 40.0) |  | 1670 | against the stage further out |  |  |  |  |  |  |  |  |
| HALO_LEAST | 0.05 |  | 1671 | linear luminance: the edge brighter than the far stage by at least this |  |  |  |  |  |  |  |  |
| OUTLINE_POINTS | 3000 |  | 1672 | outline points read per frame at most |  |  |  |  |  |  |  |  |
| EDGE_IN | (3.0, 6.0) |  | 1673 | 720 line px inside the outline: the person's colour at her edge (the rim's band) ... |  |  |  |  |  | ○ |  |  |
| EDGE_OUT | (12.0, 20.0) |  | 1674 | ... against the stage's just outside it, past her glow and the mask's error |  |  |  |  |  |  |  |  |
| MERGE_DE | 15.0 |  | 1675 | CIE76 dE*ab: an edge whose two sides differ by less does not stand out (stagecity) |  |  |  |  |  |  |  |  |
| SEG_SIZE | 1024 |  | 1676 | the person model's input (square, the frame letterboxed into it) |  |  |  |  |  | ○ |  |  |
| FACE_CHEEK | ((0.55, 0.85), (0.25, 0.75)) |  | 1677 | rows and columns of a face's box read for the light on her skin: the cheeks |  |  |  |  |  |  |  |  |
| FACE_LEAST | 20 | px | 1680 | pixels of the cheeks on the person at least, for a face to be read |  |  |  |  |  | ○ |  |  |
| _along(order) | 1 |  | 1763 |  |  |  |  |  |  |  |  |  |
| silhouette(seed) | 0 |  | 1770 |  |  |  |  |  |  |  |  |  |
| silhouette(unit) | 1.0 |  | 1770 |  |  |  |  |  |  |  |  |  |
| edge_contrast(seed) | 0 |  | 1824 |  |  |  |  |  |  |  |  |  |
| edge_contrast(unit) | 1.0 |  | 1824 |  |  |  |  |  |  |  |  |  |
| region_measures(seed) | 0 |  | 1852 |  |  |  |  |  |  |  |  |  |
| region_measures(unit) | 1.0 |  | 1852 |  |  |  |  |  |  |  |  |  |
| seg_session(threads) | 6 |  | 1917 |  |  |  |  |  |  |  |  |  |
| BOOTSTRAP | 400 |  | 1947 |  |  |  |  |  |  |  |  |  |
| _trimmed_rms(keep) | 0.9 |  | 1950 |  |  |  |  |  |  |  |  |  |
| summarise(seed) | 0 |  | 1958 |  |  |  |  |  |  |  |  |  |
| probe(fps) | 30 |  | 2092 |  |  |  |  |  |  |  |  |  |
| read_frames(start) | 0.0 |  | 2173 |  |  |  |  |  |  |  |  |  |
| THUMB | (64, 36) |  | 2198 | every frame at this size: the cuts, flashes, repeats and the corners' darkening |  |  |  |  |  |  |  |  |
| read_thumbs(start) | 0.0 |  | 2201 |  |  |  |  |  |  |  |  |  |
| measure_video(height) | 720 |  | 2261 |  |  |  |  |  |  |  |  |  |
| measure_video(jobs) | 1 |  | 2261 |  |  |  |  |  |  |  |  |  |
| measure_video(pairs) | 120 |  | 2261 |  |  |  |  |  |  |  |  |  |
| measure_video(fps) | 30 |  | 2262 |  |  |  |  |  |  |  |  |  |
| measure_video(full_every) | 4 |  | 2262 |  |  |  |  |  |  |  |  |  |
| measure_video(pair_every) | 4 |  | 2262 |  |  |  |  |  |  |  |  |  |
| measure_video(seed) | 0 |  | 2262 |  |  |  |  |  |  |  |  |  |
| layer_masks(start) | 0.0 |  | 2388 |  |  |  |  |  |  |  |  |  |
| measure_regions(frames) | 48 |  | 2426 |  |  |  |  |  |  |  |  |  |
| measure_regions(height) | 720 |  | 2426 |  |  |  |  |  |  |  |  |  |
| measure_regions(fps) | 30 |  | 2427 |  |  |  |  |  |  |  |  |  |
| measure_regions(seed) | 0 |  | 2427 |  |  |  |  |  |  |  |  |  |
| measure_regions(threads) | 6 |  | 2427 |  |  |  |  |  |  |  |  |  |
| TEXT_LEAST | 8.0 |  | 2493 | 720 line pixels: a box of text at least this tall is counted |  |  |  |  |  |  |  |  |
| text_summary(unit) | 1.0 |  | 2517 |  |  |  |  |  |  |  |  |  |
| measure_text(frames) | 24 |  | 2546 |  |  |  |  |  |  |  |  |  |
| contact_sheet(height) | 720 |  | 2687 |  |  |  |  |  |  |  |  |  |
| contact_sheet(size) | (320, 180) |  | 2687 |  |  |  |  |  |  |  |  |  |
| annotate(height) | 720 |  | 2717 |  |  |  |  |  |  |  |  |  |
| annotate(scale) | 1.0 |  | 2717 |  |  |  |  |  |  |  |  |  |
| --pairs | 120 |  | 2899 | pairs of frames to measure, spread over the video |  |  |  |  |  |  |  |  |
| --height | 720 |  | 2900 | the analysis height (lengths are given at 720 lines) |  |  |  |  |  |  |  |  |
| --matrix | "auto" |  | 2901 |  |  |  |  |  |  |  |  |  |
| --jobs | 1 |  | 2902 |  |  |  |  |  |  |  |  |  |
| --pair-every | 4 |  | 2903 | measure the second picture too every this many pairs (the noise floor) |  |  |  |  |  |  |  |  |
| --full-every | 4 |  | 2905 | the slower measures (fringes, distortion) every this many pairs |  |  |  |  |  |  |  |  |
| --fps | 30 |  | 2907 | the rate of a folder of frames |  |  |  |  |  |  |  |  |
| --frames | 48 | frames | 2919 | frames spread evenly over the video |  |  |  |  |  |  |  |  |
| --height | 720 |  | 2920 |  |  |  |  |  |  |  |  |  |
| --matrix | "auto" |  | 2921 |  |  |  |  |  |  |  |  |  |
| --threads | 6 |  | 2922 | CPU threads of the model |  |  |  |  | ○ |  |  | rig |
| --fps | 30 |  | 2923 | the rate of a folder of frames |  |  |  |  |  |  |  |  |
| --size | (320, 180) |  | 2942 |  |  |  |  |  |  |  |  |  |
| --matrix | "auto" |  | 2944 | our untagged mp4 are BT.601 (as made): auto reads them as BT.709, as players do |  |  |  |  |  |  |  |  |
| --frames | 24 | frames | 2949 |  |  |  |  |  |  |  |  |  |
| --what | "dof" |  | 2954 |  |  |  |  |  |  |  |  |  |
| --scale | 1.0 |  | 2956 |  |  |  |  |  |  |  |  |  |
| --matrix | "auto" |  | 2958 |  |  |  |  |  |  |  |  |  |

### typo_analyze.py（確かめ・部品、126）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TEXT_TH | 0.7 |  | 74 | a box's highest region score reaches this (EasyOCR's text_threshold) |  |  |  |  |  |  |  |  |
| LOW_TEXT | 0.4 |  | 75 | the region score above this is text (EasyOCR's low_text) |  |  |  |  |  |  |  |  |
| LINK_TH | 0.4 |  | 76 | the link score above this joins characters (EasyOCR's link_threshold) |  |  |  |  |  |  |  |  |
| LEAST_AREA | 10 |  | 77 | map px: smaller parts are noise (EasyOCR) |  |  |  |  |  |  |  |  |
| VERTICAL | 50.0 | deg | 78 | degrees: a box whose long side stands steeper than this is a column of text |  |  |  |  |  |  |  |  |
| PEAK_LEAST | 0.5 |  | 79 | a character is a peak of the region score at least this high |  |  |  |  |  |  |  |  |
| PEAK_WINDOW | 3 |  | 80 | map px: a peak is the highest in this square round it |  |  |  |  |  |  |  |  |
| HALF_MAX_DIAMETER | 0.754 |  | 81 | the width of a character's peak at half its height, as a share of the character's |  |  |  |  |  |  |  |  |
| text_boxes(ratio) | 2.0 |  | 102 |  |  |  |  |  |  |  |  |  |
| char_peaks(ratio) | 2.0 |  | 148 |  |  |  |  |  |  |  |  |  |
| CRAFT_MEAN | np.array([0.485, 0.456, 0.406], np.float32) * 255.0 |  | 190 |  |  |  |  |  |  |  |  |  |
| CRAFT_STD | np.array([0.229, 0.224, 0.225], np.float32) * 255.0 |  | 191 |  |  |  |  |  |  |  |  |  |
| __init__(threads) | 3 |  | 200 |  |  |  |  |  |  |  |  |  |
| detect_video(height) | 540 |  | 252 |  |  |  |  |  |  |  |  |  |
| detect_video(rate) | 2.0 |  | 252 |  |  |  |  |  |  |  |  |  |
| detect_video(threads) | 3 |  | 252 |  |  |  |  |  |  |  |  |  |
| LINK_OVERLAP | 0.3 |  | 331 | a box continues a track when it covers this share of the smaller of the two, |  |  |  |  |  |  |  |  |
| LINK_HEIGHT | 1.6 |  | 332 | their heights are within this ratio, |  |  |  |  |  |  |  |  |
| LINK_REACH | 3.0 |  | 333 | or, not overlapping, its centre is within this many heights of where the track goes |  |  |  |  |  |  |  |  |
| GAP_SAMPLES | 1 |  | 334 | a track may miss this many samples (a blink, a missed detection) |  |  |  |  |  |  |  |  |
| LINE_SHARE | 0.8 |  | 335 | two tracks together in this share of the samples of the shorter one, |  |  |  |  |  |  |  |  |
| LINE_GAP | 1.5 |  | 336 | this many heights apart at most along their line, |  |  |  |  |  |  |  |  |
| LINE_ALIGN | 0.35 |  | 337 | off their common line by this share of the height at most: one line (CRAFT parts a |  |  |  |  |  |  |  |  |
| MID_RATE | 10.0 | frames | 483 | frames a second read between the windows (the hold) |  |  |  |  |  |  |  |  |
| BAND | 1.25 |  | 484 | heights above and below a line (or beside a column) the band reaches |  |  |  |  |  |  |  |  |
| ALPHA_SEEN | 0.15 |  | 485 | a text is seen when its strokes stand out by this share of the reference's and its |  |  |  |  |  |  |  |  |
| SEEN_NCC | 0.35 |  | 486 | template matches there at least this, or they stand out by ALPHA_SURE alone. |  |  |  |  |  |  |  |  |
| ALPHA_SURE | 0.5 |  | 487 | typorev: on RE: 踊's street the strokes' place stood out by 0.26 to 0.37 with no line |  |  |  |  |  |  |  |  |
| ALPHA_FULL | 0.85 |  | 494 | ... and is whole from this share on |  |  |  |  |  |  |  |  |
| STILL | 0.03 |  | 495 | heights a frame: a text moving less than this is still |  |  |  |  |  |  |  |  |
| STILL_SCALE | 0.006 |  | 496 | and growing or shrinking less than this a frame |  |  |  |  |  |  |  |  |
| MOVE_LEAST | (3.0, 0.15) | px | 497 | px and heights: a text comes from at least the larger of these away to have moved |  |  |  |  |  |  |  |  |
| SCALE_LEAST | 1.15 |  | 498 | it comes at least this much larger or smaller to have zoomed |  |  |  |  |  |  |  |  |
| ROTATE_LEAST | 6.0 | deg | 499 | degrees turned to have rotated |  |  |  |  |  |  |  |  |
| STAGGER_LEAST | 3 | frames | 500 | frames (and half a frame a character) between the first and the last character to |  |  |  |  |  |  |  |  |
| STAGGER_ORDER | 0.7 |  | 502 | with the order along the line at least this (Spearman) |  |  |  |  |  |  |  |  |
| STAGGER_R2 | 0.6 |  | 503 | and a straight line through the characters' times fitting at least this well |  |  |  |  |  |  |  |  |
| BLUR_LEAST | 0.6 |  | 504 | edges this much softer than the reference's while the strokes stand out: a blur |  |  |  |  |  |  |  |  |
| SHARP_FULL | 0.8 |  | 505 | a text is whole only with its edges at least this sharp against the reference's |  |  |  |  |  |  |  |  |
| LONG_S | 20.0 | s | 508 | s: a track longer than this (a watermark, a logo) is read once a second between |  |  |  |  |  |  |  |  |
| TEMPLATE_PAD | 0.15 |  | 617 | heights round the reference's box in its template |  |  |  |  |  |  |  |  |
| PRESENT_NCC | 0.5 |  | 618 | the template matches a frame at least this (normalised correlation): the text is there |  |  |  |  |  |  |  |  |
| LOCAL_SCALES | (0.94, 1.0, 1.06) |  | 619 | sizes tried round the last frame's |  |  |  |  |  |  |  |  |
| GLOBAL_SCALES | (0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.12, 1.25, 1.4, 1.6, 1.8, 2… |  | 620 |  |  |  |  |  |  |  |  |  |
| GLOBAL_NCC | 0.75 |  | 621 | a match found anywhere in the band (not near the last place) must match this well: a |  |  |  |  |  |  |  |  |
| RELIABLE_NCC | 0.6 |  | 623 | where a text came from is read on the first frame matching at least this |  |  |  |  |  |  |  |  |
| SWAP_NCC | 0.5 |  | 624 | two samples of a track whose texts match less than this are two lines |  |  |  |  |  |  |  |  |
| BG_LEAST | 1.0 | px | 625 | px a frame: the picture behind a text moves at least this to tell scene from screen |  |  |  |  |  |  |  |  |
| WORLD_SHARE | 0.6 |  | 626 | a text that moves with the picture behind it in this share of those frames is in the |  |  |  |  |  |  |  |  |
| BG_GAP | 3 | frames | 628 | frames: the picture's step behind a text is read between frames read this close (the |  |  |  |  |  |  |  |  |
| BG_PART | 24 | px | 630 | px: a part of the band beside the text (left, right, above, below) this large in both |  |  |  |  |  |  |  |  |
| BG_SPAN | (6, 15) | frames | 633 | frames: the text's and the picture's steps are added up over spans this long (one |  |  |  |  |  |  |  |  |
| _ink_region(pad) | 0.15 |  | 637 |  |  |  |  |  |  |  |  |  |
| follow(last_ncc) | 1.0 |  | 732 |  |  |  |  |  |  |  |  |  |
| measure_track(origin) | (0, 0) |  | 813 |  |  |  |  |  |  |  |  |  |
| measure_track(start) | 0.0 |  | 813 |  |  |  |  |  |  |  |  |  |
| _grad(scale) | 1.0 |  | 1008 |  |  |  |  |  |  |  |  |  |
| GLITCH_SPLIT | 2.0 | px | 1016 | px between red and blue that change within a phase: a colour split |  |  |  |  |  |  |  |  |
| TEAR_SHIFT | 3 | px | 1017 | px: a row of the text moved sideways this much against the reference is torn |  |  |  |  |  |  |  |  |
| TEAR_SHARE | 0.15 |  | 1018 | a frame with this share of the text's rows torn (in bands of 3 rows or more) is torn |  |  |  |  |  |  |  |  |
| SPLIT_REACH | 8 | px | 1019 | px searched for the colour split |  |  |  |  |  |  |  |  |
| TEAR_REACH | 12 | px | 1020 | px searched for a torn row |  |  |  |  |  |  |  |  |
| TEAR_TEXT_ROW | 0.35 |  | 1021 | a row is read for a tear when its spread in the reference is at least this share of |  |  |  |  |  |  |  |  |
| STYLE_GROUND | (0.6, 1.2) |  | 1308 | heights out from the box: the ring whose colour is the ground |  |  |  |  |  |  |  |  |
| STYLE_PAD | 0.3 |  | 1309 | heights round the box where the strokes are looked for |  |  |  |  |  |  |  |  |
| DEEP | 3.0 | px | 1310 | px into the strokes: the fill |  |  |  |  |  |  |  |  |
| EDGE_BAND | (1.0, 2.5) | px | 1311 | px into the strokes: the edge band (an outline, a shadow's side) |  |  |  |  |  |  |  |  |
| OUTLINE_DE | 15.0 |  | 1312 | CIEDE76 between the edge band and the fill for another colour at the edge |  |  |  |  |  |  |  |  |
| SHADOW_ONE_WAY | 0.35 |  | 1313 | the edge pixels of that colour face one way at least this much (mean resultant |  |  |  |  |  |  |  |  |
| GLOW_AT | (2.0, 5.0) | px | 1315 | px out from the strokes where the glow is read, against the fill's rise |  |  |  |  |  |  |  |  |
| HOLLOW | 0.8 |  | 1316 | holes of the ground inside the strokes this many times the strokes' area: hollow |  |  |  |  |  |  |  |  |
| TYPE_HV | 0.62 |  | 1464 | horizontal strokes thinner than this share of the vertical ones: mincho. Measured |  |  |  |  |  |  |  |  |
| TYPE_PAD | 0.1 |  | 1550 | heights round the box where a text's letters are looked for: farther out lie a rule |  |  |  |  |  |  |  |  |
| TYPE_CONTRAST | 25.0 |  | 1552 | CIEDE76 between the letters' fill and the ground under which they are not read (a |  |  |  |  |  |  |  |  |
| TYPE_TAIL | 0.25 |  | 1554 | the cover under this (a glow) is none, over 1 - this is whole |  |  |  |  |  |  |  |  |
| FONT_CORE | 0.75 |  | 1555 | the cover the font match takes as the letters (drawn glyphs cut at a half) |  |  |  |  |  |  |  |  |
| LETTER_TALL | 1.15 |  | 1556 | a piece taller than this many box heights is not a letter (a figure behind the text, |  |  |  |  |  |  |  |  |
| LETTER_RULE | (2.5, 0.3) |  | 1558 | a piece wider than 2.5 box heights and lower than 0.3 of one is a rule, not a letter |  |  |  | ○ |  |  |  | dance |
| _glyph(size) | 160 |  | 1653 |  |  |  |  |  |  |  |  |  |
| font_match(size) | 160 |  | 1665 |  |  |  |  |  |  |  |  |  |
| iter_frames(start) | 0.0 |  | 1738 |  |  |  |  |  |  |  |  |  |
| track_video(threads) | 3 |  | 1787 |  |  |  |  |  |  |  |  |  |
| PHRASE_DB | -35.0 |  | 1965 | dB re the voice's 99th percentile: the voice sounds above this |  |  |  |  |  |  |  |  |
| PHRASE_GAP | 0.30 | s | 1966 | s: a quieter gap shorter than this stays inside the phrase |  |  |  |  |  |  |  |  |
| PHRASE_LEAST | 0.20 | s | 1967 | s: a shorter run is no phrase |  |  |  |  |  |  |  |  |
| PHRASE_ONSET | (0.05, 0.15) | s | 1968 | s before and after a run's start where its first onset is taken as its start |  |  |  |  |  |  |  |  |
| voice_events(sr) | 16000 |  | 1971 |  |  |  |  |  |  |  |  |  |
| read_sound(sr) | 16000 |  | 2035 |  |  |  |  |  |  |  |  |  |
| voice_file(offset) | 0.0 |  | 2044 |  |  |  |  |  |  |  |  |  |
| PAIR_REACH | 1.5 | s | 2063 | s: a text and a phrase start further apart than this are not paired |  |  |  |  |  |  |  |  |
| MARK_SHARE | 0.4 |  | 2064 | a text on the screen this share of the video or more is a mark (a logo, a watermark) |  |  |  |  |  |  |  |  |
| LYRIC_SOUNDS | 0.5 |  | 2065 | a screen text over which the voice sounds (VOICE_ON) this share of its time is a lyric |  |  |  |  |  |  |  |  |
| VOICE_ON | -30.0 |  | 2066 | dB re the voice's 99th percentile: the voice sounds |  |  |  |  |  |  |  |  |
| BEAT_REACH | 0.01 | s | 2067 | s added to a frame either side: an event this near a beat is on it |  |  |  | ○ |  |  |  | dance |
| LEAD_WINDOW | (-0.5, 1.0) | s | 2068 | s round a text's first frame where the voice's first strong onset is looked for |  |  |  |  |  |  |  |  |
| STRONG | 75.0 |  | 2069 | a strong onset: its flux at least this percentile of the song's onsets' |  |  |  | ○ |  |  |  | dance |
| TRIGGER | (-1.0, 1.5) | s | 2070 | s round the texts' first frames over which the voice is averaged |  |  |  |  |  |  |  |  |
| CHANCE_DRAWS | 200 |  | 2071 | the lyrics' first frames moved at random this many times: the chance of a lead, |  |  |  |  |  |  |  |  |
| CHANCE_SHIFT | (2.0, 8.0) | s | 2072 | each by a shift this long (s) either way, round within the voice's span (typorev: |  |  |  |  |  |  |  |  |
| _lead_chance(seed) | 0 |  | 2125 |  |  |  |  |  |  |  |  |  |
| MARK_PLACE | (0.03, 0.03, 0.25) |  | 2166 | texts within these of each other across, down and in size (shares) are one place |  |  |  |  |  |  |  |  |
| MARK_TIMES | 3 |  | 2167 | a text that comes back to one place this many times is a mark, |  |  |  |  |  |  |  |  |
| MARK_WIDTH | 0.03 |  | 2168 | if it is as wide each time (within this share) |  |  |  |  |  |  |  |  |
| SIZE_RANGE | (0.012, 0.35) |  | 2169 | a lyric's characters are this tall at least and at most (share of the picture) |  |  |  |  |  |  |  |  |
| SIG_H | 16 | px | 2172 | px: a text's signature is its box's picture this tall (as wide as its shape says, |  |  |  |  |  |  |  |  |
| SIG_W | 160 |  | 2173 | at most this) |  |  |  |  |  |  |  |  |
| MARK_SAME | 0.8 |  | 2174 | two signatures correlating at least this are the same text |  |  |  |  |  |  |  |  |
| SIGN_TIMES | 3 |  | 2234 | a text seen this many times or more, |  |  |  |  |  |  |  |  |
| SIGN_SIZES | 1.3 |  | 2235 | its largest this many times its smallest (the camera near and far): a sign of the scene |  |  |  |  |  |  |  |  |
| sync(fps) | 30.0 |  | 2262 |  |  |  |  |  |  |  |  |  |
| DISPLAY_H | 0.06 |  | 2400 | a line whose characters are this tall (share of the picture) or more is display type |  |  |  |  |  |  |  |  |
| _share_stats(seed) | 0 |  | 2403 |  |  |  |  |  |  |  |  |  |
| _one(n) | 1 |  | 2416 |  |  |  |  |  |  |  |  |  |
| CORE_SHOW | 0.3 | s | 2421 | s: a lyric line of the core is on the screen at least this long, |  |  |  |  |  |  |  |  |
| CORE_EDGE | 0.01 |  | 2422 | its box clear of the picture's edges by this share of the picture. (Standing still |  |  |  |  |  |  |  |  |
| typo_summary(seed) | 0 |  | 2447 |  |  |  |  |  |  |  |  |  |
| annotate(height) | 540 |  | 2650 |  |  |  |  |  |  |  |  |  |
| annotate(scale) | 1.0 |  | 2650 |  |  |  |  |  |  |  |  |  |
| --rate | 2.0 | frames | 2694 | frames sampled a second |  |  |  |  |  |  |  |  |
| --height | 540 |  | 2695 | lines the frames are read at |  |  |  |  |  |  |  |  |
| --threads | 3 |  | 2697 |  |  |  |  |  |  |  |  |  |
| --matrix | "auto" |  | 2698 |  |  |  |  |  |  |  |  |  |
| --threads | 3 |  | 2704 |  |  |  |  |  |  |  |  |  |
| --offset | 0.0 | s | 2719 | s added to every time |  |  |  |  |  |  |  |  |
| --height | 540 |  | 2752 |  |  |  |  |  |  |  |  |  |
| --scale | 1.0 |  | 2754 |  |  |  |  |  |  |  |  |  |

### mograph_analyze.py（確かめ・部品、54）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| REFERENCE_HEIGHT | 720.0 |  | 71 |  |  |  |  |  |  |  |  |  |
| FADE_BLACK | 0.06 |  | 72 | mean Y' under this: black |  |  |  |  |  |  |  |  |
| FADE_WHITE | 0.90 |  | 73 | over this: white |  |  |  |  |  |  |  |  |
| FADE_LEAST | 3 | frames | 74 | frames the picture takes going there at least |  |  |  |  |  |  |  |  |
| DISSOLVE_W | (2, 3, 5, 8) | frames | 75 | half widths (frames) tried for a dissolve |  |  |  |  |  |  |  |  |
| DISSOLVE_LEAST | 0.05 |  | 76 | mean ／Y' change／ between its ends at least this |  |  |  |  |  |  |  |  |
| DISSOLVE_MID | 0.25 |  | 77 | its middle frame within this share of that change of the mean of its ends, |  |  |  |  |  |  |  |  |
| DISSOLVE_ENDS | 0.6 |  | 78 | and its ends two pictures (correlation under this; a picture dimmed, or a line of |  |  |  |  |  |  |  |  |
| PUNCH_LEAST | 0.08 |  | 80 | log scale change within three frames for a zoom punch, and |  |  |  |  |  |  |  |  |
| PUNCH_OVER | 6.0 |  | 81 | this many times the scale's usual change round it (a second each side) |  |  |  |  |  |  |  |  |
| PUNCH_MERGE | 0.3 | s | 82 | s: punches closer than this are one |  |  |  |  |  |  |  |  |
| SHAKE_WINDOW | 0.2 | s | 83 | s: the shake is the shift less its running mean over this |  |  |  |  |  |  |  |  |
| GLITCH_SPLIT | 8.0 |  | 84 | 720 line px between red and blue across the picture: a glitch frame |  |  |  |  |  |  |  |  |
| SPLIT_REACH | 6 | px | 85 | px searched at the read size |  |  |  |  |  |  |  |  |
| COLOUR_RISE | 12.0 |  | 86 | C*ab over the running median: a colour flash |  |  |  |  |  |  |  |  |
| COLOUR_LONGEST | 0.6 | s | 87 | s |  |  |  |  |  |  |  |  |
| BEAT_REACH | 0.01 | s | 88 | s added to a frame either side: on the beat |  |  |  | ○ |  |  |  | dance |
| CAMERA_ROBUST | 4.685 |  | 89 | the camera's motion is fitted to the flow robustly (Tukey's biweight, 3 rounds): flow |  |  |  |  |  |  |  |  |
| CAMERA_NOISE | 0.05 | px | 93 | px at the read size: the least robust sigma (the flow's own noise) |  |  |  | ○ |  |  |  | dance |
| CUT_SAME | 0.95 |  | 94 | a change whose thumbnail correlates with the one before it at least this is the same |  |  |  |  |  |  |  |  |
| FLASH_SAME | 0.6 |  | 98 | a flash is a light on one shot (the thumbnails before and after it correlate at least |  |  |  |  |  |  |  |  |
| FLASH_WASH | 0.7 |  | 99 | this) or a white wash (its brightest thumbnail's contrast under this share of the |  |  |  |  |  |  |  |  |
| _similarity(border) | 4 |  | 124 |  |  |  |  |  |  |  |  |  |
| read_size(size) | (128, 72) |  | 164 |  |  |  |  |  |  |  |  |  |
| finish(start) | 0.0 |  | 238 |  |  |  |  |  |  |  |  |  |
| _events(start) | 0.0 |  | 287 |  |  |  |  |  |  |  |  |  |
| events_of(start) | 0.0 |  | 438 |  |  |  |  |  |  |  |  |  |
| events_video(size) | (128, 72) |  | 446 |  |  |  |  |  |  |  |  |  |
| PARTICLE_SIGMAS | (1.2, 1.8, 2.7, 4.0, 6.0, 9.0, 13.0) |  | 480 | 720 line px |  |  |  |  |  |  |  |  |
| PARTICLE_LEAST | 0.12 |  | 481 | Y' a particle stands above the ground round it (the ring 2.5 to 4 sigma out) |  |  |  |  |  |  |  |  |
| PARTICLE_LOG | 0.04 |  | 482 | its scale-normalised Laplacian at least this |  |  |  |  |  |  |  |  |
| BOKEH_SIGMA | 4.0 |  | 483 | 720 line px: a particle this wide or wider is bokeh (a defocused light) |  |  |  |  |  |  |  |  |
| PARTICLE_ROUND | 3.0 |  | 484 | the larger of a particle's two curvatures at most this many times the smaller |  |  |  |  |  |  |  |  |
| LINE_LEAST | 0.15 |  | 485 | of the frame's height: a long line |  |  |  |  |  |  |  |  |
| LINE_JOIN | (3.0, 6.0) | deg | 486 | degrees and 720 line px: segments this parallel and near are one line's two edges |  |  |  |  |  |  |  |  |
| AXIS | 3.0 | deg | 487 | degrees from level or upright: on the frame's axes |  |  |  |  |  |  |  |  |
| particles(unit) | 1.0 |  | 490 |  |  |  |  |  |  |  |  |  |
| lines(unit) | 1.0 |  | 543 |  |  |  |  |  |  |  |  |  |
| elements_video(frames) | 60 |  | 583 |  |  |  |  |  |  |  |  |  |
| elements_video(height) | 720 |  | 583 |  |  |  |  |  |  |  |  |  |
| FLASH_CD | 20.0 |  | 626 | cd/m2 between the darker and the brighter image |  |  |  |  |  |  |  |  |
| DARK_BELOW | 160.0 |  | 627 | cd/m2: the darker image below this |  |  |  |  |  |  |  |  |
| WHITE_CD | 200.0 |  | 628 | cd/m2 of peak white (SDR) |  |  |  |  |  |  |  |  |
| QUARTER | 0.25 |  | 629 | of the screen |  |  |  |  |  |  |  |  |
| MOST_CHANGES | 6 |  | 630 | in a second: more is more than three flashes |  |  |  |  |  |  |  |  |
| RED_SHARE | 0.8 |  | 631 |  |  |  |  |  |  |  |  |  |
| RED_SCALE | 320.0 |  | 632 |  |  |  |  |  |  |  |  |  |
| RED_CHANGE | 20.0 |  | 633 |  |  |  |  |  |  |  |  |  |
| SAFETY_GRID | (64, 36) |  | 634 | cells over the picture: what flashes is told by area |  |  |  |  |  |  |  |  |
| safety_video(size) | (256, 144) |  | 776 |  |  |  |  |  |  |  |  |  |
| --size | "128x72" |  | 851 |  |  |  |  |  |  |  |  |  |
| --frames | 60 | frames | 857 |  |  |  |  |  |  |  |  |  |
| --height | 720 |  | 858 |  |  |  |  |  |  |  |  |  |
| --size | "256x144" |  | 864 | "the size the video is read at, then put into %dx%d cells" % SAFETY_GRID |  |  |  |  |  |  |  |  |

### mv_inspect.py（確かめ・部品、3）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| --size | "hip" |  | 325 | the measures of lengths also measured with her body as large as people's: by the hip's height over the floor (hip, the default) or by the legs (legs); none: not (the mod… |  |  |  |  |  | ○ |  |  |
| --top | 40 |  | 330 |  |  |  |  |  |  |  |  |  |
| --reach | 0.95 |  | 358 | shadow: the pixels whose ratio falls under this at some frame |  |  |  |  |  |  |  |  |

### param_inventory.py（確かめ・部品、3）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FORMAT | 1 |  | 44 |  |  |  |  |  |  |  |  |  |
| ORDER | [ (1, "模型の写し（rig の受け持ち）", ["pmx_rig.py", "rig_skin.py", "pm… |  | 52 | ---- the rebuild's order --------------------------------------------------------------------------------------------- (step, title, tools, what the step makes, the meas… |  |  |  | ○ |  |  |  | dance |
| _cell(n) | 170 |  | 450 |  |  |  |  |  |  |  |  |  |

### mouth_shape.py（確かめ・部品、14）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| KEY_TEETH | (0, 255, 0) |  | 51 |  |  |  |  |  |  |  |  |  |
| KEY_INSIDE | (0, 255, 255) |  | 52 | cyan: the model's outlines are purple and its irises light blue (a magenta key took the hair's outline for the inside, 2026-10-17) |  |  |  |  | ○ |  |  | rig |
| TEETH_LIGHT | 200 |  | 54 | the teeth: every channel of the texture this light or more ... |  |  |  |  |  |  |  |  |
| TEETH_GREY | 40 |  | 55 | ... and the channels this close (the gums and the tongue are pink: 60 or more apart) | v11face 2026-10-17: リンの skin.png の歯の帯は (246, 220, 220) 前後、歯ぐき・舌は (240, 176, 178) 前後（色の差 60 以上） |  |  |  |  |  |  |  |
| KEY_MARGIN | 80 |  | 56 | a key pixel: its key channels this much above the others |  |  |  |  |  |  |  |  |
| WINDOW | (0.5, 0.7) |  | 57 | the share of the picture's height and width about its middle where the mouth is |  |  |  |  |  |  |  |  |
| MID_BAND | 5 |  | 58 | columns at the opening's middle for its height |  |  |  |  |  |  |  |  |
| CORNER_COLUMNS | 3 |  | 59 | columns at each end of the opening for its corners |  |  |  |  |  |  |  |  |
| SIZE（引数 --size） | 720 |  | 60 |  |  |  |  |  |  |  |  |  |
| DISTANCE（引数 --distance） | 3.5 |  | 61 |  |  |  |  |  |  |  |  |  |
| FOV（引数 --fov） | 20 |  | 62 |  |  |  |  |  |  |  |  |  |
| DEFAULT_COMBOS | [ ("neutral", {}), ("a", {"あ": 1.0}), ("i", {"い": 1.0}), ("… |  | 64 |  |  |  |  |  |  |  |  |  |
| _sheet(size) | 240 |  | 300 |  |  |  |  |  |  |  |  |  |
| --reference | "a" |  | 371 |  |  |  |  |  |  |  |  |  |

### dump_controls.py（確かめ・部品、0）

（数を持つ定数・引数の既定なし）

### live_in_session.py（確かめ・部品、0）

（数を持つ定数・引数の既定なし）

### run_live_tests_in_session.py（確かめ・部品、3）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| START_TIMEOUT | 15.0 |  | 22 |  |  |  |  |  |  |  |  |  |
| GRACE | 2.0 |  | 23 |  |  |  |  |  |  |  |  |  |
| --tail | 25 |  | 31 | lines of the log to print at the end |  |  |  |  |  |  |  |  |

### make_figures.py（確かめ・部品、4）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| COMMON_TOP | [ ("フレーム移動", "mmd frame get / set N / next / prev / next-ke… |  | 31 | (label, command, control ids): boxes are the bounding boxes of the controls |  |  |  |  |  |  |  |  |
| COMMON_RIGHT | [ ("視点", "mmd control click ID", [402, 403, 404, 405, 406, … |  | 40 |  |  |  |  |  |  |  |  |  |
| CAMERA_GROUPS | COMMON_TOP + [ ("モデルの一覧と読込", "mmd model load / list / selec… |  | 44 |  |  |  |  |  |  |  |  |  |
| MODEL_GROUPS | COMMON_TOP + [ ("モデル", "mmd model select / delete / show / … |  | 56 |  |  |  |  |  |  |  |  |  |

### mvi/a05.py（確かめ・部品、38）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FPS | 30 |  | 15 |  |  |  |  |  |  |  |  |  |
| CM | 8.0 |  | 16 |  | a05 の台本の 8 cm/単位（人の資料も 12.5 単位/m で置いた: human_baseline の hbpack） |  |  |  |  |  |  | retarget |
| EPS_MV | 0.05 | units | 18 | units (4 mm): s04's contact tolerance for the MV (the human baseline's HB_EPS) | human_baseline の HB_EPS: MV の接地の許し 4 mm（人は 1.2 cm。打ち込みの足は雑音が無い） | ○ |  |  |  | ○ |  | retarget |
| RIN_REST.下半身 | (-0.00014960770204197615, 12.224799156188965, -0.6493073105… |  | 22 |  |  |  |  |  |  |  |  |  |
| RIN_REST.左足 | (0.9012370705604553, 10.657918930053711, 0.0072974124923348… |  | 23 |  |  |  |  |  |  |  |  |  |
| RIN_REST.右足 | (-0.9012370705604553, 10.591029167175293, 0.007297412492334… |  | 24 |  |  |  |  |  |  |  |  |  |
| RIN_REST.左ひざ | (1.003201961517334, 6.231260299682617, -0.03613106906414032) |  | 25 |  |  |  |  |  |  |  |  |  |
| RIN_REST.右ひざ | (-1.003201961517334, 6.231260299682617, -0.0361310690641403… |  | 26 |  |  |  |  |  |  |  |  |  |
| RIN_REST.左足首 | (1.120466947555542, 1.7452340126037598, 0.3699590861797333) |  | 27 |  |  |  |  |  |  |  |  |  |
| RIN_REST.右足首 | (-1.120466947555542, 1.7452340126037598, 0.3699590861797333) |  | 28 |  |  |  |  |  |  |  |  |  |
| RIN_REST.左つま先 | (1.0462599992752075, 0.10000000149011612, -1.15003597736358… |  | 29 |  |  |  |  |  |  |  |  |  |
| RIN_REST.右つま先 | (-1.0462599992752075, 0.10000000149011612, -1.1500359773635… |  | 30 |  |  |  |  |  |  |  |  |  |
| runs(min_len) | 1 |  | 74 |  |  |  |  |  |  |  |  |  |
| R | 0.5 | units | 84 | units: half the width of a shoe sole (4 cm), an inference | a05 の推定（靴底の幅の半分 4 cm）。人の資料にも同じ値（human_baseline） | ○ |  |  |  |  |  | retarget |
| FLY | 0.2 | units | 85 | units: both feet at least this high = in the air (1.6 cm) |  | ○ |  |  |  |  |  | retarget |
| G | 9.81 |  | 86 |  |  |  | ○ |  |  |  |  | retarget |
| M_PER_UNIT | CM / 100.0 |  | 87 |  |  |  |  |  |  |  |  |  |
| SH.foot | .0145 |  | 88 |  |  |  |  |  |  |  |  |  |
| SH.fore | .016 |  | 88 |  |  |  |  |  |  |  |  |  |
| SH.hand | .006 |  | 88 |  |  |  |  |  |  |  |  |  |
| SH.head | .081 |  | 88 |  |  |  |  |  |  |  |  |  |
| SH.shank | .0465 |  | 88 |  |  |  |  |  |  |  |  |  |
| SH.thigh | .100 |  | 88 |  |  |  |  |  |  |  |  |  |
| SH.trunk | .497 |  | 88 |  |  |  |  |  |  |  |  |  |
| SH.upper | .028 |  | 88 |  |  |  |  |  |  |  |  |  |
| S_RANGE.ball | (0.6, 1.0) |  | 184 | ---- s04_contacts.py ------------------------------------------------------------------------------------------------ |  |  |  |  |  |  |  |  |
| S_RANGE.flat | (-0.3, 1.0) |  | 184 | ---- s04_contacts.py ------------------------------------------------------------------------------------------------ |  |  |  |  |  |  |  |  |
| S_RANGE.heel | (-0.3, 0.0) |  | 184 | ---- s04_contacts.py ------------------------------------------------------------------------------------------------ |  |  |  |  |  |  |  |  |
| GAP | 4 |  | 265 | ---- s06_touchdown.py ----------------------------------------------------------------------------------------------- |  |  |  |  |  |  |  |  |
| SWING_MIN_H | 0.2 |  | 266 |  |  |  |  |  |  |  |  |  |
| W | 20 |  | 267 |  |  |  |  |  |  |  |  |  |
| AIR | 0.2 |  | 268 |  |  |  |  |  |  |  |  |  |
| LIFT | 5.0 |  | 433 | ---- s14_hang.py (held phases) -------------------------------------------------------------------------------------- |  |  |  |  |  |  |  |  |
| R_CM | 4.0 | cm | 518 |  |  | ○ |  |  |  |  |  | retarget |
| GRID | [(5.0, 9)] |  | 519 |  |  |  |  |  |  |  |  |  |
| HAND_CM | 10.0 | cm | 520 |  |  | ○ |  |  |  |  |  | retarget |
| KNEE_CM | 15.0 | cm | 520 |  |  | ○ |  |  |  |  |  | retarget |
| p24(floor) | 0.0 |  | 523 |  |  |  |  |  |  |  |  |  |

### mvi/analysts.py（確かめ・部品、40）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UNIT_MM | 80.0 | mm | 20 | 1 MMD unit ~ 8 cm (pack README) |  | ○ |  |  |  |  |  | retarget |
| FPS | 30 |  | 21 |  |  |  |  |  |  |  |  |  |
| EXACT | 0.01 | mm/s | 22 | mm/s: below this a step is a numerically exact hold (float32 positions give ~0.003 mm/s) |  | ○ |  |  |  |  |  | retarget |
| MAIN | 1.0 | mm/s | 23 | mm/s: the main "stopped" threshold (see report: 1/6 of the stillest person's head speed) |  | ○ |  |  |  | ○ |  | retarget |
| PARTS.trunk | (["下半身", "上半身2", "首", "左肩", "右肩"], [("下半身", (0.9, -1.0, 0.0… |  | 26 |  |  |  |  |  |  |  |  |  |
| U2CM | 8.0 |  | 70 | 1 MMD unit ~ 8 cm (pack README) |  |  |  |  |  |  |  |  |
| FPS20 | 30.0 |  | 71 |  |  |  |  |  |  |  |  |  |
| runs20(min_len) | 1 |  | 106 |  |  |  |  |  |  |  |  |  |
| BINS | [0.0, 0.25, 0.5, 0.75, 0.9] |  | 115 | ==== a02_spacing/s13_dips.py ======================================================================================== |  |  |  |  |  |  |  |  |
| band(hi) | 6.0 |  | 140 |  |  |  |  |  |  |  |  |  |
| band(lo) | 3.0 |  | 140 |  |  |  |  |  |  |  |  |  |
| FPS08 | 30.0 |  | 153 | ==== a08_smooth: common.py, s1_events.py, s2_spectrum.py ============================================================ |  |  |  |  |  |  |  |  |
| UNIT_M | 0.08 | m | 154 | 1 MMD unit is about 8 cm (README) |  | ○ |  |  |  |  |  | retarget |
| VFAST.センター | 0.6 |  | 163 |  |  |  |  |  |  |  |  |  |
| VFAST.右中指３ | 1.5 |  | 163 |  |  |  |  |  |  |  |  |  |
| VFAST.右手首 | 1.5 |  | 163 |  |  |  |  |  |  |  |  |  |
| VFAST.右足ＩＫ | 1.0 |  | 163 |  |  |  |  |  |  |  |  |  |
| VFAST.左中指３ | 1.5 |  | 163 |  |  |  |  |  |  |  |  |  |
| VFAST.左手首 | 1.5 |  | 163 |  |  |  |  |  |  |  |  |  |
| VFAST.左足ＩＫ | 1.0 |  | 163 |  |  |  |  |  |  |  |  |  |
| VFAST.頭 | 0.6 |  | 163 |  |  |  |  |  |  |  |  |  |
| WIN | 8 |  | 164 |  |  |  |  |  |  |  |  |  |
| DEEP | 0.4 |  | 165 |  |  |  |  |  |  |  |  |  |
| T_SPIKE.センター | 0.15 |  | 232 |  |  |  |  |  |  |  |  |  |
| T_SPIKE.右中指３ | 0.6 |  | 232 |  |  |  |  |  |  |  |  |  |
| T_SPIKE.右手首 | 0.5 |  | 232 |  |  |  |  |  |  |  |  |  |
| T_SPIKE.右足ＩＫ | 0.4 |  | 232 |  |  |  |  |  |  |  |  |  |
| T_SPIKE.左中指３ | 0.6 |  | 232 |  |  |  |  |  |  |  |  |  |
| T_SPIKE.左手首 | 0.5 |  | 232 |  |  |  |  |  |  |  |  |  |
| T_SPIKE.左足ＩＫ | 0.4 |  | 232 |  |  |  |  |  |  |  |  |  |
| T_SPIKE.頭 | 0.15 |  | 232 |  |  |  |  |  |  |  |  |  |
| BANDS | [(0, 1), (1, 2), (2, 3), (3, 4), (4, 6), (6, 8), (8, 10), (… |  | 233 |  |  |  |  |  |  |  |  |  |
| NWIN | 128 |  | 234 |  |  |  |  |  |  |  |  |  |
| angular_speed(fps) | 30 |  | 313 |  |  |  |  |  |  |  |  |  |
| xcorr_lags(maxlag) | 6 |  | 339 |  |  |  |  |  |  |  |  |  |
| xcorr_lags(step) | 15 |  | 339 |  |  |  |  |  |  |  |  |  |
| xcorr_lags(win) | 60 |  | 339 |  |  |  |  |  |  |  |  |  |
| rests(minlen) | 3 |  | 362 |  |  |  |  |  |  |  |  |  |
| rests(thr) | 5.0 |  | 362 |  |  |  |  |  |  |  |  |  |
| FPS18 | 30.0 |  | 389 | ==== a18_physics/scripts/body_motion.py ============================================================================= |  |  |  |  |  |  |  |  |

### mvi/arms.py（確かめ・部品、0）

（数を持つ定数・引数の既定なし）

### mvi/balance.py（確かめ・部品、0）

（数を持つ定数・引数の既定なし）

### mvi/base.py（確かめ・部品、10）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FPS | 30.0 |  | 38 |  |  |  |  |  |  |  |  |  |
| UNIT_CM | 8.0 | cm | 39 | one unit of Sour's Rin is 8 cm (the analysis pack's README) | 解析の資料の README の「1 ≒ 8 cm」。adapt（10-17）の測り: リンの背（靴底 0.111 から髪の上 19.197、リボン・アホ毛を除く）19.086 単位で公式 152 cm なら 7.96 cm/単位、頭先の骨… | ○ |  |  | ○ |  |  | retarget |
| G_UNITS | 122.5 | m/s^2 | 40 | 9.8 m/s^2 in her units (8 cm a unit) | 9.8 m/s² を 8 cm/単位で（122.5）。リンの大きさの幅 7.96〜8.15 cm/単位なら 120.4〜123.1（adapt 10-17） | ○ | ○ |  |  |  |  | retarget |
| MV_SECONDS | 246.0 |  | 41 | the MV's dance range (p31_table's resolution) | human_baseline の p31_table の分解能（踊りの範囲 246 秒） |  |  | ○ |  |  |  | dance |
| SIDE_WORDS | {0: "中", 1: "上へ外", -1: "下へ外"} |  | 46 |  |  |  |  |  |  |  |  |  |
| ref_text(digits) | 3 |  | 256 |  |  |  |  |  |  |  |  |  |
| _num(digits) | 3 |  | 276 |  |  |  |  |  |  |  |  |  |
| event(side) | 1 |  | 307 |  |  |  |  |  |  |  |  |  |
| runs(min_len) | 1 |  | 333 |  |  |  |  |  |  |  |  |  |
| round_tree(digits) | 6 |  | 358 |  |  |  |  |  |  |  |  |  |

### mvi/body.py（確かめ・部品、1）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CACHE_VERSION | 1 |  | 39 |  |  |  |  |  |  |  |  |  |

### mvi/eyes.py（確かめ・部品、1）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EDGE_RUN_S | 0.5 | s | 18 |  |  |  |  |  |  |  |  |  |

### mvi/feet.py（確かめ・部品、4）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UNDER_CM | 0.1 | cm | 23 |  |  | ○ |  |  |  |  |  | retarget |
| SUPPORT_CM | 1.6 | cm | 24 |  |  | ○ |  |  |  |  |  | retarget |
| IK_MISS | 0.05 | units | 25 | units (4 mm): tools/balance_layer.IK_MISS |  | ○ |  |  |  |  |  | retarget |
| IK_WORSE | 0.0125 | units | 26 | units (1 mm): tools/balance_layer.IK_WORSE |  | ○ |  |  |  |  |  | retarget |

### mvi/fq.py（確かめ・部品、8）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FPS | 30.0 |  | 18 |  |  |  |  |  |  |  |  |  |
| DT | 1.0 / FPS |  | 19 |  |  |  |  |  |  |  |  |  |
| G_CM | 980.0 | cm | 20 |  |  | ○ | ○ |  |  |  |  | retarget |
| U | 8.0 |  | 21 |  |  |  |  |  |  |  |  |  |
| CONTACT_CM | 2.5 | cm | 26 |  |  | ○ |  |  |  |  |  | retarget |
| DROP_CM | 3.0 | cm | 27 |  |  | ○ |  |  |  |  |  | retarget |
| HALF_G | -61.25 | units/s^2 | 28 | units/s^2: half of gravity, downwards | 重力の半分（8 cm/単位で 61.25）。floaty（10-17）の宙の放物線の決め | ○ | ○ |  |  |  |  | retarget |
| runs(min_len) | 1 |  | 31 |  |  |  |  |  |  |  |  |  |

### mvi/gravity.py（確かめ・部品、0）

（数を持つ定数・引数の既定なし）

### mvi/hb.py（確かめ・部品、6）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FPS | 30.0 |  | 14 |  |  |  |  |  |  |  |  |  |
| U2M | 0.08 |  | 15 |  |  |  |  |  |  |  |  |  |
| dance_range(thr) | 50.0 |  | 23 |  |  |  |  |  |  |  |  |  |
| dance_range(trim) | 15 |  | 23 |  |  |  |  |  |  |  |  |  |
| _runs_in(min_len) | 1 |  | 33 |  |  |  |  |  |  |  |  |  |
| measure(trim) | 15 |  | 192 |  |  |  |  |  |  |  |  |  |

### mvi/marks.py（確かめ・部品、1）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UNIT_M | 0.08 | m | 31 |  |  | ○ |  |  |  |  |  | retarget |

### mvi/mouth.py（確かめ・部品、0）

（数を持つ定数・引数の既定なし）

### mvi/pixels.py（確かめ・部品、5）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A_MIN | 128 |  | 21 |  |  |  |  |  |  |  |  |  |
| G_MIN | 160 |  | 21 |  |  |  |  |  |  |  |  |  |
| RB_MAX | 90 |  | 21 |  |  |  |  |  |  |  |  |  |
| shadow(min_plain) | 4.0 |  | 62 |  |  |  |  |  |  |  |  |  |
| shadow(reach) | 0.95 |  | 62 |  |  |  |  |  |  |  |  |  |

### mvi/plot.py（確かめ・部品、11）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| WIDTH | 1800 |  | 14 |  |  |  |  |  |  |  |  |  |
| ROW | 150 |  | 15 |  |  |  |  |  |  |  |  |  |
| LEFT | 70 |  | 16 |  |  |  |  |  |  |  |  |  |
| RIGHT | 20 |  | 16 |  |  |  |  |  |  |  |  |  |
| TOP | 50 |  | 16 |  |  |  |  |  |  |  |  |  |
| INK | (40, 40, 40) |  | 17 |  |  |  |  |  |  |  |  |  |
| GRID | (225, 225, 225) |  | 18 |  |  |  |  |  |  |  |  |  |
| CURVE | (31, 119, 180) |  | 19 |  |  |  |  |  |  |  |  |  |
| BAND | (210, 235, 210) |  | 20 |  |  |  |  |  |  |  |  |  |
| LIMIT | (200, 120, 0) |  | 21 |  |  |  |  |  |  |  |  |  |
| EVENT | (214, 39, 40) |  | 22 |  |  |  |  |  |  |  |  |  |

### mvi/report.py（確かめ・部品、5）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TOP_MD | 60 |  | 23 |  |  |  |  |  |  |  |  |  |
| FORMAT | 2 |  | 24 | 2: which places are listed changed (toward / also / extreme, the review of 10-17) |  |  |  |  |  |  |  |  |
| PER_CONCEPT | 3 |  | 226 |  |  |  |  |  |  |  |  |  |
| PER_MEASURE | 8 |  | 227 | one measure's places in the heaviest-first table at most (the ZMP's stretches, whose tilts run to 80 of their scale, would fill it: the review of 10-17) |  |  |  |  |  |  |  |  |
| compare_md(top) | 30 |  | 379 |  |  |  |  |  |  |  |  |  |

### mvi/retarget.py（確かめ・部品、0）

（数を持つ定数・引数の既定なし）

### mvi/shared.py（確かめ・部品、2）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| WB_CONTACT | 0.15 | units | 23 | units (1.2 cm): wbbalance's contact for people and the MV alike |  | ○ |  |  |  | ○ |  | retarget |
| WB_CUTOFF | 6.0 |  | 24 |  |  |  |  |  |  |  |  |  |

### mvi/skirt.py（確かめ・部品、2）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BOUND | 122.0 | units/s^2 | 18 |  | 体重の層の DOWN_ACC_MAX 122（HANDOVER 2026-10-16）。スカートの研究（2026-10-15）: 腰の下向きの加速度が重力を越えると布が水平を越える |  |  |  |  |  |  | retarget |
| TOL | 0.5 |  | 19 |  |  |  |  |  |  |  |  |  |

### mvi/spikes.py（確かめ・部品、0）

（数を持つ定数・引数の既定なし）

### mvi/upper.py（確かめ・部品、6）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CARRIED | 0.75 |  | 31 | upper_body_check.local_follow: a window whose slope passes this is carried |  |  |  |  |  |  |  |  |
| HOP | 15 | frames | 32 | frames: its windows |  |  |  |  |  |  |  |  |
| WIN | 60 | frames | 32 | frames: its windows |  |  |  |  |  |  |  |  |
| local_windows(cutoff_hz) | 6.0 | Hz | 44 |  |  |  |  |  |  |  |  |  |
| local_windows(fs) | 30.0 |  | 44 |  |  |  |  |  |  |  |  |  |
| locked_runs(least) | 2 |  | 61 |  |  |  |  |  |  |  |  |  |

### mvi/vertical.py（確かめ・部品、6）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FPS | 30.0 |  | 15 |  |  |  |  |  |  |  |  |  |
| CM | 8.0 |  | 16 |  |  |  |  |  |  |  |  |  |
| BEAT0 | 0.01593 |  | 17 |  |  |  |  |  |  |  |  |  |
| PERIOD | 0.4285714 |  | 17 |  |  |  |  |  |  |  |  |  |
| dips(min_cm) | 2.0 | cm | 26 |  |  | ○ |  |  |  |  |  | retarget |
| dips(win) | 15 |  | 26 |  |  |  |  |  |  |  |  |  |

### look_credits.py（確かめ・部品、3）

| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| count(examples) | 3 |  | 287 |  |  |  |  |  |  |  |  |  |
| to_md(top) | 60 |  | 341 |  |  |  |  |  |  |  |  |  |
| --top | 60 |  | 359 |  |  |  |  |  |  |  |  |  |

