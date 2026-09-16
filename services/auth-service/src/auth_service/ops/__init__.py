"""Operator commands that are not scheduled jobs.

``maintenance/`` holds the cron twins — things that run on a timer and
have a scheduler as their primary caller. This package holds the things a
person runs, deliberately, once: onboarding somebody by hand (OPS-0), and
clearing out the accounts that never confirmed.

The split matters because the audiences differ. A maintenance job is read
by whoever is on call at 3 a.m.; these are read by whoever is answering a
request-access form on a Tuesday afternoon, and their failure modes have
to be legible to that person without opening the code.
"""
