"""Compositor service (spec §8): the only node with a "wait for everything"
dependency. Reads the timeline, pulls assets from object storage, and renders the
final MP4 with FFmpeg. Single instance, dedicated Celery queue."""
