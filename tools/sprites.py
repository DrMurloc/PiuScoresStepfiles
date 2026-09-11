# Match the actual arrow, not "a bright blob about the right size".
#
# The blob detector's model of an arrow is a shape statistic - one lane wide, as tall as it is
# wide, fills its box. Bright art satisfies that constantly and a dim arrow fails it. But PIU
# draws its notes from a fixed, tiny set of pictures: five panel shapes, the same sprite every
# time, at the same size for the whole song. Matching the picture is a far stronger test than
# matching its bounding box, and it is proven in this repo already - the result-screen reader
# matches digit templates at 0.99 correlation.
#
# The sprites ship in the game, not in anything we can read, and every video is a different
# resolution and crop. But the game draws them for us: THE RECEPTORS AT THE TOP OF THE SCREEN
# ARE THE FIVE PANEL SHAPES, at exactly the size and resolution this video draws notes at, and
# receptors.geometry already isolates them - they are the only static thing in that band, so a
# temporal median keeps them and washes out the notes and the BGA. Measured on Dr. M D18, a
# receptor correlates 0.86-0.97 with a note of its own panel and under 0.3 with any other.
#
# Two seeds were tried first and both are worse:
#   - the median of the candidate crops the blob detector found. Its false positives are text
#     and stage lighting, and on a chart whose notes have not started yet they are ALL of them,
#     so the median is a picture of the BGA and every refinement round protects it.
#   - the MEDOID of those crops - the one most like the others - which is right whenever arrows
#     are a plurality. On Dr. M D18 it recovered three panels perfectly and handed the other two
#     a "3" and an "O" off the background, because a plurality vote can simply lose.
# The receptor cannot lose: it is the picture, not a vote about the picture.
#
# The harvested notes still matter, as REFINEMENT - a receptor is the panel outline and a note
# is the filled sprite - but they refine an anchor instead of choosing one.
#
# Correlation is normalised cross-correlation of the GREY patch, so it reads structure and not
# colour, and a chart that recolours its notes matches the same template.
import os

import cv2
import numpy as np

PAD = 6            # slack around each harvested sample, so it can be re-centred onto the anchor
MIN_SAMPLES = 12   # fewer than this and the median is still mostly background
MIN_ANCHOR = 0.45  # a refined template must still look like the receptor it came from

def highpass(img, rows):
    """Take out whatever does not change down the screen, and keep what does.

    The contamination this exists for is a permanent bright SEAM where two players' fields meet:
    each pad's field is drawn with a glowing inner edge, and on a doubles layout those two glows
    sit side by side through the boxes of columns 4 and 5. Measured on ESCAPE D26 over 1,736
    frames, those two columns never go dark - their dimmest tenth of frames is twice as bright
    as any other column's - while hit explosions would show as a bright tail over a normal floor,
    and a bright BGA would lift all ten columns together. Dr. M D18's video has no such seam, so
    this is a property of a recording rather than of doubles.

    Two ways of removing it do not work, and the third is not obvious:

      across TIME, which is the first thing anyone reaches for, is wrong in principle: the seam
      is static, and so is the receptor, so any background estimated over time contains the very
      thing being looked for.

      an isotropic BLUR cannot separate them by size: the seam is about a lane wide and so is an
      arrow, so a filter wide enough to erase the glow erases the sprite with it.

    What separates them is that the seam is a vertical band - constant down the screen - and an
    arrow is not. So the smooth part is measured DOWN each column of pixels only, over a couple
    of sprite heights, and subtracted. A y-invariant glow is its own local average and vanishes
    completely; an arrow, which is small in y, keeps its shape and loses only its brightness,
    which normalised correlation was discarding anyway.

    Applied to the template and the strip alike, because a template and a search image filtered
    differently are no longer comparable.
    """
    if not rows:
        return img
    f = img.astype(np.float32)
    k = max(3, int(rows) | 1)
    return f - cv2.blur(f, (1, k), borderType=cv2.BORDER_REFLECT)

def size_for(pitch):
    """The sprite box, in pixels, for a field of this lane pitch. Odd so it has a centre."""
    tw = int(round(pitch * 0.86)) | 1
    return tw, tw

