"""Put MV-style text (title, credits, lyrics) on a video MMD rendered, with ffmpeg: nothing happens in MMD.

    python tools/overlay_text.py IN.avi cues.json OUT.mp4 [--frames out_dir]

cues.json: [{"text": "...", "start": 0.5, "end": 4.0, "style": "title|lyric|credit|caption",
             "anim": "fade|slide-up|slide-left", "x": "center|left|right", "y": "top|middle|bottom|lower"}]
Times are seconds in the video.  Each cue becomes one drawtext filter; the text travels in a UTF-8 file so that
no quoting of Japanese or punctuation is needed on the command line.  --frames writes a PNG at the middle of
every cue (what the viewer sees) for a report.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

FONT = "C:/Windows/Fonts/meiryob.ttc" if os.path.exists("C:/Windows/Fonts/meiryob.ttc") else "C:/Windows/Fonts/meiryo.ttc"
STYLES = {
    "title": {"fontsize": 96, "fontcolor": "white", "borderw": 3, "bordercolor": "black@0.55", "shadow": 4},
    "lyric": {"fontsize": 44, "fontcolor": "white", "borderw": 2, "bordercolor": "black@0.6", "shadow": 2},
    "credit": {"fontsize": 28, "fontcolor": "white@0.9", "borderw": 1, "bordercolor": "black@0.5", "shadow": 1},
    "caption": {"fontsize": 36, "fontcolor": "#ffe680", "borderw": 2, "bordercolor": "black@0.6", "shadow": 2},
}
FADE = 0.5
SLIDE = 0.6
SLIDE_PX = 36


def ffmpeg_path(text):
    return text.replace("\\", "/").replace(":", "\\:")


def position(cue, style):
    x_key, y_key = cue.get("x", "center"), cue.get("y", "lower")
    margin = 48
    x = {"center": "(w-text_w)/2", "left": "%d" % margin, "right": "w-text_w-%d" % margin}[x_key]
    y = {"top": "%d" % margin, "middle": "(h-text_h)/2", "lower": "h-text_h-%d" % (margin + 60),
         "bottom": "h-text_h-%d" % margin}[y_key]
    start, end = cue["start"], cue["end"]
    anim = cue.get("anim", "fade")
    if anim == "slide-up":
        y = "(%s)+%d*(1-min(1,(t-%.3f)/%.3f))" % (y, SLIDE_PX, start, SLIDE)
    elif anim == "slide-left":
        x = "(%s)+%d*(1-min(1,(t-%.3f)/%.3f))" % (x, SLIDE_PX, start, SLIDE)
    alpha = "if(lt(t,%.3f),(t-%.3f)/%.3f,if(gt(t,%.3f),(%.3f-t)/%.3f,1))" % (start + FADE, start, FADE, end - FADE, end, FADE)
    return x, y, alpha


def drawtext(cue, textfile):
    style = STYLES[cue.get("style", "lyric")]
    x, y, alpha = position(cue, style)
    parts = ["fontfile='%s'" % ffmpeg_path(FONT), "textfile='%s'" % ffmpeg_path(textfile),
             "fontsize=%d" % cue.get("fontsize", style["fontsize"]), "fontcolor=%s" % style["fontcolor"],
             "borderw=%d" % style["borderw"], "bordercolor=%s" % style["bordercolor"],
             "shadowcolor=black@0.5", "shadowx=%d" % style["shadow"], "shadowy=%d" % style["shadow"],
             "x='%s'" % x, "y='%s'" % y, "alpha='%s'" % alpha, "enable='between(t,%.3f,%.3f)'" % (cue["start"], cue["end"])]
    return "drawtext=" + ":".join(parts)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("video")
    p.add_argument("cues")
    p.add_argument("out")
    p.add_argument("--frames", help="folder for a PNG at the middle of each cue")
    p.add_argument("--crf", type=int, default=18)
    args = p.parse_args(argv)
    with open(args.cues, encoding="utf-8") as f:
        cues = json.load(f)
    folder = tempfile.mkdtemp(prefix="mmd-overlay-")
    filters = []
    for i, cue in enumerate(cues):
        path = os.path.join(folder, "cue%02d.txt" % i)
        with open(path, "w", encoding="utf-8") as f:
            f.write(cue["text"])
        filters.append(drawtext(cue, path))
    graph = ",".join(filters) if filters else "null"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", args.video, "-vf", graph,
           "-c:v", "libx264", "-crf", str(args.crf), "-preset", "medium", "-pix_fmt", "yuv420p", "-movflags", "+faststart", args.out]
    subprocess.run(cmd, check=True)
    report = {"out": args.out, "cues": len(cues), "frames": []}
    if args.frames:
        os.makedirs(args.frames, exist_ok=True)
        for i, cue in enumerate(cues):
            at = (cue["start"] + cue["end"]) / 2
            png = os.path.join(args.frames, "cue%02d_%05.2fs.png" % (i, at))
            subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", "%.3f" % at, "-i", args.out,
                            "-frames:v", "1", png], check=True)
            report["frames"].append(png)
    print(json.dumps(report, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
