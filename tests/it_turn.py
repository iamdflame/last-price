"""One telegram-sourced stranger turn through Hermes's own AIAgent, in a fresh process (= a restarted
gateway's agent for that chat). argv: session_id message port. Prints a JSON verdict line."""
import json
import os
import sys

sid, msg, port = sys.argv[1], sys.argv[2], sys.argv[3]

from hermes_state import SessionDB  # noqa: E402
from run_agent import AIAgent  # noqa: E402

db = SessionDB()
history = []
try:
    if db.get_session(sid):
        history = db.get_messages_as_conversation(sid)
except Exception as exc:
    print("history-read-failed", exc, file=sys.stderr)

agent = AIAgent(base_url=f"http://127.0.0.1:{port}/v1", api_key="sk-fake", provider="custom", model="fake-model",
                quiet_mode=True, session_id=sid, platform="telegram", user_id="777001", user_name="stranger",
                session_db=db, skip_context_files=True, enabled_toolsets=["lastprice"])
res = agent.run_conversation(msg, conversation_history=history)
row = db.get_session(sid) or {}
print("VERDICT " + json.dumps({"final": (res or {}).get("final_response"),
                               "stored_prompt_has_marker": "OWNER-MEMORY-MARKER" in (row.get("system_prompt") or "")}))
