"""Pytest configuration and shared fixtures."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Default to explicit opt-in demo provider for offline pytest test suite
os.environ.setdefault("DATA_PROVIDER", "demo")