def crop(gray, cy, cx, th, tw, pad=PAD):
    y0, x0 = int(round(cy - th / 2.0)) - pad, int(round(cx - tw / 2.0)) - pad
    if y0 < 0 or x0 < 0 or y0 + th + 2 * pad > gray.shape[0] or x0 + tw + 2 * pad > gray.shape[1]:
        return None
    return gray[y0:y0 + th + 2 * pad, x0:x0 + tw + 2 * pad].astype(np.float32)

def anchors(path, vid, band, y0, y1, xs, th, tw, n=96, pct=50, hp=0.0, rest=0.0):
    """The five panel shapes, read off the receptors. Cached - it costs a pass of seeks.

    A plain median over time, and the two pads AVERAGED, because everything cleverer was
    measured and every one of them is worse.

    A receptor is only ever spoiled by something BRIGHTER than itself - it lights up when it is
    hit, a hit explosion lingers, the stage flares between the pads - and the spoiling is local.
    ESCAPE D26's band has a flare sitting on columns 4 and 5, which are exactly the columns
    pooled into its two worst panels: down-right 60% recall and down-left 84%, against 97% for
    the up arrows, which pool clean columns. So three ways of not averaging the spoiled one in
    were tried on that chart, and all three lose:

      a dimmer percentile     p35 78.8%, p50 78.6%, p70 73.2%. The flare is in most frames, so
                              no percentile escapes it, and 0.2% is noise.
      the pixel-wise MINIMUM  66.1%, down-right collapsing to 7%. The two pads' receptors are
                              not aligned to the pixel, so min() erodes the shape rather than
                              rejecting the flare.
      auditioning the two     75.4% scoring each candidate on both its columns - which FIXES
                              down-right, 60% to 85%, and breaks down-left and centre - and
                              64.4% cross-validated on the other pad only. Normalised
                              correlation rewards a FLAT template, because a low-variance patch
                              correlates spuriously well with anything, so an audition scored on
                              correlation prefers the very flare it was meant to reject.

    The diagnosis is right and none of the cures is. What would work is a template that is not
    one picture: learned from notes rather than receptors, with the flare modelled rather than
    averaged away.
    """
    # the lanes are part of the key: a template cut at the wrong x is a different template, and a
    # key without them hands the old picture back after the geometry under it has been corrected
    ck = os.path.join("work", "receptor",
                      vid + "." + band + "." + str(len(xs)) + ".p%d.h%.2f.r%.2f" % (pct, hp, rest)
                      + ".x%d-%d" % (xs[0], xs[-1]) + ".sprites.npz")
    if os.path.exists(ck):
        z = np.load(ck)
        return [z["p%d" % k] if ("p%d" % k) in z else None for k in range(5)]
    cap = cv2.VideoCapture(path)
    dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / (cap.get(cv2.CAP_PROP_FPS) or 60)
    fr = []
    for k in range(n):
        cap.set(cv2.CAP_PROP_POS_MSEC, dur * (k + 0.5) / n * 1000)
        ok, f = cap.read()
        if ok:
            # only the receptor band is ever read from these, and a percentile over 96 full
            # 720p frames is 700MB of sort that nothing looks at
            fr.append(cv2.cvtColor(f[y0:y1], cv2.COLOR_BGR2GRAY))
    cap.release()
    stack = np.stack(fr)
    half = max(4, int(tw * 0.32))
    out = []
    for k in range(5):
        got = []
        for i in (k, k + 5):
            if i >= len(xs):
                continue
            sel = stack
            if rest:
                # The receptor is not one picture. It pulses on the beat, and it LIGHTS UP when
                # its panel is stepped on - so the more a column is played, the more of its
                # frames show a lit receptor, and a median over all of them is a picture of
                # being hit rather than a picture of the panel. Measured on ESCAPE D26, how
                # bright a receptor box reads over the whole song tracks how many notes that
                # column carries at r = +0.925, and the busiest column is also the worst by
                # recall at 58%.
                #
                # So each column picks its OWN frames: the dimmest share of them, meant to be
                # the ones where nobody was standing on it. MEASURED, THIS DOES NOT WORK, and
                # the reason is worth keeping. Brightness picks dark SCENES, not unlit
                # receptors: the dimmest frames of a song are its fades and its black passages,
                # where the receptor is barely drawn at all, so the template loses its contrast
                # and the matcher loses everything. On ESCAPE D26, keeping half the frames is a
                # wash (78.9% against 78.2%), a quarter collapses to 44%, and an eighth to 30%
                # with the up arrows at 0-1%. Selecting properly needs the STEP TIMES rather
                # than brightness - which is the receptor flash reader, and that turns out to
                # recover only about half the events and invent as many again. Left off.
                b = stack[:, :, max(0, xs[i] - half):xs[i] + half].mean(axis=(1, 2))
                sel = stack[np.argsort(b)[:max(8, int(len(b) * rest))]]
            m = np.percentile(sel, pct, axis=0).astype(np.float32)
            c = crop(m, (y1 - y0) / 2.0, xs[i], th, tw, pad=0)
            if c is not None:
                got.append(c)
        T = np.mean(got, axis=0).astype(np.float32) if got else None
        out.append(None if T is None else highpass(T, hp * th))
    os.makedirs(os.path.dirname(ck), exist_ok=True)
    np.savez(ck, **{"p%d" % k: T for k, T in enumerate(out) if T is not None})
    return out

