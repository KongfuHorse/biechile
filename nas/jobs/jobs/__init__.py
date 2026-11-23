"""Job handlers for the biechile NAS agent.

This package is the "code bundle": it is zipped and stored in Supabase (table nas_code),
and the agent on the NAS downloads it when the version changes. Each handler is
    handler(args: dict, ctx) -> dict
where ctx has .log (a logger), .put_file(name, mime, bytes), .data_dir and .job_id.
"""
from . import assist, probe

HANDLERS = {
    "net": probe.net,      # plain HTTP checks, no browser
    "probe": probe.probe,  # open pages in a real browser, report status, take screenshots
    "fetch": probe.fetch,  # open one page in the browser and return its text (and HTML)
    "capture": probe.capture,  # do a few clicks/typing on a page and record its data requests
    "spcj_search": assist.spcj_search,  # food sampling search; a person finishes the slider check
}
