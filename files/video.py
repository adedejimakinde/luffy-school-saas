"""The website's hero loop: short, muted, small. Nothing else is self-hosted.

Video with sound, or longer than about ten seconds, is a YouTube or Vimeo link
(docs/school-sites.md §9.2), never an upload. What is accepted:

- **A container that is MP4/MOV or WebM/Matroska**, recognised by its first
  bytes in the request and probed by FFmpeg (through PyAV) in the worker: it
  must hold a video stream, at most `VIDEO_MAX_SECONDS` long.
- **What is kept** is one H.264 MP4, at most 720 p and 30 frames a second,
  `faststart` so it plays while it downloads, **with no audio track and no
  metadata**, and at most `VIDEO_MAX_OUTPUT_BYTES`. If the first encode is
  larger it is tried again smaller; if it still does not fit, it is refused.
- **A poster**, the first frame, made exactly like a hero photo: it is the
  page's largest paint, and phones see only the poster (§9.2).
"""

import os
import tempfile
from fractions import Fraction

from .images import Refused
from .kinds import (
    VIDEO_MAX_FPS,
    VIDEO_MAX_HEIGHT,
    VIDEO_MAX_OUTPUT_BYTES,
    VIDEO_MAX_SECONDS,
    Profile,
    profile_for,
)

#: Tried in order until one fits the byte limit: (CRF, largest height).
ATTEMPTS = ((26, 720), (30, 720), (32, 540))

_CONTAINERS = ("mov", "mp4", "matroska", "webm")


def looks_like_video(head: bytes) -> bool:
    """MP4/MOV (an `ftyp` box first) or WebM/Matroska (the EBML magic)."""
    return head[4:8] == b"ftyp" or head[:4] == b"\x1a\x45\xdf\xa3"


def _probe(path):
    import av

    try:
        container = av.open(path, metadata_errors="ignore")
    except (av.error.FFmpegError, OSError, ValueError):
        raise Refused("That file is not a video this can read. Use an MP4 or MOV file.")
    with container:
        if not any(name in container.format.name for name in _CONTAINERS):
            raise Refused("A video is an MP4, MOV or WebM file.")
        if not container.streams.video:
            raise Refused("That file has no video in it.")
        stream = container.streams.video[0]
        if container.duration is not None:
            seconds = container.duration / av.time_base
        elif stream.duration is not None and stream.time_base:
            seconds = float(stream.duration * stream.time_base)
        else:
            raise Refused("That video does not say how long it is. Save it again as MP4.")
        if seconds > VIDEO_MAX_SECONDS:
            raise Refused(
                f"A video here can be at most {int(VIDEO_MAX_SECONDS)} seconds, a short silent loop. "
                "Put a longer video on YouTube or Vimeo and add its link instead."
            )
        width, height = stream.codec_context.width, stream.codec_context.height
        if not width or not height or width * height > 4096 * 4096:
            raise Refused("That video's picture is a size this cannot use.")
        rate = stream.average_rate or stream.guessed_rate or Fraction(30)
        return seconds, width, height, float(rate)


def _size_for(width, height, limit):
    if height <= limit:
        w, h = width, height
    else:
        w, h = round(width * limit / height), limit
    return max(2, w - w % 2), max(2, h - h % 2)


def _encode(source, target, crf, limit):
    import av

    poster = None
    with av.open(source, metadata_errors="ignore") as inp:
        stream_in = inp.streams.video[0]
        stream_in.thread_type = "AUTO"
        width, height = _size_for(stream_in.codec_context.width, stream_in.codec_context.height, limit)
        rate = min(float(stream_in.average_rate or VIDEO_MAX_FPS), VIDEO_MAX_FPS)
        fps = Fraction(round(rate * 1000), 1000).limit_denominator(1001)
        with av.open(target, "w", format="mp4", options={"movflags": "+faststart"}) as out:
            stream = out.add_stream("libx264", rate=fps)
            stream.width, stream.height = width, height
            stream.pix_fmt = "yuv420p"
            stream.options = {
                "crf": str(crf), "preset": "slow", "profile": "high",
                "maxrate": "2400k", "bufsize": "4800k", "movflags": "+faststart",
            }
            next_at, step, index = 0.0, 1.0 / float(fps), 0
            for frame in inp.decode(stream_in):
                at = float(frame.time or 0.0)
                if at > VIDEO_MAX_SECONDS:
                    break
                if at + 1e-6 < next_at:
                    continue  # dropping frames above 30 a second
                next_at += step
                if poster is None:
                    poster = frame.to_image()
                scaled = frame.reformat(width=width, height=height, format="yuv420p")
                scaled.pts = index
                scaled.time_base = Fraction(1) / fps
                index += 1
                for packet in stream.encode(scaled):
                    out.mux(packet)
            for packet in stream.encode():
                out.mux(packet)
            # No audio stream is ever added, and no metadata is copied over.
    if poster is None:
        raise Refused("That video has no pictures in it.")
    return poster, width, height


def hero_loop(raw: bytes, profile: Profile):
    from . import images

    if len(raw) > profile.max_bytes:
        raise Refused(f"{profile.noun} can be at most {profile.max_mb} MB. Save it smaller and try again.")
    if not looks_like_video(raw[:16]):
        raise Refused("A video is an MP4, MOV or WebM file.")
    with tempfile.TemporaryDirectory(prefix="classnode-video-") as work:
        source = os.path.join(work, "in")
        target = os.path.join(work, "out.mp4")
        with open(source, "wb") as handle:
            handle.write(raw)
        seconds, *_ = _probe(source)
        for crf, limit in ATTEMPTS:
            poster, width, height = _encode(source, target, crf, limit)
            if os.path.getsize(target) <= VIDEO_MAX_OUTPUT_BYTES:
                break
        else:
            raise Refused(
                "That video is too busy to fit in 3 MB even at a smaller size. "
                "Try a shorter or calmer clip, or link to it on YouTube or Vimeo."
            )
        with open(target, "rb") as handle:
            data = handle.read()
    poster.info.clear()
    still = images.site_photo_from(poster.convert("RGB"), profile_for("hero_image"), prefix="poster-")
    variants = dict(still["variants"])
    blobs = dict(still["data"])
    variants["loop.mp4"] = {"bytes": len(data), "width": width, "height": height}
    blobs["loop.mp4"] = data
    return {
        "variants": variants,
        "data": blobs,
        "master": "loop.mp4",
        "width": width,
        "height": height,
        "seconds": round(min(seconds, VIDEO_MAX_SECONDS), 2),
        "colour": still["colour"],
    }


__all__ = ["looks_like_video", "hero_loop"]
