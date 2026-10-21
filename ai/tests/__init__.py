"""Tests for the `ai/` package.

The suite here must run with **numpy only** — no scikit-learn, no dataset, no
network, no database. Anything that needs a trained model is written to skip
cleanly when the model file is absent, because the model file is git-ignored
and a fresh clone will not have one.
"""