def build(samples, anchor, th, tw, rounds=3, pad=PAD, keep=0.45):
    """One template per panel: the receptor, sharpened into the note the game actually draws.

    Returns (templates, samples kept). A refinement that drifts off its own receptor is thrown
    away and the receptor kept - it means the samples were background, not notes.
    """
    out, kept = [], []
    for k, cl in enumerate(samples):
        A = anchor[k]
        if A is None:
            out.append(None)
            kept.append(0)
            continue
        T, n = A, 0
        for _ in range(rounds):
            al = []
            for c in cl:
                r = cv2.matchTemplate(c, T, cv2.TM_CCOEFF_NORMED)
                _, mx, _, loc = cv2.minMaxLoc(r)
                if mx < keep:                    # this sample was background, not an arrow
                    continue
                al.append(c[loc[1]:loc[1] + th, loc[0]:loc[0] + tw])
            if len(al) < MIN_SAMPLES:
                break
            n = len(al)
            T = np.median(np.stack(al), axis=0).astype(np.float32)
        if n < MIN_SAMPLES or float(cv2.matchTemplate(
                cv2.copyMakeBorder(A, 6, 6, 6, 6, cv2.BORDER_REPLICATE), T,
                cv2.TM_CCOEFF_NORMED).max()) < MIN_ANCHOR:
            T, n = A, 0
        out.append(T)
        kept.append(n)
    return out, kept

def colourfulness(bgr, y, x, th, tw):
    """How coloured this box is, 0-1. Not a hue test - the largest channel gap over the largest
    channel, which is saturation without caring WHICH colour. The game's notes are coloured and
    a great many BGAs are not; a chart that recolours its notes still reads as coloured."""
    H, W = bgr.shape[:2]
    y0, x0 = max(0, min(H - th, y)), max(0, min(W - tw, x))
    box = bgr[y0:y0 + th, x0:x0 + tw].astype(np.float32)
    mx = box.max(axis=2)
    return float(np.mean((mx - box.min(axis=2)) / np.maximum(mx, 1.0)))

def peaks(strip_gray, xs, tmpl, tw, th, floor, sep=None):
    """Per column: where this frame's sprite correlations peak, and how strongly.

    A note is a single peak, so the response is thinned to local maxima - without that, one
    arrow reports a dozen adjacent rows and every streak links to itself.
    """
    per_col = []
    H, W = strip_gray.shape
    for c, x in enumerate(xs):
        T = tmpl[c]
        if T is None:
            per_col.append([])
            continue
        x0 = max(0, min(W - tw, int(round(x - tw / 2.0))))
        r = cv2.matchTemplate(strip_gray[:, x0:x0 + tw].astype(np.float32), T,
                              cv2.TM_CCOEFF_NORMED).ravel()
        # The local maximum comes from a dilation, not a sliding Python window: the window was
        # one numpy call per ROW per column per frame, which is most of a whole-song pass.
        k = sep if sep else th // 2
        top = cv2.dilate(r.reshape(-1, 1), np.ones((2 * k + 1, 1), np.uint8)).ravel()
        idx = np.nonzero((r >= floor) & (r >= top - 1e-6))[0]
        hits, last = [], -10 ** 9
        for i in idx:                      # a plateau can hand back neighbours; keep one
            i = int(i)
            if i - last <= k:
                if hits and r[i] > hits[-1][2]:
                    hits[-1] = (i, i + th, float(r[i]))
                    last = i
                continue
            hits.append((i, i + th, float(r[i])))
            last = i
        per_col.append(hits)
    return per_col
