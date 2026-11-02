"""What uvicorn serves: `python -m agentqa ui` → agentqa.api.server:app (API + new web app + old dashboard)."""
from __future__ import annotations

import os

from agentqa.api import create_app
from agentqa.api.settings import Settings, load_dotenv

# backend/.env is read into the settings object only; it never enters os.environ (stage processes inherit that).
app = create_app(Settings.from_env({**load_dotenv(), **os.environ}), legacy=True)
