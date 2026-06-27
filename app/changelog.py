"""Human-curated release notes shown in the dashboard's version dialog.

This ships inside the container (unlike git history, which isn't copied into
the image), so it's the source of truth for "what changed in each version".
Keep the newest release first, and update it alongside ``app.__version__``
whenever you cut a release. ``date`` is the release (commit/tag) date.
"""

CHANGELOG = [
    {
        "version": "1.5.0",
        "date": "2026-06-27",
        "changes": [
            "Click the version number to view this changelog, with release dates and the running build.",
        ],
    },
    {
        "version": "1.4.1",
        "date": "2026-06-27",
        "changes": [
            "Enforce the per-channel episode cap even when a poll's fetch fails (e.g. expired cookies), so channels no longer drift over the limit.",
            "Cap the RSS feed itself as a safety net so podcast apps never see more than the limit.",
            "Fix a crash that could blank the feed for channels without cover art.",
        ],
    },
    {
        "version": "1.4.0",
        "date": "2026-06-27",
        "changes": [
            "Browse a channel's downloaded episodes in a modal, with inline playback.",
        ],
    },
    {
        "version": "1.3.1",
        "date": "2026-06-27",
        "changes": [
            "Enforce a per-channel episode cap and fast-skip members-only videos.",
        ],
    },
    {
        "version": "1.3.0",
        "date": "2026-06-27",
        "changes": [
            "Dashboard overhaul: channel cards, live progress, search, bulk actions, and QR feed sharing.",
        ],
    },
    {
        "version": "1.2.5",
        "date": "2026-06-25",
        "changes": [
            "Harden the app against security-review findings.",
        ],
    },
    {
        "version": "1.2.2",
        "date": "2026-06-25",
        "changes": [
            "Rebrand from YouTube RSS to Slipcast.",
        ],
    },
]
